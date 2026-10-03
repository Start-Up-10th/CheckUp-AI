from __future__ import annotations

import os
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path


def _optional_float(name: str) -> float | None:
    value = os.getenv(name)
    return float(value) if value else None


@dataclass(frozen=True)
class Settings:
    """Runtime configuration; no attendance/database configuration belongs here."""

    model_dir: Path = Path(os.getenv("FACE_MODEL_DIR", "models"))
    landmarker_path: Path = Path(
        os.getenv("FACE_LANDMARKER_PATH", "models/face_landmarker.task")
    )
    embedding_model_path: Path = Path(
        os.getenv("FACE_EMBEDDING_MODEL_PATH", "models/face-reidentification-retail-0095.xml")
    )
    service_token: str | None = os.getenv("FACE_SERVICE_TOKEN")
    match_threshold: float | None = field(
        default_factory=lambda: _optional_float("FACE_MATCH_THRESHOLD")
    )
    match_margin: float | None = field(
        default_factory=lambda: _optional_float("FACE_MATCH_MARGIN")
    )
    max_body_bytes: int = int(os.getenv("FACE_MAX_BODY_BYTES", str(60 * 1024 * 1024)))
    enrollment_frames: int = int(os.getenv("FACE_ENROLLMENT_FRAMES", "100"))
    representative_vectors: int = int(os.getenv("FACE_REPRESENTATIVE_VECTORS", "20"))
    session_idle_seconds: float = float(os.getenv("FACE_SESSION_IDLE_SECONDS", "300"))
    session_cleanup_interval_seconds: float = float(
        os.getenv("FACE_SESSION_CLEANUP_INTERVAL_SECONDS", "60")
    )

    def __post_init__(self) -> None:
        if (
            not isfinite(self.session_idle_seconds)
            or not isfinite(self.session_cleanup_interval_seconds)
            or self.session_idle_seconds <= 0
            or self.session_cleanup_interval_seconds <= 0
        ):
            raise ValueError("face session expiry settings must be positive")

    @property
    def model_version(self) -> str:
        return os.getenv("FACE_MODEL_VERSION", "face-reidentification-retail-0095@2023.0-fp32")

    @property
    def ready_for_inference(self) -> bool:
        return (
            self.landmarker_path.is_file()
            and self.embedding_model_path.is_file()
            and self.match_threshold is not None
            and self.match_margin is not None
        )
