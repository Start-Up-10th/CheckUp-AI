# Repeated known-face benchmark — 2026-10-13

[`face_recheck_benchmark.py`](../../benchmarks/face_recheck_benchmark.py) compares the
real frame API with success rechecks disabled and enabled. It uses a procedural,
non-photographic frame and seeds the synthetic gallery with the embedding generated
from that same frame. Both lanes run interleaved in one process with the same 200
students and 20 templates per student.

Reproduce with:

```powershell
.\.venv\Scripts\python.exe benchmarks\face_recheck_benchmark.py --requests 120 --warmup 20 --students 200 --vectors 20
```

Two runs each used 20 warmups and 120 measured requests per lane:

| Run | Recheck | Total median | Total p95 | Embedding attempts |
| ---: | --- | ---: | ---: | ---: |
| 1 | Disabled | 12.131 ms | 16.720 ms | 40 |
| 1 | 1 second | 11.925 ms | 14.541 ms | 3 |
| 2 | Disabled | 11.861 ms | 16.248 ms | 40 |
| 2 | 1 second | 11.798 ms | 13.841 ms | 3 |

The feature reduced embedding and gallery-match attempts by 92.5%. Total median
latency changed by less than 2% across these runs, while p95 fell by 13.0% and
14.8%. Face detection remained about 10.7 ms per frame and dominated total time.

This measures repeated computation only. The synthetic frame is not representative
of real faces and cannot establish recognition accuracy or field throughput. During
the recheck window the API reports `NOT_ATTEMPTED` with no student ID; it does not
replay the previous `KNOWN` result. Real labeled validation is needed before drawing
accuracy conclusions or making any detector-resolution change.
