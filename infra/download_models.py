from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

CHUNK_SIZE = 1024 * 1024


def pinned_url(record: dict[str, object]) -> str:
    source_url = record.get("source_url")
    if not isinstance(source_url, str):
        raise ValueError("model entry is missing source_url")

    generation = record.get("source_generation")
    if generation is None:
        return source_url

    parts = urlsplit(source_url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    existing = [value for key, value in query if key == "generation"]
    if existing and existing != [str(generation)]:
        raise ValueError("model URL generation does not match the manifest")
    if not existing:
        query.append(("generation", str(generation)))
    return urlunsplit(parts._replace(query=urlencode(query)))


def matches_manifest(path: Path, size: int, expected_sha256: str) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False

    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected_sha256


def download_model(record: dict[str, object], destination: Path) -> None:
    filename = record.get("file")
    size = record.get("bytes")
    expected_sha256 = record.get("sha256")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise ValueError("model entry has an invalid filename")
    if not isinstance(size, int) or size <= 0:
        raise ValueError(f"model entry has an invalid size: {filename}")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError(f"model entry has an invalid SHA-256: {filename}")

    target = destination / filename
    if matches_manifest(target, size, expected_sha256):
        print(f"verified existing model: {filename}")
        return

    request = Request(
        pinned_url(record),
        headers={"User-Agent": "CheckUp-Face-AI-model-fetcher/1.0"},
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{filename}.", suffix=".part", dir=destination, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            digest = hashlib.sha256()
            received = 0
            with urlopen(request, timeout=120) as response:
                while chunk := response.read(CHUNK_SIZE):
                    received += len(chunk)
                    if received > size:
                        raise ValueError(f"download is larger than expected: {filename}")
                    digest.update(chunk)
                    temporary_file.write(chunk)

            if received != size:
                raise ValueError(f"download size does not match the manifest: {filename}")
            if digest.hexdigest() != expected_sha256:
                raise ValueError(f"download SHA-256 does not match the manifest: {filename}")

        os.replace(temporary_path, target)
        temporary_path = None
        print(f"downloaded and verified model: {filename}")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and verify face model artifacts.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(records, list) or not records:
        raise ValueError("model manifest must contain a non-empty files list")

    args.destination.mkdir(parents=True, exist_ok=True)
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("model manifest entries must be objects")
        download_model(record, args.destination)


if __name__ == "__main__":
    main()
