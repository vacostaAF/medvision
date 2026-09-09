import numpy as np

from medvision.bags.seam_band import detect_seam_band, detect_seam_bands


def _make_uniform_crop(height=400, width=300, color=(180, 170, 160)) -> np.ndarray:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = color
    return img


def _add_blue_bright_band(img: np.ndarray, row: int, thickness: int = 12) -> np.ndarray:
    out = img.copy()
    r1, r2 = max(0, row - thickness // 2), min(out.shape[0], row + thickness // 2)
    # BGR: azul alto, brillo alto -> firma de la costura real observada.
    out[r1:r2, :] = (240, 200, 190)
    return out


def test_detect_seam_band_finds_no_seam_in_uniform_crop():
    crop = _make_uniform_crop()
    found, pos, prominence = detect_seam_band(crop)
    assert found is False
    assert pos is None


def test_detect_seam_band_finds_seam_near_top():
    crop = _add_blue_bright_band(_make_uniform_crop(), row=80)  # ~20% de 400
    found, pos, prominence = detect_seam_band(crop)
    assert found is True
    assert 0.10 < pos < 0.30
    assert prominence > 3.0


def test_detect_seam_band_finds_seam_near_bottom():
    crop = _add_blue_bright_band(_make_uniform_crop(height=560), row=540)  # ~96%
    found, pos, prominence = detect_seam_band(crop)
    assert found is True
    assert pos > 0.85


def test_detect_seam_band_ignores_bright_band_without_blue_tint():
    # Brillo alto pero sin tinte azulado (p.ej. un reflejo blanco neutro,
    # como el de una pastilla) no debe confundirse con la costura.
    crop = _make_uniform_crop()
    crop[180:192, :] = (200, 200, 200)  # brillante pero neutro, sin canal azul dominante
    found, pos, prominence = detect_seam_band(crop)
    assert found is False


def test_detect_seam_band_handles_empty_input():
    found, pos, prominence = detect_seam_band(np.zeros((0, 0, 3), dtype=np.uint8))
    assert found is False
    assert pos is None


def _make_multi_band_image(height=1800, width=1000, seam_rows=(500, 1200)):
    img = np.full((height, width, 3), (150, 150, 150), dtype=np.uint8)
    for row in seam_rows:
        band_h = 40
        r0, r1 = max(0, row - band_h // 2), min(height, row + band_h // 2)
        img[r0:r1, :] = (230, 190, 150)
    return img


def test_detect_seam_bands_finds_two_distinct_seams():
    img = _make_multi_band_image(seam_rows=(500, 1200))
    bands = detect_seam_bands(img)
    assert len(bands) == 2
    rows_found = [int(pos * 1800) for pos, _ in bands]
    assert abs(rows_found[0] - 500) < 30
    assert abs(rows_found[1] - 1200) < 30


def test_detect_seam_bands_single_seam_gives_one_result():
    img = _make_multi_band_image(seam_rows=(900,))
    bands = detect_seam_bands(img)
    assert len(bands) == 1


def test_detect_seam_bands_flat_image_gives_no_results():
    img = np.full((1800, 1000, 3), (150, 150, 150), dtype=np.uint8)
    bands = detect_seam_bands(img)
    assert bands == []


def test_detect_seam_bands_returns_native_python_floats_not_numpy():
    """Regresión real (3.28): detect_seam_bands() devolvía numpy.float32
    sin convertir a float nativo -- sqlite3 lo guardaba como BLOB en vez
    de REAL, y una lectura posterior con float() reventaba con
    'could not convert string to float: b\\'...\\''. Encontrado en una
    ejecución real completa (--fresh, ~104 vídeos) que falló justo al
    final, en el paso de emparejamiento."""
    img = _make_multi_band_image(seam_rows=(500, 1200))
    bands = detect_seam_bands(img)
    assert len(bands) == 2
    for pos, prom in bands:
        assert type(pos) is float, f"posición debe ser float nativo, es {type(pos)}"
        assert type(prom) is float, f"prominencia debe ser float nativo, es {type(prom)}"


def test_detect_seam_bands_survives_real_sqlite_roundtrip(tmp_path):
    """Prueba de integración real (3.28): el mismo camino exacto que
    reventó en producción -- detectar, guardar en SQLite con
    update_bag_seam(), releer, y convertir con float() (lo que hace
    group_pill_bags_by_seam en el pipeline real)."""
    import sys
    sys.path.insert(0, str(tmp_path.parent))
    from medvision.database.repository import Repository

    db_path = tmp_path / "medvision.sqlite"
    img = _make_multi_band_image(seam_rows=(500, 1200))
    seam_bands = detect_seam_bands(img)
    seam_positions = [pos for pos, _ in seam_bands]
    primary_pos = seam_positions[0] if seam_positions else None
    primary_prom = seam_bands[0][1] if seam_bands else 0.0

    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="v.MOV", filename="v.MOV", side="pill_side",
            fps=25.0, width=1080, height=1920, frame_count=10, duration_seconds=1.0,
        )
        frame_id = repo.upsert_frame(
            video_id=video_id, frame_index=0, timestamp_seconds=0.0, image_path="f.jpg",
            sharpness=10.0, brightness=55.0, contrast=40.0, overexposed_ratio=0.0,
            quality_score=0.3, strip_detected=1,
        )
        bag_id = repo.upsert_bag(
            frame_id=frame_id, bag_index_in_frame=0, side="pill_side",
            crop_path="b.jpg", y1=8, y2=1800, segment_confidence=0.9, quality_score=0.3, track_key=None,
        )
        repo.update_bag_seam(bag_id, primary_prom, primary_pos, all_seam_positions=seam_positions)

        observations = repo.get_pill_observations_for_video("v")
        assert len(observations) == 1
        # Esto mismo (float() sobre lo releido) es lo que reventó en produccion
        val = float(observations[0].get("seam_prominence") or 0.0)
        assert val > 0
