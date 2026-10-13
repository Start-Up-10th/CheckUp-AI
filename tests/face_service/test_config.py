import pytest

from face_config import Settings


@pytest.mark.parametrize(
    ("precision_hint", "version"),
    [
        ("f32", "face-reidentification-retail-0095@2023.0-fp32"),
        ("bf16", "face-reidentification-retail-0095@2023.0-bf16"),
    ],
)
def test_model_version_identifies_inference_precision(monkeypatch, precision_hint, version):
    monkeypatch.delenv("FACE_MODEL_VERSION", raising=False)

    assert Settings(inference_precision_hint=precision_hint).model_version == version


def test_face_model_version_override_keeps_fp32_identity(monkeypatch):
    monkeypatch.setenv("FACE_MODEL_VERSION", "custom-face-model@1")

    assert Settings(inference_precision_hint="f32").model_version == "custom-face-model@1"


def test_bf16_precision_is_added_to_custom_model_version(monkeypatch):
    monkeypatch.setenv("FACE_MODEL_VERSION", "custom-face-model@1")

    assert Settings(inference_precision_hint="bf16").model_version == "custom-face-model@1-bf16"


def test_inference_precision_hint_reads_environment(monkeypatch):
    monkeypatch.setenv("FACE_INFERENCE_PRECISION_HINT", "BF16")
    monkeypatch.delenv("FACE_MODEL_VERSION", raising=False)

    settings = Settings()

    assert settings.inference_precision_hint == "bf16"
    assert settings.model_version == "face-reidentification-retail-0095@2023.0-bf16"


def test_unknown_inference_precision_hint_is_rejected():
    with pytest.raises(ValueError, match="FACE_INFERENCE_PRECISION_HINT"):
        Settings(inference_precision_hint="fp16")


def test_success_recheck_defaults_to_one_second(monkeypatch):
    monkeypatch.delenv("FACE_SUCCESS_RECHECK_SECONDS", raising=False)

    assert Settings().success_recheck_seconds == 1.0


@pytest.mark.parametrize("seconds", ["0", "0.25", "1"])
def test_success_recheck_reads_environment(monkeypatch, seconds):
    monkeypatch.setenv("FACE_SUCCESS_RECHECK_SECONDS", seconds)

    assert Settings().success_recheck_seconds == float(seconds)


@pytest.mark.parametrize("seconds", [-0.1, 1.1, float("inf"), float("-inf"), float("nan")])
def test_invalid_success_recheck_seconds_are_rejected(seconds):
    with pytest.raises(ValueError, match="FACE_SUCCESS_RECHECK_SECONDS"):
        Settings(success_recheck_seconds=seconds)
