"""Compare repeated successful recognition with success recheck suppression.

Only a procedural non-photographic frame is used. The exact embedding generated
from that frame seeds one synthetic gallery entry so both lanes recognize it.
The benchmark measures the existing API and prints only aggregate timings/counts.

Example:
    .venv/Scripts/python.exe benchmarks/face_recheck_benchmark.py
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from pathlib import Path

import cv2
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from face_api_synthetic import parse_timing_records, summarize, synthetic_candidates  # noqa: E402
from face_detection_modes import positive_int, synthetic_frame  # noqa: E402

from face_api import create_app  # noqa: E402
from face_config import Settings  # noqa: E402
from face_models import EMBEDDING_DIMENSION, MODEL_ID, ModelMetadata  # noqa: E402
from face_pipeline import clear_observations, quality_issues  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=positive_int, default=100, help="measured requests per lane")
    parser.add_argument("--warmup", type=positive_int, default=20)
    parser.add_argument("--students", type=positive_int, default=50)
    parser.add_argument("--vectors", type=positive_int, default=20)
    parser.add_argument("--seed", type=int, default=20261013)
    args = parser.parse_args()
    if args.warmup >= args.requests:
        parser.error("--warmup must be less than --requests")
    if args.students > 200 or args.vectors > 20:
        parser.error("synthetic gallery is limited to 200 students and 20 vectors")

    token = "synthetic-benchmark-token"
    settings = Settings(service_token=token, match_threshold=0.6, match_margin=0.1)
    metadata = ModelMetadata(version=settings.model_version)
    candidate_vectors, candidates = synthetic_candidates(args.students, args.vectors, args.seed)
    log_buffer = io.StringIO()
    handler = logging.StreamHandler(log_buffer)
    logger = logging.getLogger("face_api")
    previous_level = logger.level
    previous_handlers = logger.handlers[:]
    previous_propagate = logger.propagate
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    app = create_app(settings=settings)
    lanes = (
        ("recheck_disabled", "synthetic-recheck-disabled"),
        ("recheck_enabled", "synthetic-recheck-enabled"),
    )
    headers = {"Authorization": f"Bearer {token}"}
    frame = synthetic_frame(0)
    encoded = None
    probe = None
    observations = []
    try:
        with TestClient(app) as client:
            runtime = app.state.models
            observations = runtime.detect_faces(frame)
            eligible = [item for item in observations if not quality_issues(item)]
            if not eligible:
                raise RuntimeError("the procedural frame did not produce a quality face")
            probe = runtime.embed_face(frame, eligible[0])
            # CandidateGallery scores the mean of its best three templates.
            candidate_vectors[0, :3] = probe
            candidates[0]["vectors"] = candidate_vectors[0].tolist()
            payload = {
                "model": {
                    "model_id": MODEL_ID,
                    "version": metadata.version,
                    "dimension": EMBEDDING_DIMENSION,
                    "normalization": metadata.normalization,
                },
                "candidates": candidates,
            }
            for _, session_id in lanes:
                response = client.put(
                    f"/internal/v1/face/sessions/{session_id}", headers=headers, json=payload
                )
                response.raise_for_status()
            app.state.sessions[lanes[0][1]].tracker.success_recheck_seconds = 0
            app.state.sessions[lanes[1][1]].tracker.success_recheck_seconds = 1

            success_counts = dict.fromkeys((name for name, _ in lanes), 0)
            measured_statuses = {name: {} for name, _ in lanes}
            for index in range(args.warmup + args.requests):
                for name, session_id in lanes:
                    success, encoded = cv2.imencode(".jpg", frame)
                    if not success:
                        raise RuntimeError("could not encode synthetic frame")
                    response = client.post(
                        f"/internal/v1/face/sessions/{session_id}/frames",
                        headers={**headers, "Content-Type": "image/jpeg"},
                        content=encoded.tobytes(),
                    )
                    response.raise_for_status()
                    faces = response.json()["faces"]
                    if not faces:
                        raise RuntimeError("the procedural face disappeared during the benchmark")
                    status = faces[0]["recognition"]["status"]
                    if status == "KNOWN":
                        success_counts[name] += 1
                    if index >= args.warmup:
                        measured_statuses[name][status] = measured_statuses[name].get(status, 0) + 1
                    encoded.fill(0)
            for _, session_id in lanes:
                client.delete(f"/internal/v1/face/sessions/{session_id}", headers=headers).raise_for_status()
    finally:
        logger.handlers = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        handler.close()
        frame.fill(0)
        if encoded is not None:
            encoded.fill(0)
        if probe is not None:
            probe.fill(0)
        clear_observations(observations)
        candidate_vectors.fill(0)
        for candidate in candidates:
            for vector in candidate["vectors"]:
                vector[:] = [0.0] * len(vector)

    records = parse_timing_records(log_buffer.getvalue())
    expected = 2 * (args.warmup + args.requests)
    if len(records) != expected:
        raise RuntimeError(f"expected {expected} timing records, received {len(records)}")
    measured = {name: [] for name, _ in lanes}
    for index, record in enumerate(records):
        lane_index = index % len(lanes)
        pair_index = index // len(lanes)
        if pair_index >= args.warmup:
            measured[lanes[lane_index][0]].append(record)

    results = {}
    for name, _ in lanes:
        lane_records = measured[name]
        stages = {}
        for stage in ("admission", "queue", "decode", "detect", "embed", "match", "total"):
            values = [float(record[stage]) for record in lane_records if stage in record]
            if values:
                stages[stage] = {**summarize(values), "samples": len(values)}
        results[name] = {
            "stages": stages,
            "embedding_attempts": sum(int(record["embeddings"]) for record in lane_records),
            "recognized_attempts_including_warmup": success_counts[name],
            "measured_recognition_statuses": measured_statuses[name],
        }

    baseline = results["recheck_disabled"]
    optimized = results["recheck_enabled"]
    if optimized["embedding_attempts"] >= baseline["embedding_attempts"]:
        raise RuntimeError("success recheck did not reduce embedding attempts")
    if optimized["recognized_attempts_including_warmup"] == 0:
        raise RuntimeError("known-face recognition was not exercised")
    base_stages = baseline["stages"]
    optimized_stages = optimized["stages"]
    comparison = {
        "embedding_attempt_reduction_percent": 100 * (
            baseline["embedding_attempts"] - optimized["embedding_attempts"]
        ) / baseline["embedding_attempts"],
        "total_median_reduction_percent": 100 * (
            base_stages["total"]["median_ms"] - optimized_stages["total"]["median_ms"]
        ) / base_stages["total"]["median_ms"],
        "total_p95_reduction_percent": 100 * (
            base_stages["total"]["p95_ms"] - optimized_stages["total"]["p95_ms"]
        ) / base_stages["total"]["p95_ms"],
    }

    print(json.dumps({
        "scope": "synthetic_known_face_recheck_api_comparison",
        "input_kind": "procedural_non_photographic_frame_with_matching_model_embedding",
        "requests_per_lane": args.requests,
        "warmup_per_lane": args.warmup,
        "synthetic_students": args.students,
        "synthetic_vectors_per_student": args.vectors,
        "lanes": results,
        "comparison_percent_reduction": comparison,
        "note": "Measures repeated-known-face compute savings, not real face accuracy or field throughput.",
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
