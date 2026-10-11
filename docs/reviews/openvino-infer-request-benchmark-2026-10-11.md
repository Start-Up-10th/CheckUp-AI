# OpenVINO inference-request benchmark — 2026-10-11

[`openvino_infer_request.py`](../../benchmarks/openvino_infer_request.py) compares the
current `CompiledModel` callable with a dedicated reusable `InferRequest`. Both variants
also run with output sharing enabled to check whether skipping the output copy helps.
The timed function includes the existing 128×128 HWC-to-NCHW conversion, inference,
256D L2 normalization, and cleanup. Input pixels are generated noise; no face data is used.

Environment: Windows, Python 3.12.0, NumPy 1.26.4, OpenVINO 2026.3.1, 16 logical CPUs.
Each strategy used 100 warmups and 1,000 timed runs. Strategies ran serially in rotating
order. Every returned normalized embedding matched the current callable exactly in this run
(cosine 1.0, maximum absolute difference 0.0).

| Strategy | Median | p95 |
| --- | ---: | ---: |
| CompiledModel callable | 2.204 ms | 3.664 ms |
| CompiledModel callable, shared output | 2.231 ms | 3.688 ms |
| Reused InferRequest | 2.223 ms | 3.703 ms |
| Reused InferRequest, shared output | 2.226 ms | 3.640 ms |

The median spread was under 0.03 ms and no alternative consistently improved both median
and p95, so keep the existing production call. OpenVINO documents that the callable wrapper
uses a temporary request it can reuse on consecutive calls, and suggests a dedicated
`InferRequest` for workflows that need more control; this simple serialized workload did not
benefit from switching. See [CompiledModel](https://docs.openvino.ai/2026/api/ie_python_api/_autosummary/openvino.CompiledModel.html)
and [InferRequest](https://docs.openvino.ai/2026/api/ie_python_api/_autosummary/openvino.InferRequest.html).

This is a model-call microbenchmark, not full frame latency or a concurrency test. No runtime
code, model, embedding dimension, or vector format changed.
