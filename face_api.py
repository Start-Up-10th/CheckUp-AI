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
            runtime = InferenceModels(str(cfg.landmarker_path), str(cfg.embedding_model_path), metadata)
        app.state.models = runtime
        app.state.sessions = sessions
        yield
        for session in sessions.values():
            session.tracker.reset()
            _clear_vectors(session.candidates)
        sessions.clear()
        _clear_vectors(registered_candidates)
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
        if not token or not accepted or token not in accepted:
            raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED"})
        return token

    def public_student_id(authorization: str | None) -> str:
        token = public_token(authorization)
        student_id = cfg.student_token_map.get(token)
        if not student_id:
            raise HTTPException(status_code=403, detail={"code": "STUDENT_NOT_FOUND"})
        return student_id

    def handle_error(exc: FaceServiceError) -> HTTPException:
        return HTTPException(
            status_code=exc.status, detail={"code": exc.code, "message": exc.message}
        )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> Response:
        if getattr(app.state, "models", None) is None or not cfg.ready_for_inference:
            return Response(status_code=503, content='{"status":"not_ready"}', media_type="application/json")
        return Response(status_code=200, content='{"status":"ready"}', media_type="application/json")

    async def read_images(images: list[UploadFile]) -> list[np.ndarray]:
        if not images:
            raise FaceServiceError("INVALID_MEDIA", "images must contain at least one file", 400)
        decoded: list[np.ndarray] = []
        try:
            for upload in images:
                if upload.content_type not in {"image/jpeg", "image/webp", "image/png"}:
                    raise FaceServiceError("INVALID_MEDIA", "images must be JPEG, WebP, or PNG", 400)
                raw = bytearray(await upload.read())
                try:
                    if len(raw) > cfg.max_body_bytes:
                        raise FaceServiceError("PAYLOAD_TOO_LARGE", "image exceeds configured limit", 400)
                    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
                finally:
                    raw[:] = b"\x00" * len(raw)
                if image is None:
                    raise FaceServiceError("INVALID_MEDIA", "one image is not decodable", 400)
                decoded.append(image)
            return decoded
        except Exception:
            _clear_images(decoded)
            raise
        finally:
            for upload in images:
                await upload.close()

    async def read_body(request: Request) -> bytearray:
        data = bytearray()
        try:
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > cfg.max_body_bytes:
                    raise FaceServiceError("PAYLOAD_TOO_LARGE", "request body exceeds configured limit", 413)
            return data
        except Exception:
            data[:] = b"\x00" * len(data)
            raise

    @app.post("/internal/v1/face/enrollments/extract", dependencies=[Depends(auth)])
    async def enroll(request: Request) -> dict[str, object]:
        runtime: InferenceModels | None = app.state.models
        if runtime is None:
            raise handle_error(FaceServiceError("MODEL_NOT_READY", "models are not loaded", 503))
        if request.headers.get("content-type", "").split(";", 1)[0] not in {"video/webm", "video/mp4"}:
            raise handle_error(FaceServiceError("INVALID_MEDIA", "expected WebM or MP4 video", 400))
        body: bytearray | None = None
        container = None
        observations: list[FaceObservation] = []
        vectors: list[np.ndarray] = []
        try:
            body = await read_body(request)
            container = __import__("av").open(io.BytesIO(body), mode="r")
            stream = container.streams.video[0]
            total = int(stream.frames or 0)
            targets = _sample_indices(total, cfg.enrollment_frames) if total else None
            tracks = TrackManager()
            per_track: dict[str, list[FaceObservation]] = {}
            reviewed_count = 0
            for index, frame in enumerate(container.decode(video=0)):
                if targets is not None and index not in targets:
                    continue
                if targets is None and reviewed_count >= cfg.enrollment_frames:
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
            # Enrollment is for one student. A second tracked face must never be
            # silently treated as background or folded into the student's vectors.
            if len(per_track) > 1:
                raise FaceServiceError(
                    "MULTIPLE_IDENTITIES", "enrollment must contain one face identity"
                )
            viable = {
                track_id: items
                for track_id, items in per_track.items()
                if sum(not quality_issues(item) for item in items) >= cfg.representative_vectors
            }
            if not viable:
                if observations and all("LOW_LIGHT" in quality_issues(item) for item in observations):
                    raise FaceServiceError("LOW_LIGHT", "enrollment video is too dark")
                raise FaceServiceError(
                    "INSUFFICIENT_QUALITY_FRAMES",
                    f"need {cfg.representative_vectors} quality observations",
                )
            if len(viable) != 1:
                raise FaceServiceError("MULTIPLE_IDENTITIES", "enrollment must contain one face identity")
            vectors = select_representatives(next(iter(viable.values())), cfg.representative_vectors)
            return {
                "model": metadata.__dict__,
                "reviewedFrames": reviewed_count,
                "acceptedFrames": sum(not quality_issues(item) for item in observations),
                "vectors": [vector.tolist() for vector in vectors],
            }
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        except Exception as exc:
            raise handle_error(FaceServiceError("INVALID_MEDIA", "video could not be decoded", 400)) from exc
        finally:
            if container is not None:
                container.close()
            clear_observations(observations)
            _clear_vectors({"temporary": vectors})
            if body is not None:
                body[:] = b"\x00" * len(body)

    @app.post("/api/v1/face/registration", status_code=201)
    async def public_registration(
        images: list[UploadFile] | None = File(None),
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, bool]:
        student_id = public_student_id(authorization)
        if student_id in registered_candidates:
            raise HTTPException(status_code=409, detail={"code": "FACE_ALREADY_REGISTERED"})
        runtime: InferenceModels | None = app.state.models
        if runtime is None:
            raise handle_error(FaceServiceError("MODEL_NOT_READY", "models are not loaded", 500))
        decoded: list[np.ndarray] = []
        observations: list[FaceObservation] = []
        vectors: list[np.ndarray] = []
        try:
            decoded = await read_images(images or [])
            for image in decoded:
                observations.extend(runtime.detect(image))
            if not observations:
                raise FaceServiceError("NO_FACE", "no face was detected")
            if all("LOW_LIGHT" in quality_issues(item) for item in observations):
                raise FaceServiceError("LOW_LIGHT", "images are too dark")
            vectors = select_representatives(observations, cfg.representative_vectors)
            async with lock:
                registered_candidates[student_id] = vectors
            vectors = []
            return {"success": True}
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        except Exception as exc:
            raise handle_error(FaceServiceError("INTERNAL_ERROR", "face registration failed", 500)) from exc
        finally:
            _clear_images(decoded)
            clear_observations(observations)
            _clear_vectors({"temporary": vectors})

    @app.get("/api/v1/face/detect", status_code=201)
    async def public_detect(
        images: list[UploadFile] | None = File(None),
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        public_student_id(authorization)
        runtime: InferenceModels | None = app.state.models
        if runtime is None:
            raise handle_error(FaceServiceError("MODEL_NOT_READY", "models are not loaded", 500))
        if not registered_candidates:
            raise handle_error(FaceServiceError("NO_FACE", "no registered face data is available"))
        decoded: list[np.ndarray] = []
        observations: list[FaceObservation] = []
        try:
            decoded = await read_images(images or [])
            faces: list[dict[str, object]] = []
            for image in decoded:
                found = runtime.detect(image)
                observations.extend(found)
                for index, observation in enumerate(found):
                    recognition = _recognize(observation, registered_candidates, cfg)
                    faces.append({"faceIndex": index, "bbox": observation.bbox, "recognition": recognition})
            if not faces:
                raise FaceServiceError("NO_FACE", "no face was detected")
            # Preserve the legacy scalar response only for exactly one known face.
            known = [item["recognition"] for item in faces if item["recognition"]["status"] == "KNOWN"]
            if len(faces) == 1 and len(known) == 1:
                value = known[0]["studentId"]
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    pass
                return {"student_id": value, "success": True, "faces": faces}
            return {"success": any(item["recognition"]["status"] == "KNOWN" for item in faces), "faces": faces}
        except FaceServiceError as exc:
            raise handle_error(exc) from exc
        finally:
            _clear_images(decoded)
            clear_observations(observations)

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
            raise handle_error(FaceServiceError("MODEL_MISMATCH", "duplicate student IDs are not allowed"))
        async with lock:
            old = sessions.get(session_id)
            if old is not None:
                old.tracker.reset()
                _clear_vectors(old.candidates)
            sessions[session_id] = Session(candidates, TrackManager())
        return {"status": "ready"}

    @app.post("/internal/v1/face/sessions/{session_id}/frames", dependencies=[Depends(auth)])
    async def frame(
        session_id: str, request: Request, x_frame_id: Annotated[str, Header()] = ""
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
                        "landmarks": observation.landmarks,
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

    @app.delete("/internal/v1/face/sessions/{session_id}", dependencies=[Depends(auth)])
    async def delete_session(session_id: str) -> dict[str, str]:
        session = sessions.pop(session_id, None)
        if session:
            session.tracker.reset()
            _clear_vectors(session.candidates)
        return {"status": "deleted"}

    return app


def _sample_indices(total: int, count: int) -> set[int]:
    if total <= 0:
        return set()
    return set(np.linspace(0, total - 1, min(total, count), dtype=int).tolist())


def _recognize(observation: FaceObservation, candidates: dict[str, list[np.ndarray]], cfg: Settings) -> dict[str, object]:
    issues = quality_issues(observation)
    if observation.embedding is None or issues or cfg.match_threshold is None or cfg.match_margin is None:
        return {"status": "NOT_ATTEMPTED", "studentId": None, "score": None, "margin": None}
    outcome = match_embedding(observation.embedding, candidates, cfg.match_threshold, cfg.match_margin)
    return {
        "status": outcome.status,
        "studentId": outcome.student_id if outcome.status == "KNOWN" else None,
        "score": outcome.score,
        "margin": outcome.margin,
    }


def _clear_images(images: list[np.ndarray]) -> None:
    for image in images:
        image.fill(0)
    images.clear()


def _clear_vectors(groups: dict[str, list[np.ndarray]]) -> None:
    for vectors in groups.values():
        for vector in vectors:
            vector.fill(0)


app = create_app()
