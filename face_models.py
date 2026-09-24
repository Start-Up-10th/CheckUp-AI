from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MODEL_ID = "openvino/face-reidentification-retail-0095"
EMBEDDING_DIMENSION = 256


@dataclass(frozen=True)
class ModelMetadata:
    model_id: str = MODEL_ID
    version: str = "face-reidentification-retail-0095@2023.0-fp32"
    dimension: int = EMBEDDING_DIMENSION
    normalization: str = "l2"


@dataclass(frozen=True)
class FaceObservation:
    """One detected face. Detection fields remain meaningful without identity."""

    bbox: tuple[float, float, float, float]
    landmarks: tuple[tuple[float, float], ...]
    embedding: np.ndarray | None
    brightness: float
    sharpness: float
    pose_bucket: str


class InferenceModels:
    """MediaPipe detector/landmarker plus a separate OpenVINO identity embedder.

    MediaPipe never produces or decides a student identity. The embedder is invoked
    only after a face has been detected and aligned from MediaPipe landmarks.
    """

    def __init__(self, landmarker_path: str, embedding_model_path: str, metadata: ModelMetadata):
        self.metadata = metadata
        self._landmarker = None
        self._compiled = None
        try:
            import mediapipe as mp
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            options = vision.FaceLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=landmarker_path),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=8,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
            )
            self._landmarker = vision.FaceLandmarker.create_from_options(options)
            self._mp = mp
        except ImportError as exc:
            raise RuntimeError("MediaPipe dependency is not installed") from exc

        try:
            from openvino import Core

            core = Core()
            model = core.read_model(embedding_model_path)
            self._compiled = core.compile_model(model, "CPU")
        except ImportError as exc:
            raise RuntimeError("OpenVINO dependency is not installed") from exc

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
        self._landmarker = None
        self._compiled = None

    def detect(self, bgr: np.ndarray) -> list[FaceObservation]:
        import cv2

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        try:
            image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            result = self._landmarker.detect(image)
            observations: list[FaceObservation] = []
            height, width = bgr.shape[:2]
            for landmarks in result.face_landmarks:
                points = np.array(
                    [(p.x * width, p.y * height) for p in landmarks], dtype=np.float32
                )
                x0, y0 = points.min(axis=0)
                x1, y1 = points.max(axis=0)
                bbox = (
                    float(max(0.0, x0) / width),
                    float(max(0.0, y0) / height),
                    float(max(0.0, x1 - x0) / width),
                    float(max(0.0, y1 - y0) / height),
                )
                five = _five_landmarks(points)
                aligned = _align_face(bgr, five)
                crop = bgr[
                    max(0, int(y0)) : min(height, int(y1)),
                    max(0, int(x0)) : min(width, int(x1)),
                ]
                try:
                    embedding = self.embed(aligned)
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.size else None
                    brightness = float(np.mean(gray)) if gray is not None else 0.0
                    sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var()) if crop.size else 0.0
                    observations.append(
                        FaceObservation(
                            bbox,
                            tuple(map(tuple, five)),
                            embedding,
                            brightness,
                            sharpness,
                            _pose_bucket(five),
                        )
                    )
                finally:
                    aligned.fill(0)
            return observations
        finally:
            rgb.fill(0)

    def embed(self, aligned_bgr: np.ndarray) -> np.ndarray:
        blob = np.transpose(aligned_bgr.astype(np.float32), (2, 0, 1))[None, ...]
        try:
            result = self._compiled([blob])[self._compiled.output(0)]
            vector = np.asarray(result, dtype=np.float32).reshape(-1)
            norm = float(np.linalg.norm(vector))
            if vector.size != self.metadata.dimension or not np.isfinite(vector).all() or norm == 0:
                raise ValueError("embedding model returned an invalid vector")
            return (vector / norm).astype(np.float32, copy=True)
        finally:
            blob.fill(0)


def _five_landmarks(points: np.ndarray) -> np.ndarray:
    # MediaPipe Face Mesh indices: eye corners, nose tip, mouth corners.
    return points[[33, 263, 1, 61, 291]]


def _align_face(image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    import cv2

    target = np.array(
        [[40.4, 59.1], [87.4, 59.1], [64.0, 82.0], [44.7, 105.6], [83.6, 105.6]],
        dtype=np.float32,
    )
    matrix, _ = cv2.estimateAffinePartial2D(landmarks.astype(np.float32), target)
    if matrix is None:
        raise ValueError("unable to align face landmarks")
    return cv2.warpAffine(image, matrix, (128, 128), flags=cv2.INTER_LINEAR)


def _pose_bucket(landmarks: np.ndarray) -> str:
    eye_midpoint = (landmarks[0] + landmarks[1]) / 2.0
    eye_width = max(float(np.linalg.norm(landmarks[1] - landmarks[0])), 1.0)
    yaw_proxy = abs(float(landmarks[2][0] - eye_midpoint[0])) / eye_width
    if yaw_proxy > 0.35:
        return "extreme"
    if yaw_proxy > 0.18:
        return "turned"
    return "frontal"
