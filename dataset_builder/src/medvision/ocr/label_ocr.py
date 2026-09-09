from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    raw_text: str
    normalized_text: str
    # Se mantiene en escala 0-100 (no 0-1) a propósito: es el mismo contrato que
    # tenía la implementación anterior basada en pytesseract, para no romper los
    # umbrales ya definidos en config/*.yaml (auto_accept_confidence, etc.).
    mean_confidence: float
    word_count: int
    words: list[str]
    processed_image: np.ndarray
    # Posición vertical normalizada (0-1, respecto a processed_image) de cada
    # línea reconstruida en `words` — mismo índice, misma longitud. Permite
    # verificar geométricamente a qué bolsita pertenece una línea cuando el
    # orden de lectura del OCR no es de fiar cerca de la costura entre dos
    # bolsitas del mismo frame (ver docs/cuaderno_ingenieria_3.11.md). Lista
    # vacía si no se pudieron extraer posiciones (compatibilidad).
    word_y_norm: list[float] | None = None


def _ensure_min_resolution(image_bgr: np.ndarray, min_side: int = 480) -> np.ndarray:
    """Los recortes de bolsa suelen llegar pequeños tras el recorte perspectivo.

    PaddleOCR incluye su propio preprocesado (orientación, desdoblado), así que aquí
    solo compensamos resolución insuficiente; no aplicamos binarización ni realce
    agresivo como con Tesseract, porque puede degradar la detección del propio modelo.
    """
    if image_bgr is None or image_bgr.size == 0:
        return image_bgr
    h, w = image_bgr.shape[:2]
    scale = max(1.0, min_side / max(1, min(h, w)))
    if scale > 1.01:
        image_bgr = cv2.resize(image_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return image_bgr


def normalize_label_text(text: str) -> str:
    text = text.replace('\n', ' | ')
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s*\|\s*', ' | ', text)
    text = re.sub(r'[^0-9A-Za-zÀ-ÿ%+./()\- |]', '', text)
    return text.strip(' |')


def _try_getitem(res: Any) -> dict[str, Any] | None:
    """Intenta acceso estilo dict: res['rec_texts'] / res['rec_scores']."""
    try:
        payload = {"rec_texts": res["rec_texts"], "rec_scores": res["rec_scores"]}
    except Exception:
        return None
    try:
        payload["rec_polys"] = res["rec_polys"]
    except Exception:
        pass  # sin cajas no se puede reordenar por Y, pero los textos siguen siendo válidos
    return payload


def _try_json_attribute(res: Any) -> dict[str, Any] | None:
    """Intenta acceso vía `.json`, que replica lo que guarda save_to_json().

    Según versión, el payload puede venir en la raíz o anidado bajo la clave 'res'
    (así aparece en la documentación oficial de Quick Start). Comprobamos ambas
    formas para no acoplarnos a un detalle de empaquetado que ya ha cambiado antes.
    """
    try:
        data = res.json
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if "rec_texts" in data:
        return data
    nested = data.get("res")
    if isinstance(nested, dict) and "rec_texts" in nested:
        return nested
    return None


def _box_y_range_and_x(box: Any) -> tuple[float, float, float]:
    """(y_top, y_bottom, x_left) de un polígono de detección."""
    ys = [float(p[1]) for p in box]
    xs = [float(p[0]) for p in box]
    return (min(ys), max(ys), min(xs))


def _overlap_ratio(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Fracción de solapamiento vertical entre dos rangos [y_top, y_bottom],
    relativa al más pequeño de los dos. 0 si no se solapan."""
    overlap = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    smaller = min(a[1] - a[0], b[1] - b[0])
    if smaller <= 0:
        return 0.0
    return overlap / smaller


def _cluster_into_rows(
    entries: list[tuple[str, float, Any]], min_overlap_ratio: float = 0.5
) -> list[tuple[str, float, float]]:
    """Agrupa detecciones sueltas en líneas reconstruidas por fila visual.

    PaddleOCR detecta cada fragmento de texto como una caja independiente. En
    una bolsita SPD, la cantidad ("1", "2") suele caer en su propia caja,
    separada de la caja del fármaco aunque compartan fila visual (ver
    docs/cuaderno_ingenieria_1.6.md). Sin este paso, la cantidad y el fármaco
    llegan al parser como líneas sueltas.

    Importante: la pertenencia a una fila se compara contra el rango vertical
    de la PRIMERA caja que abrió esa fila, no contra una media que se va
    recalculando — una media móvil permite que una fila "encadene" hacia cajas
    cada vez más lejanas sin que ninguna comparación individual sea válida
    (bug real encontrado en 1.6: fusionaba líneas de fármacos distintos que no
    deberían haberse juntado). Con una referencia fija esto no puede pasar.

    Devuelve (texto, score, y_centro_en_píxeles) por fila — la posición Y se
    usa más adelante para verificar geométricamente a qué bolsita pertenece
    cada línea cuando hay más de una en el mismo frame (ver
    docs/cuaderno_ingenieria_3.11.md).
    """
    if not entries:
        return []

    decorated = []
    for text, score, box in entries:
        try:
            y_top, y_bottom, x_left = _box_y_range_and_x(box)
        except Exception:
            y_top, y_bottom, x_left = 0.0, 20.0, 0.0
        decorated.append((y_top, y_bottom, x_left, text, score))
    decorated.sort(key=lambda d: d[0])  # por y_top

    rows: list[dict[str, Any]] = []  # cada fila: {"ref": (y_top,y_bottom), "items": [...]}
    for y_top, y_bottom, x_left, text, score in decorated:
        placed = False
        for row in rows:
            if _overlap_ratio((y_top, y_bottom), row["ref"]) >= min_overlap_ratio:
                row["items"].append((x_left, text, score))
                placed = True
                break
        if not placed:
            rows.append({"ref": (y_top, y_bottom), "items": [(x_left, text, score)]})

    result = []
    for row in rows:
        items = sorted(row["items"], key=lambda t: t[0])  # izquierda a derecha
        joined = " ".join(t[1] for t in items).strip()
        if joined:
            y_center = (row["ref"][0] + row["ref"][1]) / 2.0
            result.append((joined, sum(t[2] for t in items) / len(items), y_center))
    return result


def _extract_texts_and_scores(res: Any, min_score: float = 0.0) -> tuple[list[str], list[float], list[float]]:
    for extractor in (_try_getitem, _try_json_attribute):
        payload = extractor(res)
        if payload is None:
            continue
        texts = [str(t) for t in (payload.get("rec_texts") or [])]
        scores = [float(s) for s in (payload.get("rec_scores") or [])]
        boxes = payload.get("rec_polys")
        filtered = [
            (t.strip(), s, (boxes[i] if boxes is not None and i < len(boxes) else None))
            for i, (t, s) in enumerate(zip(texts, scores))
            if t.strip() and s >= min_score
        ]
        if boxes is not None and len(boxes) == len(texts):
            rows = _cluster_into_rows(filtered)
            return [t for t, _, _ in rows], [s for _, s, _ in rows], [y for _, _, y in rows]
        # Sin cajas no se puede reconstruir por fila ni conocer la posición Y;
        # se devuelve ya filtrado por score, con y=0.0 (desconocida) para cada línea.
        return [e[0] for e in filtered], [e[1] for e in filtered], [0.0] * len(filtered)
    logger.warning(
        "No se pudieron extraer 'rec_texts'/'rec_scores' del resultado de PaddleOCR "
        "(tipo recibido: %r). Puede que la versión instalada de paddleocr haya "
        "cambiado el formato de salida.",
        type(res),
    )
    return [], [], []


class PaddleLabelOCR:
    """Envoltorio perezoso y reutilizable sobre el pipeline PaddleOCR.

    Cargar PaddleOCR inicializa varios modelos de detección/reconocimiento (coste de
    varios segundos y cientos de MB en memoria). Crearlo una vez por proceso y
    combinación (idioma, motor) y reutilizarlo es obligatorio para que procesar un
    vídeo completo no reinstancie el modelo en cada frame.
    """

    _lock = threading.Lock()
    _instances: dict[str, "PaddleLabelOCR"] = {}

    def __init__(self, lang: str = "es", engine: str = "paddle") -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "paddleocr no está instalado. Instala primero el motor de inferencia "
                "y luego el paquete, por ejemplo (CPU):\n"
                "  pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/\n"
                "  pip install \"paddleocr[all]\"\n"
                "Ver docs/cuaderno_ingenieria_1.4.md para más detalle."
            ) from exc
        self._engine = PaddleOCR(
            lang=lang,
            engine=engine,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )
        self.lang = lang
        self.engine_name = engine

    @classmethod
    def get(cls, lang: str = "es", engine: str = "paddle") -> "PaddleLabelOCR":
        key = f"{lang}:{engine}"
        with cls._lock:
            instance = cls._instances.get(key)
            if instance is None:
                instance = cls(lang=lang, engine=engine)
                cls._instances[key] = instance
            return instance

    def read(self, image_bgr: np.ndarray, min_score: float = 0.5) -> OCRResult:
        proc = _ensure_min_resolution(image_bgr)
        if proc is None or proc.size == 0:
            return OCRResult('', '', 0.0, 0, [], proc, [])

        results = self._engine.predict(proc)
        if not results:
            return OCRResult('', '', 0.0, 0, [], proc, [])

        texts, scores, y_positions = _extract_texts_and_scores(results[0], min_score=min_score)
        words = [t for t in texts if t]
        word_y_norm = [
            round(y / max(1, proc.shape[0]), 4) for t, y in zip(texts, y_positions) if t
        ]
        # Importante: unir con '\n', no con espacio. `words` se usa tal cual como
        # lista de líneas por parse_label_sheet() (una línea reconstruida = un
        # fármaco de la bolsita); si aquí se aplanase con espacios se perdería
        # esa estructura y normalize_label_text() tampoco podría reconstruir
        # los separadores '|'.
        raw = '\n'.join(words)
        mean_conf = round(100.0 * (sum(scores) / len(scores)), 2) if scores else 0.0
        return OCRResult(raw, normalize_label_text(raw), mean_conf, len(words), words, proc, word_y_norm)


def read_label(image_bgr: np.ndarray, lang: str = "es", engine: str = "paddle", min_score: float = 0.5) -> OCRResult:
    """Punto de entrada usado por el pipeline (dataset/builder.py).

    Firma compatible en espíritu con la versión anterior basada en Tesseract:
    misma forma de OCRResult, misma escala de confianza (0-100).
    """
    return PaddleLabelOCR.get(lang=lang, engine=engine).read(image_bgr, min_score=min_score)


def read_label_text(image_bgr: np.ndarray, lang: str = "es", engine: str = "paddle") -> str:
    return read_label(image_bgr, lang=lang, engine=engine).normalized_text
