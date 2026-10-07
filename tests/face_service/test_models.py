from dataclasses import replace
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import face_models
from face_models import FaceObservation, InferenceModels, ModelMetadata


def metadata_observation(brightness: float = 100) -> FaceObservation:
    return FaceObservation(
        (0.0, 0.25, 0.75, 0.375),
        ((-5.0, 20.0), (70.0, 20.0), (32.5, 32.0), (15.0, 50.0), (50.0, 50.0)),
        None,
        brightness,
        100,
        "frontal",
    )


def detector_runtime():
    points = [(20.0, 30.0)] * 300
    expected = metadata_observation()
    for index, point in zip((33, 263, 1, 61, 291), expected.landmarks, strict=True):
        points[index] = point
    landmarks = [SimpleNamespace(x=x / 100, y=y / 80) for x, y in points]
    captured_rgb = []

    def make_image(**kwargs):
        captured_rgb.append(kwargs["data"])
        return object()

    runtime = InferenceModels.__new__(InferenceModels)
    runtime.metadata = ModelMetadata()
    runtime._mp = SimpleNamespace(Image=make_image, ImageFormat=SimpleNamespace(SRGB="srgb"))
    runtime._landmarker = SimpleNamespace(
        detect=lambda _image: SimpleNamespace(face_landmarks=[landmarks])
    )
    return runtime, captured_rgb


def test_detection_preserves_geometry_quality_and_skips_alignment_and_embedding(monkeypatch):
    runtime, captured_rgb = detector_runtime()
    bgr = np.random.default_rng(7).integers(0, 256, (80, 100, 3), dtype=np.uint8)
    original = bgr.copy()
    crop = bgr[20:50, 0:70]
    expected_brightness = float(np.mean(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)))
    expected_sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var())
    captured_gray = []
    real_cvt_color = cv2.cvtColor

    def capture_color(image, code):
        result = real_cvt_color(image, code)
        if code == cv2.COLOR_BGR2GRAY:
            captured_gray.append(result)
        return result

    def unexpected_work(*_args):
        pytest.fail("metadata detection must not align or embed faces")

    monkeypatch.setattr(cv2, "cvtColor", capture_color)
    monkeypatch.setattr(face_models, "_align_face", unexpected_work)
    monkeypatch.setattr(runtime, "embed", unexpected_work)

    found = runtime.detect_faces(bgr)

    assert len(found) == 1
    face = found[0]
    assert face.embedding is None
    assert face.bbox == metadata_observation().bbox
    assert face.landmarks == metadata_observation().landmarks
    assert face.pose_bucket == "frontal"
    assert face.brightness == expected_brightness
    assert face.sharpness == expected_sharpness
    assert captured_rgb and not captured_rgb[0].any()
    assert captured_gray and not captured_gray[0].any()
    np.testing.assert_array_equal(bgr, original)


def test_detection_clears_rgb_when_landmarker_fails():
    runtime, captured_rgb = detector_runtime()

    def fail(_image):
        raise RuntimeError("synthetic detection failure")

    runtime._landmarker.detect = fail
    with pytest.raises(RuntimeError, match="synthetic detection failure"):
        runtime.detect_faces(np.full((80, 100, 3), 127, dtype=np.uint8))
    assert captured_rgb and not captured_rgb[0].any()


@pytest.mark.parametrize("fail", [False, True])
def test_embed_face_uses_original_landmarks_and_clears_aligned_image(monkeypatch, fail):
    runtime = InferenceModels.__new__(InferenceModels)
    observation = metadata_observation()
    bgr = np.full((80, 100, 3), 127, dtype=np.uint8)
    aligned = np.full((128, 128, 3), 101, dtype=np.uint8)
    expected_vector = np.zeros(256, dtype=np.float32)
    expected_vector[0] = 1

    def align(image, landmarks):
        assert image is bgr
        assert landmarks.dtype == np.float32
        np.testing.assert_array_equal(landmarks, observation.landmarks)
        assert landmarks[0, 0] == -5
        return aligned

    def embed(image):
        assert image is aligned and image.any()
        if fail:
            raise RuntimeError("synthetic embedding failure")
        return expected_vector

    monkeypatch.setattr(face_models, "_align_face", align)
    monkeypatch.setattr(runtime, "embed", embed)
    if fail:
        with pytest.raises(RuntimeError, match="synthetic embedding failure"):
            runtime.embed_face(bgr, observation)
    else:
        assert runtime.embed_face(bgr, observation) is expected_vector
        assert expected_vector[0] == 1
    assert not aligned.any()
    assert bgr.all()


def test_eager_detection_preserves_metadata_and_embeds_low_quality_faces(monkeypatch):
    runtime = InferenceModels.__new__(InferenceModels)
    detected = [metadata_observation(), metadata_observation(brightness=20)]
    calls = []
    vectors = [np.eye(1, 256, index, dtype=np.float32).reshape(-1) for index in range(2)]
    bgr = np.full((80, 100, 3), 127, dtype=np.uint8)

    def embed_face(image, observation):
        assert image is bgr
        calls.append(observation)
        return vectors[len(calls) - 1]

    monkeypatch.setattr(runtime, "detect_faces", lambda image: detected)
    monkeypatch.setattr(runtime, "embed_face", embed_face)

    eager = runtime.detect(bgr)

    assert calls == detected
    assert len(eager) == len(detected)
    for face, original, vector in zip(eager, detected, vectors, strict=True):
        assert replace(face, embedding=None) == original
        assert face.embedding is vector
        assert vector.any()
    assert all(face.embedding is None for face in detected)


@pytest.mark.parametrize("error", [RuntimeError("embedding failed"), KeyboardInterrupt()])
def test_eager_detection_clears_partial_embeddings_when_later_face_fails(monkeypatch, error):
    runtime = InferenceModels.__new__(InferenceModels)
    first_vector = np.ones(256, dtype=np.float32)
    calls = 0

    def embed_face(_image, _observation):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error
        return first_vector

    monkeypatch.setattr(runtime, "detect_faces", lambda image: [metadata_observation()] * 2)
    monkeypatch.setattr(runtime, "embed_face", embed_face)
    with pytest.raises(type(error)):
        runtime.detect(np.full((80, 100, 3), 127, dtype=np.uint8))
    assert not first_vector.any()


class CapturingCompiled:
    def __init__(self, raw_output, failure=None):
        self.raw_output = raw_output
        self.failure = failure
        self.blob = None
        self.input_values = None

    def __call__(self, inputs):
        self.blob = inputs[0]
        self.input_values = self.blob.copy()
        if self.failure == "inference":
            raise RuntimeError("synthetic inference failure")
        return {"vector": self.raw_output}

    def output(self, index):
        assert index == 0
        if self.failure == "lookup":
            raise RuntimeError("synthetic output lookup failure")
        return "vector"


def embedding_runtime(raw_output, failure=None):
    runtime = InferenceModels.__new__(InferenceModels)
    runtime.metadata = ModelMetadata()
    runtime._compiled = CapturingCompiled(raw_output, failure)
    return runtime


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_embed_returns_independent_normalized_vector_and_scrubs_raw_buffers(monkeypatch, dtype):
    raw = np.arange(1, 257, dtype=dtype).reshape(1, -1)
    converted = raw.astype(np.float32).reshape(-1)
    expected = (converted / float(np.linalg.norm(converted))).astype(np.float32, copy=True)
    runtime = embedding_runtime(raw)
    image = np.random.default_rng(8).integers(0, 256, (128, 128, 3), dtype=np.uint8)
    expected_blob = np.transpose(image.astype(np.float32), (2, 0, 1))[None, ...]
    captured_vectors = []
    real_asarray = np.asarray

    def capture_asarray(value, *args, **kwargs):
        result = real_asarray(value, *args, **kwargs)
        if value is raw:
            captured_vectors.append(result)
        return result

    monkeypatch.setattr(np, "asarray", capture_asarray)
    result = runtime.embed(image)

    np.testing.assert_array_equal(result, expected)
    np.testing.assert_array_equal(runtime._compiled.input_values, expected_blob)
    assert result.dtype == np.float32 and result.shape == (256,)
    assert not np.shares_memory(result, raw)
    assert not raw.any()
    assert captured_vectors and all(not vector.any() for vector in captured_vectors)
    assert not runtime._compiled.blob.any()
    assert image.any()


@pytest.mark.parametrize("invalid", ["dimension", "nonfinite", "zero", "overflow"])
def test_embed_rejects_invalid_outputs_and_scrubs_raw_output_and_blob(invalid):
    raw = np.ones((1, 255 if invalid == "dimension" else 256), dtype=np.float32)
    if invalid == "nonfinite":
        raw[0, 0] = np.nan
    elif invalid == "zero":
        raw.fill(0)
    elif invalid == "overflow":
        raw.fill(np.finfo(np.float32).max)
    runtime = embedding_runtime(raw)
    with np.errstate(over="ignore", invalid="ignore"):
        with pytest.raises(ValueError, match="embedding model returned an invalid vector"):
            runtime.embed(np.full((128, 128, 3), 127, dtype=np.uint8))
    assert not raw.any()
    assert not runtime._compiled.blob.any()


@pytest.mark.parametrize("failure", ["inference", "lookup", "conversion", "norm"])
def test_embed_errors_scrub_owned_raw_output_and_blob(monkeypatch, failure):
    raw = np.ones((1, 256), dtype=np.float32)
    runtime = embedding_runtime(raw, failure)

    def fail(*_args, **_kwargs):
        raise RuntimeError(f"synthetic {failure} failure")

    if failure == "conversion":
        monkeypatch.setattr(np, "asarray", fail)
    elif failure == "norm":
        monkeypatch.setattr(np.linalg, "norm", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        runtime.embed(np.full((128, 128, 3), 127, dtype=np.uint8))
    assert not runtime._compiled.blob.any()
    if failure != "inference":
        assert not raw.any()
