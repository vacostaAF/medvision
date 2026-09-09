from __future__ import annotations
import cv2
import numpy as np


def frame_quality(frame_bgr: np.ndarray) -> dict:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean_brightness = float(gray.mean())
    contrast = float(gray.std())
    overexposed_ratio = float((gray >= 245).mean())
    underexposed_ratio = float((gray <= 10).mean())
    return {
        "sharpness_laplacian": round(sharpness, 3),
        "mean_brightness": round(mean_brightness, 3),
        "contrast_std": round(contrast, 3),
        "overexposed_ratio": round(overexposed_ratio, 5),
        "underexposed_ratio": round(underexposed_ratio, 5),
    }


def quality_score(metrics: dict) -> float:
    sharp = min(metrics["sharpness_laplacian"] / 800.0, 1.0)
    contrast = min(metrics["contrast_std"] / 80.0, 1.0)
    over_penalty = min(metrics["overexposed_ratio"] / 0.35, 1.0)
    score = 0.55 * sharp + 0.35 * contrast + 0.10 * (1.0 - over_penalty)
    return round(float(max(0.0, min(1.0, score))), 4)
