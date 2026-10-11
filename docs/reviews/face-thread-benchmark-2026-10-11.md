# OpenVINO CPU thread benchmark — 2026-10-11

The reproducible benchmark is [`benchmarks/openvino_cpu_threads.py`](../../benchmarks/openvino_cpu_threads.py).
It measures preprocessing and inference for the existing `face-reidentification-retail-0095`
model with synthetic 128×128 input. It does not use face or enrollment data and does not
measure detection, full-request latency, production concurrency, or recognition accuracy.

Environment: Windows, Python 3.12.0, NumPy 1.26.4, OpenVINO 2026.3.1, 16 logical CPUs.
Each setting used 20 warmups and 200 timed runs.

| CPU threads | Resolved threads | Median (ms) | p95 (ms) |
| ---: | ---: | ---: | ---: |
| OpenVINO default | 14 | 1.857 | 2.568 |
| 1 | 1 | 5.439 | 6.728 |
| 2 | 2 | 3.510 | 4.087 |
| 4 | 4 | 2.371 | 2.873 |
| 8 | 8 | 1.974 | 2.543 |

All settings returned the same normalized 256-dimensional vector in this run
(cosine similarity 1.0; maximum absolute difference 0.0). The default had the best
median latency, so this measurement does not support changing the service's thread
configuration. It also does not establish performance on the production host.
