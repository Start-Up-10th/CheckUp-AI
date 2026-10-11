"""Compare OpenVINO's callable wrapper with a reused InferRequest.

Only a synthetic 128x128 input is used. The benchmark includes the same input
layout conversion, output normalization, and buffer cleanup as InferenceModels.embed.

Example:
    .venv/Scripts/python.exe benchmarks/openvino_infer_request.py
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

STRATEGIES = (
    "compiled_callable",
    "compiled_callable_shared_output",
    "infer_request",
    "infer_request_shared_output",
)


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def run(compiled, request, image: np.ndarray, strategy: str) -> np.ndarray:
    blob = np.transpose(image.astype(np.float32), (2, 0, 1))[None, ...]
    outputs = None
    result = None
    normalized = None
    try:
        if strategy.startswith("compiled_callable"):
            outputs = compiled(
                [blob],
                share_inputs=True,
                share_outputs=strategy == "compiled_callable_shared_output",
            )
        else:
            outputs = request.infer(
                [blob],
                share_inputs=True,
                share_outputs=strategy == "infer_request_shared_output",
            )
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
    compiled = core.compile_model(model, "CPU")
    request = compiled.create_infer_request()
    rng = np.random.default_rng(args.seed)
    image = rng.integers(0, 256, size=(128, 128, 3), dtype=np.uint8)
    references: dict[str, np.ndarray] = {}
    results = {}
    try:
        for strategy in STRATEGIES:
            output = run(compiled, request, image, strategy)
            try:
                if not references:
                    references["default"] = output.copy()
                reference = references["default"]
                results[strategy] = {
                    "cosine_similarity_to_default": float(reference @ output),
                    "max_abs_vector_difference": float(np.max(np.abs(reference - output))),
                }
            finally:
                output.fill(0)

        for _ in range(args.warmup):
            for strategy in STRATEGIES:
                output = run(compiled, request, image, strategy)
                output.fill(0)

        durations = {strategy: [] for strategy in STRATEGIES}
        for index in range(args.repeats):
            offset = index % len(STRATEGIES)
            order = STRATEGIES[offset:] + STRATEGIES[:offset]
            for strategy in order:
                started = perf_counter_ns()
                output = run(compiled, request, image, strategy)
                durations[strategy].append(perf_counter_ns() - started)
                output.fill(0)

        for strategy in STRATEGIES:
            results[strategy].update(timing_summary(durations[strategy]))
            results[strategy]["samples"] = len(durations[strategy])
    finally:
        image.fill(0)
        for reference in references.values():
            reference.fill(0)
        request = None
        compiled = None

    print(
        json.dumps(
            {
                "scope": "synthetic_embedding_api_latency_and_vector_parity",
                "model": "face-reidentification-retail-0095",
                "dimension": EMBEDDING_DIMENSION,
                "openvino": __version__,
                "python": platform.python_version(),
                "logical_cpus": __import__("os").cpu_count(),
                "input": "synthetic_128x128",
                "warmup_per_strategy": args.warmup,
                "repeats_per_strategy": args.repeats,
                "serialized_calls": True,
                "results": results,
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
