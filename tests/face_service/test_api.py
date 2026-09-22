from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from face_api import create_app
from face_config import Settings
from face_models import FaceObservation, ModelMetadata


def test_liveness_and_not_ready_without_models():
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503


class FakeModels:
    metadata = ModelMetadata()

    def detect(self, _image: np.ndarray) -> list[FaceObservation]:
        known = np.zeros(256, dtype=np.float32)
        known[0] = 1
        unknown = np.zeros(256, dtype=np.float32)
        unknown[1] = 1
        return [
            FaceObservation((0.1, 0.1, 0.2, 0.2), tuple(), known, 100, 100, "frontal"),
            FaceObservation((0.6, 0.1, 0.2, 0.2), tuple(), unknown, 100, 100, "frontal"),
        ]

    def close(self) -> None:
        pass


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
    setup_headers = {"Authorization": "Bearer test-token", "Content-Type": "application/json"}
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
        setup = client.put("/internal/v1/face/sessions/s1", headers=setup_headers, json=payload)
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


class SingleFakeModels:
    metadata = ModelMetadata()

    def detect(self, _image: np.ndarray) -> list[FaceObservation]:
        vector = np.zeros(256, dtype=np.float32)
        vector[0] = 1
        return [FaceObservation((0.1, 0.1, 0.5, 0.5), tuple(), vector, 100, 100, "frontal")]

    def close(self) -> None:
        pass


def test_public_registration_and_detect_match_multipart_contract():
    settings = Settings(
        landmarker_path=Path("missing-landmarker.task"),
        embedding_model_path=Path("missing-embedding.xml"),
        service_token="access-token",
        student_token_map={"access-token": "123"},
        match_threshold=0.5,
        match_margin=0.1,
    )
    app = create_app(settings, SingleFakeModels())
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", image)
    headers = {"Authorization": "Bearer access-token"}
    files = [("images", ("face.jpg", encoded.tobytes(), "image/jpeg")) for _ in range(20)]
    with TestClient(app) as client:
        registration = client.post("/api/v1/face/registration", headers=headers, files=files)
        assert registration.status_code == 201
        assert registration.json() == {"success": True}
        detected = client.request("GET", "/api/v1/face/detect", headers=headers, files=files[:1])
        assert detected.status_code == 201
        assert detected.json() == {"student_id": 123, "success": True}
        duplicate = client.post("/api/v1/face/registration", headers=headers, files=files)
        assert duplicate.status_code == 409
