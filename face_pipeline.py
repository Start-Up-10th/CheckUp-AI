from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from face_models import EMBEDDING_DIMENSION, FaceObservation, ModelMetadata


class FaceServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Match:
    status: str
    student_id: str | None
    score: float | None
    margin: float | None


def normalize_vector(vector: Iterable[float], dimension: int = EMBEDDING_DIMENSION) -> np.ndarray:
    array = np.asarray(list(vector), dtype=np.float32)
    if array.shape != (dimension,) or not np.isfinite(array).all():
        raise FaceServiceError("MODEL_MISMATCH", "embedding dimension or values are invalid", 422)
    norm = float(np.linalg.norm(array))
    if norm == 0:
        raise FaceServiceError("MODEL_MISMATCH", "embedding cannot be zero", 422)
    return (array / norm).astype(np.float32, copy=True)


def quality_issues(observation: FaceObservation) -> list[str]:
    issues: list[str] = []
    if observation.brightness < 35:
        issues.append("LOW_LIGHT")
    if observation.sharpness < 40:
        issues.append("BLUR")
    if observation.bbox[2] < 0.08 or observation.bbox[3] < 0.08:
        issues.append("FACE_TOO_SMALL")
    if observation.pose_bucket == "extreme":
        issues.append("POSE")
    return issues


def select_representatives(
    observations: list[FaceObservation], count: int = 20, consistency_threshold: float = 0.55
) -> list[np.ndarray]:
    """Select diverse vectors for one identity; never merge unrelated faces."""

    candidates = [o for o in observations if o.embedding is not None and not quality_issues(o)]
    if len(candidates) < count:
        raise FaceServiceError("INSUFFICIENT_QUALITY_FRAMES", f"need {count} quality observations")
    vectors = np.stack([normalize_vector(o.embedding) for o in candidates])
    centroid = normalize_vector(np.mean(vectors, axis=0))
    coherent = vectors @ centroid >= consistency_threshold
    if int(coherent.sum()) < count or not coherent.all():
        raise FaceServiceError("MULTIPLE_IDENTITIES", "quality observations do not form one identity")
    vectors = vectors[coherent]
    chosen = [int(np.argmax(vectors @ centroid))]
    while len(chosen) < count:
        distances = 1.0 - vectors @ vectors[chosen].T
        score = distances.min(axis=1)
        score[chosen] = -1
        chosen.append(int(np.argmax(score)))
    return [vectors[index].astype(np.float32, copy=True) for index in chosen]


def match_embedding(
    probe: np.ndarray,
    candidates: dict[str, list[np.ndarray]],
    threshold: float,
    margin_threshold: float,
) -> Match:
    probe = normalize_vector(probe)
    scores: list[tuple[float, str]] = []
    for student_id, vectors in candidates.items():
        similarities = sorted(
            (float(probe @ normalize_vector(vector)) for vector in vectors), reverse=True
        )
        scores.append((float(np.mean(similarities[:3])), student_id))
    if not scores:
        return Match("UNKNOWN", None, None, None)
    scores.sort(reverse=True)
    best_score, best_id = scores[0]
    second = scores[1][0] if len(scores) > 1 else -1.0
    margin = best_score - second
    if best_score < threshold or margin < margin_threshold:
        return Match("UNKNOWN", None, best_score, margin)
    return Match("KNOWN", best_id, best_score, margin)


def validate_model(metadata: ModelMetadata, expected: ModelMetadata) -> None:
    if metadata != expected:
        raise FaceServiceError("MODEL_MISMATCH", "candidate vectors use a different model")


def clear_observations(observations: Iterable[FaceObservation]) -> None:
    """Best-effort clearing for request-scoped identity vectors."""

    for observation in observations:
        if observation.embedding is not None:
            observation.embedding.fill(0)
