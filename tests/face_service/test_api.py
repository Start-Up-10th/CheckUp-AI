import io
from pathlib import Path

import cv2
import numpy as np
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

    def detect(self, _image: np.ndarray) -> list[FaceObservation]:
        embedding = np.zeros(256, dtype=np.float32)
        embedding[0] = 1
        return [FaceObservation((0.1, 0.1, 0.2, 0.2), ((8.0, 8.0),), embedding, 100, 100, "frontal")]

    def close(self) -> None:
        pass


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
        "candidates": [{"student_id": "student-a", "vectors": [[1.0] + [0.0] * 255]}],
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
        assert results[0]["recognition"]["studentId"] == "student-a"
        assert results[1]["recognition"]["status"] == "UNKNOWN"
        assert results[1]["recognition"]["studentId"] is None
        assert results[0]["landmarks"] == [[1.25, 2.5]]


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


def test_internal_enrollment_rejects_datagsm_user_token():
    settings = Settings(
        landmarker_path=Path("missing-landmarker.task"),
        embedding_model_path=Path("missing-embedding.xml"),
        service_token="service-token",
    )
    app = create_app(settings, EnrollmentFakeModels())
    with TestClient(app) as client:
        response = client.post(
            "/internal/v1/face/enrollments/extract",
            headers={
                "Authorization": "Bearer datagsm-user-token",
                "Content-Type": "video/mp4",
            },
            content=make_test_mp4(),
        )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


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
