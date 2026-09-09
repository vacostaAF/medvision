import numpy as np
import pytest

from medvision.ocr.label_ocr import (
    PaddleLabelOCR,
    _extract_texts_and_scores,
    _ensure_min_resolution,
    normalize_label_text,
)


def test_normalize_label_text_collapses_whitespace_and_strips_noise():
    raw = "  PARACETAMOL   650MG\ncomprimidos ###  "
    # Los saltos de línea se preservan como separador '|' (líneas distintas del
    # reverso impreso), y los caracteres fuera del alfabeto permitido se eliminan.
    assert normalize_label_text(raw) == "PARACETAMOL 650MG | comprimidos"


def test_ensure_min_resolution_upscales_small_crops():
    small = np.zeros((60, 40, 3), dtype=np.uint8)
    out = _ensure_min_resolution(small, min_side=480)
    assert min(out.shape[:2]) >= 480


def test_ensure_min_resolution_leaves_large_crops_untouched():
    big = np.zeros((900, 700, 3), dtype=np.uint8)
    out = _ensure_min_resolution(big, min_side=480)
    assert out.shape == big.shape


class _DictLikeResult:
    """Simula un resultado de PaddleOCR accesible como res['rec_texts']."""

    def __init__(self, texts, scores):
        self._data = {"rec_texts": texts, "rec_scores": scores}

    def __getitem__(self, key):
        return self._data[key]


class _JsonAttributeResult:
    """Simula un resultado de PaddleOCR accesible solo vía `.json`, anidado bajo 'res'."""

    def __init__(self, texts, scores):
        self.json = {"res": {"rec_texts": texts, "rec_scores": scores}}


def test_extract_texts_and_scores_supports_dict_style_result():
    res = _DictLikeResult(["PARACETAMOL", "650", "MG"], [0.95, 0.88, 0.91])
    texts, scores = _extract_texts_and_scores(res)
    assert texts == ["PARACETAMOL", "650", "MG"]
    assert scores == [0.95, 0.88, 0.91]


def test_extract_texts_and_scores_reorders_by_vertical_position():
    # PaddleOCR no garantiza devolver rec_texts en orden de lectura; para una
    # bolsita SPD el orden top-to-bottom es crítico (cabecera antes que items).
    class _DictLikeWithPolys(_DictLikeResult):
        def __init__(self, texts, scores, polys):
            super().__init__(texts, scores)
            self._data["rec_polys"] = polys

    res = _DictLikeWithPolys(
        texts=["linea_de_abajo", "linea_de_arriba"],
        scores=[0.9, 0.9],
        polys=[
            [[0, 500], [100, 500], [100, 520], [0, 520]],  # y~510
            [[0, 10], [100, 10], [100, 30], [0, 30]],       # y~20
        ],
    )
    texts, _ = _extract_texts_and_scores(res)
    assert texts == ["linea_de_arriba", "linea_de_abajo"]


def test_extract_texts_and_scores_reattaches_detached_quantity_column():
    # Regresión de un bug real: en una bolsita SPD real, PaddleOCR detecta la
    # cantidad ("1") en una caja separada de la del nombre del fármaco, aunque
    # compartan fila visual. Sin reconstrucción por fila, el parser recibía
    # "1" y "CALCIFEDIOL 0,266 MG CAPSULA" como dos líneas sueltas (ver
    # docs/cuaderno_ingenieria_1.6.md) y perdía todos los items.
    class _DictLikeWithPolys(_DictLikeResult):
        def __init__(self, texts, scores, polys):
            super().__init__(texts, scores)
            self._data["rec_polys"] = polys

    def row(x1, x2, y1, y2):
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    res = _DictLikeWithPolys(
        texts=["1", "CALCIFEDIOL 0,266 MG CAPSULA", "1", "BISOPROLOL 5 MG COMPRIMIDO"],
        scores=[1.0, 1.0, 1.0, 1.0],
        polys=[row(50, 70, 200, 225), row(100, 500, 200, 225),
               row(50, 70, 230, 255), row(100, 500, 230, 255)],
    )
    texts, _ = _extract_texts_and_scores(res, min_score=0.5)
    assert texts == ["1 CALCIFEDIOL 0,266 MG CAPSULA", "1 BISOPROLOL 5 MG COMPRIMIDO"]


def test_extract_texts_and_scores_filters_low_score_before_clustering():
    class _DictLikeWithPolys(_DictLikeResult):
        def __init__(self, texts, scores, polys):
            super().__init__(texts, scores)
            self._data["rec_polys"] = polys

    def row(x1, x2, y1, y2):
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    # fragmento de baja confianza ("L", 0.43) junto a texto real: no debe
    # colarse en la línea reconstruida ni bajar el resto del score.
    res = _DictLikeWithPolys(
        texts=["L", "AMLODIPINO 5 MG COMPRIMIDO"],
        scores=[0.43, 0.97],
        polys=[row(30, 45, 200, 225), row(100, 500, 200, 225)],
    )
    texts, scores = _extract_texts_and_scores(res, min_score=0.5)
    assert texts == ["AMLODIPINO 5 MG COMPRIMIDO"]
    assert scores == [0.97]


def test_cluster_into_rows_does_not_chain_distinct_tightly_spaced_lines():
    # Regresión de un bug real: la primera versión del clustering (media
    # móvil) fusionaba líneas de fármacos DISTINTOS con espaciado ajustado
    # entre sí, aunque ninguna comparación individual debiera juntarlas —
    # encadenamiento clásico de clustering incremental. Ver
    # docs/cuaderno_ingenieria_1.6.md.
    class _DictLikeWithPolys(_DictLikeResult):
        def __init__(self, texts, scores, polys):
            super().__init__(texts, scores)
            self._data["rec_polys"] = polys

    def row(x1, x2, y1, y2):
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    res = _DictLikeWithPolys(
        texts=["SIMVASTATINA 40 MG COMPRIMIDO", "CINITAPRIDA 1 MG COMPRIMIDO",
               "RISPERIDONA AUROBINDO 1 MCG"],
        scores=[1.0, 1.0, 1.0],
        polys=[row(100, 500, 200, 225), row(100, 500, 228, 253), row(100, 500, 256, 281)],
    )
    texts, _ = _extract_texts_and_scores(res, min_score=0.5)
    assert texts == [
        "SIMVASTATINA 40 MG COMPRIMIDO",
        "CINITAPRIDA 1 MG COMPRIMIDO",
        "RISPERIDONA AUROBINDO 1 MCG",
    ]


def test_extract_texts_and_scores_supports_nested_json_result():
    res = _JsonAttributeResult(["IBUPROFENO"], [0.72])
    texts, scores = _extract_texts_and_scores(res)
    assert texts == ["IBUPROFENO"]
    assert scores == [0.72]


def test_extract_texts_and_scores_returns_empty_on_unknown_shape():
    class Unknown:
        pass

    texts, scores = _extract_texts_and_scores(Unknown())
    assert texts == []
    assert scores == []


def test_paddle_label_ocr_raises_clear_error_when_dependency_missing():
    # En este entorno de pruebas 'paddleocr' no está instalado a propósito: el test
    # comprueba que el fallo es explicativo, no un ImportError críptico aguas abajo.
    try:
        import paddleocr  # noqa: F401

        pytest.skip("paddleocr está instalado en este entorno; el caso no aplica")
    except ImportError:
        pass

    with pytest.raises(RuntimeError, match="paddleocr no está instalado"):
        PaddleLabelOCR(lang="es")
