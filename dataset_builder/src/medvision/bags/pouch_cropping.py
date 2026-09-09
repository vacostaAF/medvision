from __future__ import annotations

import numpy as np


def crop_pouches_by_y_boundaries(
    image: np.ndarray, cut_positions_norm: list[float], margin_px: int = 0,
) -> list[np.ndarray]:
    """Recorta una imagen en N+1 sub-imágenes (una por bolsita) según N
    posiciones de corte normalizadas (0-1). Uso general para cuando SÍ se
    conocen todas las fronteras reales dentro de la imagen (p.ej. costuras
    ya validadas). Para generar una imagen por bolsita a partir del
    contenido (nombre de paciente + pie de farmacia), usar
    `crop_complete_pouches()` en su lugar — esta función asume que el
    borde de la imagen SÍ es una frontera válida, lo cual no es cierto en
    ese caso (ver docs/cuaderno_ingenieria_3.37.md).
    """
    if image is None or image.size == 0:
        return []
    h = image.shape[0]
    if not cut_positions_norm:
        return [image]

    sorted_cuts = sorted(cut_positions_norm)
    cut_rows = [int(c * h) for c in sorted_cuts]
    boundaries = [0] + cut_rows + [h]

    crops = []
    for i in range(len(boundaries) - 1):
        y0 = max(0, boundaries[i] - (margin_px if i > 0 else 0))
        y1 = min(h, boundaries[i + 1] + (margin_px if i < len(boundaries) - 2 else 0))
        if y1 > y0:
            crops.append(image[y0:y1, :].copy())
    return crops


def crop_complete_pouches(
    image: np.ndarray, boundaries_norm: list[tuple[float, float]] | list[tuple[float, float, str]],
    margin_px: int = 0, margin_bottom_px: int | None = None,
) -> list[np.ndarray]:
    """Recorta una imagen usando pares (inicio, fin[, firma]) YA
    EMPAREJADOS de `ocr.parser.find_complete_pouch_boundaries()` — a
    diferencia de `crop_pouches_by_y_boundaries()`, el borde de la imagen
    NUNCA se trata como frontera: solo se recorta lo que está
    EXPLÍCITAMENTE entre un inicio y un fin detectados por contenido.
    Cualquier fragmento parcial (cola de una bolsita sin su cabecera
    visible, o cabecera sin llegar a su pie) queda fuera a propósito — se
    recupera solo en un fotograma vecino que sí lo contenga completo
    (caso real que motivó este cambio, ver
    docs/cuaderno_ingenieria_3.37.md). El tercer elemento (firma), si
    está presente, se ignora aquí — es solo para deduplicar, no afecta al
    recorte.

    `margin_px`: margen arriba (y abajo, si `margin_bottom_px` no se
    especifica). `margin_bottom_px`: margen abajo, si se quiere distinto
    del de arriba.

    Límite de seguridad: el margen inferior NUNCA hace que un recorte
    sobrepase el INICIO de la siguiente bolsita en la lista (sea cual sea
    el margen configurado) — se asume que `boundaries_norm` viene
    ordenada de arriba a abajo, como la devuelve
    `find_complete_pouch_boundaries()`. Sin este límite, un margen
    generoso podía colarse en la bolsita vecina cuando el hueco real
    entre dos bolsitas es más pequeño que el propio margen (caso real,
    ver docs/cuaderno_ingenieria_3.45.md).
    """
    if image is None or image.size == 0:
        return []
    h = image.shape[0]
    margin_bottom = margin_bottom_px if margin_bottom_px is not None else margin_px
    crops = []
    for i, boundary in enumerate(boundaries_norm):
        start_norm, end_norm = boundary[0], boundary[1]
        y0 = max(0, int(start_norm * h) - margin_px)
        y1 = min(h, int(end_norm * h) + margin_bottom)
        if i + 1 < len(boundaries_norm):
            next_start_px = int(boundaries_norm[i + 1][0] * h)
            y1 = min(y1, next_start_px)
        if y1 > y0:
            crops.append(image[y0:y1, :].copy())
    return crops
