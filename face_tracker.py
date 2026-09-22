from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class Track:
    track_id: str = field(default_factory=lambda: str(uuid4()))
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    failures: int = 0
    missed_frames: int = 0
    quality_observations: int = 0
    cooldown_frames: int = 0


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


class TrackManager:
    def __init__(self, max_missed: int = 6):
        self.max_missed = max_missed
        self.tracks: list[Track] = []

    def assign(self, boxes: list[tuple[float, float, float, float]]) -> list[Track]:
        result: list[Track] = []
        unused = set(range(len(self.tracks)))
        for box in boxes:
            best_index = max(unused, key=lambda i: iou(self.tracks[i].bbox, box), default=None)
            if best_index is not None and iou(self.tracks[best_index].bbox, box) >= 0.2:
                track = self.tracks[best_index]
                unused.remove(best_index)
            else:
                track = Track()
            track.bbox, track.missed_frames = box, 0
            result.append(track)
        for index in unused:
            self.tracks[index].missed_frames += 1
        self.tracks = [
            *result,
            *(
                self.tracks[index]
                for index in unused
                if self.tracks[index].missed_frames <= self.max_missed
            ),
        ]
        return result

    def record_failure(self, track: Track) -> int:
        track.failures += 1
        track.quality_observations = 0
        track.cooldown_frames = 5
        return track.failures

    def record_success(self, track: Track) -> None:
        track.failures = 0
        track.quality_observations = 0
        track.cooldown_frames = 0

    def observe_quality(self, track: Track) -> bool:
        if track.cooldown_frames:
            track.cooldown_frames -= 1
            return False
        track.quality_observations += 1
        return track.quality_observations >= 3

    def reset(self) -> None:
        self.tracks.clear()
