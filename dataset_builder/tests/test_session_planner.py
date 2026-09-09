import os
import time

from medvision.acquisition.session_planner import plan_sessions, sessions_to_config_dict


def _touch(path, mtime_offset_seconds: float):
    path.write_bytes(b"")
    base = time.time()
    os.utime(path, (base + mtime_offset_seconds, base + mtime_offset_seconds))
    return path


def test_plan_sessions_pairs_consecutive_videos_by_real_capture_order(tmp_path):
    # Nombres deliberadamente "al revés" del orden real, para comprobar que
    # el orden lo decide el tiempo de captura, no el nombre de fichero.
    label1 = _touch(tmp_path / "MVI_9999.MOV", 32)
    pill1 = _touch(tmp_path / "MVI_0001.MOV", 0)

    sessions = plan_sessions([label1, pill1], max_gap_seconds=120.0)
    assert len(sessions) == 1
    assert sessions[0].pill_video == "MVI_0001"
    assert sessions[0].label_video == "MVI_9999"
    assert sessions[0].status == "ok"


def test_plan_sessions_pairs_multiple_sessions_in_order(tmp_path):
    p1 = _touch(tmp_path / "v1.MOV", 0)
    l1 = _touch(tmp_path / "v2.MOV", 30)
    p2 = _touch(tmp_path / "v3.MOV", 200)
    l2 = _touch(tmp_path / "v4.MOV", 232)

    sessions = plan_sessions([p1, l1, p2, l2], max_gap_seconds=120.0)
    assert len(sessions) == 2
    assert (sessions[0].pill_video, sessions[0].label_video) == ("v1", "v2")
    assert (sessions[1].pill_video, sessions[1].label_video) == ("v3", "v4")
    assert all(s.status == "ok" for s in sessions)


def test_plan_sessions_flags_large_gap_for_review(tmp_path):
    pill = _touch(tmp_path / "a.MOV", 0)
    label = _touch(tmp_path / "b.MOV", 500)  # hueco mayor al esperado
    sessions = plan_sessions([pill, label], max_gap_seconds=120.0)
    assert sessions[0].status == "needs_review"
    assert "hueco" in sessions[0].reason


def test_plan_sessions_flags_odd_video_count(tmp_path):
    p1 = _touch(tmp_path / "a.MOV", 0)
    l1 = _touch(tmp_path / "b.MOV", 30)
    orphan = _touch(tmp_path / "c.MOV", 300)

    sessions = plan_sessions([p1, l1, orphan], max_gap_seconds=120.0)
    assert len(sessions) == 2
    assert sessions[0].status == "ok"
    assert sessions[1].label_video == ""
    assert sessions[1].status == "needs_review"
    assert "impar" in sessions[1].reason


def test_sessions_to_config_dict_matches_builder_expected_shape(tmp_path):
    pill = _touch(tmp_path / "a.MOV", 0)
    label = _touch(tmp_path / "b.MOV", 30)
    sessions = plan_sessions([pill, label])
    cfg = sessions_to_config_dict(sessions)
    assert cfg["video_sides"] == {"a": "pill_side", "b": "label_side"}
    assert cfg["video_pairs"] == [
        {"pair_key": "session_0000", "pill_video": "a", "label_video": "b", "direction": "direct"}
    ]


def test_sessions_to_config_dict_skips_orphan_without_pair(tmp_path):
    p1 = _touch(tmp_path / "a.MOV", 0)
    l1 = _touch(tmp_path / "b.MOV", 30)
    orphan = _touch(tmp_path / "c.MOV", 300)
    sessions = plan_sessions([p1, l1, orphan])
    cfg = sessions_to_config_dict(sessions)
    # el huerfano se marca como pill_side (para no perderlo de vista) pero
    # no genera una entrada en video_pairs, ya que no tiene con qué emparejar.
    assert cfg["video_sides"]["c"] == "pill_side"
    assert len(cfg["video_pairs"]) == 1
