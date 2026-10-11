# OpenVINO BF16 embedding benchmark — 2026-10-11

[`openvino_precision.py`](../../benchmarks/openvino_precision.py) compares the current
FP32 CPU compile with `INFERENCE_PRECISION_HINT=bf16`. Both use the same 0095 model,
128×128 synthetic input, HWC-to-NCHW conversion, L2 normalization, and buffer cleanup.
Each run used 100 warmups and 1,000 timed calls per precision.

Environment: Windows, Intel Core Ultra 7 255H, 16 logical CPUs, Python 3.12.0,
OpenVINO 2026.3.1. The CPU runtime reports BF16 support and resolves the explicit hint to
`bfloat16`.

| Run | Precision | Median | p95 |
| ---: | --- | ---: | ---: |
| 1 | FP32 | 2.396 ms | 3.436 ms |
| 1 | BF16 | 2.275 ms | 3.262 ms |
| 2 | FP32 | 2.083 ms | 2.971 ms |
| 2 | BF16 | 1.944 ms | 2.775 ms |

BF16 was about 5–7% faster in both runs. It returned the same 256-dimensional shape;
normalized vector cosine similarity to FP32 was 0.999281 and maximum per-component
difference was 0.00721. These are synthetic-input comparisons, not genuine face match,
false-accept, or false-reject results.

OpenVINO separates model storage precision from runtime inference precision, and CPU BF16
execution depends on hardware support. See its [precision control guide](https://docs.openvino.ai/2026/openvino-workflow/running-inference/optimize-inference/precision-control.html)
and [CPU device guide](https://docs.openvino.ai/2026/openvino-workflow/running-inference/inference-devices-and-modes/cpu-device.html).

## Decision

Expose BF16 as an opt-in CPU setting, keep FP32 as the default, and put the precision in
the model version so vectors from different inference modes cannot be mixed accidentally.
The API still carries normalized float32 vectors with dimension 256; there is no vector
schema change or DB migration. Enrollments must be regenerated together under BF16 before
using that model version. Do not enable BF16 for attendance until a representative,
consented validation set confirms the matching thresholds and error rates.
