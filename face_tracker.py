from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from math import isfinite
from uuid import uuid4


@dataclass
class Track:
    track_id: str = field(default_factory=lambda: str(uuid4()))
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    failures: int = 0
    missed_frames: int = 0
    quality_observations: int = 0
    cooldown_frames: int = 0
    success_recheck_at: float | None = None


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


class TrackManager:
    def __init__(
        self,
        max_missed: int = 6,
        success_recheck_seconds: float = 1.0,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if not isfinite(success_recheck_seconds) or not 0 <= success_recheck_seconds <= 1:
            raise ValueError("success_recheck_seconds must be between 0 and 1")
        self.max_missed = max_missed
        self.success_recheck_seconds = success_recheck_seconds
        self.monotonic = monotonic
        self.tracks: list[Track] = []

    def assign(self, boxes: list[tuple[float, float, float, float]]) -> list[Track]:
        result: list[Track] = []
        unused = set(range(len(self.tracks)))
        # Snapshot all overlaps before mutating any bounding box. Continuity must
        # be unambiguous in both directions, including already assigned tracks.
        overlaps = [[iou(track.bbox, box) for track in self.tracks] for box in boxes]
        for box_index, box in enumerate(boxes):
            row = overlaps[box_index]
            best_index = max(unused, key=lambda i: row[i], default=None)
            if best_index is not None and row[best_index] >= 0.2:
                track = self.tracks[best_index]
                unused.remove(best_index)
                if track.success_recheck_at is not None:
                    overlap = row[best_index]
                    other_track = max(
                        (score for index, score in enumerate(row) if index != best_index),
                        default=0.0,
                    )
                    other_box = max(
                        (
                            scores[best_index]
                            for index, scores in enumerate(overlaps)
                            if index != box_index
                        ),
                        default=0.0,
                    )
                    if (
                        track.missed_frames
                        or overlap < 0.5
                        or overlap - other_track < 0.2
                        or overlap - other_box < 0.2
                    ):
                        self.reject_quality(track)
            else:
                track = Track()
            track.bbox, track.missed_frames = box, 0
            result.append(track)
        for index in unused:
            self.tracks[index].missed_frames += 1
            self.reject_quality(self.tracks[index])
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
        track.success_recheck_at = None
        track.failures += 1
        track.quality_observations = 0
        track.cooldown_frames = 5
        return track.failures

    def record_success(self, track: Track) -> None:
        track.failures = 0
        track.quality_observations = 0
        track.cooldown_frames = 0
        track.success_recheck_at = (
            self.monotonic() + self.success_recheck_seconds
            if self.success_recheck_seconds
            else None
        )

    def reject_quality(self, track: Track) -> None:
        """Invalidate success reuse without changing legacy failure cooldowns."""
        if track.success_recheck_at is not None:
            track.success_recheck_at = None
            track.quality_observations = 0

    def observe_quality(self, track: Track) -> bool:
        if track.cooldown_frames:
            track.cooldown_frames -= 1
            return False
        if track.success_recheck_at is None:
            track.quality_observations += 1
        else:
            track.quality_observations = min(3, track.quality_observations + 1)
        if track.success_recheck_at is not None and self.monotonic() < track.success_recheck_at:
            return False
        return track.quality_observations >= 3

    def reset(self) -> None:
        self.tracks.clear()
