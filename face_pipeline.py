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


@dataclass
class CandidateGallery:
    """Session-owned normalized templates, prepared once and scrubbed on retirement."""

    student_ids: tuple[str, ...]
    vectors: np.ndarray
    counts: np.ndarray
    cleared: bool = False

    @classmethod
    def from_candidates(cls, candidates: dict[str, list[Iterable[float]]]) -> CandidateGallery:
        student_ids = tuple(candidates)
        vectors = np.zeros((len(student_ids), 20, EMBEDDING_DIMENSION), dtype=np.float32)
        counts = np.zeros(len(student_ids), dtype=np.int32)
        try:
            for index, items in enumerate(candidates.values()):
                if not 1 <= len(items) <= 20:
                    raise FaceServiceError("MODEL_MISMATCH", "need 1 to 20 vectors per candidate")
                counts[index] = len(items)
                for offset, vector in enumerate(items):
                    normalized = normalize_vector(vector)
                    try:
                        vectors[index, offset] = normalized
                    finally:
                        normalized.fill(0)
            return cls(student_ids, vectors, counts)
        except BaseException:
            vectors.fill(0)
            counts.fill(0)
            raise

    def clear(self) -> None:
        self.vectors.fill(0)
        self.counts.fill(0)
        self.cleared = True

    def match(self, probe: np.ndarray, threshold: float, margin_threshold: float) -> Match:
        if self.cleared:
            raise FaceServiceError("SESSION_NOT_FOUND", "candidate gallery was retired", 404)
        normalized = normalize_vector(probe)
        try:
            if not self.student_ids:
                return Match("UNKNOWN", None, None, None)
            similarities = self.vectors @ normalized
            valid = np.arange(20)[None, :] < self.counts[:, None]
            similarities[~valid] = -np.inf
            top = np.partition(similarities, 17, axis=1)[:, -3:]
            top = np.where(np.isfinite(top), top, 0.0)
            values = top.sum(axis=1, dtype=np.float64) / np.minimum(self.counts, 3)
            scores = sorted(zip(values.tolist(), self.student_ids, strict=True), reverse=True)
            best, _ = scores[0]
            second = scores[1][0] if len(scores) > 1 else -1.0
            # Batched float32 reductions may differ in their last bits from scalar dot.
            # Recheck decisions/rankings close to a boundary using the legacy arithmetic.
            if (
                abs(best - threshold) <= 1e-4
                or abs(best - second - margin_threshold) <= 2e-4
                or (len(scores) > 1 and abs(best - second) <= 2e-4)
            ):
                scores = []
                for index, student_id in enumerate(self.student_ids):
                    scalar = sorted(
                        (float(normalized @ vector) for vector in self.vectors[index, :self.counts[index]]),
                        reverse=True,
                    )
                    scores.append((float(np.mean(scalar[:3])), student_id))
                scores.sort(reverse=True)
            return _match_scores(scores, threshold, margin_threshold)
        finally:
            normalized.fill(0)


def normalize_vector(vector: Iterable[float], dimension: int = EMBEDDING_DIMENSION) -> np.ndarray:
    array = np.asarray(list(vector), dtype=np.float32)
    try:
        if array.shape != (dimension,) or not np.isfinite(array).all():
            raise FaceServiceError("MODEL_MISMATCH", "embedding dimension or values are invalid", 422)
        norm = float(np.linalg.norm(array))
        if not np.isfinite(norm) or norm == 0:
            raise FaceServiceError("MODEL_MISMATCH", "embedding norm is invalid", 422)
        normalized = array / norm
        try:
            return normalized.astype(np.float32, copy=True)
        finally:
            normalized.fill(0)
    finally:
        array.fill(0)


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
    return _match_scores(scores, threshold, margin_threshold)


def _match_scores(
    scores: list[tuple[float, str]], threshold: float, margin_threshold: float
) -> Match:
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
