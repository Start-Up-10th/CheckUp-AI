from __future__ import annotations

import numpy as np
import pytest

import face_pipeline
from face_models import EMBEDDING_DIMENSION
from face_pipeline import (
    CandidateGallery,
    FaceServiceError,
    Match,
    match_embedding,
    normalize_vector,
)


def unit_vector(index: int = 0, scale: float = 1.0) -> np.ndarray:
    value = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
    value[index] = scale
    return value


def cosine_vector(score: float) -> np.ndarray:
    value = unit_vector(scale=score)
    value[1] = np.sqrt(1.0 - score * score)
    return value


def assert_parity(actual: Match, expected: Match, *, exact: bool = False) -> None:
    assert actual.status == expected.status
    assert actual.student_id == expected.student_id
    if expected.score is None:
        assert actual.score is None
        assert actual.margin is None
    elif exact:
        assert actual.score == expected.score
        assert actual.margin == expected.margin
    else:
        assert actual.score == pytest.approx(expected.score, abs=1e-6)
        assert actual.margin == pytest.approx(expected.margin, abs=2e-6)


@pytest.mark.parametrize("student_count", [1, 50, 200])
@pytest.mark.parametrize("vector_count", [1, 2, 3, 20])
@pytest.mark.parametrize("stored_normalized", [False, True])
def test_batched_matching_matches_scalar_for_known_and_unknown_probes(
    student_count: int, vector_count: int, stored_normalized: bool
):
    rng = np.random.default_rng(1200 + student_count + vector_count)
    centers = rng.normal(size=(student_count, EMBEDDING_DIMENSION)).astype(np.float32)
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    candidates = {}
    for index, center in enumerate(centers):
        candidates[f"synthetic-{index:03}"] = [
            (center + rng.normal(0, 0.015, EMBEDDING_DIMENSION).astype(np.float32))
            * rng.uniform(0.25, 8.0)
            for _ in range(vector_count)
        ]
    if stored_normalized:
        candidates = {
            student_id: [normalize_vector(vector) for vector in vectors]
            for student_id, vectors in candidates.items()
        }
    gallery = CandidateGallery.from_candidates(candidates)
    try:
        for probe in (centers[-1] * 4.0, rng.normal(size=EMBEDDING_DIMENSION)):
            expected = match_embedding(probe, candidates, 0.6, 0.1)
            assert_parity(gallery.match(probe, 0.6, 0.1), expected)
    finally:
        gallery.clear()


def test_empty_gallery_has_no_guessed_identity_or_scores():
    gallery = CandidateGallery.from_candidates({})
    assert gallery.match(unit_vector(), 0.6, 0.1) == Match("UNKNOWN", None, None, None)
    assert gallery.vectors.shape == (0, 20, EMBEDDING_DIMENSION)
    gallery.clear()


@pytest.mark.parametrize("vector_count", [1, 2, 3, 20])
def test_padding_cannot_replace_negative_cosine_scores(vector_count: int):
    candidates = {"synthetic": [cosine_vector(-0.9 + index * 0.01) for index in range(vector_count)]}
    gallery = CandidateGallery.from_candidates(candidates)
    try:
        expected = match_embedding(unit_vector(), candidates, -0.95, 0.0)
        assert expected.score < 0
        assert expected.margin == pytest.approx(expected.score + 1.0)
        assert_parity(gallery.match(unit_vector(), -0.95, 0.0), expected)
    finally:
        gallery.clear()


def test_top_three_average_is_per_student_and_excludes_lower_vectors():
    candidates = {
        "synthetic-a": [cosine_vector(value) for value in [0.95, 0.8, 0.7, -0.9]],
        "synthetic-b": [cosine_vector(0.79)] * 20,
    }
    gallery = CandidateGallery.from_candidates(candidates)
    try:
        expected = match_embedding(unit_vector(), candidates, 0.6, 0.02)
        assert expected.student_id == "synthetic-a"
        assert expected.score == pytest.approx((0.95 + 0.8 + 0.7) / 3, abs=1e-6)
        assert_parity(gallery.match(unit_vector(), 0.6, 0.02), expected)
    finally:
        gallery.clear()


def test_exact_ties_keep_legacy_reverse_id_order_and_margin_rejection():
    candidates = {student_id: [cosine_vector(0.75)] for student_id in ["synthetic-a", "synthetic-z"]}
    gallery = CandidateGallery.from_candidates(candidates)
    try:
        known = gallery.match(unit_vector(), 0.6, 0.0)
        assert known.student_id == "synthetic-z"
        assert known.margin == 0.0
        assert_parity(known, match_embedding(unit_vector(), candidates, 0.6, 0.0), exact=True)
        unknown = gallery.match(unit_vector(), 0.6, 0.1)
        assert unknown.status == "UNKNOWN"
        assert unknown.student_id is None
    finally:
        gallery.clear()


@pytest.mark.parametrize("vector_count", [1, 3, 20])
def test_threshold_and_margin_boundaries_use_exact_scalar_decisions(vector_count: int):
    rng = np.random.default_rng(42 + vector_count)
    probe = rng.normal(size=EMBEDDING_DIMENSION).astype(np.float32)
    candidates = {
        "synthetic-a": [probe + rng.normal(0, 0.2, EMBEDDING_DIMENSION) for _ in range(vector_count)],
        "synthetic-b": [rng.normal(size=EMBEDDING_DIMENSION) for _ in range(vector_count)],
    }
    gallery = CandidateGallery.from_candidates(candidates)
    try:
        reference = match_embedding(probe, candidates, -1.0, 0.0)
        for threshold in [
            np.nextafter(reference.score, -np.inf),
            reference.score,
            np.nextafter(reference.score, np.inf),
        ]:
            assert_parity(
                gallery.match(probe, threshold, 0.0),
                match_embedding(probe, candidates, threshold, 0.0),
                exact=True,
            )
        for margin in [
            np.nextafter(reference.margin, -np.inf),
            reference.margin,
            np.nextafter(reference.margin, np.inf),
        ]:
            assert_parity(
                gallery.match(probe, -1.0, margin),
                match_embedding(probe, candidates, -1.0, margin),
                exact=True,
            )
    finally:
        gallery.clear()


def test_close_competitors_preserve_identity_order_even_with_permissive_margin():
    candidates = {
        "synthetic-z": [cosine_vector(0.75000)],
        "synthetic-a": [cosine_vector(0.75001)],
    }
    gallery = CandidateGallery.from_candidates(candidates)
    try:
        assert_parity(
            gallery.match(unit_vector(), 0.6, 0.0),
            match_embedding(unit_vector(), candidates, 0.6, 0.0),
            exact=True,
        )
        assert gallery.match(unit_vector(), 0.6, 0.0).student_id == "synthetic-a"
    finally:
        gallery.clear()


def test_templates_are_copied_once_and_not_normalized_again_during_matches(monkeypatch):
    source = unit_vector(scale=4.0)
    candidates = {"synthetic": [source]}
    original_normalize = face_pipeline.normalize_vector
    normalized_buffers = []

    def counted_normalize(value, dimension=EMBEDDING_DIMENSION):
        result = original_normalize(value, dimension)
        normalized_buffers.append(result)
        return result

    monkeypatch.setattr(face_pipeline, "normalize_vector", counted_normalize)
    gallery = CandidateGallery.from_candidates(candidates)
    assert len(normalized_buffers) == 1
    assert not normalized_buffers[0].any()
    assert gallery.vectors.dtype == np.float32
    assert gallery.vectors.flags.c_contiguous
    assert not np.shares_memory(source, gallery.vectors)
    assert np.allclose(np.linalg.norm(gallery.vectors[:, :1], axis=-1), 1.0)
    assert source[0] == 4.0
    source.fill(0)
    try:
        for threshold in (0.6, 1.0):  # Includes the scalar boundary recheck.
            assert gallery.match(unit_vector(), threshold, 0.1).status == "KNOWN"
        assert len(normalized_buffers) == 3  # One template preparation and two probes.
        assert all(not buffer.any() for buffer in normalized_buffers)
    finally:
        gallery.clear()


@pytest.mark.parametrize(
    "bad_vectors",
    [
        [],
        [unit_vector()] * 21,
        [np.zeros(EMBEDDING_DIMENSION)],
        [np.ones(EMBEDDING_DIMENSION - 1)],
        [np.ones((2, EMBEDDING_DIMENSION))],
        [np.full(EMBEDDING_DIMENSION, np.nan)],
        [np.full(EMBEDDING_DIMENSION, np.inf)],
        [np.full(EMBEDDING_DIMENSION, 1e30, dtype=np.float32)],
    ],
    ids=["empty", "too-many", "zero", "dimension", "matrix", "nan", "infinity", "norm-overflow"],
)
def test_failed_builder_wipes_partial_gallery_and_leaves_input_unchanged(monkeypatch, bad_vectors):
    original_zeros = np.zeros
    allocations = []

    def captured_zeros(*args, **kwargs):
        result = original_zeros(*args, **kwargs)
        allocations.append(result)
        return result

    good = unit_vector(scale=2.0)
    monkeypatch.setattr(face_pipeline.np, "zeros", captured_zeros)
    with pytest.raises(FaceServiceError) as error:
        CandidateGallery.from_candidates({"synthetic-good": [good], "synthetic-bad": bad_vectors})
    assert error.value.code == "MODEL_MISMATCH"
    assert len(allocations) == 2
    assert all(not allocation.any() for allocation in allocations)
    assert good[0] == 2.0


@pytest.mark.parametrize("kind", ["valid", "zero", "dimension", "nan", "norm-overflow"])
def test_normalization_scrubs_conversion_array_without_mutating_source(monkeypatch, kind):
    sources = {
        "valid": unit_vector(scale=4.0),
        "zero": np.zeros(EMBEDDING_DIMENSION, dtype=np.float32),
        "dimension": np.ones(EMBEDDING_DIMENSION - 1, dtype=np.float32),
        "nan": np.full(EMBEDDING_DIMENSION, np.nan, dtype=np.float32),
        "norm-overflow": np.full(EMBEDDING_DIMENSION, 1e30, dtype=np.float32),
    }
    source = sources[kind]
    original = source.copy()
    original_asarray = np.asarray
    converted = []

    def captured_asarray(*args, **kwargs):
        result = original_asarray(*args, **kwargs)
        converted.append(result)
        return result

    monkeypatch.setattr(face_pipeline.np, "asarray", captured_asarray)
    if kind == "valid":
        result = normalize_vector(source)
        assert result[0] == 1.0
        assert not np.shares_memory(result, converted[0])
        result.fill(0)
    else:
        with pytest.raises(FaceServiceError, match="embedding"):
            normalize_vector(source)
    assert len(converted) == 1
    assert not converted[0].any()
    assert np.array_equal(source, original, equal_nan=True)


def test_gallery_retirement_wipes_owned_vectors_and_is_idempotent():
    source = unit_vector()
    gallery = CandidateGallery.from_candidates({"synthetic": [source]})
    held_vectors = gallery.vectors
    held_counts = gallery.counts
    gallery.clear()
    gallery.clear()
    assert gallery.cleared
    assert not held_vectors.any()
    assert not held_counts.any()
    assert source[0] == 1.0
    with pytest.raises(FaceServiceError) as error:
        gallery.match(unit_vector(), 0.6, 0.1)
    assert error.value.code == "SESSION_NOT_FOUND"
