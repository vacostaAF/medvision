from medvision.pairing.seam_grouping import group_pill_bags_by_seam

# Prominencia real calculada por detect_seam_band() contra las 8 fotos reales
# de MVI_2713 (frames 80-190) — ver docs/cuaderno_ingenieria_2.4.md y 2.5.md.
REAL_SEAM_SEQUENCE = [
    {"bag_id": 1, "frame_index": 80,  "seam_prominence": 14.44, "quality_score": 0.279, "center_norm": 0.1, "crop_path": "f80.jpg"},
    {"bag_id": 2, "frame_index": 90,  "seam_prominence": 4.82,  "quality_score": 0.283, "center_norm": 0.2, "crop_path": "f90.jpg"},
    {"bag_id": 3, "frame_index": 100, "seam_prominence": 1.88,  "quality_score": 0.284, "center_norm": 0.3, "crop_path": "f100.jpg"},
    {"bag_id": 4, "frame_index": 110, "seam_prominence": 9.74,  "quality_score": 0.283, "center_norm": 0.4, "crop_path": "f110.jpg"},
    {"bag_id": 5, "frame_index": 120, "seam_prominence": 8.41,  "quality_score": 0.281, "center_norm": 0.5, "crop_path": "f120.jpg"},
    {"bag_id": 6, "frame_index": 130, "seam_prominence": 2.41,  "quality_score": 0.275, "center_norm": 0.6, "crop_path": "f130.jpg"},
    {"bag_id": 7, "frame_index": 140, "seam_prominence": 2.49,  "quality_score": 0.273, "center_norm": 0.7, "crop_path": "f140.jpg"},
    {"bag_id": 8, "frame_index": 190, "seam_prominence": 12.54, "quality_score": 0.276, "center_norm": 0.9, "crop_path": "f190.jpg"},
]


def test_group_pill_bags_by_seam_bridges_short_gap_inside_transition_zone():
    # f100 (prominencia 1.88, por debajo del umbral) esta rodeada por frames
    # de costura alta (f90=4.8, f110=9.7) a solo 10 frames de distancia:
    # debe tratarse como parte de la MISMA zona de transicion, no como una
    # zona estable aparte.
    groups = group_pill_bags_by_seam(REAL_SEAM_SEQUENCE)
    assert len(groups) == 3
    assert groups[0].bag_ids == [1, 2, 3, 4, 5]
    assert groups[0].in_transition is True


def test_group_pill_bags_by_seam_keeps_stable_zone_separate():
    groups = group_pill_bags_by_seam(REAL_SEAM_SEQUENCE)
    stable = groups[1]
    assert stable.bag_ids == [6, 7]
    assert stable.in_transition is False


def test_group_pill_bags_by_seam_marks_trailing_transition_alone():
    groups = group_pill_bags_by_seam(REAL_SEAM_SEQUENCE)
    last = groups[2]
    assert last.bag_ids == [8]
    assert last.in_transition is True


def test_group_pill_bags_by_seam_does_not_bridge_across_large_frame_gap():
    # Si el hueco entre observaciones es grande (deteccion fallida durante
    # varios segundos), no debe puentearse aunque ambos lados tengan costura.
    observations = [
        {"bag_id": 1, "frame_index": 0, "seam_prominence": 10.0,
         "quality_score": 0.3, "center_norm": 0.1, "crop_path": "a.jpg"},
        {"bag_id": 2, "frame_index": 500, "seam_prominence": 1.0,
         "quality_score": 0.3, "center_norm": 0.5, "crop_path": "b.jpg"},
        {"bag_id": 3, "frame_index": 1000, "seam_prominence": 10.0,
         "quality_score": 0.3, "center_norm": 0.9, "crop_path": "c.jpg"},
    ]
    groups = group_pill_bags_by_seam(observations, max_bridge_frames=15)
    assert len(groups) == 3
    assert groups[1].in_transition is False


def test_group_pill_bags_by_seam_empty_input():
    assert group_pill_bags_by_seam([]) == []
