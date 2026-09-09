import cv2
import numpy as np

from medvision.acquisition.motion import compute_cumulative_pan_distances, estimate_frame_shift


def _make_textured_strip(height: int = 600, width: int = 300) -> np.ndarray:
    """Imagen con textura variada (no uniforme) para que la correlación de
    fase tenga algo real de lo que tirar — una imagen en blanco no tiene
    ningún desplazamiento detectable."""
    rng = np.random.default_rng(42)
    strip = rng.integers(0, 255, size=(height, width), dtype=np.uint8)
    return np.stack([strip] * 3, axis=-1).astype(np.uint8)


def _shift_vertically(img: np.ndarray, shift_px: int) -> np.ndarray:
    """Desplaza la imagen verticalmente `shift_px` (positivo = hacia abajo),
    rellenando el hueco con la propia textura de la imagen (envolvente) para
    que la correlación tenga contenido real cerca de los bordes."""
    h = img.shape[0]
    out = np.zeros_like(img)
    if shift_px >= 0:
        out[shift_px:] = img[: h - shift_px]
        out[:shift_px] = img[h - shift_px:]
    else:
        s = -shift_px
        out[: h - s] = img[s:]
        out[h - s:] = img[:s]
    return out


def test_estimate_frame_shift_detects_known_vertical_shift():
    base = _make_textured_strip()
    shifted = _shift_vertically(base, 40)
    dy = estimate_frame_shift(base, shifted)
    # phaseCorrelate da el desplazamiento con signo segun su propia convencion;
    # lo que importa es que la MAGNITUD se acerque al desplazamiento real.
    assert 30 < abs(dy) < 50


def test_compute_cumulative_pan_distances_accumulates_across_frames():
    base = _make_textured_strip()
    frames = [base]
    for _ in range(4):
        frames.append(_shift_vertically(frames[-1], 25))
    cum = compute_cumulative_pan_distances(frames)
    assert len(cum) == 5
    assert cum[0] == 0.0
    # tras 4 pasos de 25px cada uno, la distancia acumulada deberia rondar 100px
    assert 70 < abs(cum[-1]) < 130


def test_compute_cumulative_pan_distances_single_frame_returns_zero():
    base = _make_textured_strip()
    cum = compute_cumulative_pan_distances([base])
    assert cum == [0.0]
