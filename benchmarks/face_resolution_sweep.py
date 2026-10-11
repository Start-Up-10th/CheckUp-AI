"""Measure detector latency and geometry across input resolutions.

With --video, frames are decoded and processed in memory only. By default, the
script uses a procedural non-photographic face at several apparent sizes.
Only aggregate timing and detection counts are printed.

Example:
    .venv/Scripts/python.exe benchmarks/face_resolution_sweep.py
    .venv/Scripts/python.exe benchmarks/face_resolution_sweep.py --video local-test.mp4
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from face_detection_modes import face_points, synthetic_frame  # noqa: E402


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def resolution_scale(value: str) -> float:
    scale = float(value)
    if not np.isfinite(scale) or not 0 < scale <= 1:
        raise argparse.ArgumentTypeError("resolution scales must be in (0, 1]")
    return scale


def synthetic_frame_at_size(index: int, face_size: float) -> np.ndarray:
    image = synthetic_frame(index)
    if face_size == 1.0:
        return image
    transform = cv2.getRotationMatrix2D((320, 240), 0, face_size)
    scaled = cv2.warpAffine(
        image,
        transform,
        (640, 480),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(224, 224, 224),
    )
    image.fill(0)
    return scaled


def empty_measurement() -> dict[str, object]:
    return {
        "durations_ns": [],
        "faces_total": 0,
        "reference_faces_total": 0,
        "count_mismatch_frames": 0,
        "same_count_frames": 0,
        "landmark_max_deltas": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, help="local test video; frames stay in memory")
    parser.add_argument("--input-scales", nargs="+", type=resolution_scale, default=[1.0, 0.75, 0.5, 0.375])
    parser.add_argument("--face-sizes", nargs="+", type=resolution_scale, default=[1.0, 0.75, 0.5, 0.375, 0.25])
    parser.add_argument("--warmup", type=positive_int, default=10)
    parser.add_argument("--max-frames", type=positive_int, default=60)
    args = parser.parse_args()
    if args.warmup >= args.max_frames:
        parser.error("--warmup must be less than --max-frames")
    if 1.0 not in args.input_scales:
        parser.error("--input-scales must include 1.0 as the full-resolution reference")
    if len(set(args.input_scales)) != len(args.input_scales):
        parser.error("--input-scales cannot contain duplicates")
    if len(set(args.face_sizes)) != len(args.face_sizes):
        parser.error("--face-sizes cannot contain duplicates")

    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    model_path = ROOT / "models" / "face_landmarker.task"
    if not model_path.is_file():
        raise SystemExit("face landmarker model is unavailable")

    video_capture = None
    if args.video is not None:
        video_capture = cv2.VideoCapture(str(args.video))
        if not video_capture.isOpened():
            video_capture.release()
            raise SystemExit("could not open benchmark video")
        face_sizes = [1.0]
    else:
        face_sizes = args.face_sizes

    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=8,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
    )
    task = vision.FaceLandmarker.create_from_options(options)
    all_measurements = []
    base_width = None
    base_height = None
    frame_total = 0
    try:
        for face_size in face_sizes:
            measurements = {scale: empty_measurement() for scale in args.input_scales}
            frames_for_size = 0
            try:
                for index in range(args.max_frames):
                    if video_capture is None:
                        frame = synthetic_frame_at_size(index, face_size)
                    else:
                        success, frame = video_capture.read()
                        if not success:
                            break
                    base_height, base_width = frame.shape[:2]
                    frame_results: dict[float, list[np.ndarray]] = {}
                    try:
                        order = list(args.input_scales)
                        offset = index % len(order)
                        order = order[offset:] + order[:offset]
                        for scale in order:
                            target_width = max(1, int(round(base_width * scale)))
                            target_height = max(1, int(round(base_height * scale)))
                            input_frame = frame
                            if scale != 1.0:
                                input_frame = cv2.resize(
                                    frame,
                                    (target_width, target_height),
                                    interpolation=cv2.INTER_AREA,
                                )
                            rgb = None
                            mp_image = None
                            result = None
                            try:
                                started = perf_counter_ns()
                                rgb = cv2.cvtColor(input_frame, cv2.COLOR_BGR2RGB)
                                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                                result = task.detect(mp_image)
                                elapsed = perf_counter_ns() - started
                                frame_results[scale] = face_points(result)
                                if index >= args.warmup:
                                    measurement = measurements[scale]
                                    measurement["durations_ns"].append(elapsed)
                                    measurement["faces_total"] += len(frame_results[scale])
                            finally:
                                result = None
                                mp_image = None
                                if rgb is not None:
                                    rgb.fill(0)
                                if input_frame is not frame:
                                    input_frame.fill(0)

                        reference = frame_results[1.0]
                        if index >= args.warmup:
                            for scale, faces in frame_results.items():
                                measurement = measurements[scale]
                                measurement["reference_faces_total"] += len(reference)
                                if len(faces) != len(reference):
                                    measurement["count_mismatch_frames"] += 1
                                else:
                                    measurement["same_count_frames"] += 1
                                    frame_deltas = []
                                    for reference_points, points in zip(reference, faces, strict=True):
                                        if reference_points.shape == points.shape and points.size:
                                            frame_deltas.append(
                                                float(np.max(np.abs(reference_points - points)))
                                            )
                                    if frame_deltas:
                                        measurement["landmark_max_deltas"].append(max(frame_deltas))
                    finally:
                        for faces in frame_results.values():
                            for points in faces:
                                points.fill(0)
                        frame.fill(0)
                    frames_for_size += 1
            finally:
                if video_capture is not None:
                    video_capture.release()
                    video_capture = None
            frame_total = max(frame_total, frames_for_size)

            for scale, measurement in measurements.items():
                durations = np.asarray(measurement["durations_ns"], dtype=np.float64) / 1_000_000
                deltas = np.asarray(measurement["landmark_max_deltas"], dtype=np.float64)
                if not durations.size:
                    continue
                all_measurements.append(
                    {
                        "synthetic_face_size": face_size if args.video is None else None,
                        "input_scale": scale,
                        "input_width": max(1, int(round(base_width * scale))),
                        "input_height": max(1, int(round(base_height * scale))),
                        "samples": int(durations.size),
                        "median_ms": float(np.median(durations)),
                        "p95_ms": float(np.percentile(durations, 95)),
                        "faces_total": int(measurement["faces_total"]),
                        "full_resolution_reference_faces": int(measurement["reference_faces_total"]),
                        "face_count_mismatch_frames": int(measurement["count_mismatch_frames"]),
                        "same_count_frames": int(measurement["same_count_frames"]),
                        "landmark_max_abs_delta_median": float(np.median(deltas)) if deltas.size else None,
                        "landmark_max_abs_delta_p95": float(np.percentile(deltas, 95)) if deltas.size else None,
                    }
                )
    finally:
        if video_capture is not None:
            video_capture.release()
        task.close()

    if not all_measurements:
        raise SystemExit("input did not contain enough frames after warmup")

    print(
        json.dumps(
            {
                "scope": "mediapipe_input_resolution_latency_and_geometry_only",
                "input_kind": "local_video" if args.video is not None else "synthetic_non_photographic",
                "mediapipe": mp.__version__,
                "opencv": cv2.__version__,
                "python": platform.python_version(),
                "base_width": base_width,
                "base_height": base_height,
                "frames_per_face_size": frame_total,
                "warmup_frames": args.warmup,
                "results": all_measurements,
                "note": "No image, frame, landmark, or identity data is written or printed.",
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
