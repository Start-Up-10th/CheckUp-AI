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
    bbox: tuple[float, float, float, float]
    landmarks: tuple[tuple[float, float], ...]
    embedding: np.ndarray | None
    brightness: float
    sharpness: float
    pose_bucket: str


class InferenceModels:
    """MediaPipe detector/landmarker plus a separate OpenVINO identity embedder."""

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
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect(image)
        observations: list[FaceObservation] = []
        height, width = bgr.shape[:2]
        for landmarks in result.face_landmarks:
            points = np.array([(p.x * width, p.y * height) for p in landmarks], dtype=np.float32)
            x0, y0 = points.min(axis=0)
            x1, y1 = points.max(axis=0)
            bbox = (
                float(x0 / width),
                float(y0 / height),
                float((x1 - x0) / width),
                float((y1 - y0) / height),
            )
            five = _five_landmarks(points)
            aligned = _align_face(bgr, five)
            embedding = self.embed(aligned)
            crop = bgr[
                max(0, int(y0)) : min(height, int(y1)), max(0, int(x0)) : min(width, int(x1))
            ]
            brightness = (
                float(np.mean(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))) if crop.size else 0.0
            )
            sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var()) if crop.size else 0.0
            observations.append(
                FaceObservation(
                    bbox, tuple(map(tuple, five)), embedding, brightness, sharpness, "frontal"
                )
            )
            aligned.fill(0)
        rgb.fill(0)
        return observations

    def embed(self, aligned_bgr: np.ndarray) -> np.ndarray:
        blob = np.transpose(aligned_bgr.astype(np.float32), (2, 0, 1))[None, ...]
        result = self._compiled([blob])[self._compiled.output(0)]
        vector = np.asarray(result, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        blob.fill(0)
        if vector.size != self.metadata.dimension or not np.isfinite(vector).all() or norm == 0:
            raise ValueError("embedding model returned an invalid vector")
        return vector / norm


def _five_landmarks(points: np.ndarray) -> np.ndarray:
    # MediaPipe Face Mesh indices: eye corners, nose tip, mouth corners.
    indices = (33, 263, 1, 61, 291)
    return points[list(indices)]


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
