from __future__ import annotations

import asyncio
import io
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Literal

import cv2
import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from face_config import Settings
from face_models import FaceObservation, InferenceModels, ModelMetadata
from face_pipeline import (
    FaceServiceError,
    clear_observations,
    match_embedding,
    normalize_vector,
    quality_issues,
    select_representatives,
    validate_model,
)
from face_tracker import TrackManager

VectorValues = Annotated[list[float], Field(min_length=256, max_length=256)]


class VectorModel(BaseModel):
    model_id: str
    version: str
    dimension: Literal[256]
    normalization: Literal["l2"]


class Candidate(BaseModel):
    student_id: str = Field(min_length=1)
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
    candidates: dict[str, list[np.ndarray]]
    tracker: TrackManager


def create_app(settings: Settings | None = None, models: InferenceModels | None = None) -> FastAPI:
    cfg = settings or Settings()
    metadata = ModelMetadata(version=cfg.model_version)
    sessions: dict[str, Session] = {}
    lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = models
        if runtime is None and cfg.landmarker_path.is_file() and cfg.embedding_model_path.is_file():
            runtime = InferenceModels(str(cfg.landmarker_path), str(cfg.embedding_model_path), metadata)
        app.state.models = runtime
        app.state.sessions = sessions
        yield
        for session in sessions.values():
            session.tracker.reset()
            _clear_vectors(session.candidates)
        sessions.clear()
        if runtime is not None and models is None:
            runtime.close()

    app = FastAPI(title="Dormitory Face Inference Service", version="0.1.0", lifespan=lifespan)

    service_bearer = HTTPBearer(
        auto_error=False,
        scheme_name="serviceBearer",
        description="Private Spring-to-AI service token. This is not a DataGSM OAuth access token.",
    )

    async def auth(
        credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer),
    ) -> None:
        if (
            not cfg.service_token
            or credentials is None
            or credentials.credentials != cfg.service_token
        ):
            raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED"})

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
        try:
            incoming = ModelMetadata(
                payload.model.model_id,
                payload.model.version,
                payload.model.dimension,
                payload.model.normalization,
            )
            validate_model(incoming, metadata)
            candidates = {
                item.student_id: [normalize_vector(vector) for vector in item.vectors]
                for item in payload.candidates
            }
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        if len(candidates) != len(payload.candidates):
            raise handle_error(FaceServiceError("MODEL_MISMATCH", "duplicate student IDs are not allowed"))
        async with lock:
            old = sessions.get(session_id)
            if old is not None:
                old.tracker.reset()
                _clear_vectors(old.candidates)
            sessions[session_id] = Session(candidates, TrackManager())
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
        runtime: InferenceModels | None = app.state.models
        session = sessions.get(session_id)
        if runtime is None:
            raise handle_error(FaceServiceError("MODEL_NOT_READY", "models are not loaded", 503))
        if session is None:
            raise handle_error(FaceServiceError("SESSION_NOT_FOUND", "session is not active", 404))
        if request.headers.get("content-type", "").split(";", 1)[0] not in {"image/jpeg", "image/webp"}:
            raise handle_error(FaceServiceError("INVALID_MEDIA", "expected JPEG or WebP image", 400))
        body: bytearray | None = None
        image: np.ndarray | None = None
        observations: list[FaceObservation] = []
        try:
            body = await read_body(request)
            image = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise FaceServiceError("INVALID_MEDIA", "frame is not a valid image", 400)
            observations = runtime.detect(image)
            tracks = session.tracker.assign([observation.bbox for observation in observations])
            results = []
            for observation, track in zip(observations, tracks):
                issues = quality_issues(observation)
                if observation.embedding is None or issues or not session.tracker.observe_quality(track):
                    recognition = {"status": "NOT_ATTEMPTED", "studentId": None, "score": None, "margin": None}
                elif cfg.match_threshold is None or cfg.match_margin is None:
                    recognition = {"status": "NOT_ATTEMPTED", "studentId": None, "score": None, "margin": None}
                else:
                    outcome = match_embedding(
                        observation.embedding,
                        session.candidates,
                        cfg.match_threshold,
                        cfg.match_margin,
                    )
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
                        "bbox": observation.bbox,
                        "landmarks": [
                            [float(x), float(y)] for x, y in observation.landmarks
                        ],
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
            return {"frameId": x_frame_id, "faces": results}
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        finally:
            if image is not None:
                image.fill(0)
            clear_observations(observations)
            if body is not None:
                body[:] = b"\x00" * len(body)

    @app.delete(
        "/internal/v1/face/sessions/{session_id}",
        response_model=SessionDeletedResponse,
        dependencies=[Depends(auth)],
        responses={401: {"model": ErrorResponse, "description": "Missing or invalid service bearer token."}},
    )
    async def delete_session(
        session_id: Annotated[str, Path(min_length=1)],
    ) -> SessionDeletedResponse:
        session = sessions.pop(session_id, None)
        if session:
            session.tracker.reset()
            _clear_vectors(session.candidates)
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
        container = __import__("av").open(io.BytesIO(body), mode="r")
        stream = container.streams.video[0]
        frame_limit = max(1, min(cfg.enrollment_frames, 100))
        vector_limit = max(1, min(cfg.representative_vectors, 20))
        total = int(stream.frames or 0)
        targets = _sample_indices(total, frame_limit) if total else None
        tracks = TrackManager()
        per_track: dict[str, list[FaceObservation]] = {}
        reviewed_count = 0
        for index, frame in enumerate(container.decode(video=0)):
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
        raise FaceServiceError("INVALID_MEDIA", "video could not be decoded", 400) from exc
    finally:
        if container is not None:
            container.close()
        clear_observations(observations)
        if not transferred:
            _clear_vectors({"temporary": vectors})


def _sample_indices(total: int, count: int) -> set[int]:
    if total <= 0:
        return set()
    return set(np.linspace(0, total - 1, min(total, count), dtype=int).tolist())


def _clear_vectors(groups: dict[str, list[np.ndarray]]) -> None:
    for vectors in groups.values():
        for vector in vectors:
            vector.fill(0)


app = create_app()
