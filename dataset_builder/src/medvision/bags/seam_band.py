from __future__ import annotations

import cv2
import numpy as np


def detect_seam_band(crop_bgr: np.ndarray, min_prominence_ratio: float = 3.0) -> tuple[bool, float | None, float]:
    """Detecta si hay una banda de sellado (costura entre bolsitas) visible
    en el recorte, a partir de su firma visual: brillo alto + tinte azulado
    del reflejo del foco/anillo LED usado al grabar (visto en las imágenes
    reales, tanto del lado etiqueta como del lado pastilla).

    A diferencia de `bags/splitter.py::estimate_horizontal_seams()` (gradiente
    Sobel-Y genérico), que en estas fotos confunde el borde de las letras
    impresas con la costura real (probado contra datos reales, ver
    docs/cuaderno_ingenieria_2.4.md), esto busca específicamente la firma de
    color del reflejo, no cualquier borde horizontal fuerte.

    Devuelve (encontrada, posición_normalizada [0-1] o None, prominencia).
    `min_prominence_ratio` es cuántas veces por encima de la mediana debe
    estar el pico para considerarse una costura real y no ruido de fondo.
    """
    if crop_bgr is None or crop_bgr.size == 0:
        return False, None, 0.0

    h, w = crop_bgr.shape[:2]
    x1, x2 = int(0.1 * w), int(0.9 * w)
    region = crop_bgr[:, x1:x2].astype(np.float32)
    b, g, r = region[..., 0], region[..., 1], region[..., 2]
    blue_tint = np.clip(b - (g + r) / 2.0, 0, None)

    hsv = cv2.cvtColor(crop_bgr[:, x1:x2], cv2.COLOR_BGR2HSV)
    brightness = hsv[..., 2].astype(np.float32) / 255.0

    combined = (blue_tint * brightness).mean(axis=1)
    kernel = max(5, int(h * 0.02) | 1)
    combined = cv2.GaussianBlur(combined.reshape(-1, 1), (1, kernel), 0).ravel()

    peak_row = int(np.argmax(combined))
    peak_val = float(combined[peak_row])
    median_val = float(np.median(combined))

    if median_val <= 1e-6:
        prominence = float("inf") if peak_val > 0 else 0.0
    else:
        prominence = peak_val / median_val

    found = prominence >= min_prominence_ratio
    return found, (peak_row / h if found else None), prominence


def detect_seam_bands(
    crop_bgr: np.ndarray, min_prominence_ratio: float = 3.0, min_separation_ratio: float = 0.12,
) -> list[tuple[float, float]]:
    """Como detect_seam_band(), pero encuentra TODAS las costuras
    suficientemente marcadas, no solo la más prominente — para fotos con
    3 o más bolsitas (2+ costuras), donde la versión de una sola costura
    deja sin separar todo lo que cae al lado que le tocó "más grande" (bug
    real con datos reales, ver docs/cuaderno_ingenieria_3.26.md: 433 de
    734 pares del dataset tocan este patrón).

    Devuelve una lista de (posición_normalizada, prominencia), ordenada de
    arriba a abajo. Lista vacía si no hay ninguna costura suficientemente
    marcada. `min_separation_ratio`: distancia mínima entre dos costuras
    (como fracción de la altura) para contarlas como distintas — evita que
    ruido alrededor de un mismo pico se cuente como dos costuras separadas.
    """
    if crop_bgr is None or crop_bgr.size == 0:
        return []

    h, w = crop_bgr.shape[:2]
    x1, x2 = int(0.1 * w), int(0.9 * w)
    region = crop_bgr[:, x1:x2].astype(np.float32)
    b, g, r = region[..., 0], region[..., 1], region[..., 2]
    blue_tint = np.clip(b - (g + r) / 2.0, 0, None)

    hsv = cv2.cvtColor(crop_bgr[:, x1:x2], cv2.COLOR_BGR2HSV)
    brightness = hsv[..., 2].astype(np.float32) / 255.0

    combined = (blue_tint * brightness).mean(axis=1)
    kernel = max(5, int(h * 0.02) | 1)
    combined = cv2.GaussianBlur(combined.reshape(-1, 1), (1, kernel), 0).ravel()

    median_val = float(np.median(combined))
    if median_val <= 1e-6:
        median_val = 1e-6

    min_sep_px = max(1, int(h * min_separation_ratio))

    # Picos locales: un punto es pico si es mayor que sus vecinos inmediatos
    # (ventana pequeña, ya suavizada arriba con el GaussianBlur).
    candidates = []
    for i in range(1, len(combined) - 1):
        if combined[i] >= combined[i - 1] and combined[i] >= combined[i + 1]:
            prominence = float(combined[i]) / median_val  # float() explícito: sin esto, sqlite3
            if prominence >= min_prominence_ratio:          # guarda un numpy.float32 como BLOB en vez
                candidates.append((i, prominence))           # de REAL (bug real, ver 3.28)

    # De mayor a menor prominencia, aceptando solo picos suficientemente
    # separados de los ya aceptados -- evita contar el mismo pico ancho
    # como varios picos vecinos.
    candidates.sort(key=lambda c: c[1], reverse=True)
    accepted: list[tuple[int, float]] = []
    for row, prominence in candidates:
        if all(abs(row - a_row) >= min_sep_px for a_row, _ in accepted):
            accepted.append((row, prominence))

    accepted.sort(key=lambda a: a[0])
    return [(row / h, prominence) for row, prominence in accepted]
