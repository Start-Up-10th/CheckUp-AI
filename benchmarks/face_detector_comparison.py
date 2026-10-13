"""Experimental MediaPipe versus YuNet 2023mar FP32 comparison (never a runtime switch).

Examples (run from the repository root):
    .venv/Scripts/python.exe benchmarks/face_detector_comparison.py --download-yunet
    .venv/Scripts/python.exe benchmarks/face_detector_comparison.py --video .local/approved.mp4
    .venv/Scripts/python.exe benchmarks/face_detector_comparison.py --video .local/approved.mp4 \
        --gallery-json .local/gallery.json --threshold 0.6 --margin 0.1

Gallery JSON uses the existing AI session PUT payload: {"model": {...},
"candidates": [{"student_id": "...", "vectors": [[...]]}]}. Supply the actual
deployment threshold/margin explicitly. Do not commit or collect biometric inputs
for this benchmark. It never copies local inputs or writes frames/vectors/results.
The optional download retrieves only the publicly released detector model.

Without --video, procedural drawings test execution and timing only. They cannot
measure face accuracy. Even with a gallery, agreement with MediaPipe is not ground
truth: labelled, approved validation is still needed before enabling a detector.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from time import perf_counter_ns
from urllib.request import urlopen

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.face_detection_modes import positive_int, synthetic_frame  # noqa: E402
from face_models import FaceObservation, InferenceModels, ModelMetadata, _pose_bucket  # noqa: E402
from face_pipeline import CandidateGallery, Match, normalize_vector, quality_issues  # noqa: E402

YUNET_NAME = "face_detection_yunet_2023mar.onnx"
YUNET_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
    f"models/face_detection_yunet/{YUNET_NAME}"
)
# Verified against the official repository's Git LFS pointer (not an INT8 variant).
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_BYTES = 232589
LANDMARK_REFERENCE = "https://docs.opencv.org/4.11.0/df/d20/classcv_1_1FaceDetectorYN.html"


def ensure_yunet(path: Path, download: bool) -> None:
    """Verify before OpenCV parses the model; never replace an existing file."""
    if not path.is_file():
        if not download:
            raise ValueError("YuNet model is missing; run with --download-yunet")
        with urlopen(YUNET_URL, timeout=30) as response:
            content = response.read(YUNET_BYTES + 1)
        if len(content) != YUNET_BYTES or hashlib.sha256(content).hexdigest() != YUNET_SHA256:
            raise ValueError("downloaded YuNet model failed size/SHA-256 verification")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as destination:
            destination.write(content)
    if path.stat().st_size != YUNET_BYTES:
        raise ValueError("YuNet model has an unexpected size")
    if hashlib.sha256(path.read_bytes()).hexdigest() != YUNET_SHA256:
        raise ValueError("YuNet model has an unexpected SHA-256")


def observation_from_yunet(row: np.ndarray, frame: np.ndarray) -> FaceObservation:
    """Use YuNet landmarks with the existing 128x128 BGR 0095 alignment.

    OpenCV documents right eye, left eye, nose, right mouth, left mouth: subject
    right is image left for a frontal face, matching _align_face's target order.
    YuNet eye locations and MediaPipe eye corners are NOT identical landmarks.
    Its detector box also differs from the MediaPipe mesh envelope; we measure
    resulting quality/embedding changes instead of treating them as compatible.
    """
    height, width = frame.shape[:2]
    x, y, box_width, box_height = map(float, row[:4])
    x0, y0 = max(0.0, x), max(0.0, y)
    x1, y1 = min(float(width), x + box_width), min(float(height), y + box_height)
    bbox = (x0 / width, y0 / height, max(0.0, x1 - x0) / width, max(0.0, y1 - y0) / height)
    five = np.asarray(row[4:14], dtype=np.float32).reshape(5, 2)
    crop = frame[int(y0):int(max(y0, y1)), int(x0):int(max(x0, x1))]
    gray = None
    try:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.size else None
        return FaceObservation(
            bbox,
            tuple((float(x), float(y)) for x, y in five),
            None,
            float(np.mean(gray)) if gray is not None else 0.0,
            float(cv2.Laplacian(crop, cv2.CV_64F).var()) if crop.size else 0.0,
            _pose_bucket(five),
        )
    finally:
        if gray is not None:
            gray.fill(0)


class YuNetDetector:
    def __init__(self, model_path: Path):
        self.detector = cv2.FaceDetectorYN.create(
            str(model_path), "", (640, 480), 0.9, 0.3, 5000,
            cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU,
        )

    def detect_faces(self, frame: np.ndarray) -> list[FaceObservation]:
        self.detector.setInputSize((frame.shape[1], frame.shape[0]))
        rows = None
        try:
            _, rows = self.detector.detect(frame)
            if rows is None:
                return []
            # The service's MediaPipe configuration also has a maximum of 8 faces.
            indices = np.argsort(-rows[:, 14], kind="stable")[:8]
            return [observation_from_yunet(rows[index], frame) for index in indices]
        finally:
            if rows is not None:
                rows.fill(0)


def overlap(left: FaceObservation, right: FaceObservation) -> float:
    x, y, w, h = left.bbox
    a, b, c, d = right.bbox
    intersection = max(0.0, min(x + w, a + c) - max(x, a)) * max(
        0.0, min(y + h, b + d) - max(y, b)
    )
    union = w * h + c * d - intersection
    return intersection / union if union > 0 else 0.0


def match_faces(
    baseline: list[FaceObservation], candidate: list[FaceObservation], minimum_iou: float = 0.3
) -> tuple[tuple[int, int], ...]:
    """Maximize paired count, then total IoU; never zip faces by horizontal order.

    At most eight faces make an exact bit-mask assignment small. Each candidate
    is used once. Missing/non-overlapping faces remain explicitly unmatched.
    This establishes spatial correspondence, not identity or temporal tracking.
    """
    if len(baseline) > 8 or len(candidate) > 8:
        raise ValueError("comparison supports at most eight faces per detector")
    weights = [[overlap(left, right) for right in candidate] for left in baseline]

    @cache
    def assign(index: int, used: int) -> tuple[int, float, tuple[tuple[int, int], ...]]:
        if index == len(baseline):
            return 0, 0.0, ()
        best = assign(index + 1, used)
        for other, weight in enumerate(weights[index]):
            if used & (1 << other) or weight < minimum_iou:
                continue
            count, total, pairs = assign(index + 1, used | (1 << other))
            option = count + 1, total + weight, ((index, other), *pairs)
            if option[:2] > best[:2]:
                best = option
        return best

    return assign(0, 0)[2]


def clear_json(value: object) -> None:
    """Release decoded containers promptly; Python immutable scalars cannot be zeroed."""
    if isinstance(value, dict):
        for child in value.values():
            clear_json(child)
        value.clear()
    elif isinstance(value, list):
        for child in value:
            clear_json(child)
        value.clear()


def load_gallery(path: Path) -> CandidateGallery:
    """Validate the existing session payload without printing validation input."""
    raw = bytearray()
    payload = None
    normalized: dict[str, list[np.ndarray]] = {}
    try:
        # Same 60 MiB body ceiling as the service, without retaining a bytes copy.
        with path.open("rb") as stream:
            raw = bytearray(stream.read(60 * 1024 * 1024 + 1))
        if len(raw) > 60 * 1024 * 1024:
            raise ValueError("gallery is too large")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("model") != asdict(ModelMetadata()):
            raise ValueError("gallery model metadata must match existing 0095 FP32")
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 200:
            raise ValueError("gallery needs 1 to 200 candidates")
        for item in candidates:
            if not isinstance(item, dict):
                raise ValueError("invalid gallery candidate")
            student_id, vectors = item.get("student_id"), item.get("vectors")
            if not isinstance(student_id, str) or not student_id or student_id in normalized:
                raise ValueError("gallery candidate identifiers must be nonempty and unique")
            if not isinstance(vectors, list) or not 1 <= len(vectors) <= 20:
                raise ValueError("gallery candidates need 1 to 20 vectors")
            normalized[student_id] = []
            for vector in vectors:
                normalized[student_id].append(normalize_vector(vector))
        # Preserve the session PUT's first normalization, then gallery normalization.
        return CandidateGallery.from_candidates(normalized)
    finally:
        raw[:] = b"\x00" * len(raw)
        clear_json(payload)
        for vectors in normalized.values():
            for vector in vectors:
                vector.fill(0)
        normalized.clear()


@dataclass
class PipelineResult:
    observations: list[FaceObservation]
    vectors: list[np.ndarray | None]
    decisions: list[Match | None]
    detection_ns: int
    total_ns: int

    def clear(self) -> None:
        for vector in self.vectors:
            if vector is not None:
                vector.fill(0)
        self.vectors.clear()
        self.observations.clear()
        self.decisions.clear()


def run_pipeline(
    frame: np.ndarray,
    detect: Callable[[np.ndarray], list[FaceObservation]],
    models: InferenceModels,
    gallery: CandidateGallery | None,
    threshold: float | None,
    margin: float | None,
) -> PipelineResult:
    result = PipelineResult([], [], [], 0, 0)
    started = perf_counter_ns()
    try:
        result.observations = detect(frame)
        result.detection_ns = perf_counter_ns() - started
        for observation in result.observations:
            if quality_issues(observation):
                result.vectors.append(None)
                result.decisions.append(None)
                continue
            vector = models.embed_face(frame, observation)
            result.vectors.append(vector)
            result.decisions.append(gallery.match(vector, threshold, margin) if gallery else None)
        result.total_ns = perf_counter_ns() - started
        return result
    except BaseException:
        result.clear()
        raise


def distribution(values: list[float]) -> dict[str, float | int | None]:
    return {
        "samples": len(values),
        "median": float(np.median(values)) if values else None,
        "p95": float(np.percentile(values, 95)) if values else None,
    }


def synthetic_scene(index: int, face_count: int) -> np.ndarray:
    if face_count == 1:
        return synthetic_frame(index)
    columns, rows = (2, 2) if face_count == 4 else (4, 2)
    canvas = np.full((480, 640, 3), 224, np.uint8)
    width, height = 640 // columns, 480 // rows
    drawing = None
    resized = None
    try:
        for number in range(face_count):
            drawing = synthetic_frame(index + number * 3)
            resized = cv2.resize(drawing, (width, height), interpolation=cv2.INTER_AREA)
            x, y = (number % columns) * width, (number // columns) * height
            canvas[y:y + height, x:x + width] = resized
            drawing.fill(0)
            resized.fill(0)
        return canvas
    finally:
        if drawing is not None:
            drawing.fill(0)
        if resized is not None:
            resized.fill(0)


def compare_stream(args, models, detector, gallery, synthetic_faces: int | None) -> dict:
    capture = None
    if args.video is not None:
        if not args.video.is_file():
            raise ValueError("benchmark video must be an existing local file")
        capture = cv2.VideoCapture(str(args.video))
        if not capture.isOpened():
            capture.release()
            raise ValueError("could not open benchmark video")
    stage_times = {name: {"detect_geometry_quality_ms": [], "pipeline_ms": []} for name in ("mediapipe", "yunet")}
    totals = {name: {"detected": 0, "embedded": 0} for name in stage_times}
    paired = mismatch_frames = unmatched_baseline = unmatched_candidate = quality_disagreements = 0
    decision_pairs = decision_agreements = different_known = 0
    landmark_drifts: list[float] = []
    cosines: list[float] = []
    try:
        for index in range(args.max_frames):
            if capture is None:
                frame = synthetic_scene(index, synthetic_faces)
            else:
                success, frame = capture.read()
                if not success:
                    break
            results: dict[str, PipelineResult] = {}
            try:
                detectors = [("mediapipe", models.detect_faces), ("yunet", detector.detect_faces)]
                for name, detect in detectors[::1 if index % 2 == 0 else -1]:
                    results[name] = run_pipeline(frame, detect, models, gallery, args.threshold, args.margin)
                if index < args.warmup:
                    continue
                for name, result in results.items():
                    stage_times[name]["detect_geometry_quality_ms"].append(result.detection_ns / 1e6)
                    stage_times[name]["pipeline_ms"].append(result.total_ns / 1e6)
                    totals[name]["detected"] += len(result.observations)
                    totals[name]["embedded"] += sum(vector is not None for vector in result.vectors)
                baseline, candidate = results["mediapipe"], results["yunet"]
                pairs = match_faces(baseline.observations, candidate.observations)
                paired += len(pairs)
                mismatch_frames += len(baseline.observations) != len(candidate.observations)
                unmatched_baseline += len(baseline.observations) - len(pairs)
                unmatched_candidate += len(candidate.observations) - len(pairs)
                for left, right in pairs:
                    first, second = baseline.observations[left], candidate.observations[right]
                    delta = np.asarray(first.landmarks) - np.asarray(second.landmarks)
                    # Aggregate RMS in pixels; landmark locations themselves are never output.
                    landmark_drifts.append(float(np.sqrt(np.mean(np.sum(delta * delta, axis=1)))))
                    delta.fill(0)
                    one, two = baseline.vectors[left], candidate.vectors[right]
                    quality_disagreements += (one is None) != (two is None)
                    if one is not None and two is not None:
                        cosines.append(float(np.clip(one @ two, -1.0, 1.0)))
                    if gallery is not None:
                        a, b = baseline.decisions[left], candidate.decisions[right]
                        decision_pairs += 1
                        decision_agreements += (a.status, a.student_id) == (b.status, b.student_id) if a and b else a is b
                        different_known += bool(a and b and a.status == b.status == "KNOWN" and a.student_id != b.student_id)
            finally:
                for result in results.values():
                    result.clear()
                frame.fill(0)
    finally:
        if capture is not None:
            capture.release()
    measured = len(stage_times["mediapipe"]["pipeline_ms"])
    if not measured:
        raise ValueError("input did not contain enough frames after warmup")
    metrics = {
        name: {**{stage: distribution(values) for stage, values in times.items()}, **totals[name]}
        for name, times in stage_times.items()
    }
    baseline_p95 = metrics["mediapipe"]["detect_geometry_quality_ms"]["p95"]
    candidate_p95 = metrics["yunet"]["detect_geometry_quality_ms"]["p95"]
    return {
        "synthetic_drawings": synthetic_faces,
        "measured_frames": measured,
        "detectors": metrics,
        "detection_p95_improvement_percent": 100 * (baseline_p95 - candidate_p95) / baseline_p95,
        "face_count_mismatch_frames": mismatch_frames,
        "spatially_paired_faces": paired,
        "unmatched_baseline_faces": unmatched_baseline,
        "unmatched_candidate_faces": unmatched_candidate,
        "quality_disagreements": quality_disagreements,
        "five_landmark_rms_drift_pixels": distribution(landmark_drifts),
        "embedding_cosine": distribution(cosines),
        "recognition": {
            "evaluated_with_existing_gallery": gallery is not None,
            "paired_decisions": decision_pairs,
            "decision_agreements": decision_agreements,
            "different_known_identity_pairs": different_known,
            "false_accept_rate": None,
            "false_reject_rate": None,
        },
        "activation_eligible": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, help="approved local video only; no webcam/network inputs")
    parser.add_argument("--gallery-json", type=Path, help="private existing 0095 session PUT payload")
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--margin", type=float)
    parser.add_argument("--download-yunet", action="store_true", help="download and verify public model if absent")
    parser.add_argument("--yunet-model", type=Path, default=ROOT / "models" / YUNET_NAME)
    parser.add_argument("--synthetic-faces", type=int, choices=[1, 4, 8], nargs="+", default=[1, 4, 8])
    parser.add_argument("--warmup", type=positive_int, default=10)
    parser.add_argument("--max-frames", type=positive_int, default=60)
    args = parser.parse_args()
    if args.max_frames <= args.warmup:
        parser.error("--max-frames must exceed --warmup")
    if args.gallery_json and (args.threshold is None or args.margin is None):
        parser.error("gallery comparison requires explicit --threshold and --margin")
    if args.gallery_json and args.video is None:
        parser.error("gallery comparison requires an approved local --video")
    if any(value is not None and not np.isfinite(value) for value in (args.threshold, args.margin)):
        parser.error("threshold and margin must be finite")
    gallery = None
    models = None
    try:
        ensure_yunet(args.yunet_model, args.download_yunet)
        if args.gallery_json is not None:
            gallery = load_gallery(args.gallery_json)
        models = InferenceModels(
            str(ROOT / "models" / "face_landmarker.task"),
            str(ROOT / "models" / "face-reidentification-retail-0095.xml"),
            ModelMetadata(),
            "f32",
        )
        detector = YuNetDetector(args.yunet_model)
        measurements = [
            compare_stream(args, models, detector, gallery, count)
            for count in ([None] if args.video is not None else args.synthetic_faces)
        ]
        import mediapipe
        import openvino

        print(json.dumps({
            "scope": "experimental_detector_quality_alignment_embedding_comparison",
            "input_kind": "approved_local_video" if args.video else "synthetic_non_photographic",
            "versions": {"python": platform.python_version(), "opencv": cv2.__version__, "mediapipe": mediapipe.__version__, "openvino": openvino.__version__},
            "candidate_model": {"name": YUNET_NAME, "sha256": YUNET_SHA256, "size_bytes": YUNET_BYTES, "source": YUNET_URL, "landmark_reference": LANDMARK_REFERENCE},
            "embedding_model": asdict(models.metadata),
            "candidate_parameters": {"score_threshold": 0.9, "nms_threshold": 0.3, "top_k": 5000, "max_faces": 8, "input_resize": False, "target": "CPU_FP32"},
            "threshold": args.threshold,
            "margin": args.margin,
            "warmup_frames_per_case": args.warmup,
            "measurements": measurements,
            "limitations": [
                "Synthetic drawing counts are input counts, not labelled real faces or accuracy evidence.",
                "Different detector boxes and eye landmark conventions can change quality and alignment.",
                "Pipeline embeds every quality-passing face; HTTP, temporal gates and session queues are excluded.",
                "Spatial IoU matching can be ambiguous for overlapping faces; it does not prove identity.",
                "Gallery decisions show baseline agreement, not false acceptance/rejection without ground truth.",
                "No activation: approved labelled accuracy validation and the 15 percent p95 gate remain required.",
                "No frames, vectors, identities, landmarks, video paths or gallery paths are written or printed.",
            ],
        }, indent=2, allow_nan=False))
    finally:
        if models is not None:
            models.close()
        if gallery is not None:
            gallery.clear()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Library/JSON exceptions may contain private input or local file paths.
        print(f"Benchmark failed ({type(exc).__name__}); verify local inputs/model files and arguments.", file=sys.stderr)
        raise SystemExit(1) from None
