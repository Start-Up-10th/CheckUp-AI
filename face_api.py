from __future__ import annotations

import asyncio
import io
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from face_config import Settings
from face_models import InferenceModels, ModelMetadata
from face_pipeline import (
    FaceServiceError,
    match_embedding,
    normalize_vector,
    quality_issues,
    select_representatives,
    validate_model,
)
from face_tracker import TrackManager


class VectorModel(BaseModel):
    model_id: str
    version: str
    dimension: int
    normalization: str


class Candidate(BaseModel):
    student_id: str = Field(min_length=1)
    vectors: list[list[float]] = Field(min_length=1, max_length=20)


class SessionPayload(BaseModel):
    model: VectorModel
    candidates: list[Candidate] = Field(max_length=200)


@dataclass
class Session:
    candidates: dict[str, list[np.ndarray]]
    tracker: TrackManager


def create_app(settings: Settings | None = None, models: InferenceModels | None = None) -> FastAPI:
    cfg = settings or Settings()
    metadata = ModelMetadata(version=cfg.model_version)
    sessions: dict[str, Session] = {}
    registered_candidates: dict[str, list[np.ndarray]] = {}
    lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = models
        if runtime is None and cfg.landmarker_path.is_file() and cfg.embedding_model_path.is_file():
            runtime = InferenceModels(
                str(cfg.landmarker_path), str(cfg.embedding_model_path), metadata
            )
        app.state.models = runtime
        app.state.sessions = sessions
        yield
        for session in sessions.values():
            session.tracker.reset()
        sessions.clear()
        for vectors in registered_candidates.values():
            for vector in vectors:
                vector.fill(0)
        registered_candidates.clear()
        if runtime is not None and models is None:
            runtime.close()

    app = FastAPI(title="Dormitory Face Inference Service", version="0.1.0", lifespan=lifespan)

    async def auth(authorization: Annotated[str | None, Header()] = None) -> None:
        if not cfg.service_token or authorization != f"Bearer {cfg.service_token}":
            raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED"})

    def public_token(authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED"})
        token = authorization.removeprefix("Bearer ").strip()
        accepted = {value for value in (cfg.access_token, cfg.service_token) if value}
        if not token or (accepted and token not in accepted):
            raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED"})
        return token

    def public_student_id(authorization: str | None) -> str:
        token = public_token(authorization)
        student_id = cfg.student_token_map.get(token)
        if not student_id or not student_id.isdigit():
            raise HTTPException(status_code=403, detail={"code": "STUDENT_NOT_FOUND"})
        return student_id

    def public_error(exc: FaceServiceError) -> HTTPException:
        status = {
            "INVALID_MEDIA": 400,
            "PAYLOAD_TOO_LARGE": 400,
            "MODEL_NOT_READY": 500,
            "NO_FACE": 422,
            "LOW_LIGHT": 422,
            "INSUFFICIENT_QUALITY_FRAMES": 422,
            "MULTIPLE_IDENTITIES": 422,
            "MODEL_MISMATCH": 500,
        }.get(exc.code, 500)
        return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})

    async def read_images(images: list[UploadFile]) -> list[np.ndarray]:
        if not images:
            raise FaceServiceError("INVALID_MEDIA", "images must contain at least one file", 400)
        decoded: list[np.ndarray] = []
        try:
            for upload in images:
                if upload.content_type not in {"image/jpeg", "image/webp", "image/png"}:
                    raise FaceServiceError("INVALID_MEDIA", "images must be JPEG, WebP, or PNG", 400)
                raw = await upload.read()
                if len(raw) > cfg.max_body_bytes:
                    raise FaceServiceError("PAYLOAD_TOO_LARGE", "image exceeds configured limit", 400)
                image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
                raw = b""
                if image is None:
                    raise FaceServiceError("INVALID_MEDIA", "one image is not decodable", 400)
                decoded.append(image)
            return decoded
        except Exception:
            for image in decoded:
                image.fill(0)
            decoded.clear()
            raise
        finally:
            for upload in images:
                await upload.close()

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> Response:
        runtime_ready = getattr(app.state, "models", None) is not None
        if not runtime_ready or not cfg.ready_for_inference:
            return Response(
                status_code=503, content='{"status":"not_ready"}', media_type="application/json"
            )
        return Response(
            status_code=200, content='{"status":"ready"}', media_type="application/json"
        )

    async def read_body(request: Request) -> bytes:
        data = bytearray()
        try:
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > cfg.max_body_bytes:
                    raise FaceServiceError(
                        "PAYLOAD_TOO_LARGE", "request body exceeds configured limit", 413
                    )
            return bytes(data)
        finally:
            data.clear()

    def handle_error(exc: FaceServiceError) -> HTTPException:
        return HTTPException(
            status_code=exc.status, detail={"code": exc.code, "message": exc.message}
        )

    @app.post("/internal/v1/face/enrollments/extract", dependencies=[Depends(auth)])
    async def enroll(request: Request) -> dict:
        runtime: InferenceModels | None = app.state.models
        if runtime is None:
            raise handle_error(FaceServiceError("MODEL_NOT_READY", "models are not loaded", 503))
        if request.headers.get("content-type", "").split(";", 1)[0] not in {
            "video/webm",
            "video/mp4",
        }:
            raise handle_error(FaceServiceError("INVALID_MEDIA", "expected WebM or MP4 video"))
        try:
            body = await read_body(request)
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        observations = []
        container = None
        reviewed_count = 0
        try:
            container = __import__("av").open(io.BytesIO(body), mode="r")
            stream = container.streams.video[0]
            total = int(stream.frames or 0)
            if not total:
                total = sum(1 for _ in container.decode(video=0))
                container.seek(0)
            targets = (
                set(np.linspace(0, max(total - 1, 0), cfg.enrollment_frames, dtype=int).tolist())
                if total
                else None
            )
            for index, frame in enumerate(container.decode(video=0)):
                if targets is not None and index not in targets:
                    continue
                image = frame.to_ndarray(format="bgr24")
                reviewed_count += 1
                observations.extend(runtime.detect(image))
                image.fill(0)
            if not observations:
                raise FaceServiceError("NO_FACE", "no face was detected in the enrollment video")
            if observations and all("LOW_LIGHT" in quality_issues(o) for o in observations):
                raise FaceServiceError("LOW_LIGHT", "enrollment video is too dark")
            representatives = select_representatives(observations, cfg.representative_vectors)
            return {
                "model": metadata.__dict__,
                "reviewedFrames": reviewed_count,
                "acceptedFrames": len(
                    [o for o in observations if not quality_issues(o)]
                ),
                "vectors": [vector.tolist() for vector in representatives],
            }
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        except Exception as exc:
            raise handle_error(
                FaceServiceError("INVALID_MEDIA", "video could not be decoded")
            ) from exc
        finally:
            if container is not None:
                container.close()
            body = b""

    @app.post("/api/v1/face/registration", status_code=201)
    async def public_registration(
        request: Request,
        images: list[UploadFile] | None = File(None),
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, bool]:
        student_id = public_student_id(authorization)
        if student_id in registered_candidates:
            raise HTTPException(status_code=409, detail={"code": "FACE_ALREADY_REGISTERED"})
        runtime: InferenceModels | None = app.state.models
        if runtime is None:
            raise public_error(FaceServiceError("MODEL_NOT_READY", "models are not loaded", 500))
        decoded: list[np.ndarray] = []
        try:
            decoded = await read_images(images or [])
            observations = []
            for image in decoded:
                observations.extend(runtime.detect(image))
            if not observations:
                raise FaceServiceError("NO_FACE", "no face was detected")
            if all("LOW_LIGHT" in quality_issues(o) for o in observations):
                raise FaceServiceError("LOW_LIGHT", "images are too dark")
            vectors = select_representatives(observations, cfg.representative_vectors)
            async with lock:
                registered_candidates[student_id] = vectors
            return {"success": True}
        except FaceServiceError as exc:
            raise public_error(exc) from exc
        except Exception as exc:
            raise public_error(FaceServiceError("INTERNAL_ERROR", "face registration failed", 500)) from exc
        finally:
            for image in decoded:
                image.fill(0)
            decoded.clear()

    @app.get("/api/v1/face/detect", status_code=201)
    async def public_detect(
        request: Request,
        images: list[UploadFile] | None = File(None),
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        public_student_id(authorization)
        runtime: InferenceModels | None = app.state.models
        if runtime is None:
            raise public_error(FaceServiceError("MODEL_NOT_READY", "models are not loaded", 500))
        if not registered_candidates:
            raise public_error(FaceServiceError("NO_FACE", "no registered face data is available"))
        decoded: list[np.ndarray] = []
        try:
            decoded = await read_images(images or [])
            found: set[str] = set()
            for image in decoded:
                for observation in runtime.detect(image):
                    if observation.embedding is None or quality_issues(observation):
                        continue
                    if cfg.match_threshold is None or cfg.match_margin is None:
                        raise FaceServiceError("MODEL_NOT_READY", "threshold and margin are unset", 500)
                    outcome = match_embedding(
                        observation.embedding,
                        registered_candidates,
                        cfg.match_threshold,
                        cfg.match_margin,
                    )
                    if outcome.status == "KNOWN" and outcome.student_id is not None:
                        found.add(outcome.student_id)
            if len(found) != 1:
                raise FaceServiceError("NO_FACE", "no single known face was detected")
            student_id = next(iter(found))
            try:
                response_id: int | str = int(student_id)
            except ValueError:
                response_id = student_id
            return {"student_id": response_id, "success": True}
        except FaceServiceError as exc:
            raise public_error(exc) from exc
        finally:
            for image in decoded:
                image.fill(0)
            decoded.clear()

    @app.put("/internal/v1/face/sessions/{session_id}", dependencies=[Depends(auth)])
    async def put_session(session_id: str, payload: SessionPayload) -> dict[str, str]:
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
            raise handle_error(
                FaceServiceError("MODEL_MISMATCH", "duplicate student IDs are not allowed")
            )
        async with lock:
            sessions[session_id] = Session(candidates, TrackManager())
        return {"status": "ready"}

    @app.post("/internal/v1/face/sessions/{session_id}/frames", dependencies=[Depends(auth)])
    async def frame(
        session_id: str, request: Request, x_frame_id: Annotated[str, Header()] = ""
    ) -> dict:
        runtime: InferenceModels | None = app.state.models
        session = sessions.get(session_id)
        if runtime is None:
            raise handle_error(FaceServiceError("MODEL_NOT_READY", "models are not loaded", 503))
        if session is None:
            raise handle_error(FaceServiceError("SESSION_NOT_FOUND", "session is not active", 404))
        if request.headers.get("content-type", "").split(";", 1)[0] not in {
            "image/jpeg",
            "image/webp",
        }:
            raise handle_error(FaceServiceError("INVALID_MEDIA", "expected JPEG or WebP image"))
        try:
            body = await read_body(request)
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        image: np.ndarray | None = None
        try:
            image = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise FaceServiceError("INVALID_MEDIA", "frame is not a valid image")
            observations = runtime.detect(image)
            tracks = session.tracker.assign([observation.bbox for observation in observations])
            results = []
            for observation, track in zip(observations, tracks):
                issues = quality_issues(observation)
                if (
                    observation.embedding is None
                    or issues
                    or not session.tracker.observe_quality(track)
                ):
                    match = {"status": "NOT_ATTEMPTED", "studentId": None, "score": None}
                elif cfg.match_threshold is None or cfg.match_margin is None:
                    match = {"status": "NOT_ATTEMPTED", "studentId": None, "score": None}
                else:
                    outcome = match_embedding(
                        observation.embedding,
                        session.candidates,
                        cfg.match_threshold,
                        cfg.match_margin,
                    )
                    match = {
                        "status": outcome.status,
                        "studentId": outcome.student_id,
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
                        "quality": {
                            "brightness": observation.brightness,
                            "sharpness": observation.sharpness,
                            "issues": issues,
                        },
                        "recognition": match,
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
            body = b""

    @app.delete("/internal/v1/face/sessions/{session_id}", dependencies=[Depends(auth)])
    async def delete_session(session_id: str) -> dict[str, str]:
        session = sessions.pop(session_id, None)
        if session:
            session.tracker.reset()
            for vectors in session.candidates.values():
                for vector in vectors:
                    vector.fill(0)
        return {"status": "deleted"}

    return app


app = create_app()
