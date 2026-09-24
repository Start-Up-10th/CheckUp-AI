from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _optional_float(name: str) -> float | None:
    value = os.getenv(name)
    return float(value) if value else None


def _student_token_map() -> dict[str, str]:
    raw = os.getenv("FACE_STUDENT_TOKEN_MAP", "")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {str(token): str(student_id) for token, student_id in value.items()}


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
    access_token: str | None = os.getenv("FACE_ACCESS_TOKEN")
    student_token_map: dict[str, str] = field(default_factory=_student_token_map)
    match_threshold: float | None = field(
        default_factory=lambda: _optional_float("FACE_MATCH_THRESHOLD")
    )
    match_margin: float | None = field(
        default_factory=lambda: _optional_float("FACE_MATCH_MARGIN")
    )
    max_body_bytes: int = int(os.getenv("FACE_MAX_BODY_BYTES", str(60 * 1024 * 1024)))
    enrollment_frames: int = int(os.getenv("FACE_ENROLLMENT_FRAMES", "100"))
    representative_vectors: int = int(os.getenv("FACE_REPRESENTATIVE_VECTORS", "20"))

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
