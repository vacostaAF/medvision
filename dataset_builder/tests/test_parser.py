from medvision.ocr.parser import parse_label, parse_label_sheet, parse_label_sheets, parse_label_sheets_by_position, parse_label_sheets_by_multi_position

def test_parse_label():
    parsed=parse_label("PARACETAMOL 650 MG COMPRIMIDOS")
    assert parsed.drug_name == "PARACETAMOL"
    assert parsed.dose_value == 650
    assert parsed.dose_unit == "MG"


REAL_SHEET_LINES = [
    "PELAYO PEINADO JOSEFA",
    "EL PUERTO",
    "domingo 01/03/26 DESAYUNO",
    "1 CALCIFEDIOL 0,266 MG CAPSULA",
    "1 BISOPROLOL 5 MG COMPRIMIDO",
    "1 CINITAPRIDA 1 MG COMPRIMIDO",
    "1 AMLODIPINO 5 MG COMPRIMIDO",
    "1 LISINOPRIL/HIDROCLOROTIAZIDA 20/12,5 MG COMPRIMIDO",
    "2 PLUSVENT 25 MICROGRAMOS COMPRIMIDO",
    "1 ONY-TEC 80 MG/G BARNIZ DE UÑAS",
    "FARMACIA MARACENA",
    "www.farmaciamaracena.com",
    "958 42 02 73",
]


def test_parse_label_sheet_extracts_header():
    sheet = parse_label_sheet(REAL_SHEET_LINES)
    assert sheet.header.patient_name == "PELAYO PEINADO JOSEFA"
    assert sheet.header.patient_location == "EL PUERTO"
    assert sheet.header.dose_weekday == "DOMINGO"
    assert sheet.header.dose_date == "01/03/26"
    assert sheet.header.dose_slot == "DESAYUNO"


def test_parse_label_sheet_extracts_all_items_not_just_first():
    sheet = parse_label_sheet(REAL_SHEET_LINES)
    names = [item.drug_name for item in sheet.items]
    assert names == [
        "CALCIFEDIOL", "BISOPROLOL", "CINITAPRIDA", "AMLODIPINO",
        "LISINOPRIL/HIDROCLOROTIAZIDA", "PLUSVENT", "ONY-TEC",
    ]


def test_parse_label_sheet_handles_spelled_out_micrograms():
    sheet = parse_label_sheet(REAL_SHEET_LINES)
    plusvent = next(i for i in sheet.items if i.drug_name == "PLUSVENT")
    assert plusvent.dose_value == 25.0
    assert plusvent.dose_unit == "MCG"
    assert plusvent.quantity == 2.0


def test_parse_label_sheet_flags_compound_dose_for_review_instead_of_guessing():
    sheet = parse_label_sheet(REAL_SHEET_LINES)
    combo = next(i for i in sheet.items if "LISINOPRIL" in (i.drug_name or ""))
    assert combo.dose_value is None  # "20/12,5" no se adivina, se deja para revisión
    assert combo.dose_unit == "MG"


def test_parse_label_sheet_ignores_pharmacy_footer():
    sheet = parse_label_sheet(REAL_SHEET_LINES)
    joined_names = " ".join(i.drug_name or "" for i in sheet.items)
    assert "FARMACIA" not in joined_names
    assert "MARACENA" not in joined_names


def test_parse_label_sheet_returns_empty_items_on_unrelated_text():
    sheet = parse_label_sheet(["texto sin ningun formato de bolsita reconocible"])
    assert sheet.items == []
    assert sheet.is_empty is True


# Texto real devuelto por PaddleOCR contra MVI_2714.MOV (frame 0), reportado
# por el usuario. Antes del fix de 1.6: 0 items reconocidos y patient_name
# corrompido con la marca manuscrita "51". Ver docs/cuaderno_ingenieria_1.6.md.
REAL_PADDLEOCR_OUTPUT_UNCLUSTERED = [
    "51", "PELAYO PEINADO JOSEFA", "EL PUERTO", "domingo 01/03/26 DESAYL",
    "CALCIFEDIOL 0,266 MG CAPSULA", "BISOPROLOL 5 MG COMPRIMIDO",
    "CINITAPRIDA 1 MG COMPRIMIDO", "AMLODIPINO 5 MG COMPRIMIDO",
    "1", "LISINOPRIL/HIDROCLOROTIAZIDA", " PLUSVENT 25 MICROGRAMOS/1:",
    "2", "1", " ONY-TEC 80 MG/G BARNIZ DE UI",
]


def test_parse_label_sheet_handwritten_marker_does_not_corrupt_patient_name():
    sheet = parse_label_sheet(REAL_PADDLEOCR_OUTPUT_UNCLUSTERED)
    assert sheet.header.patient_name == "PELAYO PEINADO JOSEFA"
    assert sheet.header.patient_location == "EL PUERTO"


def test_parse_label_sheet_recovers_items_even_without_row_reconstruction():
    # Caso pesimista: sin _cluster_into_rows (p.ej. si rec_polys no estuviera
    # disponible), la cantidad sigue suelta. Aun así no deben perderse todos
    # los fármacos como pasaba antes del fix.
    sheet = parse_label_sheet(REAL_PADDLEOCR_OUTPUT_UNCLUSTERED)
    names = {i.drug_name for i in sheet.items}
    assert {"CALCIFEDIOL", "BISOPROLOL", "CINITAPRIDA", "AMLODIPINO", "PLUSVENT", "ONY-TEC"} <= names


# Líneas reales fusionadas por un agrupado de fila demasiado laxo (bug real,
# corregido en 1.6 tanto en label_ocr.py como aquí, con una capa de
# recuperación por si una fusión se cuela de todos modos).
def test_parse_label_sheet_splits_two_drugs_merged_into_one_line():
    sheet = parse_label_sheet(["SIMVASTATINA 40 MG COMPRIMID CINITAPRIDA 1 MG COMPRIMIDO"])
    assert [i.drug_name for i in sheet.items] == ["SIMVASTATINA", "CINITAPRIDA"]
    assert [i.dose_value for i in sheet.items] == [40.0, 1.0]
    assert all(i.dose_unit == "MG" for i in sheet.items)


def test_parse_label_sheet_splits_recovers_partial_items_from_triple_merge():
    # Fusión de 3 fármacos donde uno no tiene dosis propia reconocible en el
    # texto: se recuperan los 2 que sí tienen dosis, no se pierden los tres.
    sheet = parse_label_sheet(
        ["1 LISINOPRIL/HIDROCLOROTIAZIDA AMLODIPINO 5 MG COMPRIMIDO CINITAPRIDA 1 MG COMPRIMIDO"]
    )
    assert len(sheet.items) == 2
    assert sheet.items[1].drug_name == "CINITAPRIDA"
    assert sheet.items[1].dose_value == 1.0


def test_clean_drug_tokens_tolerates_truncated_form_word():
    # "COMPRIMID" (sin la "O" final) es un truncado real de OCR observado;
    # debe filtrarse igual que "COMPRIMIDO" completo.
    from medvision.ocr.parser import _clean_drug_tokens
    assert _clean_drug_tokens(["COMPRIMID", "CINITAPRIDA"]) == "CINITAPRIDA"


def test_parse_label_sheet_split_items_share_raw_line_for_review_flagging():
    # builder.py usa esto para marcar needs_review cuando una línea fusionada
    # se dividió en varios fármacos: los items resultantes comparten raw_line.
    sheet = parse_label_sheet(["SIMVASTATINA 40 MG COMPRIMID CINITAPRIDA 1 MG COMPRIMIDO"])
    assert len(sheet.items) == 2
    assert sheet.items[0].raw_line == sheet.items[1].raw_line


def test_parse_label_sheet_tolerates_mc_truncation_of_mcg():
    # Texto real: RISPERIDONA se perdía porque el OCR trunca "MCG" a "MC".
    sheet = parse_label_sheet(["O RISPERIDONA AUROBINDO 1 MC"])
    assert len(sheet.items) == 1
    assert sheet.items[0].dose_value == 1.0
    assert sheet.items[0].dose_unit == "MCG"


def test_parse_label_sheet_mc_does_not_leak_into_mcg():
    sheet = parse_label_sheet(["1 PLUSVENT 25 MCG COMPRIMIDO"])
    assert sheet.items[0].dose_unit == "MCG"
    assert sheet.items[0].dose_value == 25.0


# Con muestreo denso (0.4s), fecha y franja horaria aparecen a menudo pegadas
# sin espacio ("28/02/26ALMUEI", "28/02/26DESAYL") -- texto real reportado.
def test_parse_label_sheet_handles_date_and_slot_glued_together():
    sheet = parse_label_sheet(["sabado 28/02/26ALMUEI", "1 CARBIMAZOL 5 MG COMPRIMIDO"])
    assert sheet.header.dose_date == "28/02/26"
    assert sheet.header.dose_slot == "ALMUERZO"


def test_parse_label_sheet_canonicalizes_truncated_slot_variants():
    # Distintos frames de la MISMA bolsita real truncan la franja de forma
    # distinta; deben normalizar a la misma categoria para poder agruparse.
    for raw in ("DESAYUNO", "DESAYU", "DESAYL", "28/02/26DESAYL"):
        sheet = parse_label_sheet([f"domingo {raw}" if not raw[0].isdigit() else f"domingo {raw}"])
        assert sheet.header.dose_slot == "DESAYUNO", f"fallo con: {raw!r} -> {sheet.header.dose_slot!r}"


# Bugs reales encontrados con muestreo denso (0.4s): el dia de la semana se
# detectaba solo como "primera palabra de la linea", lo que fallaba cuando
# se pegaba a otro texto sin salto de linea ni espacio.
def test_parse_label_sheet_finds_weekday_merged_with_patient_name():
    sheet = parse_label_sheet([
        "51", "PELAYO PEINADO JOSEFA domingo 01/03/26 DESAYL EL PUERTO",
        "CALCIFEDIOL 0,266 MG CAPSULA",
    ])
    assert sheet.header.dose_weekday == "DOMINGO"
    assert sheet.header.dose_date == "01/03/26"
    assert sheet.header.dose_slot == "DESAYUNO"


def test_parse_label_sheet_finds_weekday_date_slot_all_glued_together():
    sheet = parse_label_sheet(["ELPUERTO PELAYO PEINADO JOSEFA", "sábado28/02/26CENA",
                                "1 CINITAPRIDA 1 MG COMPRIMIDO"])
    assert sheet.header.dose_weekday == "SABADO"
    assert sheet.header.dose_date == "28/02/26"
    assert sheet.header.dose_slot == "CENA"


def test_parse_label_sheet_weekday_canonicalizes_accent():
    sheet_a = parse_label_sheet(["sabado 28/02/26 CENA", "1 X 1 MG COMPRIMIDO"])
    sheet_b = parse_label_sheet(["sábado 28/02/26 CENA", "1 X 1 MG COMPRIMIDO"])
    assert sheet_a.header.dose_weekday == sheet_b.header.dose_weekday == "SABADO"


# Bugs reales encontrados al procesar los 108 videos completos (lote real,
# no solo los 2 de validacion): "MO" como truncado de "MG", y las franjas
# "Ayunas"/"Merienda" sin reconocer.
def test_parse_label_sheet_tolerates_mo_truncation_of_mg():
    sheet = parse_label_sheet(["OMEPRAZOL 30 MO CAFSULA"])
    assert len(sheet.items) == 1
    assert sheet.items[0].drug_name == "OMEPRAZOL"
    assert sheet.items[0].dose_value == 30.0
    assert sheet.items[0].dose_unit == "MG"


def test_parse_label_sheet_mo_does_not_leak_into_normal_mg():
    sheet = parse_label_sheet(["1 PARACETAMOL 650 MG COMPRIMIDO"])
    assert sheet.items[0].dose_unit == "MG"
    assert sheet.items[0].dose_value == 650.0


def test_parse_label_sheet_recognizes_ayunas_slot():
    sheet = parse_label_sheet(["domingo 01/03/26 Ayunas", "1 LEVOTIROXINA 100 MCG COMPRIMIDO"])
    assert sheet.header.dose_slot == "AYUNAS"


def test_parse_label_sheet_recognizes_merienda_slot():
    sheet = parse_label_sheet(["lunes 02/03/26 MERIENDA", "1 X 5 MG COMPRIMIDO"])
    assert sheet.header.dose_slot == "MERIENDA"


# Grabación vertical (10 vídeos de prueba, agosto 2026): con más resolución a
# lo largo de la tira, dos bolsitas completas caben en el mismo frame -- el
# parser de una sola bolsita las fusionaba bajo la cabecera de la primera.
REAL_TWO_POUCHES_ONE_FRAME = [
    "MORALES BARRIOS CONCEPCION", "SANTA ANA", "jueves 12/03/26 Ayunas",
    "1 LEVOTIROXINA 100 MICROGRAMOS", "1 OMEPRAZOL 20 MG CAPSULA",
    "FARMACIA MARACENA", "www.farmaciamaracena.com", "958 42 02 73",
    "MORALES BARRIOS CONCEPCION", "SANTA ANA", "miércoles 11/03/26 Ayunas",
    "1 LEVOTIROXINA 100 MICROGRAMOS", "1 OMEPRAZOL 20 MG CAPSULA",
]


def test_parse_label_sheets_splits_two_full_pouches_in_one_reading():
    sheets = parse_label_sheets(REAL_TWO_POUCHES_ONE_FRAME)
    assert len(sheets) == 2
    assert sheets[0].header.dose_weekday == "JUEVES"
    assert sheets[1].header.dose_weekday == "MIERCOLES"


def test_parse_label_sheets_does_not_duplicate_or_mix_items_between_pouches():
    sheets = parse_label_sheets(REAL_TWO_POUCHES_ONE_FRAME)
    assert len(sheets[0].items) == 2
    assert len(sheets[1].items) == 2
    # Antes del arreglo: 4 items bajo una sola cabecera (2 duplicados).
    assert {i.drug_name for i in sheets[0].items} == {"LEVOTIROXINA", "OMEPRAZOL"}
    assert {i.drug_name for i in sheets[1].items} == {"LEVOTIROXINA", "OMEPRAZOL"}


def test_parse_label_sheet_singular_still_returns_first_sheet_for_backward_compat():
    single = parse_label_sheet(REAL_TWO_POUCHES_ONE_FRAME)
    assert single.header.dose_weekday == "JUEVES"
    assert len(single.items) == 2


def test_parse_label_sheets_returns_no_items_on_unrelated_text():
    sheets = parse_label_sheets(["texto sin ningun formato reconocible"])
    assert all(not s.items for s in sheets)


def test_parse_label_sheets_generalizes_beyond_two_pouches():
    # Camara mas alejada -> pueden entrar mas de 2 bolsitas por lectura.
    # El corte no debe depender de un numero fijo.
    lines = [
        "MORALES BARRIOS CONCEPCION", "SANTA ANA", "jueves 12/03/26 Ayunas",
        "1 LEVOTIROXINA 100 MICROGRAMOS", "1 OMEPRAZOL 20 MG CAPSULA",
        "FARMACIA MARACENA", "958 42 02 73",
        "MORALES BARRIOS CONCEPCION", "SANTA ANA", "miércoles 11/03/26 Ayunas",
        "1 LEVOTIROXINA 100 MICROGRAMOS", "1 OMEPRAZOL 20 MG CAPSULA",
        "FARMACIA MARACENA", "958 42 02 73",
        "MORALES BARRIOS CONCEPCION", "SANTA ANA", "martes 10/03/26 Ayunas",
        "1 LEVOTIROXINA 100 MICROGRAMOS", "1 OMEPRAZOL 20 MG CAPSULA",
    ]
    sheets = parse_label_sheets(lines)
    assert len(sheets) == 3
    assert [s.header.dose_date for s in sheets] == ["12/03/26", "11/03/26", "10/03/26"]
    assert all(len(s.items) == 2 for s in sheets)


# Caso real (session_0002, agosto 2026): dos bolsitas en un mismo frame
# ("lunes 02/03/26 DESAYUNO" con 5 farmacos, "domingo 01/03/26 CENA" con 2).
# El OCR entrego "PENTOXIFILINA"/"EXTRACTO LIPIDICO DE SERENOA" fuera de
# orden -- despues de la cabecera de CENA en el texto -- perdiendolos de la
# lista de DESAYUNO. Ver docs/cuaderno_ingenieria_3.11.md.
REAL_SEAM_MISORDER_CASE = [
    ("PEDRO FRANCISCO MARTINEZ", 0.05),
    ("Tierra de Lorca", 0.07),
    ("lunes 02/03/26 DESAYUNO", 0.10),
    ("1 PARACETAMOL 650 MG COMPRIMIDO", 0.14),
    ("1 ACIDO ACETILSALICILICO 100 MG", 0.18),
    ("1 OMEPRAZOL 20 MG CAPSULA", 0.22),
    ("domingo 01/03/26 CENA", 0.48),
    ("1 PENTOXIFILINA 600 MG COMPRIMIDO", 0.26),
    ("1 EXTRACTO LIPIDICO DE SERENOA 320 MG", 0.30),
    ("1 PARACETAMOL 650 MG COMPRIMIDO", 0.52),
]


def test_parse_label_sheets_by_position_fixes_real_seam_misorder_case():
    sheets = parse_label_sheets_by_position(REAL_SEAM_MISORDER_CASE, seam_y_norm=0.45)
    desayuno = next(s for s in sheets if s.header.dose_slot == "DESAYUNO")
    cena = next(s for s in sheets if s.header.dose_slot == "CENA")
    assert len(desayuno.items) == 5
    assert {"PARACETAMOL", "ACIDO ACETILSALICILICO", "OMEPRAZOL",
            "PENTOXIFILINA", "EXTRACTO LIPIDICO DE SERENOA"} == {i.drug_name for i in desayuno.items}
    assert len(cena.items) == 1


def test_parse_label_sheets_by_position_without_seam_falls_back_to_order():
    sheets = parse_label_sheets_by_position(REAL_SEAM_MISORDER_CASE, seam_y_norm=None)
    old_sheets = parse_label_sheets([l for l, _ in REAL_SEAM_MISORDER_CASE])
    assert [s.header.dose_slot for s in sheets] == [s.header.dose_slot for s in old_sheets]
    for a, b in zip(sheets, old_sheets):
        assert [i.drug_name for i in a.items] == [i.drug_name for i in b.items]


def test_parse_label_sheets_by_position_single_pouch_no_seam_split_needed():
    # Costura detectada pero TODA la lectura cae de un mismo lado (no hay
    # segunda bolsita real en esta foto pese a la costura visible en algun
    # borde) -- debe comportarse igual que sin posicion.
    lines_with_y = [
        ("lunes 02/03/26 DESAYUNO", 0.10),
        ("1 PARACETAMOL 650 MG COMPRIMIDO", 0.14),
    ]
    sheets = parse_label_sheets_by_position(lines_with_y, seam_y_norm=0.90)
    assert len(sheets) == 1
    assert len(sheets[0].items) == 1


# Caso real (session_0002, agosto 2026, cuaderno 3.26): 3 bolsitas en una
# misma foto (MARTES CENA / LUNES DESAYUNO / DOMINGO CENA) -- la version
# de 1 sola costura solo separaba en 2 tramos, dejando el bug escondido
# dentro del tramo mas grande.
REAL_3_POUCH_CASE = [
    ("martes 03/03/26 CENA", 0.05),
    ("lunes 02/03/26 DESAYUNO", 0.35),
    ("1 PARACETAMOL 650 MG COMPRIMIDO", 0.40),
    ("1 ACIDO ACETILSALICILICO 100 MG", 0.44),
    ("1 OMEPRAZOL 20 MG CAPSULA", 0.48),
    ("domingo 01/03/26 CENA", 0.68),
    ("1 PENTOXIFILINA 600 MG COMPRIMIDO", 0.52),
    ("1 EXTRACTO LIPIDICO DE SERENOA 320 MG", 0.56),
    ("1 PARACETAMOL 650 MG COMPRIMIDO", 0.72),
]


def test_parse_label_sheets_by_multi_position_fixes_real_3_pouch_case():
    sheets = parse_label_sheets_by_multi_position(REAL_3_POUCH_CASE, seam_positions=[0.20, 0.62])
    assert len(sheets) == 3
    desayuno = next(s for s in sheets if s.header.dose_slot == "DESAYUNO")
    assert {"PARACETAMOL", "ACIDO ACETILSALICILICO", "OMEPRAZOL",
            "PENTOXIFILINA", "EXTRACTO LIPIDICO DE SERENOA"} == {i.drug_name for i in desayuno.items}
    cena_arriba = next(s for s in sheets if s.header.dose_weekday == "MARTES")
    assert cena_arriba.seam_side == "segment_0"
    assert desayuno.seam_side == "segment_1"
    cena_abajo = next(s for s in sheets if s.header.dose_weekday == "DOMINGO")
    assert cena_abajo.seam_side == "segment_2"
    assert len(cena_abajo.items) == 1


def test_parse_label_sheets_by_multi_position_single_seam_keeps_above_below_naming():
    # Con 1 sola costura (2 tramos), debe mantener el nombrado "above"/"below"
    # ya existente -- compatibilidad con el sombreado de la app de revisión.
    lines_with_y = [(l, y) for l, y in REAL_SEAM_MISORDER_CASE]
    sheets = parse_label_sheets_by_multi_position(lines_with_y, seam_positions=[0.45])
    sides = {s.header.dose_slot: s.seam_side for s in sheets}
    assert sides["DESAYUNO"] == "above"
    assert sides["CENA"] == "below"


def test_parse_label_sheets_by_multi_position_no_seams_behaves_like_plain_parse():
    lines_with_y = [(l, y) for l, y in REAL_SEAM_MISORDER_CASE]
    sheets = parse_label_sheets_by_multi_position(lines_with_y, seam_positions=[])
    old_sheets = parse_label_sheets([l for l, _ in lines_with_y])
    assert [s.header.dose_slot for s in sheets] == [s.header.dose_slot for s in old_sheets]


def test_parse_label_sheets_by_multi_position_empty_segment_falls_back():
    # Una costura que deja un tramo vacio (no hay de verdad una bolsita ahi)
    # debe caer al parseo normal, sin partir.
    lines_with_y = [
        ("lunes 02/03/26 DESAYUNO", 0.50),
        ("1 PARACETAMOL 650 MG COMPRIMIDO", 0.55),
    ]
    sheets = parse_label_sheets_by_multi_position(lines_with_y, seam_positions=[0.90])
    assert len(sheets) == 1
    assert sheets[0].seam_side is None


def test_parser_accepts_decimal_quantities():
    """Regresión (3.33): la cantidad puede ser decimal en la vida real
    (medias pastillas, 0,8...) -- confirma que la expresión regular ya lo
    soportaba, con coma y con punto decimal."""
    from medvision.ocr.parser import _parse_item_line

    items_comma = _parse_item_line("0,8 QUETIAPINA 25 MG COMPRIMIDO", 0)
    assert items_comma[0].quantity == 0.8

    items_dot = _parse_item_line("0.5 PARACETAMOL 650 MG COMPRIMIDO", 0)
    assert items_dot[0].quantity == 0.5

    items_int = _parse_item_line("1 OMEPRAZOL 20 MG CAPSULA", 0)
    assert items_int[0].quantity == 1.0


def test_find_footer_positions_and_group_real_pattern():
    """Nueva capacidad (3.36): localizar el pie de farmacia por texto para
    usarlo como punto de corte por CONTENIDO en vez de señal visual de
    costura -- pensado para generar una imagen por bolsita a partir de
    vídeos de validación nunca vistos por el sistema."""
    from medvision.ocr.parser import find_footer_positions, group_footer_positions

    lines_with_y = [
        ("PEDRO FRANCISCO MARTINEZ", 0.05),
        ("Tierra de Lorca", 0.07),
        ("lunes 02/03/26 DESAYUNO", 0.10),
        ("1 PARACETAMOL 650 MG COMPRIMIDO", 0.14),
        ("FARMACIA MARACENA", 0.30),
        ("www.farmaciamaracena.com", 0.31),
        ("958 42 02 73", 0.32),
        ("MARTIN RODRIGUEZ AGUSTIN", 0.50),
        ("domingo 22/02/26 DESAYUNO", 0.55),
        ("1 OMEPRAZOL 20 MG CAPSULA", 0.58),
        ("FARMACIA MARACENA", 0.70),
        ("958 42 02 73", 0.72),
    ]
    raw = find_footer_positions(lines_with_y)
    assert raw == [0.3, 0.31, 0.7]

    grouped = group_footer_positions(raw)
    assert len(grouped) == 2
    assert abs(grouped[0] - 0.305) < 1e-6
    assert abs(grouped[1] - 0.7) < 1e-6


def test_find_footer_positions_recognizes_ocr_variants():
    from medvision.ocr.parser import find_footer_positions

    lines_with_y = [
        ("FARMAOIA MARACENA", 0.2),   # variante real de OCR (G->O)
        ("otra linea cualquiera", 0.5),
        ("FARMAGIA MARACENA", 0.8),   # otra variante real (C->G)
    ]
    positions = find_footer_positions(lines_with_y)
    assert positions == [0.2, 0.8]


def test_group_footer_positions_empty_list():
    from medvision.ocr.parser import group_footer_positions
    assert group_footer_positions([]) == []


def test_find_complete_pouch_boundaries_discards_headerless_tail():
    """Regresión real (3.37): un fragmento de bolsita SIN su cabecera
    visible en este fotograma (la cola de la anterior, que ya quedó fuera
    del encuadre por arriba) no debe tratarse como una bolsita completa.
    Reproduce el patrón exacto de la primera foto real enviada por el
    usuario, donde el borde del fotograma se trataba (mal) como frontera."""
    from medvision.ocr.parser import find_complete_pouch_boundaries

    lines_with_y = [
        ("0.80 NEBIVOLOL 5 MG COMPRIMIDO", 0.02),
        ("1 CALCIO CARBONATO", 0.04),
        ("FARMACIA MARACENA", 0.08),
        ("www.farmaciamaracena.com", 0.085),
        ("958 42 02 73", 0.09),
        ("ZAMBRANA MILLAN MARIA", 0.50),
        ("TOMARES", 0.52),
        ("miercoles 25/02/26 CENA", 0.55),
        ("5 METAMIZOL 575 MG CAPSULA", 0.58),
        ("FARMACIA MARACENA", 0.92),
        ("958 42 02 73", 0.94),
    ]
    boundaries = find_complete_pouch_boundaries(lines_with_y)
    assert len(boundaries) == 1
    start, end, signature = boundaries[0]
    assert abs(start - 0.50) < 0.005
    assert abs(end - 0.94) < 0.005  # se extiende hasta la última línea del pie (958 42 02 73), no solo "FARMACIA"
    assert signature == "25/02/26|CENA"


def test_find_complete_pouch_boundaries_discards_footerless_head():
    """Segundo patrón real enviado por el usuario: el pie de la bolsita
    ANTERIOR visible arriba (sin su propia cabecera en este fotograma),
    seguido de una bolsita completa."""
    from medvision.ocr.parser import find_complete_pouch_boundaries

    lines_with_y = [
        ("FARMACIA MARACENA", 0.10),
        ("958 42 02 73", 0.12),
        ("GR473-F 1004411", 0.13),
        ("ZAMBRANA MILLAN MARIA", 0.45),
        ("TOMARES", 0.47),
        ("sabado 21/02/26 CENA", 0.50),
        ("5 METAMIZOL 575 MG CAPSULA", 0.53),
        ("FARMACIA MARACENA", 0.85),
    ]
    boundaries = find_complete_pouch_boundaries(lines_with_y)
    assert len(boundaries) == 1
    start, end, signature = boundaries[0]
    assert abs(start - 0.45) < 0.005
    assert abs(end - 0.85) < 0.005


def test_find_complete_pouch_boundaries_multiple_complete_pouches():
    """Con 2 bolsitas completas en el mismo fotograma, deben salir las 2,
    cada una con su propio inicio y fin, y firmas DISTINTAS."""
    from medvision.ocr.parser import find_complete_pouch_boundaries

    lines_with_y = [
        ("PACIENTE UNO", 0.05),
        ("lunes 02/03/26 DESAYUNO", 0.10),
        ("1 PARACETAMOL 650 MG", 0.13),
        ("FARMACIA MARACENA", 0.30),
        ("PACIENTE DOS", 0.55),
        ("martes 03/03/26 CENA", 0.60),
        ("1 OMEPRAZOL 20 MG", 0.63),
        ("FARMACIA MARACENA", 0.85),
    ]
    boundaries = find_complete_pouch_boundaries(lines_with_y)
    assert len(boundaries) == 2
    assert abs(boundaries[0][0] - 0.05) < 0.01 and abs(boundaries[0][1] - 0.30) < 0.005
    assert abs(boundaries[1][0] - 0.55) < 0.01 and abs(boundaries[1][1] - 0.85) < 0.005
    assert boundaries[0][2] != boundaries[1][2]  # firmas distintas para bolsitas distintas


def test_find_complete_pouch_boundaries_no_footer_at_all_gives_nothing():
    from medvision.ocr.parser import find_complete_pouch_boundaries

    lines_with_y = [("PACIENTE", 0.1), ("lunes 02/03/26 DESAYUNO", 0.15), ("1 PARACETAMOL 650 MG", 0.2)]
    assert find_complete_pouch_boundaries(lines_with_y) == []


def test_find_complete_pouch_boundaries_same_pouch_across_frames_gives_same_signature():
    """Regresión real (3.42): la MISMA bolsita real, leída en dos
    fotogramas distintos con variación REAL de OCR (espacio de más/menos,
    franja truncada de forma distinta -- "DESAYL" vs "DESAYU", visto en
    los propios ficheros del usuario, que hacía que la deduplicación
    dejara pasar la misma bolsita dos veces con la firma de texto crudo
    anterior), debe dar la MISMA firma canónica (fecha+franja)."""
    from medvision.ocr.parser import find_complete_pouch_boundaries

    frame_a = [
        ("ZAMBRANA MILLAN MARIA", 0.4865), ("TOMARES", 0.5138),
        ("jueves 26/02/26 DESAYL", 0.5339),
        ("S METANIZOL 575 MG CAPS", 0.5745),
        ("FARMACIA MARACENA", 0.8242),
    ]
    frame_b = [
        ("ZAMBRANA MILLAN MARIA", 0.4401), ("TOMARES", 0.4661),
        ("jueves 26/02/26DESAYU", 0.4878),  # sin espacio, franja truncada distinta
        ("S METANIZOL 575 MG CAPS", 0.5279),
        ("FARMACIA MARACENA", 0.7747),
    ]
    b1 = find_complete_pouch_boundaries(frame_a)
    b2 = find_complete_pouch_boundaries(frame_b)
    assert len(b1) == 1 and len(b2) == 1
    assert b1[0][2] == b2[0][2] == "26/02/26|DESAYUNO"


def test_find_complete_pouch_boundaries_different_slot_gives_different_signature():
    """Dos bolsitas del MISMO día pero franja distinta (desayuno vs cena)
    deben tener firmas DISTINTAS -- no deben deduplicarse entre sí."""
    from medvision.ocr.parser import find_complete_pouch_boundaries

    lines_with_y = [
        ("PACIENTE", 0.05), ("jueves 26/02/26 DESAYUNO", 0.10),
        ("1 PARACETAMOL 650 MG", 0.13), ("FARMACIA MARACENA", 0.30),
        ("PACIENTE", 0.55), ("jueves 26/02/26 CENA", 0.60),
        ("1 OMEPRAZOL 20 MG", 0.63), ("FARMACIA MARACENA", 0.85),
    ]
    boundaries = find_complete_pouch_boundaries(lines_with_y)
    assert len(boundaries) == 2
    assert boundaries[0][2] != boundaries[1][2]


def test_find_complete_pouch_boundaries_extends_to_full_footer_block():
    """Regresión real (3.44): el pie de página real tiene varias líneas
    (web, teléfono, código) que no llevan la palabra clave "FARMACIA" y
    por tanto no se contaban -- el fin se quedaba en la primera línea del
    pie, dejando fuera el resto del bloque (y el margen en píxeles nunca
    era suficiente para compensarlo, por mucho que se subiera). Ahora se
    extiende hasta la última línea de texto cercana."""
    from medvision.ocr.parser import find_complete_pouch_boundaries

    lines_with_y = [
        ("ZAMBRANA MILLAN MARIA", 0.4865), ("TOMARES", 0.5138),
        ("jueves 26/02/26 DESAYUNO", 0.5339),
        ("S METAMIZOL 575 MG CAPS", 0.5745),
        ("FARMACIA MARACENA", 0.8242),
        ("www.farmaciamaracena.com", 0.8451),
        ("958 42 02 73", 0.8708),
        ("GR473-F 1001411", 0.8919),
    ]
    boundaries = find_complete_pouch_boundaries(lines_with_y)
    assert len(boundaries) == 1
    assert abs(boundaries[0][1] - 0.8919) < 0.001


def test_find_complete_pouch_boundaries_footer_extension_does_not_bleed_into_next_pouch():
    """La extensión del pie no debe colarse en el nombre de la SIGUIENTE
    bolsita, aunque esté cerca (dentro del hueco de tolerancia)."""
    from medvision.ocr.parser import find_complete_pouch_boundaries

    lines_with_y = [
        ("ZAMBRANA MILLAN MARIA", 0.4865), ("TOMARES", 0.5138),
        ("jueves 26/02/26 DESAYUNO", 0.5339),
        ("S METAMIZOL 575 MG CAPS", 0.5745),
        ("FARMACIA MARACENA", 0.8242),
        ("www.farmaciamaracena.com", 0.8451),
        ("958 42 02 73", 0.8708),
        ("GR473-F 1001411", 0.8919),
        ("MARTIN RODRIGUEZ AGUSTIN", 0.95),  # nombre de la SIGUIENTE bolsita, cerca
        ("viernes 27/02/26 CENA", 0.98),
    ]
    boundaries = find_complete_pouch_boundaries(lines_with_y)
    assert abs(boundaries[0][1] - 0.8919) < 0.001, "no debe colarse en el nombre de la bolsita siguiente"


def test_find_footer_positions_recognizes_farma_short_variant():
    """Regresión real (3.47): con OCR muy degradado (vídeo con más
    desenfoque de movimiento que el habitual), 'FARMACIA' a veces se lee
    tan mal que ni las variantes de 8 letras ya conocidas lo reconocen,
    pero el principio 'FARMA' se mantiene legible en más casos."""
    from medvision.ocr.parser import find_footer_positions

    lines_with_y = [
        ("FARMALIAMARALSIN", 0.2),  # caso real visto en un vídeo de validación
        ("FARMA", 0.5),             # caso real, pie muy degradado
        ("FARMSACARA", 0.8),        # caso real que SIGUE sin reconocerse (la S rompe FARMA)
    ]
    positions = find_footer_positions(lines_with_y)
    assert positions == [0.2, 0.5]
