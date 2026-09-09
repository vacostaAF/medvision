from __future__ import annotations
import cv2
import numpy as np


def order_points(pts: np.ndarray) -> np.ndarray:
    pts = pts.astype("float32")
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    rect = np.zeros((4, 2), dtype="float32")
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def rotate_crop_from_box(image: np.ndarray, box: np.ndarray, padding_ratio: float = 0.03) -> np.ndarray:
    rect = order_points(box)
    (tl, tr, br, bl) = rect
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_w = max(1, int(max(width_a, width_b)))
    max_h = max(1, int(max(height_a, height_b)))
    pad_w = int(max_w * padding_ratio)
    pad_h = int(max_h * padding_ratio)
    dst = np.array([[pad_w, pad_h], [max_w + pad_w - 1, pad_h], [max_w + pad_w - 1, max_h + pad_h - 1], [pad_w, max_h + pad_h - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (max_w + 2*pad_w, max_h + 2*pad_h))


def detect_bag_strip(frame_bgr: np.ndarray, threshold_value: int = 165, min_area_ratio: float = 0.08):
    """Detecta la tira/bolsa clara sobre fondo oscuro mediante umbral + contorno principal.
    Devuelve dict con box, crop, mask_area_ratio y confianza heurística, o None.
    """
    h, w = frame_bgr.shape[:2]
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (7,7), 0)
    _, th = cv2.threshold(blur, threshold_value, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 17))
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel, iterations=2)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, kernel, iterations=1)
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(contour)
    area_ratio = area / float(w*h)
    if area_ratio < min_area_ratio:
        return None
    rect = cv2.minAreaRect(contour)
    box = cv2.boxPoints(rect)
    crop = rotate_crop_from_box(frame_bgr, box)
    confidence = min(1.0, area_ratio / 0.35)
    return {"box": box.astype(int), "crop": crop, "area_ratio": round(area_ratio,4), "confidence": round(confidence,4)}


def draw_detection(frame_bgr: np.ndarray, box: np.ndarray | None, label: str = "bag") -> np.ndarray:
    out = frame_bgr.copy()
    if box is not None:
        cv2.drawContours(out, [box.astype(int)], 0, (0, 255, 0), 3)
        x, y = box.astype(int).min(axis=0)
        cv2.putText(out, label, (max(0,x), max(25,y-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
    return out
