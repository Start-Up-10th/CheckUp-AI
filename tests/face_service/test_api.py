from fastapi.testclient import TestClient

from face_api import create_app


def test_liveness_and_not_ready_without_models():
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
