from medvision.pairing.track_pairer import pair_tracks


def _row(k, bag, y):
    return {"track_key": k, "best_bag_id": bag, "center_norm": y, "best_quality": 0.9}


def test_direct_pairing_and_unmatched():
    out = pair_tracks([_row("p1", 1, .2), _row("p2", 2, .8)], [_row("l1", 3, .2)], "x")
    assert out[0].pill_track_key == "p1"
    assert out[0].label_track_key == "l1"
    assert out[1].status == "unmatched_pill"


def test_reverse_pairing():
    out = pair_tracks([_row("p1", 1, .2), _row("p2", 2, .8)], [_row("l1", 3, .2), _row("l2", 4, .8)], "x", "reverse")
    assert out[0].label_track_key == "l2"
