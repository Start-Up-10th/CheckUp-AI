import numpy as np
import pytest

from face_models import FaceObservation, ModelMetadata
from face_pipeline import FaceServiceError, match_embedding, select_representatives, validate_model
from face_tracker import TrackManager


def vector(index: int) -> np.ndarray:
    value = np.zeros(256, dtype=np.float32)
    value[index] = 1.0
    return value


def observation(index: int, brightness: float = 100) -> FaceObservation:
    embedding = vector(0)
    embedding[(index + 1) % 256] = 0.05
    return FaceObservation((0.1, 0.1, 0.3, 0.3), tuple(), embedding, brightness, 100, "frontal")


def test_selects_twenty_diverse_representatives():
    result = select_representatives([observation(i % 256) for i in range(25)], 20)
    assert len(result) == 20
    assert all(np.isclose(np.linalg.norm(item), 1) for item in result)


def test_rejects_low_light_and_insufficient_samples():
    with pytest.raises(FaceServiceError, match="need 20"):
        select_representatives([observation(i, 20) for i in range(20)], 20)


def test_unknown_never_has_student_id():
    result = match_embedding(vector(0), {"student-a": [vector(1)]}, 0.9, 0.1)
    assert result.status == "UNKNOWN"
    assert result.student_id is None


def test_known_requires_margin():
    result = match_embedding(
        vector(0), {"student-a": [vector(0)], "student-b": [vector(0)]}, 0.5, 0.1
    )
    assert result.status == "UNKNOWN"
    assert result.student_id is None


def test_model_metadata_mismatch_is_rejected():
    with pytest.raises(FaceServiceError, match="different model"):
        validate_model(ModelMetadata(version="new"), ModelMetadata())


def test_track_failures_are_isolated_and_reset():
    manager = TrackManager()
    tracks = manager.assign([(0, 0, 1, 1), (2, 0, 1, 1)])
    assert manager.record_failure(tracks[0]) == 1
    assert manager.record_failure(tracks[0]) == 2
    assert manager.record_failure(tracks[0]) == 3
    assert manager.record_failure(tracks[0]) == 4
    assert tracks[1].failures == 0
    manager.record_success(tracks[0])
    assert tracks[0].failures == 0
