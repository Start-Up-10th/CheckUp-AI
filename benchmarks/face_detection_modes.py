"""Compare MediaPipe IMAGE and VIDEO face detection on the same frame stream.

With --video, the input is decoded in memory and is never copied or saved.
Without it, a procedural, non-photographic face sequence is used as a smoke input.
Only timing and aggregate geometry parity are printed; no frame or face data is.

Example:
    .venv/Scripts/python.exe benchmarks/face_detection_modes.py --video local-test.mp4
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from time import perf_counter_ns

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def synthetic_frame(index: int) -> np.ndarray:
    """Make a moving, non-photographic test drawing without face imagery."""
    image = np.full((480, 640, 3), 224, dtype=np.uint8)
    center_x = 320 + int(12 * np.sin(index / 12))
    cv2.ellipse(image, (center_x, 240), (126, 164), 0, 0, 360, (174, 194, 218), -1)
    cv2.ellipse(image, (center_x, 142), (128, 74), 0, 180, 360, (42, 48, 58), -1)
    cv2.ellipse(image, (center_x - 48, 222), (28, 14), 0, 0, 360, (247, 247, 247), -1)
    cv2.ellipse(image, (center_x + 48, 222), (28, 14), 0, 0, 360, (247, 247, 247), -1)
    cv2.circle(image, (center_x - 48, 222), 7, (30, 35, 45), -1)
    cv2.circle(image, (center_x + 48, 222), 7, (30, 35, 45), -1)
    cv2.line(image, (center_x - 78, 190), (center_x - 20, 190), (48, 48, 55), 8)
    cv2.line(image, (center_x + 20, 190), (center_x + 78, 190), (48, 48, 55), 8)
    cv2.line(image, (center_x, 226), (center_x - 9, 286), (143, 160, 181), 11)
    cv2.ellipse(image, (center_x, 315), (44, 15), 0, 0, 180, (104, 38, 116), 5)
    return image


def open_video(path: Path):
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError("could not open benchmark video")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    return capture, fps if np.isfinite(fps) and fps > 0 else 30.0


def face_points(result) -> list[np.ndarray]:
    faces = [
        np.asarray([(point.x, point.y) for point in landmarks], dtype=np.float32)
        for landmarks in result.face_landmarks
    ]
    return sorted(faces, key=lambda points: (float(points[:, 0].mean()), float(points[:, 1].mean())))


def summarize(values_ns: list[int]) -> dict[str, float]:
    values_ms = np.asarray(values_ns, dtype=np.float64) / 1_000_000
    return {
        "median_ms": float(np.median(values_ms)),
        "p95_ms": float(np.percentile(values_ms, 95)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, help="local test video; frames stay in memory")
    parser.add_argument("--warmup", type=positive_int, default=10)
    parser.add_argument("--max-frames", type=positive_int, default=120)
    args = parser.parse_args()

    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    model_path = ROOT / "models" / "face_landmarker.task"
    if not model_path.is_file():
        raise SystemExit("face landmarker model is unavailable")

    capture = None
    fps = 30.0
    if args.video is not None:
        capture, fps = open_video(args.video)

    def options_for(mode):
        return vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mode,
            num_faces=8,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    image_task = vision.FaceLandmarker.create_from_options(options_for(vision.RunningMode.IMAGE))
    video_task = vision.FaceLandmarker.create_from_options(options_for(vision.RunningMode.VIDEO))

    image_times: list[int] = []
    video_times: list[int] = []
    image_face_total = 0
    video_face_total = 0
    parity_frames = 0
    count_mismatches = 0
    landmark_max_deltas: list[float] = []
    frame_count = 0
    previous_timestamp = -1
    try:
        for index in range(args.max_frames):
            if capture is None:
                frame = synthetic_frame(index)
            else:
                success, frame = capture.read()
                if not success:
                    break

            rgb = None
            mp_image = None
            image_result = None
            video_result = None
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp = max(index, int(round(index * 1000 / fps)))
                timestamp = max(timestamp, previous_timestamp + 1)
                previous_timestamp = timestamp

                if index % 2 == 0:
                    started = perf_counter_ns()
                    image_result = image_task.detect(mp_image)
                    image_elapsed = perf_counter_ns() - started
                    started = perf_counter_ns()
                    video_result = video_task.detect_for_video(mp_image, timestamp)
                    video_elapsed = perf_counter_ns() - started
                else:
                    started = perf_counter_ns()
                    video_result = video_task.detect_for_video(mp_image, timestamp)
                    video_elapsed = perf_counter_ns() - started
                    started = perf_counter_ns()
                    image_result = image_task.detect(mp_image)
                    image_elapsed = perf_counter_ns() - started

                image_faces = face_points(image_result)
                video_faces = face_points(video_result)
                image_face_total += len(image_faces)
                video_face_total += len(video_faces)
                if index >= args.warmup:
                    image_times.append(image_elapsed)
                    video_times.append(video_elapsed)
                    if len(image_faces) != len(video_faces):
                        count_mismatches += 1
                    else:
                        parity_frames += 1
                        for image_points, video_points in zip(image_faces, video_faces, strict=True):
                            if image_points.shape == video_points.shape and image_points.size:
                                landmark_max_deltas.append(
                                    float(np.max(np.abs(image_points - video_points)))
                                )
            finally:
                mp_image = None
                if rgb is not None:
                    rgb.fill(0)
                frame.fill(0)
            frame_count += 1
    finally:
        if capture is not None:
            capture.release()
        image_task.close()
        video_task.close()

    if not image_times:
        raise SystemExit("input did not contain enough frames after warmup")

    deltas = np.asarray(landmark_max_deltas, dtype=np.float64)
    result = {
        "scope": "mediapipe_detection_latency_and_geometry_only",
        "input_kind": "local_video" if args.video is not None else "synthetic_non_photographic",
        "mediapipe": mp.__version__,
        "opencv": cv2.__version__,
        "python": platform.python_version(),
        "frames": frame_count,
        "warmup_frames": min(args.warmup, frame_count),
        "measured_frames": len(image_times),
        "image_mode": {**summarize(image_times), "faces_total": image_face_total},
        "video_mode": {**summarize(video_times), "faces_total": video_face_total},
        "geometry_comparison": {
            "face_count_mismatch_frames": count_mismatches,
            "same_count_frames": parity_frames,
            "landmark_max_abs_delta_median": float(np.median(deltas)) if deltas.size else None,
            "landmark_max_abs_delta_p95": float(np.percentile(deltas, 95)) if deltas.size else None,
        },
        "note": "No image, frame, landmark, or identity data is written or printed.",
    }
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
