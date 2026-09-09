from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PillGroup:
    """Un grupo de observaciones del lado pastilla que, con razonable
    confianza, corresponden a la MISMA bolsita física — separado del
    siguiente grupo por una zona de costura detectada, no por parecido
    visual (ver docs/cuaderno_ingenieria_2.4.md / 2.5.md)."""
    bag_ids: list[int]
    representative_bag_id: int
    representative_crop_path: str | None
    center_norm: float
    best_quality: float
    in_transition: bool = False


def _mark_transition_zones(
    observations: list[dict[str, Any]],
    prominence_threshold: float = 3.0,
    max_bridge_frames: int = 15,
) -> list[bool]:
    """Marca cada observación como perteneciente o no a una zona de
    transición (costura visible), tolerando huecos cortos.

    Con datos reales, la costura no aparece limpia en un único frame — un
    paneo a pulso hace que "parpadee" (visible, no visible, visible) a lo
    largo de varios frames seguidos mientras la cámara se demora sobre el
    pliegue. Un frame de baja prominencia rodeado de frames de alta
    prominencia (dentro de `max_bridge_frames`, en número de frame) se trata
    como parte de la misma zona de transición, no como una zona estable.
    """
    elevated = [float(o.get("seam_prominence") or 0.0) >= prominence_threshold for o in observations]
    frame_indices = [int(o["frame_index"]) for o in observations]

    bridged = list(elevated)
    for i in range(1, len(bridged) - 1):
        if bridged[i]:
            continue
        prev_elevated_idx = next((j for j in range(i - 1, -1, -1) if elevated[j]), None)
        next_elevated_idx = next((j for j in range(i + 1, len(elevated)) if elevated[j]), None)
        if prev_elevated_idx is None or next_elevated_idx is None:
            continue
        gap_before = frame_indices[i] - frame_indices[prev_elevated_idx]
        gap_after = frame_indices[next_elevated_idx] - frame_indices[i]
        if gap_before <= max_bridge_frames and gap_after <= max_bridge_frames:
            bridged[i] = True
    return bridged


def group_pill_bags_by_seam(
    observations: list[dict[str, Any]],
    prominence_threshold: float = 3.0,
    max_bridge_frames: int = 15,
) -> list[PillGroup]:
    """Agrupa observaciones del lado pastilla en bolsitas, usando zonas
    estables (sin costura) como bolsitas limpias, y zonas de transición
    (costura visible, con parpadeo) como grupos marcados `in_transition`.

    Deliberadamente NO se intenta adivinar a qué bolsita pertenece una
    observación en zona de transición — se deja como su propio grupo
    marcado, para revisión humana, en vez de arriesgarse a asignarla mal.
    `observations` debe venir ordenada por frame_index.
    """
    if not observations:
        return []

    in_transition = _mark_transition_zones(observations, prominence_threshold, max_bridge_frames)

    groups: list[PillGroup] = []
    current: list[dict[str, Any]] = []
    current_transition: bool | None = None

    def _flush(members: list[dict[str, Any]], transition: bool) -> None:
        if not members:
            return
        representative = max(members, key=lambda o: float(o.get("quality_score") or 0.0))
        center = sum(float(m["center_norm"]) for m in members) / len(members)
        quality = max(float(m.get("quality_score") or 0.0) for m in members)
        groups.append(PillGroup(
            bag_ids=[m["bag_id"] for m in members],
            representative_bag_id=representative["bag_id"],
            representative_crop_path=representative.get("crop_path"),
            center_norm=center,
            best_quality=quality,
            in_transition=transition,
        ))

    for obs, is_transition in zip(observations, in_transition):
        if current_transition is None:
            current_transition = is_transition
        if is_transition == current_transition:
            current.append(obs)
        else:
            _flush(current, current_transition)
            current = [obs]
            current_transition = is_transition
    _flush(current, bool(current_transition))

    return groups
