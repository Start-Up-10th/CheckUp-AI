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
            FaceObservation((0.1, 0.1, 0.2, 0.2), ((1.0, 1.0),), known, 100, 100, "frontal"),
            FaceObservation((0.6, 0.1, 0.2, 0.2), ((2.0, 2.0),), unknown, 100, 100, "frontal"),
        ]

    def close(self) -> None:
        pass


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
