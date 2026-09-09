import numpy as np
from medvision.bags.tracker import BagObservation, BagTracker


def obs(bag_id: int, frame: int, y: int, value: int) -> BagObservation:
    crop = np.full((160, 120, 3), value, dtype=np.uint8)
    return BagObservation(
        bag_id=bag_id, frame_id=frame, frame_index=frame,
        timestamp_seconds=float(frame), bag_index_in_frame=0,
        crop=crop, y1=y, y2=y+160, frame_height=1000,
        quality_score=0.7 + bag_id * 0.01, segment_confidence=0.8,
    )


def test_tracker_links_similar_observations():
    tracker = BagTracker("video", "pill_side", min_match_score=0.4)
    a = tracker.update([obs(1, 1, 100, 80)])[0]
    b = tracker.update([obs(2, 2, 120, 82)])[0]
    assert a.track_key == b.track_key
    rows, best = tracker.finalize()
    assert rows[0]["observation_count"] == 2
    assert sum(best.values()) == 1
