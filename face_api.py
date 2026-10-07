from __future__ import annotations

import asyncio
import io
import logging
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Annotated, Literal

import cv2
import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from face_config import Settings
from face_models import FaceObservation, InferenceModels, ModelMetadata
from face_pipeline import (
    CandidateGallery,
    FaceServiceError,
    clear_observations,
    normalize_vector,
    quality_issues,
    select_representatives,
    validate_model,
)
from face_tracker import TrackManager

VectorValues = Annotated[list[float], Field(min_length=256, max_length=256)]
_LOGGER = logging.getLogger(__name__)


class _FrameTimings:
    """Opt-in stage durations only; never log frame, session or student data."""

    def __init__(self) -> None:
        self.enabled = _LOGGER.isEnabledFor(logging.DEBUG)
        self.started = time.perf_counter_ns() if self.enabled else 0
        self.durations: dict[str, float] = {}
        self.faces = 0
        self.embeddings = 0
        self.outcome = "error"

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        started = time.perf_counter_ns()
        try:
            yield
        finally:
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            self.durations[stage] = self.durations.get(stage, 0.0) + elapsed

    def finish(self) -> None:
        if self.enabled:
            self.durations["total"] = (time.perf_counter_ns() - self.started) / 1_000_000
            _LOGGER.debug("face_frame_timing_ms %s", {
                **self.durations,
                "faces": self.faces,
                "embeddings": self.embeddings,
                "outcome": self.outcome,
            })


class VectorModel(BaseModel):
    model_id: str
    version: str
    dimension: Literal[256]
    normalization: Literal["l2"]


class Candidate(BaseModel):
    student_id: str = Field(
        min_length=1,
        strict=True,
        description=(
            "Opaque string form of the DataGSM student.id canonical ID; "
            "not a database key or studentNumber."
        ),
    )
    vectors: list[VectorValues] = Field(min_length=1, max_length=20)


class SessionPayload(BaseModel):
    model: VectorModel
    candidates: list[Candidate] = Field(max_length=200)


class EnrollmentResponse(BaseModel):
    model: VectorModel
    reviewedFrames: int = Field(ge=0, le=100)
    acceptedFrames: int = Field(ge=0, le=100)
    vectors: list[VectorValues] = Field(min_length=1, max_length=20)


class ErrorDetail(BaseModel):
    code: str
    message: str | None = None


class ErrorResponse(BaseModel):
    detail: ErrorDetail | list[dict[str, object]]


class SessionReadyResponse(BaseModel):
    status: Literal["ready"]


class SessionDeletedResponse(BaseModel):
    status: Literal["deleted"]


class HealthResponse(BaseModel):
    status: Literal["ok", "ready", "not_ready"]


class FaceQuality(BaseModel):
    brightness: float
    sharpness: float
    issues: list[str]


class FaceRecognition(BaseModel):
    status: Literal["KNOWN", "UNKNOWN", "NOT_ATTEMPTED"]
    studentId: str | None
    score: float | None
    margin: float | None


class FaceResult(BaseModel):
    trackId: str
    bbox: tuple[float, float, float, float]
    landmarks: list[tuple[float, float]]
    quality: FaceQuality
    recognition: FaceRecognition
    attempts: int = Field(ge=0)
    qrRecommended: bool


class FrameResponse(BaseModel):
    frameId: str
    faces: list[FaceResult]


@dataclass
class Session:
    gallery: CandidateGallery
    tracker: TrackManager
    last_activity_at: float
    in_flight: int = 0
    closing: bool = False


def create_app(
    settings: Settings | None = None,
    models: InferenceModels | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> FastAPI:
    cfg = settings or Settings()
    metadata = ModelMetadata(version=cfg.model_version)
    sessions: dict[str, Session] = {}
    retired_sessions: dict[int, Session] = {}
    sessions_drained = asyncio.Event()
    sessions_drained.set()
    lock = asyncio.Lock()

    def discard_session(session: Session) -> None:
        session.tracker.reset()
        session.gallery.clear()
        retired_sessions.pop(id(session), None)
        if not retired_sessions:
            sessions_drained.set()

    def retire_session(session: Session) -> None:
        session.closing = True
        if session.in_flight == 0:
            discard_session(session)
        else:
            retired_sessions[id(session)] = session
            sessions_drained.clear()

    def cleanup_expired_sessions(now: float | None = None) -> int:
        current = monotonic() if now is None else now
        expired = [
            session_id
            for session_id, session in sessions.items()
            if session.in_flight == 0
            and current - session.last_activity_at >= cfg.session_idle_seconds
        ]
        for session_id in expired:
            session = sessions.pop(session_id)
            discard_session(session)
        return len(expired)

    def acquire_session(session_id: str) -> Session | None:
        session = sessions.get(session_id)
        if session is None or session.closing:
            return None
        current = monotonic()
        if session.in_flight == 0 and current - session.last_activity_at >= cfg.session_idle_seconds:
            sessions.pop(session_id, None)
            discard_session(session)
            return None
        session.in_flight += 1
        session.last_activity_at = current
        return session

    def release_session(session_id: str, session: Session) -> None:
        session.in_flight = max(0, session.in_flight - 1)
        session.last_activity_at = monotonic()
        if session.closing and session.in_flight == 0:
            if sessions.get(session_id) is session:
                sessions.pop(session_id, None)
            discard_session(session)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = models
        if runtime is None and cfg.landmarker_path.is_file() and cfg.embedding_model_path.is_file():
            runtime = InferenceModels(str(cfg.landmarker_path), str(cfg.embedding_model_path), metadata)
        app.state.models = runtime
        app.state.sessions = sessions
        app.state.retired_sessions = retired_sessions
        app.state.cleanup_expired_sessions = cleanup_expired_sessions

        async def reap_expired_sessions() -> None:
            while True:
                await asyncio.sleep(cfg.session_cleanup_interval_seconds)
                cleanup_expired_sessions()

        cleanup_task = asyncio.create_task(reap_expired_sessions())
        try:
            yield
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
            for session in list(sessions.values()) + list(retired_sessions.values()):
                retire_session(session)
            sessions.clear()
            await sessions_drained.wait()
            if runtime is not None and models is None:
                runtime.close()

    app = FastAPI(title="Dormitory Face Inference Service", version="0.1.0", lifespan=lifespan)

    service_bearer = HTTPBearer(
        auto_error=False,
        scheme_name="serviceBearer",
        description=(
            "Private Spring-to-AI service token. Browser SESSION cookies and DataGSM OAuth "
            "access tokens are not accepted."
        ),
    )

    def has_valid_service_token(credentials: HTTPAuthorizationCredentials | None) -> bool:
        return bool(
            cfg.service_token
            and credentials is not None
            and secrets.compare_digest(
                credentials.credentials.encode("utf-8"), cfg.service_token.encode("utf-8")
            )
        )

    async def auth(
        credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer),
    ) -> None:
        if not has_valid_service_token(credentials):
            raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED"})

    @app.middleware("http")
    async def authenticate_internal_requests(request: Request, call_next):
        if request.url.path.startswith("/internal/"):
            credentials = await service_bearer(request)
            if not has_valid_service_token(credentials):
                return JSONResponse(status_code=401, content={"detail": {"code": "UNAUTHORIZED"}})
        return await call_next(request)

    def handle_error(exc: FaceServiceError) -> HTTPException:
        return HTTPException(
            status_code=exc.status, detail={"code": exc.code, "message": exc.message}
        )

    @app.get("/health/live", response_model=HealthResponse)
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/health/ready",
        response_model=HealthResponse,
        responses={503: {"model": HealthResponse, "description": "Models are not ready."}},
    )
    async def ready() -> Response:
        if getattr(app.state, "models", None) is None or not cfg.ready_for_inference:
            return Response(status_code=503, content='{"status":"not_ready"}', media_type="application/json")
        return Response(status_code=200, content='{"status":"ready"}', media_type="application/json")

    async def read_body(request: Request) -> bytearray:
        data = bytearray()
        try:
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > cfg.max_body_bytes:
                    raise FaceServiceError("PAYLOAD_TOO_LARGE", "request body exceeds configured limit", 413)
            return data
        except BaseException:
            data[:] = b"\x00" * len(data)
            raise

    @app.post(
        "/internal/v1/face/enrollments/extract",
        response_model=EnrollmentResponse,
        dependencies=[Depends(auth)],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "video/webm": {"schema": {"type": "string", "format": "binary"}},
                    "video/mp4": {"schema": {"type": "string", "format": "binary"}},
                },
            }
        },
        responses={
            400: {"model": ErrorResponse, "description": "Unsupported or undecodable video."},
            401: {"model": ErrorResponse, "description": "Missing or invalid service bearer token."},
            413: {"model": ErrorResponse, "description": "Video exceeds the configured size limit."},
            422: {"model": ErrorResponse, "description": "Video contains multiple identities or insufficient quality frames."},
            500: {"model": ErrorResponse, "description": "Unexpected inference error."},
            503: {"model": ErrorResponse, "description": "Inference models are not ready."},
        },
    )
    async def enroll(request: Request) -> EnrollmentResponse:
        runtime: InferenceModels | None = app.state.models
        if runtime is None:
            raise handle_error(FaceServiceError("MODEL_NOT_READY", "models are not loaded", 503))
        if request.headers.get("content-type", "").split(";", 1)[0] not in {"video/webm", "video/mp4"}:
            raise handle_error(FaceServiceError("INVALID_MEDIA", "expected WebM or MP4 video", 400))
        body: bytearray | None = None
        vectors: list[np.ndarray] = []
        try:
            body = await read_body(request)
            stats, vectors = _extract_enrollment_vectors(body, runtime, cfg, metadata)
            return {**stats, "vectors": [vector.tolist() for vector in vectors]}
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        except Exception as exc:
            raise handle_error(FaceServiceError("INTERNAL_ERROR", "enrollment failed", 500)) from exc
        finally:
            _clear_vectors({"temporary": vectors})
            if body is not None:
                body[:] = b"\x00" * len(body)

    @app.put(
        "/internal/v1/face/sessions/{session_id}",
        response_model=SessionReadyResponse,
        dependencies=[Depends(auth)],
        responses={
            401: {"model": ErrorResponse, "description": "Missing or invalid service bearer token."},
            422: {"model": ErrorResponse, "description": "Invalid or incompatible vector payload."},
        },
    )
    async def put_session(
        session_id: Annotated[str, Path(min_length=1)], payload: SessionPayload
    ) -> SessionReadyResponse:
        candidates: dict[str, list[np.ndarray]] = {}
        gallery: CandidateGallery | None = None
        installed = False
        try:
            incoming = ModelMetadata(
                payload.model.model_id,
                payload.model.version,
                payload.model.dimension,
                payload.model.normalization,
            )
            validate_model(incoming, metadata)
            for item in payload.candidates:
                if item.student_id in candidates:
                    raise FaceServiceError("MODEL_MISMATCH", "duplicate student IDs are not allowed")
                candidates[item.student_id] = []
                for vector in item.vectors:
                    candidates[item.student_id].append(normalize_vector(vector))
            # Preserve the legacy PUT normalization followed by match normalization.
            gallery = CandidateGallery.from_candidates(candidates)
            async with lock:
                old = sessions.get(session_id)
                if old is not None:
                    retire_session(old)
                sessions[session_id] = Session(gallery, TrackManager(), monotonic())
                installed = True
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        finally:
            _clear_vectors(candidates)
            if gallery is not None and not installed:
                gallery.clear()
        return SessionReadyResponse(status="ready")

    @app.post(
        "/internal/v1/face/sessions/{session_id}/frames",
        response_model=FrameResponse,
        dependencies=[Depends(auth)],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                    "image/webp": {"schema": {"type": "string", "format": "binary"}},
                },
            }
        },
        responses={
            400: {"model": ErrorResponse, "description": "Unsupported or undecodable image."},
            401: {"model": ErrorResponse, "description": "Missing or invalid service bearer token."},
            404: {"model": ErrorResponse, "description": "Recognition session is not active."},
            413: {"model": ErrorResponse, "description": "Image exceeds the configured size limit."},
            500: {"model": ErrorResponse, "description": "Unexpected inference error."},
            503: {"model": ErrorResponse, "description": "Inference models are not ready."},
        },
    )
    async def frame(
        session_id: Annotated[str, Path(min_length=1)],
        request: Request,
        x_frame_id: Annotated[str, Header()] = "",
    ) -> dict[str, object]:
        timings = _FrameTimings()
        session: Session | None = None
        body: bytearray | None = None
        image: np.ndarray | None = None
        observations: list[FaceObservation] = []
        try:
            runtime: InferenceModels | None = app.state.models
            if runtime is None:
                raise FaceServiceError("MODEL_NOT_READY", "models are not loaded", 503)
            if request.headers.get("content-type", "").split(";", 1)[0] not in {"image/jpeg", "image/webp"}:
                raise FaceServiceError("INVALID_MEDIA", "expected JPEG or WebP image", 400)
            session = acquire_session(session_id)
            if session is None:
                raise FaceServiceError("SESSION_NOT_FOUND", "session is not active", 404)
            with timings.measure("read"):
                body = await read_body(request)
            with timings.measure("decode"):
                image = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise FaceServiceError("INVALID_MEDIA", "frame is not a valid image", 400)
            with timings.measure("detect"):
                observations = runtime.detect_faces(image)
            timings.faces = len(observations)
            height, width = image.shape[:2]
            boxes = [_response_bbox(observation.bbox) for observation in observations]
            landmarks = [
                _response_landmarks(observation.landmarks, width, height)
                for observation in observations
            ]
            tracks = session.tracker.assign(boxes)
            results = []
            for index, (observation, track) in enumerate(zip(observations, tracks, strict=True)):
                issues = quality_issues(observation)
                if issues or not session.tracker.observe_quality(track):
                    recognition = {"status": "NOT_ATTEMPTED", "studentId": None, "score": None, "margin": None}
                elif cfg.match_threshold is None or cfg.match_margin is None:
                    recognition = {"status": "NOT_ATTEMPTED", "studentId": None, "score": None, "margin": None}
                else:
                    probe: np.ndarray | None = None
                    try:
                        with timings.measure("embed"):
                            timings.embeddings += 1
                            probe = runtime.embed_face(image, observation)
                        with timings.measure("match"):
                            outcome = session.gallery.match(probe, cfg.match_threshold, cfg.match_margin)
                    finally:
                        if probe is not None:
                            probe.fill(0)
                    recognition = {
                        "status": outcome.status,
                        "studentId": outcome.student_id if outcome.status == "KNOWN" else None,
                        "score": outcome.score,
                        "margin": outcome.margin,
                    }
                    if outcome.status == "KNOWN":
                        session.tracker.record_success(track)
                    else:
                        session.tracker.record_failure(track)
                results.append(
                    {
                        "trackId": track.track_id,
                        "bbox": boxes[index],
                        "landmarks": landmarks[index],
                        "quality": {
                            "brightness": observation.brightness,
                            "sharpness": observation.sharpness,
                            "issues": issues,
                        },
                        "recognition": recognition,
                        "attempts": track.failures,
                        "qrRecommended": track.failures >= 4,
                    }
                )
            timings.outcome = "success"
            return {"frameId": x_frame_id, "faces": results}
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        except Exception as exc:
            raise handle_error(FaceServiceError("INTERNAL_ERROR", "frame inference failed", 500)) from exc
        finally:
            with timings.measure("cleanup"):
                if image is not None:
                    image.fill(0)
                clear_observations(observations)
                if body is not None:
                    body[:] = b"\x00" * len(body)
                if session is not None:
                    release_session(session_id, session)
            timings.finish()

    @app.delete(
        "/internal/v1/face/sessions/{session_id}",
        response_model=SessionDeletedResponse,
        dependencies=[Depends(auth)],
        responses={401: {"model": ErrorResponse, "description": "Missing or invalid service bearer token."}},
    )
    async def delete_session(
        session_id: Annotated[str, Path(min_length=1)],
    ) -> SessionDeletedResponse:
        session = sessions.get(session_id)
        if session:
            retire_session(session)
            if session.in_flight == 0 and sessions.get(session_id) is session:
                sessions.pop(session_id, None)
        return SessionDeletedResponse(status="deleted")

    return app


def _extract_enrollment_vectors(
    body: bytearray,
    runtime: InferenceModels,
    cfg: Settings,
    metadata: ModelMetadata,
) -> tuple[dict[str, object], list[np.ndarray]]:
    container = None
    observations: list[FaceObservation] = []
    vectors: list[np.ndarray] = []
    transferred = False
    try:
        av = __import__("av")
        try:
            container = av.open(io.BytesIO(body), mode="r")
            stream = container.streams.video[0]
            total = int(stream.frames or 0)
        except (av.error.FFmpegError, EOFError, IndexError, ValueError) as exc:
            raise FaceServiceError("INVALID_MEDIA", "video could not be decoded", 400) from exc
        frame_limit = max(1, min(cfg.enrollment_frames, 100))
        vector_limit = max(1, min(cfg.representative_vectors, 20))
        targets = _sample_indices(total, frame_limit) if total else None
        tracks = TrackManager()
        per_track: dict[str, list[FaceObservation]] = {}
        reviewed_count = 0
        for index, frame in enumerate(_decoded_video_frames(container, av)):
            if targets is not None and index not in targets:
                continue
            if targets is None and reviewed_count >= frame_limit:
                break
            image = frame.to_ndarray(format="bgr24")
            try:
                reviewed_count += 1
                found = runtime.detect(image)
                observations.extend(found)
                assigned = tracks.assign([observation.bbox for observation in found])
                for observation, track in zip(found, assigned):
                    per_track.setdefault(track.track_id, []).append(observation)
            finally:
                image.fill(0)

        # Enrollment is for one student. Never combine vectors from multiple faces.
        if len(per_track) > 1:
            raise FaceServiceError("MULTIPLE_IDENTITIES", "enrollment must contain one face identity")
        viable = {
            track_id: items
            for track_id, items in per_track.items()
            if sum(not quality_issues(item) for item in items) >= vector_limit
        }
        if not viable:
            if observations and all("LOW_LIGHT" in quality_issues(item) for item in observations):
                raise FaceServiceError("LOW_LIGHT", "enrollment video is too dark")
            raise FaceServiceError(
                "INSUFFICIENT_QUALITY_FRAMES",
                f"need {vector_limit} quality observations",
            )
        vectors = select_representatives(next(iter(viable.values())), vector_limit)
        stats = {
            "model": metadata.__dict__,
            "reviewedFrames": reviewed_count,
            "acceptedFrames": sum(not quality_issues(item) for item in observations),
        }
        transferred = True
        return stats, vectors
    except FaceServiceError:
        raise
    except Exception as exc:
        raise FaceServiceError("INTERNAL_ERROR", "enrollment inference failed", 500) from exc
    finally:
        if container is not None:
            container.close()
        clear_observations(observations)
        if not transferred:
            _clear_vectors({"temporary": vectors})


def _decoded_video_frames(container, av):
    try:
        yield from container.decode(video=0)
    except (av.error.FFmpegError, EOFError) as exc:
        raise FaceServiceError("INVALID_MEDIA", "video could not be decoded", 400) from exc


def _response_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Return a frame-normalized (left, top, width, height) box clipped to the image."""
    if len(bbox) != 4 or not np.isfinite(bbox).all():
        raise FaceServiceError("INTERNAL_ERROR", "inference returned invalid face coordinates", 500)
    x, y, width, height = (float(value) for value in bbox)
    if width < 0 or height < 0:
        raise FaceServiceError("INTERNAL_ERROR", "inference returned invalid face coordinates", 500)
    left = float(np.clip(x, 0.0, 1.0))
    top = float(np.clip(y, 0.0, 1.0))
    right = float(np.clip(x + width, left, 1.0))
    bottom = float(np.clip(y + height, top, 1.0))
    return left, top, right - left, bottom - top


def _response_landmarks(
    landmarks: tuple[tuple[float, float], ...], width: int, height: int
) -> list[list[float]]:
    """Keep landmark coordinates in pixels and clip them to the decoded image bounds."""
    points = np.asarray(landmarks, dtype=np.float64)
    if points.size == 0:
        return []
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise FaceServiceError("INTERNAL_ERROR", "inference returned invalid landmarks", 500)
    points[:, 0] = np.clip(points[:, 0], 0.0, float(width))
    points[:, 1] = np.clip(points[:, 1], 0.0, float(height))
    return points.tolist()


def _sample_indices(total: int, count: int) -> set[int]:
    if total <= 0:
        return set()
    return set(np.linspace(0, total - 1, min(total, count), dtype=int).tolist())


def _clear_vectors(groups: dict[str, list[np.ndarray]]) -> None:
    for vectors in groups.values():
        for vector in vectors:
            vector.fill(0)


app = create_app()
