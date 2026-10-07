"""Synthetic candidate-matching benchmark; does not measure camera/model latency.

Run from any directory, for example:
    .venv/Scripts/python.exe benchmarks/face_matching.py --students 1 50 200
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from time import perf_counter_ns

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from face_models import EMBEDDING_DIMENSION  # noqa: E402
from face_pipeline import CandidateGallery, match_embedding, normalize_vector  # noqa: E402


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def synthetic_inputs(student_count: int, vector_count: int, probe_count: int, seed: int):
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(student_count, EMBEDDING_DIMENSION)).astype(np.float32)
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    candidates = {}
    probes = []
    try:
        for index, center in enumerate(centers):
            vectors = []
            candidates[f"synthetic-{index:03}"] = vectors
            for _ in range(vector_count):
                raw = center + rng.normal(0, 0.015, EMBEDDING_DIMENSION).astype(np.float32)
                try:
                    # Match the API: stored candidate templates are normalized before
                    # the reference matcher or gallery applies its normalization.
                    vectors.append(normalize_vector(raw))
                finally:
                    raw.fill(0)
        for index in range(probe_count):
            if index % 4 == 3:
                probe = rng.normal(size=EMBEDDING_DIMENSION).astype(np.float32)
            else:
                probe = (
                    centers[index % student_count]
                    + rng.normal(0, 0.012, EMBEDDING_DIMENSION).astype(np.float32)
                )
            probes.append(probe)
        return candidates, probes
    except BaseException:
        for vectors in candidates.values():
            for vector in vectors:
                vector.fill(0)
        for probe in probes:
            probe.fill(0)
        raise
    finally:
        centers.fill(0)


def timing_summary(durations_ns: list[int]) -> dict[str, float]:
    milliseconds = np.asarray(durations_ns, dtype=np.float64) / 1_000_000
    return {
        "median_ms": float(np.median(milliseconds)),
        "p95_ms": float(np.percentile(milliseconds, 95)),
    }


def run_case(student_count: int, vector_count: int, args: argparse.Namespace) -> dict:
    candidates, probes = synthetic_inputs(student_count, vector_count, args.probes, args.seed)
    gallery = None
    try:
        started = perf_counter_ns()
        gallery = CandidateGallery.from_candidates(candidates)
        preparation_ms = (perf_counter_ns() - started) / 1_000_000

        def reference(probe):
            return match_embedding(probe, candidates, args.threshold, args.margin)

        def batched(probe):
            return gallery.match(probe, args.threshold, args.margin)

        max_score_error = 0.0
        max_margin_error = 0.0
        for probe in probes:
            before, after = reference(probe), batched(probe)
            if (before.status, before.student_id) != (after.status, after.student_id):
                raise RuntimeError("synthetic parity check failed; no input or identity is printed")
            max_score_error = max(max_score_error, abs(before.score - after.score))
            max_margin_error = max(max_margin_error, abs(before.margin - after.margin))

        for index in range(args.warmup):
            probe = probes[index % len(probes)]
            reference(probe)
            batched(probe)

        reference_ns, batched_ns = [], []
        for index in range(args.repeats):
            probe = probes[index % len(probes)]
            # Alternate order to avoid consistently giving one matcher a warmer CPU.
            operations = [(reference, reference_ns), (batched, batched_ns)]
            if index % 2:
                operations.reverse()
            for operation, durations in operations:
                started = perf_counter_ns()
                operation(probe)
                durations.append(perf_counter_ns() - started)

        reference_times = timing_summary(reference_ns)
        batched_times = timing_summary(batched_ns)
        speedup = reference_times["median_ms"] / batched_times["median_ms"]
        return {
            "students": student_count,
            "vectors_per_student": vector_count,
            "gallery_prepare_ms": preparation_ms,
            "reference": reference_times,
            "gallery": batched_times,
            "median_speedup": speedup,
            "tenfold_goal_met": speedup >= 10.0,
            "max_score_error": max_score_error,
            "max_margin_error": max_margin_error,
            "decision_parity": True,
        }
    finally:
        if gallery is not None:
            gallery.clear()
        for vectors in candidates.values():
            for vector in vectors:
                vector.fill(0)
        for probe in probes:
            probe.fill(0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--students", type=positive_int, nargs="+", default=[200])
    parser.add_argument("--vectors", type=int, choices=range(1, 21), nargs="+", default=[20])
    parser.add_argument("--warmup", type=positive_int, default=10)
    parser.add_argument("--repeats", type=positive_int, default=100)
    parser.add_argument("--probes", type=positive_int, default=8)
    parser.add_argument("--seed", type=int, default=20261007)
    parser.add_argument("--threshold", type=float, default=0.6)
    parser.add_argument("--margin", type=float, default=0.1)
    args = parser.parse_args()
    if any(count > 200 for count in args.students):
        parser.error("--students must be between 1 and 200")
    if not np.isfinite([args.threshold, args.margin]).all():
        parser.error("--threshold and --margin must be finite")
    report = {
        "scope": "synthetic_candidate_matching_only",
        "python": platform.python_version(),
        "numpy": np.__version__,
        "dimension": EMBEDDING_DIMENSION,
        "seed": args.seed,
        "warmup": args.warmup,
        "repeats": args.repeats,
        "probes": args.probes,
        "threshold": args.threshold,
        "margin": args.margin,
        "cases": [
            run_case(student_count, vector_count, args)
            for student_count in args.students
            for vector_count in args.vectors
        ],
    }
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
