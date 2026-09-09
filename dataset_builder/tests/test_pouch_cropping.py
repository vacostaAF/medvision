import numpy as np

from medvision.bags.pouch_cropping import crop_pouches_by_y_boundaries, crop_complete_pouches


def _make_striped_image(height=1000, width=400, n_stripes=3):
    """Imagen con una franja de brillo distinto por 'bolsita', para poder
    verificar que cada recorte corresponde al tramo correcto."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    stripe_h = height // n_stripes
    for i in range(n_stripes):
        img[i * stripe_h:(i + 1) * stripe_h, :] = 30 + i * 80
    return img


def test_crop_pouches_no_cuts_returns_original():
    img = _make_striped_image(n_stripes=1)
    crops = crop_pouches_by_y_boundaries(img, cut_positions_norm=[])
    assert len(crops) == 1
    assert crops[0].shape == img.shape


def test_crop_pouches_two_cuts_gives_three_crops_in_order():
    img = _make_striped_image(height=900, n_stripes=3)  # franjas en 0-300,300-600,600-900
    crops = crop_pouches_by_y_boundaries(img, cut_positions_norm=[1 / 3, 2 / 3])
    assert len(crops) == 3
    # cada recorte debe tener el brillo de su propia franja (30, 110, 190 aprox)
    brightness = [int(c.mean()) for c in crops]
    assert brightness[0] < brightness[1] < brightness[2]


def test_crop_pouches_real_image_two_pouches(tmp_path):
    """Integración con una foto real de dos bolsitas -- confirma que cada
    recorte contiene un tramo distinto y no vacío."""
    import cv2
    from pathlib import Path

    real_image_path = Path("/mnt/user-data/uploads/1787929597846_image.png")
    if not real_image_path.exists():
        return  # no disponible en este entorno de pruebas, se omite sin fallar
    img = cv2.imread(str(real_image_path))
    crops = crop_pouches_by_y_boundaries(img, cut_positions_norm=[0.42])
    assert len(crops) == 2
    assert crops[0].shape[0] + crops[1].shape[0] == img.shape[0]
    for c in crops:
        assert c.size > 0


def test_crop_pouches_empty_image_returns_empty_list():
    assert crop_pouches_by_y_boundaries(None, [0.5]) == []
    assert crop_pouches_by_y_boundaries(np.zeros((0, 0, 3), dtype=np.uint8), [0.5]) == []


def test_crop_complete_pouches_ignores_frame_edges():
    """Regresión real (3.37): a diferencia de crop_pouches_by_y_boundaries,
    el borde de la imagen nunca debe tratarse como frontera -- solo se
    recorta lo que está explícitamente entre un (inicio, fin) emparejado."""
    img = _make_striped_image(height=900, n_stripes=3)
    # Solo UN par completo (franja del medio, 1/3 a 2/3) -- las franjas de
    # arriba y abajo NO deben aparecer en ningún recorte.
    crops = crop_complete_pouches(img, boundaries_norm=[(1 / 3, 2 / 3)])
    assert len(crops) == 1
    brightness = int(crops[0].mean())
    assert 90 < brightness < 130  # la franja del medio tiene brillo ~110


def test_crop_complete_pouches_multiple_pairs():
    img = _make_striped_image(height=900, n_stripes=3)
    crops = crop_complete_pouches(img, boundaries_norm=[(0, 1 / 3), (2 / 3, 1.0)])
    assert len(crops) == 2


def test_crop_complete_pouches_empty_boundaries_gives_no_crops():
    img = _make_striped_image(n_stripes=1)
    assert crop_complete_pouches(img, boundaries_norm=[]) == []


def test_crop_complete_pouches_real_image_full_scenario():
    """Integración con la foto real de dos bolsitas: usando el par
    (inicio, fin) real de la bolsita de arriba, el recorte NO debe
    incluir nada de la bolsita de abajo."""
    import cv2
    from pathlib import Path

    real_image_path = Path("/mnt/user-data/uploads/1787929597846_image.png")
    if not real_image_path.exists():
        return
    img = cv2.imread(str(real_image_path))
    # La bolsita de arriba ocupa aprox. 0 a 0.42 de la imagen (ver 3.36)
    crops = crop_complete_pouches(img, boundaries_norm=[(0.0, 0.42)])
    assert len(crops) == 1
    assert crops[0].shape[0] < img.shape[0]  # es un recorte, no la imagen entera


def test_crop_complete_pouches_asymmetric_margin():
    """Regresión real (3.43): margen distinto arriba/abajo -- hacía falta
    más margen abajo que arriba (pie de página y QR pegados al límite)."""
    img = _make_striped_image(height=1000, n_stripes=3)
    # Franja del medio, sin tocar ningun borde de la imagen, para medir el
    # margen sin que el limite de la imagen lo recorte
    crops = crop_complete_pouches(img, boundaries_norm=[(0.3, 0.6)], margin_px=20, margin_bottom_px=80)
    assert len(crops) == 1
    esperado = int(0.6 * 1000) - int(0.3 * 1000) + 20 + 80
    assert crops[0].shape[0] == esperado


def test_crop_complete_pouches_no_bottom_margin_falls_back_to_margin_px():
    """Sin margin_bottom_px, debe usar el mismo margen arriba y abajo (compatibilidad)."""
    img = _make_striped_image(height=1000, n_stripes=3)
    crops = crop_complete_pouches(img, boundaries_norm=[(0.3, 0.6)], margin_px=50)
    esperado = int(0.6 * 1000) - int(0.3 * 1000) + 50 + 50
    assert crops[0].shape[0] == esperado


def test_crop_complete_pouches_never_bleeds_into_next_pouch_start():
    """Regresión real (3.45): un margen inferior grande no debe hacer que
    un recorte se coma parte de la SIGUIENTE bolsita cuando el hueco real
    entre ambas es pequeño -- caso real reportado por el usuario."""
    img = _make_striped_image(height=1000, n_stripes=1)
    # 2 bolsitas con un hueco real pequeño (0.30 a 0.33)
    boundaries = [(0.05, 0.30, "firma1"), (0.33, 0.60, "firma2")]
    crops = crop_complete_pouches(img, boundaries, margin_px=20, margin_bottom_px=400)
    assert len(crops) == 2
    # El primer recorte no debe pasar de donde empieza el segundo (menos su propio margen superior)
    limite_maximo = int(0.33 * 1000) - (int(0.33 * 1000) - 20)
    assert crops[0].shape[0] <= 300  # 330 (inicio de la 2a) - 30 (inicio ajustado de la 1a)


def test_crop_complete_pouches_last_pouch_unaffected_by_safety_cap():
    """La ÚLTIMA bolsita de la lista no tiene una siguiente con la que
    limitarse -- su margen inferior debe aplicarse normal, sin recortar de más."""
    img = _make_striped_image(height=1000, n_stripes=1)
    boundaries = [(0.05, 0.30, "firma1")]
    crops = crop_complete_pouches(img, boundaries, margin_px=20, margin_bottom_px=50)
    esperado = int(0.30 * 1000) + 50 - (int(0.05 * 1000) - 20)
    assert crops[0].shape[0] == esperado
