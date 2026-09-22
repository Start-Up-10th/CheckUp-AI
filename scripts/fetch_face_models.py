from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models"
MANIFEST = ROOT / "contracts" / "face-models.manifest.json"


def fetch() -> None:
    MODEL_DIR.mkdir(exist_ok=True)
    for item in json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]:
        target = MODEL_DIR / item["filename"]
        if not target.exists():
            urllib.request.urlretrieve(item["url"], target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise SystemExit(f"checksum mismatch: {target}")


if __name__ == "__main__":
    fetch()
