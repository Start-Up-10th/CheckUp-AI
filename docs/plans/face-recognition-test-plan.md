# Face recognition verification plan

This plan covers the AI service only. Attendance records and the attendance DB are out of scope;
the service returns recognition results to the backend contract.

## Automated checks

- Detection/landmark fields are returned separately from `recognition`.
- A frame with two faces produces two independent `faces[]` results and stable track IDs.
- A below-threshold or below-margin match is `UNKNOWN` with `studentId: null`.
- Candidate model metadata mismatch is rejected; vectors are not compared across model versions.
- Enrollment samples at most 100 frames and returns exactly 20 normalized representative vectors
  only after enough quality observations from one tracked identity.
- Low-light, blur, too-small, and extreme-pose observations are not used for recognition.
- Request-scoped image, video, decoded-frame, and embedding buffers are cleared in `finally` blocks.

## Accuracy and false-positive evaluation

Use a consented, labeled validation set split by person and capture session. Report per-person
true accept rate, false accept rate, false reject rate, unknown rate, score distributions, and
the effect of threshold/margin. Thresholds must be calibrated from held-out data and configured
through deployment settings; they are not inferred from MediaPipe confidence.

## Low-light evaluation

Run the same identities across progressively lower illumination and backlight conditions. Verify
that quality issues cause `NOT_ATTEMPTED` or `UNKNOWN`, never a guessed student ID, and that the
QR fallback signal is available after repeated failures.

## Multiple-face evaluation

Test one known plus one unknown, two known students, two unknown faces, entry/exit crossing, and
faces appearing/disappearing. Verify each result stays attached to its own bbox/track, score and
failure count; no result inherits another face's student ID, and no attendance mutation occurs.

## Disposal and operational checks

Instrument tests to assert decoded frames and temporary arrays are cleared after success, failure,
decode error, cancellation, and model error. Confirm raw video/frame bytes do not appear in logs,
fixtures, cache directories, database writes, or response payloads.
