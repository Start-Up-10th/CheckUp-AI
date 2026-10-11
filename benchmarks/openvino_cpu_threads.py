"""Measure the 256D embedder on synthetic input with CPU thread-count variants.

This measures inference and preprocessing latency only. It does not measure face
recognition accuracy or use real enrollment data.

Example:
    .venv/Scripts/python.exe benchmarks/openvino_cpu_threads.py
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from time import perf_counter_ns

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from face_models import EMBEDDING_DIMENSION  # noqa: E402


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def run_inference(compiled, image: np.ndarray) -> np.ndarray:
    blob = np.transpose(image.astype(np.float32), (2, 0, 1))[None, ...]
    outputs = None
    result = None
    normalized = None
    try:
        outputs = compiled([blob])
        result = np.asarray(outputs[compiled.output(0)], dtype=np.float32).reshape(-1)
        if result.size != EMBEDDING_DIMENSION:
            raise RuntimeError("embedding model returned an unexpected vector dimension")
        norm = float(np.linalg.norm(result))
        if not np.isfinite(norm) or norm == 0 or not np.isfinite(result).all():
            raise RuntimeError("embedding model returned an invalid vector")
        normalized = result / norm
        return normalized.astype(np.float32, copy=True)
    finally:
        if normalized is not None and normalized.flags.writeable:
            normalized.fill(0)
        if result is not None and result.flags.writeable:
            result.fill(0)
        if outputs is not None:
            for output in outputs.values():
                if isinstance(output, np.ndarray) and output.flags.writeable:
                    output.fill(0)
        blob.fill(0)


def timing_summary(durations_ns: list[int]) -> dict[str, float]:
    milliseconds = np.asarray(durations_ns, dtype=np.float64) / 1_000_000
    return {
        "median_ms": float(np.median(milliseconds)),
        "p95_ms": float(np.percentile(milliseconds, 95)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", nargs="+", default=["default", "1", "2", "4", "8"])
    parser.add_argument("--warmup", type=positive_int, default=20)
    parser.add_argument("--repeats", type=positive_int, default=200)
    parser.add_argument("--seed", type=int, default=20261011)
    args = parser.parse_args()
    if any(value != "default" and not value.isdigit() for value in args.threads):
        parser.error("--threads accepts default or positive integer values")
    if any(value != "default" and int(value) < 1 for value in args.threads):
        parser.error("thread counts must be positive")

    from openvino import Core, __version__

    model_path = ROOT / "models" / "face-reidentification-retail-0095.xml"
    core = Core()
    model = core.read_model(str(model_path))
    rng = np.random.default_rng(args.seed)
    image = rng.integers(0, 256, size=(128, 128, 3), dtype=np.uint8)
    reference = None
    results = []
    try:
        for setting in args.threads:
            properties = {} if setting == "default" else {"INFERENCE_NUM_THREADS": int(setting)}
            compiled = core.compile_model(model, "CPU", properties)
            first = run_inference(compiled, image)
            try:
                if reference is None:
                    reference = first.copy()
                similarity = float(reference @ first)
                max_abs_diff = float(np.max(np.abs(reference - first)))
            finally:
                first.fill(0)

            for _ in range(args.warmup):
                output = run_inference(compiled, image)
                output.fill(0)
            durations_ns = []
            for _ in range(args.repeats):
                started = perf_counter_ns()
                output = run_inference(compiled, image)
                durations_ns.append(perf_counter_ns() - started)
                output.fill(0)

            try:
                resolved_threads = int(compiled.get_property("INFERENCE_NUM_THREADS"))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                resolved_threads = None
            results.append(
                {
                    "requested_threads": setting,
                    "resolved_threads": resolved_threads,
                    **timing_summary(durations_ns),
                    "cosine_similarity_to_default": similarity,
                    "max_abs_vector_difference": max_abs_diff,
                }
            )
            compiled = None
    finally:
        image.fill(0)
        if reference is not None:
            reference.fill(0)

    print(
        json.dumps(
            {
                "scope": "synthetic_embedder_latency_only",
                "model": "face-reidentification-retail-0095",
                "dimension": EMBEDDING_DIMENSION,
                "openvino": __version__,
                "python": platform.python_version(),
                "logical_cpus": os.cpu_count(),
                "seed": args.seed,
                "warmup": args.warmup,
                "repeats": args.repeats,
                "results": results,
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
