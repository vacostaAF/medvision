from medvision.pairing.header_grouping import (
    group_label_bags_by_header,
    header_signature,
    merge_label_items,
)


def test_header_signature_requires_date_and_slot():
    assert header_signature({"dose_weekday": "domingo", "dose_date": "01/03/26", "dose_slot": "DESAYUNO"})
    assert header_signature({"dose_date": "01/03/26", "dose_slot": "DESAYUNO"})  # sin dia: sigue formando firma
    assert header_signature({"dose_weekday": "domingo", "dose_date": "01/03/26"}) is None  # sin franja
    assert header_signature({"dose_weekday": "domingo", "dose_slot": "DESAYUNO"}) is None  # sin fecha
    assert header_signature(None) is None
    assert header_signature({}) is None


def test_header_signature_ignores_weekday_mismatch_from_ocr_error():
    # Cambio 3.3: el dia de la semana es redundante con la fecha (un
    # 12/03/26 siempre es jueves) y no forma parte de la firma. Un error de
    # OCR en el dia ("jueves" leido como otra cosa) no debe bloquear una
    # coincidencia que fecha+franja ya identifican sin ambiguedad.
    sig_a = header_signature({"dose_weekday": "jueves", "dose_date": "12/03/26", "dose_slot": "AYUNAS"})
    sig_b = header_signature({"dose_weekday": "juebes", "dose_date": "12/03/26", "dose_slot": "AYUNAS"})
    sig_c = header_signature({"dose_date": "12/03/26", "dose_slot": "AYUNAS"})  # dia ausente del todo
    assert sig_a == sig_b == sig_c


def test_header_signature_ignores_patient_name():
    # El paciente es constante a lo largo de toda la tira; no debe formar
    # parte de la firma de identidad de una bolsita concreta.
    sig_a = header_signature({"patient_name": "A", "dose_weekday": "lunes",
                               "dose_date": "01/01/26", "dose_slot": "CENA"})
    sig_b = header_signature({"patient_name": "B", "dose_weekday": "lunes",
                               "dose_date": "01/01/26", "dose_slot": "CENA"})
    assert sig_a == sig_b


def test_merge_label_items_deduplicates_by_drug_name():
    merged = merge_label_items([
        [{"drug_name": "CALCIFEDIOL", "dose_value": 0.266, "dose_unit": "MG"}],
        [{"drug_name": "calcifediol", "dose_value": 0.266, "dose_unit": "MG"},
         {"drug_name": "BISOPROLOL", "dose_value": 5.0, "dose_unit": "MG"}],
    ])
    assert len(merged) == 2
    assert {m["drug_name"] for m in merged} == {"CALCIFEDIOL", "BISOPROLOL"}


def test_merge_label_items_prefers_the_observation_that_has_a_dose_value():
    merged = merge_label_items([
        [{"drug_name": "LISINOPRIL/HCT", "dose_value": None, "dose_unit": "MG"}],
        [{"drug_name": "LISINOPRIL/HCT", "dose_value": 20.0, "dose_unit": "MG"}],
    ])
    assert merged[0]["dose_value"] == 20.0


# Caso real que motivó este módulo: el tracker visual (bags/tracker.py) juntó
# 3 bolsitas reales de contenido distinto en un solo track (track0001) porque
# todas las bolsitas se parecen visualmente entre sí. Agrupar por cabecera en
# vez de por track visual debe mantenerlas separadas.
REAL_TRACKER_CONFUSION_CASE = [
    {
        "bag_id": 2, "ocr_result_id": 100, "center_norm": 0.1, "quality_score": 0.29,
        "mean_confidence": 99.76,
        "header": {"patient_name": "PELAYO PEINADO JOSEFA", "patient_location": None,
                    "dose_weekday": "domingo", "dose_date": "01/03/26", "dose_slot": "DESAYL"},
        "items": [
            {"drug_name": "CALCIFEDIOL", "dose_value": 0.266, "dose_unit": "MG"},
            {"drug_name": "BISOPROLOL", "dose_value": 5.0, "dose_unit": "MG"},
            {"drug_name": "CINITAPRIDA", "dose_value": 1.0, "dose_unit": "MG"},
        ],
    },
    {
        "bag_id": 5, "ocr_result_id": 101, "center_norm": 0.5, "quality_score": 0.28,
        "mean_confidence": 96.85,
        "header": {"patient_name": "PELAYO PEINADO JOSEFA", "patient_location": "EL PUERTO",
                    "dose_weekday": "sábado", "dose_date": "28/02/26", "dose_slot": "CENA"},
        "items": [
            {"drug_name": "CINITAPRIDA", "dose_value": 1.0, "dose_unit": "MG"},
            {"drug_name": "SIMVASTATINA", "dose_value": 40.0, "dose_unit": "MG"},
            {"drug_name": "RISPERIDONA AUROBINDO", "dose_value": 1.0, "dose_unit": "MCG"},
            {"drug_name": "PLUSVENT", "dose_value": 25.0, "dose_unit": "MCG"},
        ],
    },
    {
        "bag_id": 8, "ocr_result_id": 102, "center_norm": 0.9, "quality_score": 0.13,
        "mean_confidence": 87.29, "header": None, "items": [],
    },
]


def test_group_label_bags_by_header_keeps_distinct_pouches_separate():
    groups = group_label_bags_by_header(REAL_TRACKER_CONFUSION_CASE)
    assert len(groups) == 3  # antes: 1 solo track visual, mezclando 2 bolsitas reales

    domingo = next(g for g in groups if g.signature and g.signature[0] == "01/03/26")
    sabado = next(g for g in groups if g.signature and g.signature[0] == "28/02/26")

    assert {i["drug_name"] for i in domingo.merged_items} == {"CALCIFEDIOL", "BISOPROLOL", "CINITAPRIDA"}
    assert {i["drug_name"] for i in sabado.merged_items} == {
        "CINITAPRIDA", "SIMVASTATINA", "RISPERIDONA AUROBINDO", "PLUSVENT",
    }
    # Los farmacos de una bolsita no se han colado en la otra.
    assert "SIMVASTATINA" not in {i["drug_name"] for i in domingo.merged_items}
    assert "CALCIFEDIOL" not in {i["drug_name"] for i in sabado.merged_items}


def test_group_label_bags_by_header_fuses_multiple_views_of_same_pouch():
    same_header = {"patient_name": "X", "dose_weekday": "domingo",
                    "dose_date": "01/03/26", "dose_slot": "DESAYUNO"}
    observations = [
        {"bag_id": 10, "ocr_result_id": 200, "center_norm": 0.2, "quality_score": 0.3,
         "mean_confidence": 98.0, "header": same_header,
         "items": [{"drug_name": "CALCIFEDIOL", "dose_value": 0.266, "dose_unit": "MG"},
                    {"drug_name": "BISOPROLOL", "dose_value": 5.0, "dose_unit": "MG"}]},
        {"bag_id": 11, "ocr_result_id": 201, "center_norm": 0.25, "quality_score": 0.31,
         "mean_confidence": 97.0, "header": same_header,
         "items": [{"drug_name": "AMLODIPINO", "dose_value": 5.0, "dose_unit": "MG"},
                    {"drug_name": "ONY-TEC", "dose_value": 80.0, "dose_unit": "MG"}]},
    ]
    groups = group_label_bags_by_header(observations)
    assert len(groups) == 1
    assert {i["drug_name"] for i in groups[0].merged_items} == {
        "CALCIFEDIOL", "BISOPROLOL", "AMLODIPINO", "ONY-TEC",
    }
    assert set(groups[0].bag_ids) == {10, 11}


def test_group_label_bags_by_header_never_groups_missing_headers_together():
    # Dos observaciones SIN cabecera reconocida no deben fusionarse entre sí
    # solo por casualidad: sin certeza de identidad, cada una es su propio grupo.
    observations = [
        {"bag_id": 20, "ocr_result_id": 300, "center_norm": 0.1, "quality_score": 0.2,
         "mean_confidence": 50.0, "header": None, "items": []},
        {"bag_id": 21, "ocr_result_id": 301, "center_norm": 0.9, "quality_score": 0.2,
         "mean_confidence": 50.0, "header": None, "items": []},
    ]
    groups = group_label_bags_by_header(observations)
    assert len(groups) == 2


def test_header_signature_normalizes_accents_in_slot():
    # El dia ya no forma parte de la firma (3.3); el acento se sigue
    # normalizando en la franja, por si acaso llega con tilde.
    sig_a = header_signature({"dose_date": "28/02/26", "dose_slot": "MEDIODIA"})
    sig_b = header_signature({"dose_date": "28/02/26", "dose_slot": "MEDIODÍA"})
    assert sig_a == sig_b
