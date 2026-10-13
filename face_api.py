from __future__ import annotations

import asyncio
import io
import logging
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field, replace
from typing import Annotated, Literal

import cv2
import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from face_config import Settings
from face_execution import InferenceExecutor
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

    def add_duration(self, stage: str, milliseconds: float) -> None:
        if self.enabled:
            self.durations[stage] = self.durations.get(stage, 0.0) + milliseconds


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
    frame_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class _EnrollmentWork:
    """Decode sampled enrollment frames incrementally on the inference worker."""

    def __init__(
        self,
        body: bytearray,
        runtime: InferenceModels,
        cfg: Settings,
        metadata: ModelMetadata,
    ) -> None:
        self.body = body
        self.runtime = runtime
        self.cfg = cfg
        self.metadata = metadata
        self.av = __import__("av")
        self.container = None
        self.frames = None
        self.targets: set[int] | None = None
        self.frame_limit = max(1, min(cfg.enrollment_frames, 100))
        self.vector_limit = max(1, min(cfg.representative_vectors, 20))
        self.observations: list[FaceObservation] = []
        self.per_track: dict[str, list[FaceObservation]] = {}
        self.tracks = TrackManager()
        self.decoded_count = 0
        self.reviewed_count = 0
        self.accepted_count = 0
        self.done = False
        self.vectors: list[np.ndarray] = []
        self.stats: dict[str, object] = {}

    def _open(self) -> None:
        if self.container is not None:
            return
        try:
            self.container = self.av.open(io.BytesIO(self.body), mode="r")
            total = int(self.container.streams.video[0].frames or 0)
        except (self.av.error.FFmpegError, EOFError, IndexError, ValueError) as exc:
            raise FaceServiceError("INVALID_MEDIA", "video could not be decoded", 400) from exc
        self.targets = _sample_indices(total, self.frame_limit) if total else None
        self.frames = iter(_decoded_video_frames(self.container, self.av))

    def step(self) -> bool:
        """Inspect at most 20 decoded frames or one sampled frame per turn."""
        if self.done:
            return True
        try:
            self._open()
            for _ in range(20):
                if self.targets is None and self.reviewed_count >= self.frame_limit:
                    self._finish()
                    return True
                try:
                    frame = next(self.frames)
                except StopIteration:
                    self._finish()
                    return True
                index = self.decoded_count
                self.decoded_count += 1
                if self.targets is not None and index not in self.targets:
                    continue
                image = frame.to_ndarray(format="bgr24")
                try:
                    self.reviewed_count += 1
                    found = self.runtime.detect_faces(image)
                    base_index = len(self.observations)
                    self.observations.extend(found)
                    assigned = self.tracks.assign([item.bbox for item in found])
                    for index, (observation, track) in enumerate(
                        zip(found, assigned, strict=True)
                    ):
                        if not quality_issues(observation):
                            embedding = self.runtime.embed_face(image, observation)
                            observation = replace(observation, embedding=embedding)
                            self.observations[base_index + index] = observation
                            self.accepted_count += 1
                        self.per_track.setdefault(track.track_id, []).append(observation)
                finally:
                    image.fill(0)
                # Give queued camera frames a worker turn before decoding more.
                return False
            return False
        except FaceServiceError:
            raise
        except Exception as exc:
            raise FaceServiceError("INTERNAL_ERROR", "enrollment inference failed", 500) from exc

    def _finish(self) -> None:
        if self.done:
            return
        if len(self.per_track) > 1:
            raise FaceServiceError("MULTIPLE_IDENTITIES", "enrollment must contain one face identity")
        viable = {
            track_id: items
            for track_id, items in self.per_track.items()
            if sum(item.embedding is not None and not quality_issues(item) for item in items)
            >= self.vector_limit
        }
        if not viable:
            if self.observations and all(
                "LOW_LIGHT" in quality_issues(item) for item in self.observations
            ):
                raise FaceServiceError("LOW_LIGHT", "enrollment video is too dark")
            raise FaceServiceError(
                "INSUFFICIENT_QUALITY_FRAMES",
                f"need {self.vector_limit} quality observations",
            )
        self.vectors = select_representatives(next(iter(viable.values())), self.vector_limit)
        self.stats = {
            "model": self.metadata.__dict__,
            "reviewedFrames": self.reviewed_count,
            "acceptedFrames": self.accepted_count,
        }
        self.done = True

    def result(self) -> tuple[dict[str, object], list[np.ndarray]]:
        if not self.done:
            raise RuntimeError("enrollment work is not complete")
        vectors, self.vectors = self.vectors, []
        return self.stats, vectors

    def close(self) -> None:
        if self.frames is not None:
            close = getattr(self.frames, "close", None)
            if close is not None:
                close()
        if self.container is not None:
            self.container.close()
            self.container = None
        clear_observations(self.observations)
        _clear_vectors({"temporary": self.vectors})
        self.vectors.clear()
        self.per_track.clear()


def _prepare_gallery(payload: SessionPayload, metadata: ModelMetadata) -> CandidateGallery:
    candidates: dict[str, list[np.ndarray]] = {}
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
        return CandidateGallery.from_candidates(candidates)
    finally:
        _clear_vectors(candidates)


def _process_frame(
    body: bytearray,
    runtime: InferenceModels,
    session: Session,
    cfg: Settings,
    frame_id: str,
    timings: _FrameTimings,
    queued_at_ns: int,
) -> dict[str, object]:
    image: np.ndarray | None = None
    observations: list[FaceObservation] = []
    try:
        timings.add_duration("queue", (time.perf_counter_ns() - queued_at_ns) / 1_000_000)
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
            if issues:
                session.tracker.reject_quality(track)
                eligible = False
            else:
                eligible = session.tracker.observe_quality(track)
            if (
                not eligible
                or cfg.match_threshold is None
                or cfg.match_margin is None
            ):
                recognition = {
                    "status": "NOT_ATTEMPTED",
                    "studentId": None,
                    "score": None,
                    "margin": None,
                }
            else:
                probe: np.ndarray | None = None
                try:
                    with timings.measure("embed"):
                        timings.embeddings += 1
                        probe = runtime.embed_face(image, observation)
                    with timings.measure("match"):
                        outcome = session.gallery.match(
                            probe, cfg.match_threshold, cfg.match_margin
                        )
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
        return {"frameId": frame_id, "faces": results}
    finally:
        if image is not None:
            image.fill(0)
        clear_observations(observations)


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
    frame_slots = asyncio.Semaphore(4)
    enrollment_slots = asyncio.Semaphore(1)
    requests_drained = asyncio.Event()
    requests_drained.set()
    active_requests = 0
    stopping = False

    def begin_request() -> None:
        nonlocal active_requests
        if stopping:
            raise FaceServiceError("MODEL_NOT_READY", "service is shutting down", 503)
        active_requests += 1
        requests_drained.clear()

    def end_request() -> None:
        nonlocal active_requests
        active_requests -= 1
        if active_requests == 0:
            requests_drained.set()

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
        nonlocal stopping
        stopping = False
        executor = InferenceExecutor()
        runtime = models
        try:
            if runtime is None and cfg.landmarker_path.is_file() and cfg.embedding_model_path.is_file():
                runtime = await executor.run(
                    InferenceModels,
                    str(cfg.landmarker_path),
                    str(cfg.embedding_model_path),
                    metadata,
                    cfg.inference_precision_hint,
                    on_cancel=lambda loaded: loaded.close(),
                )
        except BaseException:
            await executor.close()
            raise
        app.state.models = runtime
        app.state.executor = executor
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
            stopping = True
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
            for session in list(sessions.values()) + list(retired_sessions.values()):
                retire_session(session)
            sessions.clear()
            await requests_drained.wait()
            await sessions_drained.wait()
            try:
                if runtime is not None and models is None:
                    await executor.run(runtime.close)
            finally:
                app.state.models = None
                await executor.close()

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
        admitted = False
        work: _EnrollmentWork | None = None
        try:
            begin_request()
            admitted = True
            async with enrollment_slots:
                body = await read_body(request)
                work = _EnrollmentWork(body, runtime, cfg, metadata)
                try:
                    # Yield the single inference worker between decoded video frames.
                    while not await app.state.executor.run(work.step):
                        pass
                    stats, vectors = work.result()
                    return {**stats, "vectors": [vector.tolist() for vector in vectors]}
                finally:
                    # run() drains native work before propagating cancellation.
                    await app.state.executor.run(work.close)
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        except Exception as exc:
            raise handle_error(FaceServiceError("INTERNAL_ERROR", "enrollment failed", 500)) from exc
        finally:
            _clear_vectors({"temporary": vectors})
            if body is not None:
                body[:] = b"\x00" * len(body)
            if admitted:
                end_request()

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
        gallery: CandidateGallery | None = None
        installed = False
        admitted = False
        try:
            if stopping:
                raise FaceServiceError("MODEL_NOT_READY", "service is shutting down", 503)
            begin_request()
            admitted = True
            gallery = await app.state.executor.run(
                _prepare_gallery,
                payload,
                metadata,
                on_cancel=lambda prepared: prepared.clear(),
            )
            async with lock:
                old = sessions.get(session_id)
                if old is not None:
                    retire_session(old)
                sessions[session_id] = Session(
                    gallery,
                    TrackManager(success_recheck_seconds=cfg.success_recheck_seconds, monotonic=monotonic),
                    monotonic(),
                )
                installed = True
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        finally:
            if gallery is not None and not installed:
                gallery.clear()
            if admitted:
                end_request()
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
            200: {
                "description": "Per-face results; frames from a replaced or closing session return an empty faces list."
            },
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
        admitted = False
        try:
            runtime: InferenceModels | None = app.state.models
            if runtime is None:
                raise FaceServiceError("MODEL_NOT_READY", "models are not loaded", 503)
            if request.headers.get("content-type", "").split(";", 1)[0] not in {"image/jpeg", "image/webp"}:
                raise FaceServiceError("INVALID_MEDIA", "expected JPEG or WebP image", 400)
            session = acquire_session(session_id)
            if session is None:
                raise FaceServiceError("SESSION_NOT_FOUND", "session is not active", 404)
            begin_request()
            admitted = True
            admission_started_ns = time.perf_counter_ns()
            async with frame_slots:
                async with session.frame_lock:
                    timings.add_duration(
                        "admission", (time.perf_counter_ns() - admission_started_ns) / 1_000_000
                    )
                    if session.closing or sessions.get(session_id) is not session:
                        timings.outcome = "retired"
                        return {"frameId": x_frame_id, "faces": []}
                    with timings.measure("read"):
                        body = await read_body(request)
                    queued_at_ns = time.perf_counter_ns()
                    results = await app.state.executor.run(
                        _process_frame,
                        body,
                        runtime,
                        session,
                        cfg,
                        x_frame_id,
                        timings,
                        queued_at_ns,
                    )
            # A streamed upload can resume after PUT/DELETE retired this session.
            if session.closing or sessions.get(session_id) is not session:
                results["faces"] = []
            timings.outcome = "success"
            return results
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        except Exception as exc:
            raise handle_error(FaceServiceError("INTERNAL_ERROR", "frame inference failed", 500)) from exc
        finally:
            with timings.measure("cleanup"):
                if body is not None:
                    body[:] = b"\x00" * len(body)
                if session is not None:
                    release_session(session_id, session)
                if admitted:
                    end_request()
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
