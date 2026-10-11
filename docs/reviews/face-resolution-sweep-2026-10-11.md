# Face detector input-resolution sweep — 2026-10-11

The API-level synthetic run in [the detection-mode review](face-detection-benchmark-2026-10-11.md)
found a 11.319 ms median `detect` stage, the largest measured part of the frame request.
This follow-up checks whether resizing the image before MediaPipe reduces that cost.

[`face_resolution_sweep.py`](../../benchmarks/face_resolution_sweep.py) runs the existing
MediaPipe IMAGE task at 640×480, 480×360, 320×240, and 240×180. Its default input is a
procedurally drawn, non-photographic face. Apparent face sizes are varied to expose the
limits of this synthetic check. The script also accepts a local video; its frames and
landmarks stay in memory and only aggregate results are printed.

The larger sweep used 90 measured frames for apparent face sizes 1.0 and 0.5. Both were
detected at every tested resolution. Results below compare each resized result to the same
frame processed at 640×480. Latency includes resize, BGR-to-RGB conversion, MediaPipe image
creation, and the detector call; it does not include the API's downstream quality checks.

| Synthetic face size | Input size | Median | p95 | Count mismatches | Landmark max-delta p95 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1.0 | 640×480 | 9.774 ms | 10.321 ms | 0/90 | 0 |
| 1.0 | 480×360 | 9.072 ms | 10.035 ms | 0/90 | 0.0139 |
| 1.0 | 320×240 | 9.127 ms | 9.718 ms | 0/90 | 0.0135 |
| 1.0 | 240×180 | 9.058 ms | 9.718 ms | 0/90 | 0.0190 |
| 0.5 | 640×480 | 10.089 ms | 11.440 ms | 0/90 | 0 |
| 0.5 | 480×360 | 9.404 ms | 10.554 ms | 0/90 | 0.0089 |
| 0.5 | 320×240 | 9.265 ms | 10.532 ms | 0/90 | 0.0165 |
| 0.5 | 240×180 | 9.236 ms | 10.225 ms | 0/90 | 0.0137 |

For these two synthetic sizes, 480×360 was about 7% faster at the median and retained
the face count. Its landmark max-delta p95 was about 0.9% of image width for the smaller
face. Lower scales also retained the count here, but their coordinate differences were
larger or varied by case. A smaller synthetic face (size 0.3125) was not detected at
full resolution; one 240×180 frame then produced a detection, so parity with the full-size
reference cannot establish recall or accuracy. Size 0.25 was not detected at any tested
scale.

## Decision

Do not downscale production frames yet. The apparent 7–8% speed gain is promising, but a
procedural drawing cannot validate landmark stability for real faces or embedding/match
accuracy. Use an approved representative video to compare full resolution with 480×360
before changing runtime behavior. The 256-dimensional embedding and wire/data format stay
unchanged.
