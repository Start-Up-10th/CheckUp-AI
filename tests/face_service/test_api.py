import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from face_api import create_app
from face_config import Settings
from face_models import FaceObservation, ModelMetadata


class FakeModels:
    metadata = ModelMetadata()

    def detect(self, _image: np.ndarray) -> list[FaceObservation]:
        known = np.zeros(256, dtype=np.float32)
        known[0] = 1
        unknown = np.zeros(256, dtype=np.float32)
        unknown[1] = 1
        return [
            FaceObservation(
                (0.1, 0.1, 0.2, 0.2), ((np.float32(1.25), np.float32(2.5)),),
                known, 100, 100, "frontal"
            ),
            FaceObservation((0.6, 0.1, 0.2, 0.2), ((2.0, 2.0),), unknown, 100, 100, "frontal"),
        ]

    def close(self) -> None:
        pass


class EnrollmentFakeModels:
    metadata = ModelMetadata()

    def __init__(self) -> None:
        self.detect_calls = 0

    def detect(self, _image: np.ndarray) -> list[FaceObservation]:
        self.detect_calls += 1
        embedding = np.zeros(256, dtype=np.float32)
        embedding[0] = 1
        return [FaceObservation((0.1, 0.1, 0.2, 0.2), ((8.0, 8.0),), embedding, 100, 100, "frontal")]

    def close(self) -> None:
        pass


class BoundaryModels(EnrollmentFakeModels):
    def detect(self, image: np.ndarray) -> list[FaceObservation]:
        height, width = image.shape[:2]
        return [FaceObservation((0.95, 0.9, 0.2, 0.2), ((-2.0, height + 2.0),), None,
                                100, 100, "frontal")]


class FailingModels(EnrollmentFakeModels):
    def detect(self, _image: np.ndarray) -> list[FaceObservation]:
        raise RuntimeError("synthetic inference failure")


def make_test_mp4(frame_count: int = 3) -> bytes:
    import av

    output = io.BytesIO()
    with av.open(output, mode="w", format="mp4") as container:
        stream = container.add_stream("mpeg4", rate=5)
        stream.width = 64
        stream.height = 64
        stream.pix_fmt = "yuv420p"
        for _ in range(frame_count):
            frame = av.VideoFrame.from_ndarray(
                np.full((64, 64, 3), 127, dtype=np.uint8), format="bgr24"
            )
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return output.getvalue()


def test_liveness_and_not_ready_without_models():
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503


def test_frame_results_are_per_face_and_unknown_is_null():
    settings = Settings(
        landmarker_path=Path("missing-landmarker.task"),
        embedding_model_path=Path("missing-embedding.xml"),
        service_token="test-token",
        match_threshold=0.5,
        match_margin=0.1,
    )
    app = create_app(settings, FakeModels())
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", image)
    headers = {"Authorization": "Bearer test-token", "Content-Type": "image/jpeg"}
    payload = {
        "model": {
            "model_id": "openvino/face-reidentification-retail-0095",
            "version": settings.model_version,
            "dimension": 256,
            "normalization": "l2",
        },
        "candidates": [{"student_id": "9007199254740993", "vectors": [[1.0] + [0.0] * 255]}],
    }
    with TestClient(app) as client:
        setup = client.put(
            "/internal/v1/face/sessions/s1",
            headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            json=payload,
        )
        assert setup.status_code == 200
        response = None
        for index in range(3):
            response = client.post(
                "/internal/v1/face/sessions/s1/frames",
                headers={**headers, "X-Frame-Id": str(index)},
                content=encoded.tobytes(),
            )
        assert response is not None and response.status_code == 200
        results = response.json()["faces"]
        assert len(results) == 2
        assert results[0]["recognition"]["studentId"] == "9007199254740993"
        assert results[1]["recognition"]["status"] == "UNKNOWN"
        assert results[1]["recognition"]["studentId"] is None
        assert results[0]["landmarks"] == [[1.25, 2.5]]
        deleted = client.delete(
            "/internal/v1/face/sessions/s1",
            headers={"Authorization": "Bearer test-token"},
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"status": "deleted"}


def test_candidate_rejects_numeric_student_id():
    settings = Settings(
        landmarker_path=Path("missing-landmarker.task"),
        embedding_model_path=Path("missing-embedding.xml"),
        service_token="test-token",
    )
    app = create_app(settings, FakeModels())
    payload = {
        "model": {
            "model_id": "openvino/face-reidentification-retail-0095",
            "version": settings.model_version,
            "dimension": 256,
            "normalization": "l2",
        },
        "candidates": [{"student_id": 9007199254740993, "vectors": [[1.0] + [0.0] * 255]}],
    }
    with TestClient(app) as client:
        response = client.put(
            "/internal/v1/face/sessions/s1",
            headers={"Authorization": "Bearer test-token"},
            json=payload,
        )
    assert response.status_code == 422


def test_frame_coordinates_are_clipped_to_image_bounds():
    settings = Settings(
        landmarker_path=Path("missing-landmarker.task"),
        embedding_model_path=Path("missing-embedding.xml"),
        service_token="test-token",
    )
    app = create_app(settings, BoundaryModels())
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", image)
    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "model": {
            "model_id": "openvino/face-reidentification-retail-0095",
            "version": settings.model_version,
            "dimension": 256,
            "normalization": "l2",
        },
        "candidates": [],
    }
    with TestClient(app) as client:
        assert client.put("/internal/v1/face/sessions/bounds", headers=headers, json=payload).status_code == 200
        response = client.post(
            "/internal/v1/face/sessions/bounds/frames",
            headers={**headers, "Content-Type": "image/jpeg"},
            content=encoded.tobytes(),
        )

    assert response.status_code == 200
    face = response.json()["faces"][0]
    assert face["bbox"] == pytest.approx([0.95, 0.9, 0.05, 0.1])
    assert face["landmarks"] == [[0.0, 64.0]]


def test_inference_failures_return_json_500_while_invalid_video_returns_400():
    settings = Settings(
        landmarker_path=Path("missing-landmarker.task"),
        embedding_model_path=Path("missing-embedding.xml"),
        service_token="test-token",
        representative_vectors=1,
        enrollment_frames=1,
    )
    app = create_app(settings, FailingModels())
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", image)
    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "model": {
            "model_id": "openvino/face-reidentification-retail-0095",
            "version": settings.model_version,
            "dimension": 256,
            "normalization": "l2",
        },
        "candidates": [],
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        client.put("/internal/v1/face/sessions/errors", headers=headers, json=payload)
        frame = client.post(
            "/internal/v1/face/sessions/errors/frames",
            headers={**headers, "Content-Type": "image/jpeg"},
            content=encoded.tobytes(),
        )
        enrollment = client.post(
            "/internal/v1/face/enrollments/extract",
            headers={**headers, "Content-Type": "video/mp4"},
            content=make_test_mp4(1),
        )
        invalid_video = client.post(
            "/internal/v1/face/enrollments/extract",
            headers={**headers, "Content-Type": "video/mp4"},
            content=b"not a video",
        )

    for response in (frame, enrollment):
        assert response.status_code == 500
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["detail"]["code"] == "INTERNAL_ERROR"
    assert invalid_video.status_code == 400
    assert invalid_video.json()["detail"]["code"] == "INVALID_MEDIA"


def test_idle_session_cleanup_clears_cached_vectors():
    now = [100.0]
    settings = Settings(
        landmarker_path=Path("missing-landmarker.task"),
        embedding_model_path=Path("missing-embedding.xml"),
        service_token="test-token",
        session_idle_seconds=5,
    )
    app = create_app(settings, EnrollmentFakeModels(), monotonic=lambda: now[0])
    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "model": {
            "model_id": "openvino/face-reidentification-retail-0095",
            "version": settings.model_version,
            "dimension": 256,
            "normalization": "l2",
        },
        "candidates": [{"student_id": "student-test", "vectors": [[1.0] + [0.0] * 255]}],
    }
    with TestClient(app) as client:
        assert client.put("/internal/v1/face/sessions/expired", headers=headers, json=payload).status_code == 200
        cached_vector = app.state.sessions["expired"].candidates["student-test"][0]
        now[0] += 6

        assert app.state.cleanup_expired_sessions() == 1
        assert "expired" not in app.state.sessions
        assert not cached_vector.any()
        expired_frame = client.post(
            "/internal/v1/face/sessions/expired/frames",
            headers={**headers, "Content-Type": "image/jpeg"},
            content=b"not-an-image",
        )

    assert expired_frame.status_code == 404


def test_internal_enrollment_extract_accepts_raw_video_with_service_token():
    settings = Settings(
        landmarker_path=Path("missing-landmarker.task"),
        embedding_model_path=Path("missing-embedding.xml"),
        service_token="service-token",
        representative_vectors=20,
        enrollment_frames=20,
    )
    app = create_app(settings, EnrollmentFakeModels())
    with TestClient(app) as client:
        response = client.post(
            "/internal/v1/face/enrollments/extract",
            headers={
                "Authorization": "Bearer service-token",
                "Content-Type": "video/mp4",
            },
            content=make_test_mp4(frame_count=20),
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["model"]["dimension"] == 256
    assert payload["reviewedFrames"] == 20
    assert payload["acceptedFrames"] == 20
    assert len(payload["vectors"]) == 20
    assert all(len(vector) == 256 for vector in payload["vectors"])


@pytest.mark.parametrize(
    ("method", "path", "request_kwargs"),
    [
        (
            "POST",
            "/internal/v1/face/enrollments/extract",
            {"headers": {"Content-Type": "video/mp4"}, "content": b"too-large"},
        ),
        (
            "PUT",
            "/internal/v1/face/sessions/auth-check",
            {
                "headers": {"Content-Type": "application/json"},
                "content": b"{",
            },
        ),
        (
            "POST",
            "/internal/v1/face/sessions/auth-check/frames",
            {
                "headers": {"Content-Type": "image/jpeg", "X-Frame-Id": "frame-1"},
                "content": b"too-large",
            },
        ),
        ("DELETE", "/internal/v1/face/sessions/auth-check", {}),
    ],
)
@pytest.mark.parametrize(
    ("credential_headers", "cookies"),
    [
        ({}, None),
        ({"Authorization": "Bearer wrong-service-token"}, None),
        ({"Authorization": "Bearer datagsm-user-token"}, None),
        ({}, {"SESSION": "browser-session-token"}),
    ],
    ids=["missing", "wrong-service-token", "datagsm-access-token", "browser-session-cookie"],
)
def test_internal_routes_require_service_bearer_before_processing_request(
    method, path, request_kwargs, credential_headers, cookies
):
    settings = Settings(
        landmarker_path=Path("missing-landmarker.task"),
        embedding_model_path=Path("missing-embedding.xml"),
        service_token="service-token",
        max_body_bytes=1,
    )
    models = EnrollmentFakeModels()
    app = create_app(settings, models)
    kwargs = dict(request_kwargs)
    headers = {**kwargs.pop("headers", {}), **credential_headers}

    with TestClient(app) as client:
        if cookies is not None:
            client.cookies.set("SESSION", cookies["SESSION"])
        response = client.request(method, path, headers=headers, **kwargs)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"
    assert all(
        token not in response.text
        for token in ("service-token", "wrong-service-token", "datagsm-user-token", "browser-session-token")
    )
    assert models.detect_calls == 0


def test_openapi_documents_internal_service_bearer_and_no_public_oauth_routes():
    app = create_app()
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
        assert client.post("/api/v1/face/registration").status_code == 404
        assert client.get("/api/v1/face/detect").status_code == 404

    assert set(schema["components"]["securitySchemes"]) == {"serviceBearer"}
    bearer = schema["components"]["securitySchemes"]["serviceBearer"]
    assert bearer["type"] == "http"
    assert bearer["scheme"] == "bearer"
    candidate_id = schema["components"]["schemas"]["Candidate"]["properties"]["student_id"]
    assert candidate_id["type"] == "string"
    assert "canonical ID" in candidate_id["description"]
    for path, methods in schema["paths"].items():
        if path.startswith("/internal/"):
            for operation in methods.values():
                assert operation["security"] == [{"serviceBearer": []}]

    enrollment = schema["paths"]["/internal/v1/face/enrollments/extract"]["post"]
    assert set(enrollment["requestBody"]["content"]) == {"video/webm", "video/mp4"}
    assert set(enrollment["responses"]) >= {"200", "400", "401", "413", "422", "500", "503"}
    enrollment_schema = schema["components"]["schemas"]["EnrollmentResponse"]
    assert enrollment_schema["properties"]["vectors"]["minItems"] == 1
    assert enrollment_schema["properties"]["vectors"]["maxItems"] == 20

    frames = schema["paths"]["/internal/v1/face/sessions/{session_id}/frames"]["post"]
    assert set(frames["requestBody"]["content"]) == {"image/jpeg", "image/webp"}
    assert "/api/v1/face/registration" not in schema["paths"]
    assert "/api/v1/face/detect" not in schema["paths"]
    assert not any(path.startswith("/api/v1/auth/") for path in schema["paths"])
