"""Compare the current CPU precision with a BF16 inference hint.

The output dimension stays 256. Only a synthetic 128x128 input is used, so this
measures vector drift and latency, not face recognition accuracy.

Example:
    .venv/Scripts/python.exe benchmarks/openvino_precision.py
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


def infer(compiled, image: np.ndarray) -> np.ndarray:
    blob = np.transpose(image.astype(np.float32), (2, 0, 1))[None, ...]
    outputs = None
    result = None
    normalized = None
    try:
        outputs = compiled([blob], share_inputs=True, share_outputs=False)
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
    parser.add_argument("--warmup", type=positive_int, default=100)
    parser.add_argument("--repeats", type=positive_int, default=1000)
    parser.add_argument("--seed", type=int, default=20261011)
    args = parser.parse_args()

    from openvino import Core, __version__

    model_path = ROOT / "models" / "face-reidentification-retail-0095.xml"
    core = Core()
    model = core.read_model(str(model_path))
    cpu_name = str(core.get_property("CPU", "FULL_DEVICE_NAME"))
    try:
        capabilities = [str(value) for value in core.get_property("CPU", "OPTIMIZATION_CAPABILITIES")]
    except (AttributeError, RuntimeError, TypeError):
        capabilities = []

    compiled_models = {"default": core.compile_model(model, "CPU")}
    precision_error = None
    try:
        compiled_models["bf16"] = core.compile_model(
            model,
            "CPU",
            {"INFERENCE_PRECISION_HINT": "bf16"},
        )
    except RuntimeError as exc:
        precision_error = type(exc).__name__

    rng = np.random.default_rng(args.seed)
    image = rng.integers(0, 256, size=(128, 128, 3), dtype=np.uint8)
    references = None
    results: dict[str, dict[str, object]] = {}
    try:
        default_output = infer(compiled_models["default"], image)
        references = default_output.copy()
        results["default"] = {
            "status": "ok",
            "resolved_precision_hint": str(
                compiled_models["default"].get_property("INFERENCE_PRECISION_HINT")
            ),
        }
        default_output.fill(0)
        if "bf16" in compiled_models:
            bf16_output = infer(compiled_models["bf16"], image)
            try:
                results["bf16"] = {
                    "status": "ok",
                    "resolved_precision_hint": str(
                        compiled_models["bf16"].get_property("INFERENCE_PRECISION_HINT")
                    ),
                    "cosine_similarity_to_default": float(references @ bf16_output),
                    "max_abs_vector_difference": float(
                        np.max(np.abs(references - bf16_output))
                    ),
                }
            finally:
                bf16_output.fill(0)
        else:
            results["bf16"] = {"status": "unsupported", "error_type": precision_error}

        strategies = [name for name in ("default", "bf16") if name in compiled_models]
        for _ in range(args.warmup):
            for strategy in strategies:
                output = infer(compiled_models[strategy], image)
                output.fill(0)

        durations = {strategy: [] for strategy in strategies}
        for index in range(args.repeats):
            offset = index % len(strategies)
            order = strategies[offset:] + strategies[:offset]
            for strategy in order:
                started = perf_counter_ns()
                output = infer(compiled_models[strategy], image)
                durations[strategy].append(perf_counter_ns() - started)
                output.fill(0)

        for strategy in strategies:
            results[strategy].update(timing_summary(durations[strategy]))
            results[strategy]["samples"] = len(durations[strategy])
    finally:
        image.fill(0)
        if references is not None:
            references.fill(0)
        compiled_models.clear()

    print(
        json.dumps(
            {
                "scope": "synthetic_embedding_precision_latency_and_vector_drift",
                "model": "face-reidentification-retail-0095",
                "dimension": EMBEDDING_DIMENSION,
                "openvino": __version__,
                "python": platform.python_version(),
                "logical_cpus": os.cpu_count(),
                "cpu": cpu_name,
                "cpu_optimization_capabilities": capabilities,
                "input": "synthetic_128x128",
                "warmup_per_strategy": args.warmup,
                "repeats_per_strategy": args.repeats,
                "results": results,
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
