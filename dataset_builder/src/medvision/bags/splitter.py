from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple
import cv2
import numpy as np

@dataclass
class BagSegment:
    index: int
    y1: int
    y2: int
    confidence: float
    crop: np.ndarray


def _merge_close_positions(positions: np.ndarray, min_gap: int) -> list[int]:
    if len(positions) == 0:
        return []
    groups = []
    cur = [int(positions[0])]
    for p in positions[1:]:
        p = int(p)
        if p - cur[-1] <= min_gap:
            cur.append(p)
        else:
            groups.append(cur)
            cur = [p]
    groups.append(cur)
    return [int(np.median(g)) for g in groups]


def estimate_horizontal_seams(strip_crop: np.ndarray, min_segment_height: int = 180) -> list[int]:
    """Estimate horizontal separation lines between consecutive bags in a vertical strip.

    The method is intentionally classical and explainable:
    1. Convert to grayscale.
    2. Detect horizontal edges using Sobel-Y.
    3. Project edge strength by rows.
    4. Select strong row bands as candidate thermoseal/seam lines.

    It is a preliminary heuristic for dataset building, not a final detector.
    """
    if strip_crop is None or strip_crop.size == 0:
        return []
    gray = cv2.cvtColor(strip_crop, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    # Work only in the central part to avoid dark borders of the table/background.
    x1, x2 = int(0.08*w), int(0.92*w)
    roi = gray[:, x1:x2]
    roi = cv2.GaussianBlur(roi, (5,5), 0)
    sobel_y = cv2.Sobel(roi, cv2.CV_32F, 0, 1, ksize=3)
    edge_profile = np.mean(np.abs(sobel_y), axis=1)
    # Smooth projection.
    kernel = max(11, int(h * 0.012) | 1)
    edge_profile = cv2.GaussianBlur(edge_profile.reshape(-1,1), (1, kernel), 0).ravel()
    # Normalize robustly.
    p90 = np.percentile(edge_profile, 90)
    p98 = np.percentile(edge_profile, 98)
    if p98 <= 1e-6:
        return []
    threshold = p90 + 0.25*(p98-p90)
    candidates = np.where(edge_profile >= threshold)[0]
    seams = _merge_close_positions(candidates, min_gap=max(8, int(0.035*h)))
    # Remove very top/bottom and enforce minimum segment size.
    seams = [s for s in seams if int(0.06*h) < s < int(0.94*h)]
    filtered = []
    last = 0
    for s in seams:
        if s - last >= min_segment_height:
            filtered.append(s)
            last = s
    return filtered


def fallback_equal_splits(strip_crop: np.ndarray, target_segment_height: int = 360) -> list[int]:
    h, _ = strip_crop.shape[:2]
    n = max(1, int(round(h / target_segment_height)))
    if n <= 1:
        return []
    return [int(i*h/n) for i in range(1, n)]


def split_vertical_strip_into_bags(
    strip_crop: np.ndarray,
    min_segment_height: int = 220,
    max_segments: int = 12,
    margin: int = 8,
) -> list[BagSegment]:
    """Split a vertical strip crop into individual bag crops.

    Returns BagSegment objects. If seam detection is weak, falls back to equal-size
    segmentation so the pipeline remains end-to-end for preliminary reporting.
    """
    h, w = strip_crop.shape[:2]
    seams = estimate_horizontal_seams(strip_crop, min_segment_height=min_segment_height)
    method_conf = 0.75 if len(seams) >= 2 else 0.35
    # If too few seams are detected, use equal splits based on visible strip height.
    if len(seams) < 2:
        # Empirical initial value: visible bags are usually around half the strip width tall to one strip width tall.
        target = max(min_segment_height, int(w * 0.85))
        seams = fallback_equal_splits(strip_crop, target_segment_height=target)
        method_conf = 0.30
    # Limit excessive splits.
    seams = sorted(seams)[:max_segments-1]
    bounds = [0] + seams + [h]
    segments: list[BagSegment] = []
    idx = 0
    for a, b in zip(bounds[:-1], bounds[1:]):
        y1 = max(0, int(a) + margin)
        y2 = min(h, int(b) - margin)
        if y2 - y1 < int(min_segment_height * 0.45):
            continue
        crop = strip_crop[y1:y2, :].copy()
        segments.append(BagSegment(index=idx, y1=y1, y2=y2, confidence=method_conf, crop=crop))
        idx += 1
    return segments


def draw_segments(strip_crop: np.ndarray, segments: list[BagSegment]) -> np.ndarray:
    img = strip_crop.copy()
    for seg in segments:
        cv2.rectangle(img, (0, seg.y1), (img.shape[1]-1, seg.y2), (0, 180, 255), 3)
        cv2.putText(img, f'bag {seg.index} conf {seg.confidence:.2f}', (12, max(28, seg.y1+32)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 80, 255), 2, cv2.LINE_AA)
    return img
