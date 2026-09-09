from medvision.database.repository import Repository


def _make_bag(repo: Repository) -> int:
    """Crea la cadena mínima de FKs (video -> frame -> bag) para poder colgar
    un ocr_result de un bag_id real, igual que hace el pipeline."""
    video_id = repo.upsert_video(
        path="videos/MVI_2714.MOV", filename="MVI_2714.MOV", side="label_side",
        fps=25.0, width=1920, height=1080, frame_count=278, duration_seconds=11.12,
    )
    frame_id = repo.upsert_frame(
        video_id=video_id, frame_index=0, timestamp_seconds=0.0, image_path="frames/f0.jpg",
        sharpness=10.0, brightness=55.0, contrast=40.0, overexposed_ratio=0.0,
        quality_score=0.3, strip_detected=1,
    )
    bag_id = repo.upsert_bag(
        frame_id=frame_id, bag_index_in_frame=0, side="label_side", crop_path="bags/b0.jpg",
        y1=0, y2=800, segment_confidence=0.9, quality_score=0.3, track_key=None,
    )
    return bag_id


def test_label_header_and_items_roundtrip(tmp_path):
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        bag_id = _make_bag(repo)
        ocr_result_id = repo.upsert_ocr(
            bag_id=bag_id, raw_text="raw", normalized_text="norm", mean_confidence=91.0,
            word_count=10, processed_image_path=None, drug_name=None, dose_value=None,
            dose_unit=None, needs_review=0,
        )
        assert isinstance(ocr_result_id, int) and ocr_result_id > 0

        repo.upsert_label_header(
            ocr_result_id, patient_name="PELAYO PEINADO JOSEFA", patient_location="EL PUERTO",
            dose_weekday="domingo", dose_date="01/03/26", dose_slot="DESAYUNO",
        )
        repo.replace_label_items(ocr_result_id, [
            {"line_index": 0, "quantity": 1, "drug_name": "CALCIFEDIOL", "dose_value": 0.266,
             "dose_unit": "MG", "raw_line": "1 CALCIFEDIOL 0,266 MG CAPSULA"},
            {"line_index": 1, "quantity": 1, "drug_name": "BISOPROLOL", "dose_value": 5.0,
             "dose_unit": "MG", "raw_line": "1 BISOPROLOL 5 MG COMPRIMIDO"},
        ])

    with Repository(db_path) as repo:
        header = repo.get_label_header(ocr_result_id)
        items = repo.get_label_items(ocr_result_id)

    assert header["patient_name"] == "PELAYO PEINADO JOSEFA"
    assert header["dose_slot"] == "DESAYUNO"
    assert len(items) == 2
    assert [i["drug_name"] for i in items] == ["CALCIFEDIOL", "BISOPROLOL"]


def test_replace_label_items_fully_overwrites_previous_set(tmp_path):
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        bag_id = _make_bag(repo)
        ocr_result_id = repo.upsert_ocr(
            bag_id=bag_id, raw_text="", normalized_text="", mean_confidence=0.0,
            word_count=0, processed_image_path=None, drug_name=None, dose_value=None,
            dose_unit=None, needs_review=1,
        )
        repo.replace_label_items(ocr_result_id, [
            {"line_index": 0, "quantity": 1, "drug_name": "A", "dose_value": 1.0,
             "dose_unit": "MG", "raw_line": "1 A 1 MG"},
            {"line_index": 1, "quantity": 1, "drug_name": "B", "dose_value": 2.0,
             "dose_unit": "MG", "raw_line": "1 B 2 MG"},
        ])
        # Re-ejecutar el pipeline sobre el mismo bag (p.ej. tras recalibrar el
        # umbral de detección) debe sustituir, no acumular, los items.
        repo.replace_label_items(ocr_result_id, [
            {"line_index": 0, "quantity": 1, "drug_name": "C", "dose_value": 3.0,
             "dose_unit": "MG", "raw_line": "1 C 3 MG"},
        ])
        items = repo.get_label_items(ocr_result_id)

    assert len(items) == 1
    assert items[0]["drug_name"] == "C"


def test_pair_review_items_do_not_overwrite_raw_ocr_label_items(tmp_path):
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        bag_id = _make_bag(repo)
        ocr_result_id = repo.upsert_ocr(
            bag_id=bag_id, raw_text="", normalized_text="", mean_confidence=60.0,
            word_count=3, processed_image_path=None, drug_name=None, dose_value=None,
            dose_unit=None, needs_review=1,
        )
        repo.replace_label_items(ocr_result_id, [
            {"line_index": 0, "quantity": 1, "drug_name": "PARACETAMOL_MAL_LEIDO",
             "dose_value": 650.0, "dose_unit": "MG", "raw_line": "raw"},
        ])
        track_pair_id = 0
        repo.conn.execute(
            "INSERT INTO track_pairs(id,pair_key,pill_track_key,label_track_key,"
            "pill_best_bag_id,label_best_bag_id,order_index,match_score,status,needs_review) "
            "VALUES (1,'p1',NULL,NULL,NULL,?,0,1.0,'paired',1)",
            (bag_id,),
        )
        track_pair_id = 1
        repo.conn.commit()

        # El farmacéutico corrige el nombre mal leído por el OCR.
        repo.save_pair_review(track_pair_id, "corrected", "nombre mal leído por el OCR")
        repo.save_pair_review_items(track_pair_id, [
            {"line_index": 0, "quantity": 1, "drug_name": "PARACETAMOL",
             "dose_value": 650.0, "dose_unit": "MG"},
        ])

    with Repository(db_path) as repo:
        raw_items = repo.get_label_items(ocr_result_id)
        reviewed_items = repo.get_pair_review_items(track_pair_id)

    # El OCR original queda intacto (con el error) y la corrección vive aparte.
    assert raw_items[0]["drug_name"] == "PARACETAMOL_MAL_LEIDO"
    assert reviewed_items[0]["drug_name"] == "PARACETAMOL"


def test_get_ocr_observations_for_video_end_to_end_with_header_grouping(tmp_path):
    """Integración completa: 3 bags reales (mismo caso que motivó el cambio)
    insertados vía Repository, consultados vía get_ocr_observations_for_video,
    y agrupados vía group_label_bags_by_header. No solo la función pura."""
    from medvision.pairing.header_grouping import group_label_bags_by_header

    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/MVI_2714.MOV", filename="MVI_2714.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=278, duration_seconds=11.12,
        )

        def make_bag(frame_index, y_center):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=frame_index, timestamp_seconds=frame_index / 25.0,
                image_path=f"frames/f{frame_index}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
            )
            return repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side="label_side",
                crop_path=f"bags/f{frame_index}.jpg", y1=y_center - 10, y2=y_center + 10,
                segment_confidence=0.9, quality_score=0.3, track_key=None,
            )

        # domingo desayuno
        bag_a = make_bag(0, 100)
        ocr_a = repo.upsert_ocr(bag_id=bag_a, raw_text="", normalized_text="", mean_confidence=99.0,
                                 word_count=5, processed_image_path=None, drug_name=None,
                                 dose_value=None, dose_unit=None, needs_review=0)
        repo.upsert_label_header(ocr_a, patient_name="PELAYO PEINADO JOSEFA", patient_location=None,
                                  dose_weekday="domingo", dose_date="01/03/26", dose_slot="DESAYL")
        repo.replace_label_items(ocr_a, [
            {"line_index": 0, "quantity": None, "drug_name": "CALCIFEDIOL",
             "dose_value": 0.266, "dose_unit": "MG", "raw_line": "x"},
        ])

        # sabado cena (bolsita DISTINTA)
        bag_b = make_bag(50, 500)
        ocr_b = repo.upsert_ocr(bag_id=bag_b, raw_text="", normalized_text="", mean_confidence=96.0,
                                 word_count=5, processed_image_path=None, drug_name=None,
                                 dose_value=None, dose_unit=None, needs_review=0)
        repo.upsert_label_header(ocr_b, patient_name="PELAYO PEINADO JOSEFA", patient_location="EL PUERTO",
                                  dose_weekday="sábado", dose_date="28/02/26", dose_slot="CENA")
        repo.replace_label_items(ocr_b, [
            {"line_index": 0, "quantity": None, "drug_name": "SIMVASTATINA",
             "dose_value": 40.0, "dose_unit": "MG", "raw_line": "x"},
        ])

        # pie de farmacia, sin cabecera
        bag_c = make_bag(100, 900)
        ocr_c = repo.upsert_ocr(bag_id=bag_c, raw_text="", normalized_text="", mean_confidence=87.0,
                                 word_count=2, processed_image_path=None, drug_name=None,
                                 dose_value=None, dose_unit=None, needs_review=1)

        observations = repo.get_ocr_observations_for_video("MVI_2714")
        assert len(observations) == 3

        groups = group_label_bags_by_header(observations)
        assert len(groups) == 3  # deben quedar separadas, no fusionadas en 1

        domingo = next(g for g in groups if g.signature and g.signature[0] == "01/03/26")
        sabado = next(g for g in groups if g.signature and g.signature[0] == "28/02/26")
        assert domingo.merged_items[0]["drug_name"] == "CALCIFEDIOL"
        assert sabado.merged_items[0]["drug_name"] == "SIMVASTATINA"


def test_label_groups_order_by_frame_index_not_y_position(tmp_path):
    """Regresión real: con bag_splitting.max_segments=1, cada bolsa ocupa casi
    todo el frame -> la posición Y (y1+y2)/2 es casi idéntica en todas las
    observaciones y deja de servir para ordenar. El orden debe venir del
    número de frame (orden real de paso de la cámara), no de la posición Y.

    Caso real que motivó esto: con orden por Y, la bolsita con solo el pie de
    farmacia (peor contenido) se emparejaba con la única foto de pastilla
    disponible, dejando sin pareja las 2 bolsitas con fármacos reales."""
    from medvision.pairing.header_grouping import group_label_bags_by_header

    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/MVI_2714.MOV", filename="MVI_2714.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=278, duration_seconds=11.12,
        )

        def make_bag(frame_index, weekday, date, slot, drug):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=frame_index, timestamp_seconds=frame_index / 25.0,
                image_path=f"frames/f{frame_index}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
            )
            # Misma posicion Y en las 3 (y1=8, y2=892 siempre) -- exactamente
            # lo que pasa en la practica con max_segments=1.
            bag_id = repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side="label_side",
                crop_path=f"bags/f{frame_index}.jpg", y1=8, y2=892,
                segment_confidence=0.9, quality_score=0.3, track_key=None,
            )
            ocr_id = repo.upsert_ocr(bag_id=bag_id, raw_text="", normalized_text="",
                                      mean_confidence=95.0, word_count=5, processed_image_path=None,
                                      drug_name=None, dose_value=None, dose_unit=None, needs_review=0)
            repo.upsert_label_header(ocr_id, patient_name="X", patient_location=None,
                                      dose_weekday=weekday, dose_date=date, dose_slot=slot)
            repo.replace_label_items(ocr_id, [
                {"line_index": 0, "quantity": None, "drug_name": drug,
                 "dose_value": 1.0, "dose_unit": "MG", "raw_line": "x"},
            ] if drug else [])
            return bag_id

        # Frame 100 = la bolsita "footer" (sin farmacos) grabada AL FINAL del
        # paneo, pero con la MISMA posicion Y que las otras dos.
        bag_footer = make_bag(100, "lunes", "02/03/26", "COMIDA", None)
        bag_first = make_bag(0, "domingo", "01/03/26", "DESAYUNO", "CALCIFEDIOL")
        bag_middle = make_bag(50, "sabado", "28/02/26", "CENA", "SIMVASTATINA")

        observations = repo.get_ocr_observations_for_video("MVI_2714")
        groups = group_label_bags_by_header(observations)

    assert len(groups) == 3
    ordered_bag_ids = [g.representative_bag_id for g in groups]
    # El orden debe seguir frame_index (0, 50, 100), no la posicion Y (igual
    # en los 3): la bolsita del frame 0 debe quedar PRIMERA, no la del footer.
    assert ordered_bag_ids == [bag_first, bag_middle, bag_footer]


def test_get_pill_observations_for_video_end_to_end_with_seam_grouping(tmp_path):
    """Integración completa: bags del lado pastilla con seam_prominence
    guardado vía Repository, leído vía get_pill_observations_for_video, y
    agrupado vía group_pill_bags_by_seam. Reproduce la secuencia real de
    MVI_2713 (frames 80-190)."""
    from medvision.pairing.seam_grouping import group_pill_bags_by_seam

    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/MVI_2713.MOV", filename="MVI_2713.MOV", side="pill_side",
            fps=25.0, width=1920, height=1080, frame_count=278, duration_seconds=11.12,
        )

        def make_bag(frame_index, prominence):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=frame_index, timestamp_seconds=frame_index / 25.0,
                image_path=f"frames/f{frame_index}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.28, strip_detected=1,
            )
            return repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side="pill_side",
                crop_path=f"bags/f{frame_index}.jpg", y1=8, y2=400,
                segment_confidence=0.3, quality_score=0.28, track_key=None,
                seam_prominence=prominence, seam_position=0.2 if prominence >= 3.0 else None,
            )

        for frame_index, prominence in [
            (80, 14.44), (90, 4.82), (100, 1.88), (110, 9.74),
            (120, 8.41), (130, 2.41), (140, 2.49), (190, 12.54),
        ]:
            make_bag(frame_index, prominence)

        observations = repo.get_pill_observations_for_video("MVI_2713")

    assert len(observations) == 8
    assert [o["frame_index"] for o in observations] == [80, 90, 100, 110, 120, 130, 140, 190]
    assert observations[2]["seam_prominence"] == 1.88  # frame 100, guardado y leido bien

    groups = group_pill_bags_by_seam(observations)
    assert len(groups) == 3
    assert groups[1].in_transition is False  # la zona estable (130,140)


def test_direct_header_matching_pairs_pill_and_label_by_shared_signature(tmp_path):
    """Integración completa del emparejamiento directo (2.9): si el lado
    pastilla y el lado etiqueta tienen la MISMA cabecera OCR (día+fecha+
    franja), deben poder emparejarse por contenido, sin depender de orden.

    Se reproduce a mano lo que hace dataset/builder.py en el bloque de
    emparejamiento, usando Repository real (SQL), para confirmar que la
    firma se calcula igual en ambos lados y que coincide."""
    from medvision.pairing.header_grouping import group_label_bags_by_header

    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        pill_video_id = repo.upsert_video(
            path="videos/PILL.MOV", filename="PILL.MOV", side="pill_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        label_video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )

        def make_bag(video_id, side, frame_index, header, items):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=frame_index, timestamp_seconds=frame_index / 25.0,
                image_path=f"frames/{side}_{frame_index}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
            )
            bag_id = repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side=side,
                crop_path=f"bags/{side}_{frame_index}.jpg", y1=8, y2=400,
                segment_confidence=0.9, quality_score=0.3, track_key=None,
            )
            ocr_id = repo.upsert_ocr(bag_id=bag_id, raw_text="", normalized_text="",
                                      mean_confidence=95.0, word_count=5, processed_image_path=None,
                                      drug_name=None, dose_value=None, dose_unit=None, needs_review=0)
            repo.upsert_label_header(ocr_id, **header)
            repo.replace_label_items(ocr_id, items)
            return bag_id

        same_header = {"patient_name": "X", "patient_location": None,
                        "dose_weekday": "domingo", "dose_date": "01/03/26", "dose_slot": "DESAYUNO"}

        # Lado pastilla: texto reflejado, mas ruidoso, pero misma cabecera real.
        pill_bag = make_bag(pill_video_id, "pill_side", 10, same_header, [
            {"line_index": 0, "quantity": None, "drug_name": "CALCIFEDIOL",
             "dose_value": 0.266, "dose_unit": "MG", "raw_line": "x"},
        ])
        # Lado etiqueta: misma cabecera exacta, lista completa.
        label_bag = make_bag(label_video_id, "label_side", 10, same_header, [
            {"line_index": 0, "quantity": None, "drug_name": "CALCIFEDIOL",
             "dose_value": 0.266, "dose_unit": "MG", "raw_line": "x"},
            {"line_index": 1, "quantity": None, "drug_name": "BISOPROLOL",
             "dose_value": 5.0, "dose_unit": "MG", "raw_line": "x"},
        ])

        pill_observations = repo.get_ocr_observations_for_video("PILL")
        label_observations = repo.get_ocr_observations_for_video("LABEL")

    pill_groups = group_label_bags_by_header(pill_observations)
    label_groups = group_label_bags_by_header(label_observations)

    assert len(pill_groups) == 1 and len(label_groups) == 1
    assert pill_groups[0].signature == label_groups[0].signature
    assert pill_groups[0].representative_bag_id == pill_bag
    assert label_groups[0].representative_bag_id == label_bag


def test_pair_group_members_stores_all_contributing_bags_not_just_representative(tmp_path):
    """Regresión real (encontrada revisando datos reales): si una bolsita no
    cabe entera en un frame, el grupo se fusiona a partir de varias fotos,
    pero track_pairs solo guardaba la bolsa representante. Sin esto, la app
    de revisión podía no enseñar una pastilla/línea que sí contribuyó a la
    lista fusionada. Ver docs/cuaderno_ingenieria_3.0.md."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )

        def make_bag(frame_index):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=frame_index, timestamp_seconds=frame_index / 25.0,
                image_path=f"frames/f{frame_index}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
            )
            return repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side="label_side",
                crop_path=f"bags/f{frame_index}.jpg", y1=8, y2=400,
                segment_confidence=0.9, quality_score=0.3, track_key=None,
            )

        bag_top = make_bag(0)     # muestra la mitad de arriba de la bolsita
        bag_bottom = make_bag(10)  # muestra la mitad de abajo (donde esta la pastilla que "desaparecia")

        # crea un track_pair real con orden 0 para esta pair_key
        track_pair_id = repo.upsert_track_pair(
            pair_key="p1", pill_track_key=None, label_track_key="LABEL:label_side:header:0000",
            pill_best_bag_id=None, label_best_bag_id=bag_top, order_index=0,
            match_score=0.0, status="unmatched_pill", drug_name=None, dose_value=None,
            dose_unit=None, ocr_confidence=None, needs_review=1,
        )
        assert isinstance(track_pair_id, int) and track_pair_id > 0

        # el grupo fusionado tiene las DOS fotos, no solo la representante (bag_top)
        repo.replace_pair_group_members(track_pair_id, "label", [bag_top, bag_bottom])

    with Repository(db_path) as repo:
        paths = repo.get_pair_group_image_paths(track_pair_id, "label")

    assert len(paths) == 2
    assert "bags/f0.jpg" in paths
    assert "bags/f10.jpg" in paths  # antes del arreglo, esta se perdia


def test_pair_group_members_replace_overwrites_not_accumulates(tmp_path):
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        frame_id = repo.upsert_frame(
            video_id=video_id, frame_index=0, timestamp_seconds=0.0,
            image_path="f.jpg", sharpness=10.0, brightness=55.0,
            contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
        )
        bag_id = repo.upsert_bag(
            frame_id=frame_id, bag_index_in_frame=0, side="label_side",
            crop_path="b.jpg", y1=8, y2=400, segment_confidence=0.9,
            quality_score=0.3, track_key=None,
        )
        track_pair_id = repo.upsert_track_pair(
            pair_key="p2", pill_track_key=None, label_track_key=None,
            pill_best_bag_id=None, label_best_bag_id=bag_id, order_index=0,
            match_score=0.0, status="unmatched_pill", drug_name=None, dose_value=None,
            dose_unit=None, ocr_confidence=None, needs_review=1,
        )
        repo.replace_pair_group_members(track_pair_id, "label", [bag_id])
        repo.replace_pair_group_members(track_pair_id, "label", [bag_id])  # reprocesado

    with Repository(db_path) as repo:
        paths = repo.get_pair_group_image_paths(track_pair_id, "label")
    assert len(paths) == 1  # no duplicado


def test_upsert_ocr_allows_multiple_sheets_per_bag(tmp_path):
    """Integración real (3.2): una foto con dos bolsitas completas (grabación
    vertical) debe poder guardar dos filas de ocr_results distintas para el
    MISMO bag_id, cada una con su propia cabecera y lista de fármacos —
    antes, bag_id era UNIQUE y la segunda bolsita no tenía dónde ir."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        frame_id = repo.upsert_frame(
            video_id=video_id, frame_index=0, timestamp_seconds=0.0,
            image_path="f.jpg", sharpness=10.0, brightness=55.0,
            contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
        )
        bag_id = repo.upsert_bag(
            frame_id=frame_id, bag_index_in_frame=0, side="label_side",
            crop_path="b.jpg", y1=8, y2=800, segment_confidence=0.9,
            quality_score=0.3, track_key=None,
        )

        ocr_id_0 = repo.upsert_ocr(bag_id=bag_id, sheet_index=0, raw_text="", normalized_text="",
                                    mean_confidence=95.0, word_count=5, processed_image_path=None,
                                    drug_name=None, dose_value=None, dose_unit=None, needs_review=0)
        ocr_id_1 = repo.upsert_ocr(bag_id=bag_id, sheet_index=1, raw_text="", normalized_text="",
                                    mean_confidence=93.0, word_count=5, processed_image_path=None,
                                    drug_name=None, dose_value=None, dose_unit=None, needs_review=0)
        assert ocr_id_0 != ocr_id_1  # dos filas reales, no la misma sobrescrita

        repo.upsert_label_header(ocr_id_0, patient_name="X", patient_location=None,
                                  dose_weekday="JUEVES", dose_date="12/03/26", dose_slot="AYUNAS")
        repo.upsert_label_header(ocr_id_1, patient_name="X", patient_location=None,
                                  dose_weekday="MIERCOLES", dose_date="11/03/26", dose_slot="AYUNAS")
        repo.replace_label_items(ocr_id_0, [
            {"line_index": 0, "quantity": 1, "drug_name": "LEVOTIROXINA",
             "dose_value": 100.0, "dose_unit": "MCG", "raw_line": "x"},
        ])
        repo.replace_label_items(ocr_id_1, [
            {"line_index": 0, "quantity": 1, "drug_name": "OMEPRAZOL",
             "dose_value": 20.0, "dose_unit": "MG", "raw_line": "x"},
        ])

        observations = repo.get_ocr_observations_for_video("LABEL")

    assert len(observations) == 2  # las dos bolsitas de la misma foto, no fusionadas
    headers = {o["ocr_result_id"]: o["header"] for o in observations}
    weekdays = {h["dose_weekday"] for h in headers.values()}
    assert weekdays == {"JUEVES", "MIERCOLES"}


def test_video_completion_tracking_lets_pipeline_skip_processed_videos(tmp_path):
    """Integración real (3.5): un video marcado 'completed' debe poder
    detectarse como ya procesado, para que build-dataset lo salte en la
    siguiente ejecución en vez de repetir deteccion/OCR sobre 108 videos
    cada vez que se añaden unos pocos nuevos."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/MVI_0001.MOV", filename="MVI_0001.MOV", side="pill_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        # recien insertado: NO deberia marcarse como completado todavia
        assert repo.is_video_completed("MVI_0001.MOV", "pill_side") is False

        repo.mark_video_completed(video_id)
        assert repo.is_video_completed("MVI_0001.MOV", "pill_side") is True

    # tras reabrir la base (como pasaria entre dos ejecuciones reales del CLI)
    with Repository(db_path) as repo:
        assert repo.is_video_completed("MVI_0001.MOV", "pill_side") is True
        assert repo.is_video_completed("MVI_9999_NUNCA_PROCESADO.MOV", "pill_side") is False


def test_video_completion_ignores_wrong_side_forcing_reprocess(tmp_path):
    """Caso real (3.6): un vídeo procesado como 'unknown' por olvidar
    regenerar sessions.yaml antes de lanzar el pipeline no debe darse por
    completado cuando luego se corrige la sesión — debe reprocesarse con el
    lado correcto, no saltarse arrastrando el error."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/MVI_2771.MOV", filename="MVI_2771.MOV", side="unknown",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        repo.mark_video_completed(video_id)

        # Mismo lado (unknown otra vez) -> se saltaria correctamente
        assert repo.is_video_completed("MVI_2771.MOV", "unknown") is True
        # Lado corregido (pill_side) -> NO debe darse por completado, hay que reprocesar
        assert repo.is_video_completed("MVI_2771.MOV", "pill_side") is False


def test_build_dataset_stops_before_processing_if_videos_missing_from_video_sides(tmp_path):
    """Caso real (3.7): dos veces seguidas se lanzó build-dataset sin haber
    regenerado sessions.yaml con los vídeos nuevos, y el pipeline se coló
    procesándolos como 'unknown' sin que se notara en mitad de un log
    larguísimo. Debe pararse ANTES de tocar nada, con un mensaje claro."""
    import yaml
    from medvision.dataset.builder import build_dataset

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    (videos_dir / "MVI_0001.MOV").write_bytes(b"\x00" * 100)  # contenido no importa: para antes de abrirlo

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "database": "medvision.sqlite", "video_sides": {},  # vacio a proposito
        "sampling": {"seconds_between_frames": 2.0, "max_frames_per_video": 3},
        "bag_detection": {"threshold_value": 100, "min_area_ratio": 0.08},
        "bag_splitting": {"min_segment_height": 180, "max_segments": 1, "margin": 8},
        "ocr": {"enabled": True, "lang": "es", "engine": "paddle", "min_word_score": 0.5,
                "auto_accept_confidence": 80, "pill_side_enabled": True},
        "selection": {"limit_per_video_side": 20},
        "tracking": {"appearance_weight": 0.72, "position_weight": 0.20, "order_weight": 0.08,
                     "min_match_score": 0.68, "max_position_delta": 0.48, "max_gap_seconds": 8.5,
                     "descriptor_momentum": 0.70},
        "pairing": {"auto_accept_ocr_confidence": 70},
    }), encoding="utf-8")

    output_dir = tmp_path / "output"
    try:
        build_dataset(videos_dir, output_dir, config_path)
        assert False, "debería haber lanzado RuntimeError"
    except RuntimeError as exc:
        assert "MVI_0001" in str(exc)
        assert "plan-sessions" in str(exc)

    # No debe haber creado ni el sqlite: se paró antes de tocar nada.
    assert not (output_dir / "medvision.sqlite").exists()


def test_multi_sheet_bag_used_as_representative_resolves_correct_sheet(tmp_path):
    """Integración real (3.8): si una foto tiene 2 bolsitas (sheet_index 0 y
    1) y ambas acaban siendo representantes de grupos DISTINTOS, el par de
    cada grupo debe mostrar su propia cabecera/fármacos — no los del
    sheet_index 0 para los dos, que era el bug real encontrado."""
    from medvision.dataset.builder import _build_pairs

    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        pill_video_id = repo.upsert_video(
            path="videos/PILL.MOV", filename="PILL.MOV", side="pill_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        label_video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )

        def make_bag(video_id, side, frame_index):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=frame_index, timestamp_seconds=frame_index / 25.0,
                image_path=f"frames/{side}_{frame_index}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
            )
            return repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side=side,
                crop_path=f"bags/{side}_{frame_index}.jpg", y1=8, y2=1800,
                segment_confidence=0.9, quality_score=0.3, track_key=None,
            )

        # UNA foto de etiqueta con DOS bolsitas (sheet_index 0 y 1) -- el
        # caso real que motivo el arreglo.
        label_bag_id = make_bag(label_video_id, "label_side", 10)
        ocr_sheet0 = repo.upsert_ocr(bag_id=label_bag_id, sheet_index=0, raw_text="", normalized_text="",
                                      mean_confidence=95.0, word_count=5, processed_image_path=None,
                                      drug_name=None, dose_value=None, dose_unit=None, needs_review=0)
        ocr_sheet1 = repo.upsert_ocr(bag_id=label_bag_id, sheet_index=1, raw_text="", normalized_text="",
                                      mean_confidence=95.0, word_count=5, processed_image_path=None,
                                      drug_name=None, dose_value=None, dose_unit=None, needs_review=0)
        repo.upsert_label_header(ocr_sheet0, patient_name="X", patient_location=None,
                                  dose_weekday="JUEVES", dose_date="12/03/26", dose_slot="AYUNAS")
        repo.upsert_label_header(ocr_sheet1, patient_name="X", patient_location=None,
                                  dose_weekday="VIERNES", dose_date="13/03/26", dose_slot="CENA")
        repo.replace_label_items(ocr_sheet0, [
            {"line_index": 0, "quantity": 1, "drug_name": "LEVOTIROXINA",
             "dose_value": 100.0, "dose_unit": "MCG", "raw_line": "x"},
        ])
        repo.replace_label_items(ocr_sheet1, [
            {"line_index": 0, "quantity": 1, "drug_name": "OMEPRAZOL",
             "dose_value": 20.0, "dose_unit": "MG", "raw_line": "x"},
        ])

        # Lado pastilla: 2 bags con cabeceras que coinciden con cada bolsita
        # de la foto de arriba, para que las DOS se emparejen por separado.
        pill_bag_a = make_bag(pill_video_id, "pill_side", 5)
        pill_bag_b = make_bag(pill_video_id, "pill_side", 6)
        ocr_pill_a = repo.upsert_ocr(bag_id=pill_bag_a, sheet_index=0, raw_text="", normalized_text="",
                                      mean_confidence=90.0, word_count=5, processed_image_path=None,
                                      drug_name=None, dose_value=None, dose_unit=None, needs_review=0)
        ocr_pill_b = repo.upsert_ocr(bag_id=pill_bag_b, sheet_index=0, raw_text="", normalized_text="",
                                      mean_confidence=90.0, word_count=5, processed_image_path=None,
                                      drug_name=None, dose_value=None, dose_unit=None, needs_review=0)
        repo.upsert_label_header(ocr_pill_a, patient_name="X", patient_location=None,
                                  dose_weekday="JUEVES", dose_date="12/03/26", dose_slot="AYUNAS")
        repo.upsert_label_header(ocr_pill_b, patient_name="X", patient_location=None,
                                  dose_weekday="VIERNES", dose_date="13/03/26", dose_slot="CENA")

        cfg = {
            "video_pairs": [{"pair_key": "s0", "pill_video": "PILL", "label_video": "LABEL", "direction": "direct"}],
        }
        pair_rows = _build_pairs(repo, cfg, tmp_path)

    by_date = {r["dose_date"]: r for r in pair_rows if r.get("status") == "paired"}
    assert "12/03/26" in by_date and "13/03/26" in by_date
    assert by_date["12/03/26"]["drug_names_preview"] == "LEVOTIROXINA"
    assert by_date["13/03/26"]["drug_names_preview"] == "OMEPRAZOL"
    # Antes del arreglo: los dos hubieran mostrado el sheet_index 0 (LEVOTIROXINA/AYUNAS/12-03).
    assert by_date["13/03/26"]["dose_slot"] == "CENA"


def test_list_pairs_for_review_filters_by_pipeline_status_and_samples(tmp_path):
    """Integración real (3.9): la app de revisión debe poder filtrar por
    status del pipeline (paired/unmatched_label/...) y tomar una muestra
    aleatoria -- necesario para revisar 442 pares sin tener que mirar cada
    uno de los 'paired' (ya verificados por contenido)."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        for i in range(10):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=i, timestamp_seconds=i / 25.0,
                image_path=f"f{i}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
            )
            bag_id = repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side="label_side",
                crop_path=f"b{i}.jpg", y1=8, y2=800, segment_confidence=0.9,
                quality_score=0.3, track_key=None,
            )
            status = "paired" if i < 6 else "unmatched_label"
            repo.upsert_track_pair(
                pair_key="p", pill_track_key=None, label_track_key=f"L:{i}",
                pill_best_bag_id=None, label_best_bag_id=bag_id, label_ocr_result_id=None,
                order_index=i, match_score=1.0 if status == "paired" else 0.0,
                status=status, drug_name=None, dose_value=None, dose_unit=None,
                ocr_confidence=None, needs_review=0 if status == "paired" else 1,
            )

        all_rows = repo.list_pairs_for_review("all", "all", hide_empty=False)
        assert len(all_rows) == 10

        paired_only = repo.list_pairs_for_review("all", "paired", hide_empty=False)
        assert len(paired_only) == 6
        assert all(r["status"] == "paired" for r in paired_only)

        unmatched_only = repo.list_pairs_for_review("all", "unmatched_label", hide_empty=False)
        assert len(unmatched_only) == 4

        sample = repo.list_pairs_for_review("all", "paired", sample_size=3, hide_empty=False)
        assert len(sample) == 3
        assert all(r["status"] == "paired" for r in sample)

        # muestra mayor que el total disponible: se queda con lo que hay, sin fallar
        sample_big = repo.list_pairs_for_review("all", "unmatched_label", sample_size=100, hide_empty=False)
        assert len(sample_big) == 4


def test_list_pairs_for_review_uses_exact_ocr_result_not_guessed_by_bag(tmp_path):
    """Regresión (3.9): la app de revisión buscaba la lectura OCR por
    bag_id sin distinguir sheet_index -- mismo bug que 3.8 arregló en el
    pipeline, pero en la consulta de la app. Dos bolsitas de la MISMA foto
    deben poder mostrar cada una su propio label_ocr_result_id."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        frame_id = repo.upsert_frame(
            video_id=video_id, frame_index=0, timestamp_seconds=0.0, image_path="f.jpg",
            sharpness=10.0, brightness=55.0, contrast=40.0, overexposed_ratio=0.0,
            quality_score=0.3, strip_detected=1,
        )
        bag_id = repo.upsert_bag(
            frame_id=frame_id, bag_index_in_frame=0, side="label_side",
            crop_path="b.jpg", y1=8, y2=1800, segment_confidence=0.9,
            quality_score=0.3, track_key=None,
        )
        ocr0 = repo.upsert_ocr(bag_id=bag_id, sheet_index=0, raw_text="", normalized_text="",
                                mean_confidence=95.0, word_count=5, processed_image_path=None,
                                drug_name=None, dose_value=None, dose_unit=None, needs_review=0)
        ocr1 = repo.upsert_ocr(bag_id=bag_id, sheet_index=1, raw_text="", normalized_text="",
                                mean_confidence=95.0, word_count=5, processed_image_path=None,
                                drug_name=None, dose_value=None, dose_unit=None, needs_review=0)

        repo.upsert_track_pair(
            pair_key="p", pill_track_key=None, label_track_key="L:0",
            pill_best_bag_id=None, label_best_bag_id=bag_id, label_ocr_result_id=ocr0,
            order_index=0, match_score=1.0, status="paired", drug_name=None,
            dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=0,
        )
        repo.upsert_track_pair(
            pair_key="p", pill_track_key=None, label_track_key="L:1",
            pill_best_bag_id=None, label_best_bag_id=bag_id, label_ocr_result_id=ocr1,
            order_index=1, match_score=1.0, status="paired", drug_name=None,
            dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=0,
        )

        rows = repo.list_pairs_for_review("all", "all", hide_empty=False)

    assert len(rows) == 2
    result_ids = {r["order_index"]: r["label_ocr_result_id"] for r in rows}
    assert result_ids[0] == ocr0
    assert result_ids[1] == ocr1
    assert result_ids[0] != result_ids[1]  # antes del arreglo, ambos hubieran mostrado lo mismo


def test_repository_auto_migrates_missing_columns_on_old_database(tmp_path):
    """Regresión real (3.10): una base creada con un esquema de una ronda
    anterior (sin las columnas más recientes) debe repararse sola al
    abrirla con el código nuevo, sin perder tablas ni datos existentes."""
    import sqlite3

    db_path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
            side TEXT NOT NULL, fps REAL NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
            frame_count INTEGER NOT NULL, duration_seconds REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE bags (
            id INTEGER PRIMARY KEY AUTOINCREMENT, frame_id INTEGER, bag_index_in_frame INTEGER,
            side TEXT, crop_path TEXT, y1 INTEGER, y2 INTEGER, segment_confidence REAL,
            quality_score REAL, selected INTEGER DEFAULT 0, track_key TEXT,
            track_match_score REAL DEFAULT 0, is_track_best INTEGER DEFAULT 0
        );
        CREATE TABLE ocr_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bag_id INTEGER, sheet_index INTEGER NOT NULL DEFAULT 0,
            raw_text TEXT NOT NULL DEFAULT '', normalized_text TEXT NOT NULL DEFAULT '',
            mean_confidence REAL NOT NULL DEFAULT 0, word_count INTEGER NOT NULL DEFAULT 0,
            processed_image_path TEXT, drug_name TEXT, dose_value REAL, dose_unit TEXT,
            needs_review INTEGER NOT NULL DEFAULT 1, UNIQUE(bag_id, sheet_index)
        );
        CREATE TABLE track_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pair_key TEXT NOT NULL, pill_track_key TEXT,
            label_track_key TEXT, pill_best_bag_id INTEGER, label_best_bag_id INTEGER,
            order_index INTEGER NOT NULL, match_score REAL DEFAULT 0, status TEXT NOT NULL,
            drug_name TEXT, dose_value REAL, dose_unit TEXT, ocr_confidence REAL,
            needs_review INTEGER DEFAULT 1, UNIQUE(pair_key, order_index)
        );
        INSERT INTO videos(path,filename,side,fps,width,height,frame_count,duration_seconds)
            VALUES('v.MOV','v.MOV','pill_side',25.0,1080,1920,10,1.0);
        INSERT INTO track_pairs(pair_key,order_index,status) VALUES('p',0,'paired');
    """)
    conn.commit()
    conn.close()

    with Repository(db_path) as repo:
        cols_tp = {r["name"] for r in repo.conn.execute("PRAGMA table_info(track_pairs)")}
        cols_v = {r["name"] for r in repo.conn.execute("PRAGMA table_info(videos)")}
        cols_b = {r["name"] for r in repo.conn.execute("PRAGMA table_info(bags)")}
        assert "label_ocr_result_id" in cols_tp
        assert "status" in cols_v
        assert "seam_prominence" in cols_b and "seam_position" in cols_b

        # los datos que ya existian antes de migrar no se pierden
        row = repo.conn.execute("SELECT filename FROM videos WHERE path='v.MOV'").fetchone()
        assert row["filename"] == "v.MOV"
        row2 = repo.conn.execute("SELECT status FROM track_pairs WHERE pair_key='p'").fetchone()
        assert row2["status"] == "paired"


def test_repository_refuses_pre_32_database_with_clear_error(tmp_path):
    """Regresión (3.10): una base de antes de 3.2 (sin sheet_index, que
    también cambió una restriccion UNIQUE) no se puede migrar de forma
    segura con ALTER TABLE -- debe fallar con un mensaje claro, no con un
    error de SQL a medias."""
    import sqlite3

    db_path = tmp_path / "very_old.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE ocr_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bag_id INTEGER UNIQUE,
            raw_text TEXT NOT NULL DEFAULT '', normalized_text TEXT NOT NULL DEFAULT '',
            mean_confidence REAL NOT NULL DEFAULT 0, word_count INTEGER NOT NULL DEFAULT 0,
            processed_image_path TEXT, drug_name TEXT, dose_value REAL, dose_unit TEXT,
            needs_review INTEGER NOT NULL DEFAULT 1
        );
    """)
    conn.commit()
    conn.close()

    try:
        with Repository(db_path):
            assert False, "debería haber lanzado RuntimeError"
    except RuntimeError as exc:
        assert "sheet_index" in str(exc)
        assert "--fresh" in str(exc)


def test_seam_side_and_position_persist_for_review_app_visual_aid(tmp_path):
    """Integración real (3.12): la costura y el lado de cada bolsita deben
    guardarse y poder recuperarse vía list_pairs_for_review /
    get_pair_group_images, para que la app pueda dibujar la ayuda visual."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        frame_id = repo.upsert_frame(
            video_id=video_id, frame_index=0, timestamp_seconds=0.0, image_path="f.jpg",
            sharpness=10.0, brightness=55.0, contrast=40.0, overexposed_ratio=0.0,
            quality_score=0.3, strip_detected=1,
        )
        bag_id = repo.upsert_bag(
            frame_id=frame_id, bag_index_in_frame=0, side="label_side",
            crop_path="b.jpg", y1=8, y2=1800, segment_confidence=0.9,
            quality_score=0.3, track_key=None,
        )
        repo.update_bag_seam(bag_id, seam_prominence=12.5, seam_position=0.45)

        ocr_id = repo.upsert_ocr(
            bag_id=bag_id, sheet_index=0, raw_text="", normalized_text="",
            mean_confidence=95.0, word_count=5, processed_image_path=None,
            drug_name=None, dose_value=None, dose_unit=None, needs_review=0,
            seam_side="above",
        )
        track_pair_id = repo.upsert_track_pair(
            pair_key="p", pill_track_key=None, label_track_key="L:0",
            pill_best_bag_id=None, label_best_bag_id=bag_id, label_ocr_result_id=ocr_id,
            order_index=0, match_score=1.0, status="paired", drug_name=None,
            dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=0,
        )
        repo.replace_pair_group_members(track_pair_id, "label", [bag_id])

        rows = repo.list_pairs_for_review("all", "all", hide_empty=False)
        images = repo.get_pair_group_images(track_pair_id, "label")

    assert rows[0]["label_seam_position"] == 0.45
    assert rows[0]["label_seam_side"] == "above"
    assert len(images) == 1
    assert images[0]["seam_position"] == 0.45


def test_position_matching_pairs_bags_without_direct_header_match(tmp_path):
    """Integración real (3.13): una bolsita de etiqueta sin cabecera legible
    en el lado pastilla (no hay coincidencia directa posible) debe poder
    emparejarse igualmente por posición física, si la distancia de paneo
    acumulada la sitúa cerca de una bolsa del lado pastilla."""
    from medvision.dataset.builder import _build_pairs

    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        pill_video_id = repo.upsert_video(
            path="videos/PILL.MOV", filename="PILL.MOV", side="pill_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        label_video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )

        def make_bag_with_pan(video_id, side, frame_index, cumulative_pan_px):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=frame_index, timestamp_seconds=frame_index / 25.0,
                image_path=f"frames/{side}_{frame_index}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
            )
            repo.set_frame_cumulative_pan(frame_id, cumulative_pan_px)
            bag_id = repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side=side,
                crop_path=f"bags/{side}_{frame_index}.jpg", y1=8, y2=800,
                segment_confidence=0.9, quality_score=0.3, track_key=None,
            )
            return bag_id

        # Lado pastilla: 3 bolsas repartidas a lo largo de la distancia de paneo
        # (0, -500, -1000px) -- SIN OCR (texto reflejado no legible en ninguna).
        make_bag_with_pan(pill_video_id, "pill_side", 10, 0.0)
        pill_mid_bag = make_bag_with_pan(pill_video_id, "pill_side", 50, -500.0)
        make_bag_with_pan(pill_video_id, "pill_side", 90, -1000.0)

        # Lado etiqueta: 1 bolsa a mitad de su propio recorrido de paneo (0 a -900px),
        # con cabecera OCR reconocida pero SIN equivalente en pastilla (signature unico).
        label_bag_id = make_bag_with_pan(label_video_id, "label_side", 10, 0.0)
        make_bag_with_pan(label_video_id, "label_side", 90, -900.0)  # fija el rango de paneo
        ocr_id = repo.upsert_ocr(
            bag_id=label_bag_id, sheet_index=0, raw_text="", normalized_text="",
            mean_confidence=95.0, word_count=5, processed_image_path=None,
            drug_name=None, dose_value=None, dose_unit=None, needs_review=0,
        )
        repo.upsert_label_header(ocr_id, patient_name="X", patient_location=None,
                                  dose_weekday="LUNES", dose_date="02/03/26", dose_slot="DESAYUNO")
        repo.replace_label_items(ocr_id, [
            {"line_index": 0, "quantity": 1, "drug_name": "PARACETAMOL",
             "dose_value": 650.0, "dose_unit": "MG", "raw_line": "x"},
        ])

        cfg = {
            "video_pairs": [{"pair_key": "s0", "pill_video": "PILL", "label_video": "LABEL", "direction": "direct"}],
        }
        pair_rows = _build_pairs(repo, cfg, tmp_path)

    matched = [r for r in pair_rows if r.get("status") == "position_matched"]
    assert len(matched) == 1
    assert matched[0]["match_score"] == 0.75
    assert matched[0]["needs_review"] == 1
    # label_bag esta a fraccion 0.0 de su propio rango (0 a -900) -> pastilla
    # deberia caer cerca de fraccion 0.0 de SU rango (0 a -1000) -> bag_id=1 (pan=0), no el del medio ni el final.
    assert matched[0]["pill_best_bag_id"] != pill_mid_bag


def test_get_completed_videos_missing_pan_distance_finds_old_videos(tmp_path):
    """Regresión real (3.14): un vídeo completado con código anterior a la
    3.13 no tiene cumulative_pan_px -- debe poder detectarse para rellenarlo
    a posteriori sin --fresh."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/OLD.MOV", filename="OLD.MOV", side="pill_side",
            fps=25.0, width=1080, height=1920, frame_count=10, duration_seconds=1.0,
        )
        frame_id = repo.upsert_frame(
            video_id=video_id, frame_index=0, timestamp_seconds=0.0, image_path="f.jpg",
            sharpness=10.0, brightness=55.0, contrast=40.0, overexposed_ratio=0.0,
            quality_score=0.3, strip_detected=1,
        )
        repo.mark_video_completed(video_id)  # completado, pero SIN cumulative_pan_px

        missing = repo.get_completed_videos_missing_pan_distance()
        assert "OLD.MOV" in missing

        repo.set_frame_cumulative_pan(frame_id, 42.0)
        missing_after = repo.get_completed_videos_missing_pan_distance()
        assert "OLD.MOV" not in missing_after


def test_position_matching_skips_empty_label_groups(tmp_path):
    """Regresión real (3.15): un grupo de etiqueta sin fármacos (pie de
    farmacia mal leído como cabecera) no debe consumir una foto de pastilla
    por emparejamiento de posición -- esa foto debe quedar libre para una
    bolsita real con fármacos de verdad."""
    from medvision.dataset.builder import _build_pairs

    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        pill_video_id = repo.upsert_video(
            path="videos/PILL.MOV", filename="PILL.MOV", side="pill_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        label_video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )

        def make_bag_with_pan(video_id, side, frame_index, cumulative_pan_px):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=frame_index, timestamp_seconds=frame_index / 25.0,
                image_path=f"frames/{side}_{frame_index}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
            )
            repo.set_frame_cumulative_pan(frame_id, cumulative_pan_px)
            return repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side=side,
                crop_path=f"bags/{side}_{frame_index}.jpg", y1=8, y2=800,
                segment_confidence=0.9, quality_score=0.3, track_key=None,
            )

        # Solo 1 foto de pastilla disponible en toda la sesion.
        only_pill_bag = make_bag_with_pan(pill_video_id, "pill_side", 10, 0.0)
        make_bag_with_pan(pill_video_id, "pill_side", 90, -1000.0)  # fija el rango

        # 2 lecturas de etiqueta en la MISMA posicion relativa: una vacia (ruido),
        # otra con farmacos reales. Solo deberia consumir la foto la que tiene contenido.
        empty_bag_id = make_bag_with_pan(label_video_id, "label_side", 10, 0.0)
        ocr_empty = repo.upsert_ocr(
            bag_id=empty_bag_id, sheet_index=0, raw_text="", normalized_text="",
            mean_confidence=90.0, word_count=2, processed_image_path=None,
            drug_name=None, dose_value=None, dose_unit=None, needs_review=1,
        )
        repo.upsert_label_header(ocr_empty, patient_name="GR473F181 22", patient_location=None,
                                  dose_weekday=None, dose_date=None, dose_slot=None)
        # sin replace_label_items -> 0 farmacos, exactamente el caso real encontrado

        make_bag_with_pan(label_video_id, "label_side", 90, -900.0)  # fija el rango de paneo

        cfg = {
            "video_pairs": [{"pair_key": "s0", "pill_video": "PILL", "label_video": "LABEL", "direction": "direct"}],
        }
        pair_rows = _build_pairs(repo, cfg, tmp_path)

    position_rows = [r for r in pair_rows if r.get("status") == "position_matched"]
    assert len(position_rows) == 0, "una lectura vacia no debe emparejarse por posicion"


def test_find_closest_bag_by_pan_distance_falls_through_when_closest_excluded(tmp_path):
    """Regresión real (3.16): si la bolsa de pastilla más cercana ya está
    usada, debe probar con la siguiente más cercana dentro del margen, no
    rendirse -- bug real encontrado con datos reales (varias bolsitas
    distintas competían por la misma foto cercana; solo la primera se la
    quedaba, las demás se perdían aunque hubiera otra opción válida)."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/PILL.MOV", filename="PILL.MOV", side="pill_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )

        def make_bag(frame_index, cumulative_pan_px):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=frame_index, timestamp_seconds=frame_index / 25.0,
                image_path=f"f{frame_index}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
            )
            repo.set_frame_cumulative_pan(frame_id, cumulative_pan_px)
            return repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side="pill_side",
                crop_path=f"b{frame_index}.jpg", y1=8, y2=800,
                segment_confidence=0.9, quality_score=0.3, track_key=None,
            )

        closest_bag = make_bag(10, -100.0)   # la mas cercana al objetivo (-100)
        second_bag = make_bag(20, -150.0)    # segunda mas cercana, tambien dentro del margen

        # Sin exclusiones: debe encontrar la mas cercana.
        c1 = repo.find_closest_bag_by_pan_distance("PILL", "pill_side", -100.0, tolerance_px=100.0)
        assert int(c1["bag_id"]) == closest_bag

        # Excluyendo la mas cercana (ya usada por otro grupo): debe caer a la segunda,
        # no rendirse devolviendo None.
        c2 = repo.find_closest_bag_by_pan_distance(
            "PILL", "pill_side", -100.0, tolerance_px=100.0, exclude_bag_ids={closest_bag}
        )
        assert c2 is not None, "antes del arreglo, esto devolvia None y se perdia el emparejamiento"
        assert int(c2["bag_id"]) == second_bag

        # Excluyendo las dos: no hay mas candidatas, debe devolver None de verdad.
        c3 = repo.find_closest_bag_by_pan_distance(
            "PILL", "pill_side", -100.0, tolerance_px=100.0, exclude_bag_ids={closest_bag, second_bag}
        )
        assert c3 is None


def test_list_pairs_for_review_hides_empty_readings_by_default(tmp_path):
    """Integración real (3.17): las lecturas sin ningún fármaco (ruido de
    OCR) deben poder ocultarse de la cola de revisión por defecto, sin
    afectar a las que sí tienen contenido real."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )

        def make_pair(idx, with_items):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=idx, timestamp_seconds=idx / 25.0,
                image_path=f"f{idx}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
            )
            bag_id = repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side="label_side",
                crop_path=f"b{idx}.jpg", y1=8, y2=800, segment_confidence=0.9,
                quality_score=0.3, track_key=None,
            )
            ocr_id = repo.upsert_ocr(
                bag_id=bag_id, sheet_index=0, raw_text="", normalized_text="",
                mean_confidence=90.0, word_count=2, processed_image_path=None,
                drug_name=None, dose_value=None, dose_unit=None, needs_review=1,
            )
            if with_items:
                repo.replace_label_items(ocr_id, [
                    {"line_index": 0, "quantity": 1, "drug_name": "PARACETAMOL",
                     "dose_value": 650.0, "dose_unit": "MG", "raw_line": "x"},
                ])
            repo.upsert_track_pair(
                pair_key="p", pill_track_key=None, label_track_key=f"L:{idx}",
                pill_best_bag_id=None, label_best_bag_id=bag_id, label_ocr_result_id=ocr_id,
                order_index=idx, match_score=0.0, status="unmatched_label",
                drug_name=None, dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=1,
            )

        make_pair(0, with_items=True)
        make_pair(1, with_items=False)
        make_pair(2, with_items=False)

        default_rows = repo.list_pairs_for_review("all", "all")  # hide_empty=True por defecto
        assert len(default_rows) == 1

        all_rows = repo.list_pairs_for_review("all", "all", hide_empty=False)
        assert len(all_rows) == 3


def test_pill_seam_data_persists_and_is_retrievable_for_review(tmp_path):
    """Integración real (3.18): la costura del lado pastilla (cuando se
    conoce, emparejamiento directo) debe guardarse y poder recuperarse
    igual que ya se hacía para el lado etiqueta."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        pill_video_id = repo.upsert_video(
            path="videos/PILL.MOV", filename="PILL.MOV", side="pill_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        label_video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )

        def make_bag(video_id, side, idx, seam_pos=None):
            frame_id = repo.upsert_frame(
                video_id=video_id, frame_index=idx, timestamp_seconds=idx / 25.0,
                image_path=f"{side}_{idx}.jpg", sharpness=10.0, brightness=55.0,
                contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
            )
            if seam_pos is not None:
                repo.set_frame_cumulative_pan(frame_id, 0.0)  # no relevante aqui
            bag_id = repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side=side,
                crop_path=f"{side}{idx}.jpg", y1=8, y2=1800, segment_confidence=0.9,
                quality_score=0.3, track_key=None,
            )
            if seam_pos is not None:
                repo.update_bag_seam(bag_id, seam_prominence=10.0, seam_position=seam_pos)
            return bag_id

        pill_bag = make_bag(pill_video_id, "pill_side", 5, seam_pos=0.6)
        pill_ocr_id = repo.upsert_ocr(
            bag_id=pill_bag, sheet_index=0, raw_text="", normalized_text="",
            mean_confidence=90.0, word_count=5, processed_image_path=None,
            drug_name=None, dose_value=None, dose_unit=None, needs_review=0,
            seam_side="below",
        )
        label_bag = make_bag(label_video_id, "label_side", 5, seam_pos=0.4)
        label_ocr_id = repo.upsert_ocr(
            bag_id=label_bag, sheet_index=0, raw_text="", normalized_text="",
            mean_confidence=95.0, word_count=5, processed_image_path=None,
            drug_name=None, dose_value=None, dose_unit=None, needs_review=0,
            seam_side="above",
        )
        repo.replace_label_items(label_ocr_id, [
            {"line_index": 0, "quantity": 1, "drug_name": "PARACETAMOL",
             "dose_value": 650.0, "dose_unit": "MG", "raw_line": "x"},
        ])

        track_pair_id = repo.upsert_track_pair(
            pair_key="p", pill_track_key="PILL:x", label_track_key="LABEL:x",
            pill_best_bag_id=pill_bag, label_best_bag_id=label_bag,
            label_ocr_result_id=label_ocr_id, pill_ocr_result_id=pill_ocr_id,
            order_index=0, match_score=1.0, status="paired",
            drug_name=None, dose_value=None, dose_unit=None,
            ocr_confidence=None, needs_review=0,
        )

        rows = repo.list_pairs_for_review("all", "all")

    assert len(rows) == 1
    assert rows[0]["pill_seam_side"] == "below"
    assert rows[0]["pill_seam_position"] == 0.6
    assert rows[0]["label_seam_side"] == "above"
    assert rows[0]["label_seam_position"] == 0.4


def test_multi_seam_positions_persist_and_are_retrievable(tmp_path):
    """Integración real (3.26): varias costuras (3+ bolsitas en una foto)
    deben guardarse y recuperarse todas, no solo la primera."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        frame_id = repo.upsert_frame(
            video_id=video_id, frame_index=0, timestamp_seconds=0.0, image_path="f.jpg",
            sharpness=10.0, brightness=55.0, contrast=40.0, overexposed_ratio=0.0,
            quality_score=0.3, strip_detected=1,
        )
        bag_id = repo.upsert_bag(
            frame_id=frame_id, bag_index_in_frame=0, side="label_side",
            crop_path="b.jpg", y1=8, y2=2700, segment_confidence=0.9,
            quality_score=0.3, track_key=None,
        )
        repo.update_bag_seam(bag_id, seam_prominence=12.0, seam_position=0.2,
                              all_seam_positions=[0.2, 0.6])

        positions = repo.get_bag_seam_positions(bag_id)
        assert positions == [0.2, 0.6]

        ocr_id = repo.upsert_ocr(
            bag_id=bag_id, sheet_index=1, raw_text="", normalized_text="",
            mean_confidence=95.0, word_count=5, processed_image_path=None,
            drug_name=None, dose_value=None, dose_unit=None, needs_review=0,
            seam_side="segment_1",
        )
        repo.replace_label_items(ocr_id, [
            {"line_index": 0, "quantity": 1, "drug_name": "PARACETAMOL",
             "dose_value": 650.0, "dose_unit": "MG", "raw_line": "x"},
        ])
        track_pair_id = repo.upsert_track_pair(
            pair_key="p", pill_track_key=None, label_track_key="L:0",
            pill_best_bag_id=None, label_best_bag_id=bag_id, label_ocr_result_id=ocr_id,
            order_index=0, match_score=1.0, status="paired", drug_name=None,
            dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=0,
        )
        repo.replace_pair_group_members(track_pair_id, "label", [bag_id])

        images = repo.get_pair_group_images(track_pair_id, "label")
        rows = repo.list_pairs_for_review("all", "all")

    assert images[0]["seam_positions"] == [0.2, 0.6]
    assert rows[0]["label_seam_side"] == "segment_1"


def test_get_bag_seam_positions_backward_compatible_with_single_seam(tmp_path):
    """Una bolsa guardada con el método antiguo (solo seam_position, sin
    seam_positions_json) debe seguir devolviendo esa costura al consultarla
    con el nuevo método."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/OLD.MOV", filename="OLD.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        frame_id = repo.upsert_frame(
            video_id=video_id, frame_index=0, timestamp_seconds=0.0, image_path="f.jpg",
            sharpness=10.0, brightness=55.0, contrast=40.0, overexposed_ratio=0.0,
            quality_score=0.3, strip_detected=1,
        )
        bag_id = repo.upsert_bag(
            frame_id=frame_id, bag_index_in_frame=0, side="label_side",
            crop_path="b.jpg", y1=8, y2=1800, segment_confidence=0.9,
            quality_score=0.3, track_key=None,
        )
        # Simula el metodo antiguo: solo seam_position, sin all_seam_positions
        repo.update_bag_seam(bag_id, seam_prominence=10.0, seam_position=0.5)
        positions = repo.get_bag_seam_positions(bag_id)
        assert positions == [0.5]


def test_export_import_reviews_survives_fresh_reprocess(tmp_path):
    """Integración real (3.27): una decisión de revisión debe sobrevivir a
    un --fresh (que borra track_pairs y reasigna IDs nuevos) si se
    exporta antes y se reimporta después -- emparejando por vídeo de
    etiqueta + cabecera, no por track_pair_id."""
    db_path = tmp_path / "medvision.sqlite"

    def make_pair(repo, video_id, frame_index, bag_suffix, weekday, date, slot, items, decision):
        frame_id = repo.upsert_frame(
            video_id=video_id, frame_index=frame_index, timestamp_seconds=frame_index / 25.0,
            image_path=f"f{bag_suffix}.jpg", sharpness=10.0, brightness=55.0,
            contrast=40.0, overexposed_ratio=0.0, quality_score=0.3, strip_detected=1,
        )
        bag_id = repo.upsert_bag(
            frame_id=frame_id, bag_index_in_frame=0, side="label_side",
            crop_path=f"b{bag_suffix}.jpg", y1=8, y2=800, segment_confidence=0.9,
            quality_score=0.3, track_key=None,
        )
        ocr_id = repo.upsert_ocr(
            bag_id=bag_id, sheet_index=0, raw_text="", normalized_text="",
            mean_confidence=95.0, word_count=5, processed_image_path=None,
            drug_name=None, dose_value=None, dose_unit=None, needs_review=0,
        )
        repo.upsert_label_header(ocr_id, patient_name="X", patient_location=None,
                                  dose_weekday=weekday, dose_date=date, dose_slot=slot)
        repo.replace_label_items(ocr_id, items)
        track_pair_id = repo.upsert_track_pair(
            pair_key="s0", pill_track_key=None, label_track_key=f"L:{bag_suffix}",
            pill_best_bag_id=None, label_best_bag_id=bag_id, label_ocr_result_id=ocr_id,
            order_index=frame_index, match_score=1.0, status="paired",
            drug_name=None, dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=0,
        )
        repo.save_pair_review(track_pair_id, decision, "revisado por el usuario")
        repo.save_pair_review_items(track_pair_id, [
            {"line_index": 0, "quantity": 1, "drug_name": "PARACETAMOL CORREGIDO",
             "dose_value": 650.0, "dose_unit": "MG"},
        ])
        return track_pair_id

    items = [{"line_index": 0, "quantity": 1, "drug_name": "PARACETAMOL",
              "dose_value": 650.0, "dose_unit": "MG", "raw_line": "x"}]

    # 1. Estado "antes del --fresh": una bolsita revisada y aceptada.
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        make_pair(repo, video_id, 5, "old", "LUNES", "02/03/26", "DESAYUNO", items, "accepted")
        exported = repo.export_reviews()

    assert len(exported) == 1
    assert exported[0]["label_video_filename"] == "LABEL.MOV"
    assert exported[0]["decision"] == "accepted"

    # 2. Simulo un --fresh real: borro el fichero entero y empiezo de cero
    #    (mismo efecto que shutil.rmtree + rebuild, ver cli.py).
    db_path.unlink()
    with Repository(db_path) as repo:
        video_id2 = repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        # Nueva bolsita con la MISMA identidad de contenido, pero con IDs
        # totalmente distintos (video_id, bag_id, ocr_id, track_pair_id
        # nuevos) -- justo lo que produciria un reproceso real.
        new_track_pair_id = make_pair(repo, video_id2, 99, "new", "LUNES", "02/03/26", "DESAYUNO",
                                       items, "pending")
        # Nota: el ID nuevo puede coincidir por casualidad con el antiguo
        # (el contador vuelve a empezar en una base recién creada) -- no
        # importa, lo que se prueba es que el reimportado encuentra el par
        # correcto POR CONTENIDO, no por ID.

        # Sobreescribo la decision (simulando que el "pending" es lo que
        # pondria un rebuild-pairs limpio, antes de reimportar)
        repo.save_pair_review(new_track_pair_id, "pending", "")

        # 3. Reimporto lo exportado ANTES del --fresh.
        matched, unmatched = repo.import_reviews(exported)
        assert matched == 1
        assert unmatched == []

        # Confirmo que la decision se reaplico sobre el ID NUEVO
        final = repo.export_query_params(
            "SELECT decision, reviewer_notes FROM pair_reviews WHERE track_pair_id=?",
            (new_track_pair_id,),
        )
        assert final[0]["decision"] == "accepted"
        assert final[0]["reviewer_notes"] == "revisado por el usuario"

        final_items = repo.get_pair_review_items(new_track_pair_id)
        assert len(final_items) == 1
        assert final_items[0]["drug_name"] == "PARACETAMOL CORREGIDO"


def test_import_reviews_reports_unmatched_when_content_changed(tmp_path):
    """Si tras el reproceso ya no existe una bolsita con esa cabecera exacta
    (p.ej. una fecha que ahora se lee distinto), import_reviews debe
    reportarla como no encontrada, no perderla en silencio ni fallar."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        repo.upsert_video(
            path="videos/LABEL.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        fake_export = [{
            "label_video_filename": "LABEL.MOV",
            "dose_weekday": "LUNES", "dose_date": "02/03/26", "dose_slot": "DESAYUNO_QUE_YA_NO_EXISTE",
            "decision": "accepted", "reviewer_notes": "", "reviewed_at": "2026-01-01",
            "items": [],
        }]
        matched, unmatched = repo.import_reviews(fake_export)
    assert matched == 0
    assert len(unmatched) == 1
    assert unmatched[0]["dose_slot"] == "DESAYUNO_QUE_YA_NO_EXISTE"


def test_repair_corrupted_seam_prominence_recovers_exact_original_value(tmp_path):
    """Regresión real (3.29): datos ya guardados con el bug de 3.28
    (numpy.float32 sin convertir, guardado como BLOB) deben repararse
    recuperando el valor original exacto, no perderse. Reproduce incluso
    el mismo patrón de bytes que salió en el error real del usuario."""
    import numpy as np

    db_path = tmp_path / "medvision.sqlite"
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
        original_value = np.float32(11.412107)
        repo.conn.execute("UPDATE bags SET seam_prominence=? WHERE id=?", (original_value, bag_id))
        repo.conn.commit()

        row = repo.conn.execute("SELECT seam_prominence FROM bags WHERE id=?", (bag_id,)).fetchone()
        assert isinstance(row["seam_prominence"], bytes)

        repaired = repo.repair_corrupted_seam_prominence()
        assert repaired == 1

        row2 = repo.conn.execute("SELECT seam_prominence FROM bags WHERE id=?", (bag_id,)).fetchone()
        assert isinstance(row2["seam_prominence"], float)
        assert abs(row2["seam_prominence"] - float(original_value)) < 0.001
        float(row2["seam_prominence"] or 0.0)  # no debe reventar

        # idempotente
        assert repo.repair_corrupted_seam_prominence() == 0


def test_repair_corrupted_seam_prominence_noop_on_clean_database(tmp_path):
    """Sobre una base sin ningún dato corrompido, no debe tocar nada ni
    fallar."""
    db_path = tmp_path / "medvision.sqlite"
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
        repo.upsert_bag(
            frame_id=frame_id, bag_index_in_frame=0, side="pill_side",
            crop_path="b.jpg", y1=8, y2=1800, segment_confidence=0.9, quality_score=0.3, track_key=None,
        )
        repo.update_bag_seam(1, seam_prominence=5.0, seam_position=0.3)
        assert repo.repair_corrupted_seam_prominence() == 0


def test_save_pair_review_does_not_overwrite_pipeline_status(tmp_path):
    """Regresión real (3.34): guardar una revisión NO debe sobrescribir
    track_pairs.status con la propia decisión -- status debe seguir
    reflejando siempre el origen del pipeline (paired/position_matched/...),
    la decisión vive aparte en pair_reviews.decision."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_id = repo.upsert_video(
            path="v.MOV", filename="v.MOV", side="label_side",
            fps=25.0, width=1920, height=1080, frame_count=100, duration_seconds=4.0,
        )
        frame_id = repo.upsert_frame(
            video_id=video_id, frame_index=0, timestamp_seconds=0.0, image_path="f.jpg",
            sharpness=10.0, brightness=55.0, contrast=40.0, overexposed_ratio=0.0,
            quality_score=0.3, strip_detected=1,
        )
        bag_id = repo.upsert_bag(
            frame_id=frame_id, bag_index_in_frame=0, side="label_side",
            crop_path="b.jpg", y1=8, y2=800, segment_confidence=0.9, quality_score=0.3, track_key=None,
        )
        track_pair_id = repo.upsert_track_pair(
            pair_key="p", pill_track_key=None, label_track_key="L:0",
            pill_best_bag_id=None, label_best_bag_id=bag_id, label_ocr_result_id=None,
            order_index=0, match_score=0.75, status="position_matched",
            drug_name=None, dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=1,
        )
        repo.save_pair_review(track_pair_id, "accepted", "ok")

        row = repo.conn.execute("SELECT status, needs_review FROM track_pairs WHERE id=?", (track_pair_id,)).fetchone()
        assert row["status"] == "position_matched", "status no debe cambiar al revisar"
        assert row["needs_review"] == 0

        decision_row = repo.conn.execute("SELECT decision FROM pair_reviews WHERE track_pair_id=?", (track_pair_id,)).fetchone()
        assert decision_row["decision"] == "accepted"


def test_export_training_dataset_full_scenario(tmp_path):
    """Integración real (3.34): el exportador del dataset final excluye
    rechazados y vacíos por defecto, usa items corregidos por un humano
    cuando existen (si no, los del OCR), e incluye todas las fotos de
    pastilla del grupo con su costura."""
    db_path = tmp_path / "medvision.sqlite"
    with Repository(db_path) as repo:
        video_pill = repo.upsert_video(
            path="v1.MOV", filename="PILL.MOV", side="pill_side",
            fps=25.0, width=1080, height=1920, frame_count=10, duration_seconds=1.0,
        )
        video_label = repo.upsert_video(
            path="v2.MOV", filename="LABEL.MOV", side="label_side",
            fps=25.0, width=1080, height=1920, frame_count=10, duration_seconds=1.0,
        )

        def make_label_bag(idx, weekday, date, slot, items):
            frame_id = repo.upsert_frame(
                video_id=video_label, frame_index=idx, timestamp_seconds=idx / 25, image_path=f"lf{idx}.jpg",
                sharpness=10.0, brightness=55.0, contrast=40.0, overexposed_ratio=0.0,
                quality_score=0.3, strip_detected=1,
            )
            bag_id = repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side="label_side",
                crop_path=f"lb{idx}.jpg", y1=8, y2=800, segment_confidence=0.9, quality_score=0.3, track_key=None,
            )
            ocr_id = repo.upsert_ocr(
                bag_id=bag_id, sheet_index=0, raw_text="", normalized_text="",
                mean_confidence=95.0, word_count=5, processed_image_path=None,
                drug_name=None, dose_value=None, dose_unit=None, needs_review=0,
            )
            repo.upsert_label_header(ocr_id, patient_name="PACIENTE", patient_location=None,
                                      dose_weekday=weekday, dose_date=date, dose_slot=slot)
            repo.replace_label_items(ocr_id, items)
            return bag_id, ocr_id

        def make_pill_bag(idx, seam_pos=None):
            frame_id = repo.upsert_frame(
                video_id=video_pill, frame_index=idx, timestamp_seconds=idx / 25, image_path=f"pf{idx}.jpg",
                sharpness=10.0, brightness=55.0, contrast=40.0, overexposed_ratio=0.0,
                quality_score=0.3, strip_detected=1,
            )
            bag_id = repo.upsert_bag(
                frame_id=frame_id, bag_index_in_frame=0, side="pill_side",
                crop_path=f"pb{idx}.jpg", y1=8, y2=1800, segment_confidence=0.9, quality_score=0.3, track_key=None,
            )
            if seam_pos is not None:
                repo.update_bag_seam(bag_id, seam_prominence=10.0, seam_position=seam_pos, all_seam_positions=[seam_pos])
            return bag_id

        items1 = [{"line_index": 0, "quantity": 1, "drug_name": "PARACETAMOL",
                   "dose_value": 650.0, "dose_unit": "MG", "raw_line": "x"}]

        # Caso 1: paired, 2 fotos de pastilla (una con costura), corregido por humano
        label_bag1, ocr1 = make_label_bag(0, "LUNES", "02/03/26", "DESAYUNO", items1)
        pill_bag1a = make_pill_bag(10, seam_pos=0.4)
        pill_bag1b = make_pill_bag(11)
        tp1 = repo.upsert_track_pair(
            pair_key="s0", pill_track_key="P:1", label_track_key="L:1",
            pill_best_bag_id=pill_bag1a, label_best_bag_id=label_bag1, label_ocr_result_id=ocr1,
            order_index=0, match_score=1.0, status="paired",
            drug_name=None, dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=0,
        )
        repo.replace_pair_group_members(tp1, "pill", [pill_bag1a, pill_bag1b])
        repo.save_pair_review(tp1, "corrected", "cantidad ajustada")
        repo.save_pair_review_items(tp1, [
            {"line_index": 0, "quantity": 0.5, "drug_name": "PARACETAMOL", "dose_value": 650.0, "dose_unit": "MG"},
        ])

        # Caso 2: position_matched, nunca revisado -- usa OCR tal cual
        label_bag2, ocr2 = make_label_bag(1, "MARTES", "03/03/26", "CENA", items1)
        pill_bag2 = make_pill_bag(20)
        tp2 = repo.upsert_track_pair(
            pair_key="s0", pill_track_key="P:2", label_track_key="L:2",
            pill_best_bag_id=pill_bag2, label_best_bag_id=label_bag2, label_ocr_result_id=ocr2,
            order_index=1, match_score=0.75, status="position_matched",
            drug_name=None, dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=1,
        )
        repo.replace_pair_group_members(tp2, "pill", [pill_bag2])

        # Caso 3: unmatched_label, sin fotos de pastilla -- se incluye igual
        label_bag3, ocr3 = make_label_bag(2, "MIERCOLES", "04/03/26", "ALMUERZO", items1)
        repo.upsert_track_pair(
            pair_key="s0", pill_track_key=None, label_track_key="L:3",
            pill_best_bag_id=None, label_best_bag_id=label_bag3, label_ocr_result_id=ocr3,
            order_index=2, match_score=0.0, status="unmatched_label",
            drug_name=None, dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=1,
        )

        # Caso 4: rechazado -- debe EXCLUIRSE por defecto
        label_bag4, ocr4 = make_label_bag(3, "JUEVES", "05/03/26", "CENA", items1)
        tp4 = repo.upsert_track_pair(
            pair_key="s0", pill_track_key=None, label_track_key="L:4",
            pill_best_bag_id=None, label_best_bag_id=label_bag4, label_ocr_result_id=ocr4,
            order_index=3, match_score=1.0, status="paired",
            drug_name=None, dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=0,
        )
        repo.save_pair_review(tp4, "rejected", "cabecera mal leida")

        # Caso 5: vacio -- debe EXCLUIRSE por defecto
        label_bag5, ocr5 = make_label_bag(4, None, None, "CENA", [])
        repo.upsert_track_pair(
            pair_key="s0", pill_track_key=None, label_track_key="L:5",
            pill_best_bag_id=None, label_best_bag_id=label_bag5, label_ocr_result_id=ocr5,
            order_index=4, match_score=0.0, status="unmatched_label",
            drug_name=None, dose_value=None, dose_unit=None, ocr_confidence=None, needs_review=1,
        )

        records = repo.export_training_dataset()

    assert len(records) == 3  # casos 4 y 5 excluidos

    case1 = next(r for r in records if r["order_index"] == 0)
    assert case1["pipeline_status"] == "paired"
    assert case1["label_source"] == "human_corrected"
    assert case1["label_items"][0]["quantity"] == 0.5
    assert len(case1["pill_photos"]) == 2
    seam_values = {p["seam_position"] for p in case1["pill_photos"]}
    assert 0.4 in seam_values and None in seam_values

    case2 = next(r for r in records if r["order_index"] == 1)
    assert case2["pipeline_status"] == "position_matched"
    assert case2["label_source"] == "ocr_raw"
    assert case2["label_items"][0]["quantity"] == 1.0
    assert len(case2["pill_photos"]) == 1

    case3 = next(r for r in records if r["order_index"] == 2)
    assert case3["pipeline_status"] == "unmatched_label"
    assert case3["pill_photos"] == []

    assert all(r["order_index"] not in (3, 4) for r in records)
