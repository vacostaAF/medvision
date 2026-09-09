from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PairResult:
    pair_key: str
    pill_track_key: str | None
    label_track_key: str | None
    pill_best_bag_id: int | None
    label_best_bag_id: int | None
    order_index: int
    match_score: float
    status: str


def _ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order tracks by the centre of their best observation in the strip."""
    return sorted(rows, key=lambda r: (float(r.get("center_norm", 0.0)), str(r["track_key"])))


def pair_tracks(
    pill_tracks: list[dict[str, Any]],
    label_tracks: list[dict[str, Any]],
    pair_key: str,
    direction: str = "direct",
) -> list[PairResult]:
    """Pair two recordings of the same strip using ordinal position.

    This is deliberately conservative: it creates a one-to-one match only while both
    sequences contain a track at the same ordinal position. Extra tracks are retained
    as unmatched and must be reviewed. `direction=reverse` handles a strip filmed from
    the opposite end.
    """
    pills = _ordered(pill_tracks)
    labels = _ordered(label_tracks)
    if direction == "reverse":
        labels = list(reversed(labels))
    elif direction != "direct":
        raise ValueError("direction must be 'direct' or 'reverse'")

    n = max(len(pills), len(labels))
    denom = max(1, max(len(pills), len(labels)) - 1)
    count_balance = min(len(pills), len(labels)) / max(1, max(len(pills), len(labels)))
    results: list[PairResult] = []
    for i in range(n):
        p = pills[i] if i < len(pills) else None
        l = labels[i] if i < len(labels) else None
        if p and l:
            p_rank = i / denom
            l_rank = i / denom
            ordinal_similarity = 1.0 - abs(p_rank - l_rank)
            quality = (float(p.get("best_quality", 0.0)) + float(l.get("best_quality", 0.0))) / 2.0
            score = max(0.0, min(1.0, 0.55 * ordinal_similarity + 0.25 * count_balance + 0.20 * quality))
            status = "paired" if score >= 0.70 else "review"
        else:
            score = 0.0
            status = "unmatched_pill" if p else "unmatched_label"
        results.append(PairResult(
            pair_key=pair_key,
            pill_track_key=str(p["track_key"]) if p else None,
            label_track_key=str(l["track_key"]) if l else None,
            pill_best_bag_id=int(p["best_bag_id"]) if p else None,
            label_best_bag_id=int(l["best_bag_id"]) if l else None,
            order_index=i,
            match_score=round(score, 6),
            status=status,
        ))
    return results
