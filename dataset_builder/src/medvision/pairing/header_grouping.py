from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass, field
from typing import Any


def _strip_accents(text: str) -> str:
    """Quita tildes/diacríticos para comparar de forma robusta ('sábado' ==
    'sabado'). El mismo día real se ha visto leído por OCR con y sin tilde
    según el frame; sin esto, header_signature() los trataría como
    bolsitas distintas."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def header_signature(header: dict[str, Any] | None) -> tuple[str, str] | None:
    """Firma de identidad de una bolsita a partir de su cabecera OCR.

    Se exige fecha + franja horaria completos para formar una firma. Si
    falta cualquiera de los dos, se devuelve None a propósito: es más
    seguro tratar esa observación como su propia bolsita aislada que
    arriesgarse a agruparla mal por una cabecera incompleta.

    El día de la semana NO forma parte de la firma (cambio 3.3): es
    matemáticamente redundante con la fecha (un 12/03/26 siempre es
    jueves), así que no aporta seguridad real frente a agrupar mal — solo
    añadía un tercer punto de fallo por desenfoque de OCR (visto con datos
    reales: "AMANTADINA"/"AMANT INA", el mismo tipo de error de lectura que
    también afecta al día de la semana). Dentro de un mismo vídeo de un
    mismo paciente, fecha+franja ya identifican la bolsita sin ambigüedad —
    no puede haber dos bolsitas reales con la misma fecha y franja.

    Tampoco se usa patient_name: es constante a lo largo de toda la tira
    (mismo paciente) y no aporta poder de discriminación entre bolsitas
    distintas del mismo paciente.
    """
    if not header:
        return None
    date = header.get("dose_date")
    slot = header.get("dose_slot")
    if not (date and slot):
        return None
    return (
        str(date).strip(),
        _strip_accents(str(slot).strip().upper()),
    )


def _name_similarity(a: str, b: str) -> float:
    """Similitud 0-1 entre dos nombres de fármaco, ignorando espacios (para
    que 'BI ERIDENO' compare bien contra 'BIPERIDENO')."""
    return difflib.SequenceMatcher(None, a.replace(" ", ""), b.replace(" ", "")).ratio()


def _pick_cluster_representative(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    """De un grupo de lecturas que ya se consideran el mismo fármaco (ver
    merge_label_items), elige la más representativa: la que tiene mayor
    similitud media con el resto del grupo (el "centro" del grupo, no un
    caso raro con ruido extra pegado — p.ej. "JUEVES BIERIDENO" con el día
    de la semana colado), con empate a favor de tener dosis reconocida.
    """
    if len(cluster) == 1:
        return cluster[0]
    names = [(it.get("drug_name") or "").upper() for it in cluster]

    def avg_similarity(idx: int) -> float:
        return sum(_name_similarity(names[idx], other) for other in names) / len(names)

    best_idx = max(
        range(len(cluster)),
        key=lambda i: (round(avg_similarity(i), 3), cluster[i].get("dose_value") is not None, -len(names[i])),
    )
    return cluster[best_idx]


def merge_label_items(
    item_lists: list[list[dict[str, Any]]], similarity_threshold: float = 0.72
) -> list[dict[str, Any]]:
    """Fusiona listas de fármacos de varias observaciones de la MISMA
    bolsita real (ya agrupadas por header_signature idéntica).

    No deduplica por texto exacto: con muchas observaciones de la misma
    bolsita real, el mismo fármaco puede leerse con distinto ruido en cada
    frame ("BIPERIDENO", "BI ERIDENO", "EIPERIDENO"...) — visto con datos
    reales, un solo fármaco real acabó apareciendo como 9 entradas
    "distintas" en la lista fusionada (ver docs/cuaderno_ingenieria_3.8.md).
    Se agrupan por similitud de texto (ignorando espacios) con un umbral
    conservador: prioriza no fusionar fármacos genuinamente distintos por
    encima de limpiar del todo el ruido — mejor dejar algún duplicado
    residual que fusionar dos medicamentos reales distintos.

    Solo debe llamarse dentro de un grupo cuya identidad ya está confirmada
    por cabecera — nunca para combinar bolsitas de las que no hay certeza de
    que sean la misma.
    """
    all_items = [it for items in item_lists for it in items if (it.get("drug_name") or "").strip()]
    clusters: list[list[dict[str, Any]]] = []
    for it in all_items:
        name = (it.get("drug_name") or "").upper()
        placed = False
        for cluster in clusters:
            rep_name = (cluster[0].get("drug_name") or "").upper()
            if _name_similarity(name, rep_name) >= similarity_threshold:
                cluster.append(it)
                placed = True
                break
        if not placed:
            clusters.append([it])

    result = []
    for i, cluster in enumerate(clusters):
        best = _pick_cluster_representative(cluster)
        # Si algún miembro del grupo sí reconoció la dosis y el elegido no,
        # nos quedamos con esa dosis en vez de perderla.
        if best.get("dose_value") is None:
            with_dose = next((m for m in cluster if m.get("dose_value") is not None), None)
            if with_dose is not None:
                best = with_dose
        item = dict(best)
        item["line_index"] = i
        result.append(item)
    return result


@dataclass
class LabelGroup:
    """Una bolsita real, posiblemente reconstruida a partir de varias
    observaciones (frames) que comparten cabecera."""
    signature: tuple[str, str] | None
    bag_ids: list[int]
    representative_bag_id: int
    representative_ocr_result_id: int
    representative_crop_path: str | None
    center_norm: float
    best_quality: float
    merged_items: list[dict[str, Any]] = field(default_factory=list)
    header: dict[str, Any] | None = None


def group_label_bags_by_header(observations: list[dict[str, Any]]) -> list[LabelGroup]:
    """Agrupa observaciones de bolsa (lado etiqueta) por identidad de cabecera.

    Cada entrada de `observations` debe tener: bag_id, ocr_result_id,
    header (dict o None), items (list[dict]), center_norm (float),
    quality_score (float), mean_confidence (float).

    Observaciones sin firma de cabecera (header_signature -> None) se tratan
    como su propio grupo de un solo elemento — nunca se agrupan a ciegas.
    """
    groups_by_sig: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    singleton_groups: list[list[dict[str, Any]]] = []

    for obs in observations:
        sig = header_signature(obs.get("header"))
        if sig is None:
            singleton_groups.append([obs])
        else:
            groups_by_sig.setdefault(sig, []).append(obs)

    result: list[LabelGroup] = []

    for sig, members in groups_by_sig.items():
        # Representante: el que más fármacos reconoció de por sí antes de fusionar
        # (empate roto por confianza media del OCR). Solo decide qué fila de
        # ocr_results guarda el resultado fusionado, no qué fármacos se incluyen.
        representative = max(
            members, key=lambda o: (len(o.get("items") or []), float(o.get("mean_confidence") or 0.0))
        )
        merged = merge_label_items([m.get("items") or [] for m in members])
        center = sum(float(m["center_norm"]) for m in members) / len(members)
        quality = max(float(m.get("quality_score") or 0.0) for m in members)
        result.append(LabelGroup(
            signature=sig,
            bag_ids=[m["bag_id"] for m in members],
            representative_bag_id=representative["bag_id"],
            representative_ocr_result_id=representative["ocr_result_id"],
            representative_crop_path=representative.get("crop_path"),
            center_norm=center,
            best_quality=quality,
            merged_items=merged,
            header=representative.get("header"),
        ))

    for single in singleton_groups:
        obs = single[0]
        result.append(LabelGroup(
            signature=None,
            bag_ids=[obs["bag_id"]],
            representative_bag_id=obs["bag_id"],
            representative_ocr_result_id=obs["ocr_result_id"],
            representative_crop_path=obs.get("crop_path"),
            center_norm=float(obs["center_norm"]),
            best_quality=float(obs.get("quality_score") or 0.0),
            merged_items=obs.get("items") or [],
            header=obs.get("header"),
        ))

    result.sort(key=lambda g: g.center_norm)
    return result
