from __future__ import annotations

import cv2
import numpy as np


def estimate_frame_shift(prev_img: np.ndarray, curr_img: np.ndarray) -> float:
    """Estima el desplazamiento vertical (en píxeles) entre dos frames
    consecutivos ya muestreados, por correlación de fase.

    Se usa el recorte central (15%-85% del ancho) para evitar que los bordes
    oscuros del encuadre distorsionen la correlación. Sin filtrar por
    confianza: en validación con vídeo real (ver
    docs/cuaderno_ingenieria_3.13.md), filtrar pasos de baja confianza
    introducía MÁS sesgo en la distancia total acumulada que dejarlos, pese
    a que cada paso individual pueda ser ruidoso — el ruido se cancela en la
    suma, filtrar no.
    """
    a = cv2.cvtColor(prev_img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(curr_img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = a.shape
    x1, x2 = int(w * 0.15), int(w * 0.85)
    (_dx, dy), _response = cv2.phaseCorrelate(a[:, x1:x2], b[:, x1:x2])
    return float(dy)


def compute_cumulative_pan_distances(frame_images: list[np.ndarray]) -> list[float]:
    """Distancia vertical acumulada (en píxeles) de cada frame respecto al
    primero de la lista, siguiendo el orden dado (debe ser el orden real de
    muestreo, por `frame_index` creciente).

    Es la base física para el emparejamiento por posición entre el lado
    pastilla y el lado etiqueta (ver docs/cuaderno_ingenieria_3.13.md): dos
    grabaciones independientes de la MISMA tira recorren, en conjunto, una
    distancia física comparable — aunque no exactamente igual (encuadre,
    velocidad de paneo distintos) — así que la posición relativa de una
    bolsita dentro de esa distancia total sirve de referencia aproximada
    para localizarla en la otra grabación.
    """
    cumulative = [0.0]
    for i in range(1, len(frame_images)):
        dy = estimate_frame_shift(frame_images[i - 1], frame_images[i])
        cumulative.append(cumulative[-1] + dy)
    return cumulative
