from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import cv2
import numpy as np


@dataclass
class BagObservation:
    bag_id: int
    frame_id: int
    frame_index: int
    timestamp_seconds: float
    bag_index_in_frame: int
    crop: np.ndarray
    y1: int
    y2: int
    frame_height: int
    quality_score: float
    segment_confidence: float

    @property
    def center_norm(self) -> float:
        return ((self.y1 + self.y2) / 2.0) / max(1, self.frame_height)

    @property
    def combined_quality(self) -> float:
        return 0.65 * float(self.quality_score) + 0.35 * float(self.segment_confidence)


@dataclass
class TrackAssignment:
    bag_id: int
    track_key: str
    match_score: float
    is_best: bool = False


@dataclass
class _TrackState:
    key: str
    last_frame_index: int
    last_timestamp: float
    last_center: float
    descriptor: np.ndarray
    best_bag_id: int
    best_quality: float
    bag_ids: list[int] = field(default_factory=list)


def _descriptor(crop: np.ndarray) -> np.ndarray:
    """Compact appearance descriptor using HSV histograms and coarse grayscale pixels."""
    if crop is None or crop.size == 0:
        return np.zeros(128, dtype=np.float32)
    resized = cv2.resize(crop, (64, 64), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]).flatten()
    hist = hist.astype(np.float32)
    hist /= max(float(np.linalg.norm(hist)), 1e-8)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    coarse = cv2.resize(gray, (8, 4), interpolation=cv2.INTER_AREA).astype(np.float32).flatten() / 255.0
    desc = np.concatenate([hist, coarse])
    desc /= max(float(np.linalg.norm(desc)), 1e-8)
    return desc


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    den = float(np.linalg.norm(a) * np.linalg.norm(b))
    if den <= 1e-8:
        return 0.0
    return float(np.clip(np.dot(a, b) / den, 0.0, 1.0))


class BagTracker:
    """Explainable greedy tracker for preliminary dataset construction.

    It links bag crops between sampled frames using appearance similarity, normalized
    vertical position and temporal continuity. It is deliberately lightweight and does
    not replace a trained detector/tracker in the final system.
    """

    def __init__(
        self,
        video_stem: str,
        side: str,
        appearance_weight: float = 0.72,
        position_weight: float = 0.20,
        order_weight: float = 0.08,
        min_match_score: float = 0.68,
        max_position_delta: float = 0.48,
        max_gap_seconds: float = 8.5,
        descriptor_momentum: float = 0.70,
    ) -> None:
        self.video_stem = video_stem
        self.side = side
        self.appearance_weight = appearance_weight
        self.position_weight = position_weight
        self.order_weight = order_weight
        self.min_match_score = min_match_score
        self.max_position_delta = max_position_delta
        self.max_gap_seconds = max_gap_seconds
        self.descriptor_momentum = descriptor_momentum
        self._tracks: list[_TrackState] = []
        self._counter = 0

    def _new_track(self, obs: BagObservation, desc: np.ndarray) -> _TrackState:
        self._counter += 1
        key = f"{self.video_stem}:{self.side}:track{self._counter:04d}"
        state = _TrackState(
            key=key,
            last_frame_index=obs.frame_index,
            last_timestamp=obs.timestamp_seconds,
            last_center=obs.center_norm,
            descriptor=desc,
            best_bag_id=obs.bag_id,
            best_quality=obs.combined_quality,
            bag_ids=[obs.bag_id],
        )
        self._tracks.append(state)
        return state

    def update(self, observations: Iterable[BagObservation]) -> list[TrackAssignment]:
        obs_list = sorted(list(observations), key=lambda x: x.bag_index_in_frame)
        if not obs_list:
            return []
        descriptors = [_descriptor(o.crop) for o in obs_list]

        candidates: list[tuple[float, int, int]] = []
        active_tracks = [
            (idx, t) for idx, t in enumerate(self._tracks)
            if obs_list[0].timestamp_seconds - t.last_timestamp <= self.max_gap_seconds
        ]
        max_order = max(1, len(obs_list) - 1)
        for oi, (obs, desc) in enumerate(zip(obs_list, descriptors)):
            for ti, track in active_tracks:
                pos_delta = abs(obs.center_norm - track.last_center)
                if pos_delta > self.max_position_delta:
                    continue
                appearance = _cosine(desc, track.descriptor)
                position = max(0.0, 1.0 - pos_delta / self.max_position_delta)
                # Weak order consistency: useful when the strip moves smoothly.
                previous_rank = min(max_order, len(track.bag_ids) - 1)
                order = max(0.0, 1.0 - abs(oi - previous_rank) / max_order)
                score = (
                    self.appearance_weight * appearance
                    + self.position_weight * position
                    + self.order_weight * order
                )
                candidates.append((score, oi, ti))

        assignments: dict[int, tuple[int, float]] = {}
        used_tracks: set[int] = set()
        for score, oi, ti in sorted(candidates, reverse=True):
            if score < self.min_match_score or oi in assignments or ti in used_tracks:
                continue
            assignments[oi] = (ti, score)
            used_tracks.add(ti)

        results: list[TrackAssignment] = []
        for oi, (obs, desc) in enumerate(zip(obs_list, descriptors)):
            if oi in assignments:
                ti, score = assignments[oi]
                track = self._tracks[ti]
                track.last_frame_index = obs.frame_index
                track.last_timestamp = obs.timestamp_seconds
                track.last_center = obs.center_norm
                track.descriptor = (
                    self.descriptor_momentum * track.descriptor
                    + (1.0 - self.descriptor_momentum) * desc
                )
                track.descriptor /= max(float(np.linalg.norm(track.descriptor)), 1e-8)
                track.bag_ids.append(obs.bag_id)
            else:
                track = self._new_track(obs, desc)
                score = 1.0

            is_best = obs.combined_quality > track.best_quality
            if is_best:
                track.best_bag_id = obs.bag_id
                track.best_quality = obs.combined_quality
            results.append(TrackAssignment(obs.bag_id, track.key, float(score), is_best))
        return results

    def finalize(self) -> tuple[list[dict[str, object]], dict[int, bool]]:
        rows: list[dict[str, object]] = []
        best_map: dict[int, bool] = {}
        for track in self._tracks:
            for bag_id in track.bag_ids:
                best_map[bag_id] = bag_id == track.best_bag_id
            rows.append({
                "track_key": track.key,
                "video_stem": self.video_stem,
                "side": self.side,
                "observation_count": len(track.bag_ids),
                "best_bag_id": track.best_bag_id,
                "best_quality": round(track.best_quality, 6),
                "first_bag_id": track.bag_ids[0],
                "last_bag_id": track.bag_ids[-1],
            })
        return rows, best_map
