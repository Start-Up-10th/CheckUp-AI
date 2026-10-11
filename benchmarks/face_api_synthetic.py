"""Measure the existing AI frame endpoint using only generated synthetic data.

The actual model files and route are used, but no camera image or enrollment data
is loaded. Output contains only aggregate per-stage durations and synthetic counts.

Example:
    .venv/Scripts/python.exe benchmarks/face_api_synthetic.py
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import logging
import sys
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from face_detection_modes import synthetic_frame  # noqa: E402

from face_api import create_app  # noqa: E402
from face_config import Settings  # noqa: E402
from face_models import EMBEDDING_DIMENSION, MODEL_ID, ModelMetadata  # noqa: E402


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def synthetic_candidates(students: int, vectors_per_student: int, seed: int) -> tuple[np.ndarray, list[dict]]:
    rng = np.random.default_rng(seed)
    vectors = rng.standard_normal(
        (students, vectors_per_student, EMBEDDING_DIMENSION), dtype=np.float32
    )
    norms = np.linalg.norm(vectors, axis=2, keepdims=True)
    vectors /= norms
    candidates = [
        {
            "student_id": f"synthetic-{student:03d}",
            "vectors": vectors[student].tolist(),
        }
        for student in range(students)
    ]
    return vectors, candidates


def parse_timing_records(log_text: str) -> list[dict[str, object]]:
    records = []
    marker = "face_frame_timing_ms "
    for line in log_text.splitlines():
        if marker in line:
            records.append(ast.literal_eval(line.split(marker, 1)[1]))
    return records


def summarize(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {"median_ms": float(np.median(array)), "p95_ms": float(np.percentile(array, 95))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=positive_int, default=100)
    parser.add_argument("--warmup", type=positive_int, default=10)
    parser.add_argument("--students", type=positive_int, default=50)
    parser.add_argument("--vectors", type=positive_int, default=20)
    parser.add_argument("--seed", type=int, default=20261011)
    args = parser.parse_args()
    if args.warmup >= args.requests:
        parser.error("--warmup must be less than --requests")
    if args.students > 200 or args.vectors > 20:
        parser.error("synthetic gallery is limited to 200 students and 20 vectors")

    token = "synthetic-benchmark-token"
    settings = Settings(
        service_token=token,
        match_threshold=0.6,
        match_margin=0.1,
    )
    metadata = ModelMetadata(version=settings.model_version)
    candidate_vectors, candidates = synthetic_candidates(
        args.students, args.vectors, args.seed
    )
    payload = {
        "model": {
            "model_id": MODEL_ID,
            "version": metadata.version,
            "dimension": EMBEDDING_DIMENSION,
            "normalization": metadata.normalization,
        },
        "candidates": candidates,
    }

    log_buffer = io.StringIO()
    handler = logging.StreamHandler(log_buffer)
    logger = logging.getLogger("face_api")
    previous_level = logger.level
    previous_handlers = logger.handlers[:]
    previous_propagate = logger.propagate
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    session_id = "synthetic-benchmark-session"
    try:
        with TestClient(create_app(settings=settings)) as client:
            headers = {"Authorization": f"Bearer {token}"}
            ready = client.put(
                f"/internal/v1/face/sessions/{session_id}",
                headers=headers,
                json=payload,
            )
            ready.raise_for_status()
            for index in range(args.requests):
                frame = synthetic_frame(index)
                encoded = None
                try:
                    success, encoded = cv2.imencode(".jpg", frame)
                    if not success:
                        raise RuntimeError("could not encode synthetic frame")
                    response = client.post(
                        f"/internal/v1/face/sessions/{session_id}/frames",
                        headers={**headers, "Content-Type": "image/jpeg"},
                        content=encoded.tobytes(),
                    )
                    response.raise_for_status()
                    del response
                finally:
                    frame.fill(0)
                    if encoded is not None:
                        encoded.fill(0)
            client.delete(
                f"/internal/v1/face/sessions/{session_id}",
                headers=headers,
            ).raise_for_status()
    finally:
        logger.handlers = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        handler.close()
        candidate_vectors.fill(0)
        for candidate in candidates:
            for vector in candidate["vectors"]:
                vector[:] = [0.0] * len(vector)

    records = parse_timing_records(log_buffer.getvalue())[args.warmup :]
    if len(records) != args.requests - args.warmup:
        raise RuntimeError("frame timing records were incomplete")

    stages = ("read", "decode", "detect", "embed", "match", "cleanup", "total")
    stage_results = {}
    for stage in stages:
        values = [float(record[stage]) for record in records if stage in record]
        if values:
            stage_results[stage] = {**summarize(values), "samples": len(values)}
    print(
        json.dumps(
            {
                "scope": "synthetic_ai_frame_endpoint_latency_only",
                "input_kind": "synthetic_non_photographic",
                "python": sys.version.split()[0],
                "opencv": cv2.__version__,
                "requests": args.requests,
                "warmup": args.warmup,
                "measured_requests": len(records),
                "synthetic_students": args.students,
                "synthetic_vectors_per_student": args.vectors,
                "face_observations_total": sum(int(record["faces"]) for record in records),
                "embedding_attempts_total": sum(
                    int(record["embeddings"]) for record in records
                ),
                "stages": stage_results,
                "note": "Only aggregate timing and synthetic counts are printed.",
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
