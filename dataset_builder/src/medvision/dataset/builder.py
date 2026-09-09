from __future__ import annotations

import csv
import json
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any

import cv2
import yaml
from tqdm import tqdm

from medvision.acquisition.quality import frame_quality, quality_score
from medvision.acquisition.video_reader import VideoReader
from medvision.bags.detector import detect_bag_strip
from medvision.bags.splitter import split_vertical_strip_into_bags
from medvision.bags.tracker import BagObservation, BagTracker
from medvision.database.repository import Repository
from medvision.ocr.label_ocr import read_label
from medvision.ocr.parser import (
    parse_label_sheet, parse_label_sheets, parse_label_sheets_by_position,
    parse_label_sheets_by_multi_position,
)
from medvision.acquisition.motion import compute_cumulative_pan_distances
from medvision.bags.seam_band import detect_seam_band, detect_seam_bands
from medvision.pairing.header_grouping import group_label_bags_by_header
from medvision.pairing.seam_grouping import group_pill_bags_by_seam
from medvision.pairing.track_pairer import PairResult, pair_tracks

VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv"}


def _run_ocr_and_persist(
    crop: Any, side: str, cfg: dict[str, Any], repo: Repository, bag_id: int,
    output_dir: Path, video_stem: str, frame_index: int, seg_index: int,
) -> list[dict[str, Any]]:
    """OCR de un recorte de bolsa + parseo de cabecera/fármacos + persistencia.

    Se usa para los dos lados: en la etiqueta el texto se lee directo; en la
    pastilla, cuando lo hay, se ve reflejado por transparencia desde el
    reverso de la etiqueta impresa -- se voltea horizontalmente antes de
    pasar por OCR (confirmado con foto real, ver
    docs/cuaderno_ingenieria_2.9.md). El resto del tratamiento es idéntico
    para ambos lados: misma función, sin rutas de código separadas que
    puedan divergir.

    Devuelve una lista, no un único resultado: con grabación vertical (más
    resolución a lo largo de la tira) una misma foto puede contener MÁS DE
    UNA bolsita completa — cada una se persiste como su propia fila de
    ocr_results (sheet_index 0, 1, ...), no se fusionan (ver
    docs/cuaderno_ingenieria_3.2.md).
    """
    ocr_input = cv2.flip(crop, 1) if side == "pill_side" else crop
    result = read_label(
        ocr_input,
        lang=cfg["ocr"].get("lang", "es"),
        engine=cfg["ocr"].get("engine", "paddle"),
        min_score=cfg["ocr"].get("min_word_score", 0.5),
    )
    rel_proc = Path("ocr") / video_stem / f"f{frame_index:06d}_bag{seg_index:02d}.png"
    abs_proc = output_dir / rel_proc
    abs_proc.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(abs_proc), result.processed_image)

    # Una bolsita SPD lista varios fármacos bajo una cabecera compartida
    # (paciente/fecha/toma); result.words conserva el orden de lectura línea
    # a línea que necesita el parser. Puede haber más de una bolsita.
    #
    # El orden de lectura del OCR no siempre es de fiar cerca de la costura
    # entre dos bolsitas del mismo frame (texto torcido en la frontera puede
    # entregarse fuera de su orden físico real — visto en datos reales, ver
    # docs/cuaderno_ingenieria_3.11.md). Cuando se detecta una o más
    # costuras (misma señal de brillo+tinte azul ya usada en el lado
    # pastilla, ver bags/seam_band.py), se usa la posición Y real de cada
    # línea para decidir a qué bolsita pertenece, en vez de solo el orden
    # de lectura. Desde 3.26, no solo la costura más marcada — con 3+
    # bolsitas en un mismo frame (2+ costuras), quedarse con una sola
    # dejaba el mismo bug escondido dentro del tramo más grande (433 de
    # 734 pares del dataset real lo tocaban, ver
    # docs/cuaderno_ingenieria_3.26.md).
    seam_bands = detect_seam_bands(result.processed_image)
    seam_positions = [pos for pos, _ in seam_bands]
    if seam_positions and result.word_y_norm and len(result.word_y_norm) == len(result.words):
        lines_with_y = list(zip(result.words, result.word_y_norm))
        sheets = parse_label_sheets_by_multi_position(lines_with_y, seam_positions)
    else:
        sheets = parse_label_sheets(result.words)
    if not sheets:
        sheets = [parse_label_sheet([])]  # fila vacía consistente, needs_review=1
    # Se guarda en la bolsa el mismo valor que decidió el reparto de líneas
    # (no un cálculo aparte que podría no coincidir) — así la app de revisión
    # puede dibujar exactamente estas costuras, sean las que sean.
    primary_pos = seam_positions[0] if seam_positions else None
    primary_prom = seam_bands[0][1] if seam_bands else 0.0
    repo.update_bag_seam(bag_id, primary_prom, primary_pos, all_seam_positions=seam_positions)

    rows: list[dict[str, Any]] = []
    for sheet_index, sheet in enumerate(sheets):
        # Si dos o más items comparten raw_line, la línea reconstruida traía
        # varios fármacos fusionados y _parse_item_line() tuvo que separarlos
        # (ver docs/cuaderno_ingenieria_1.6.md); es una señal precisa de que
        # esta bolsita necesita revisión, no una suposición basada en la
        # confianza del OCR (que puede seguir siendo alta aunque haya fusión).
        raw_line_counts: dict[str, int] = {}
        for it in sheet.items:
            raw_line_counts[it.raw_line] = raw_line_counts.get(it.raw_line, 0) + 1
        had_merge_split = any(c > 1 for c in raw_line_counts.values())
        needs_review = int(
            result.mean_confidence < cfg["ocr"].get("auto_accept_confidence", 80)
            or not sheet.items
            or had_merge_split
        )
        ocr_row = {
            "bag_id": bag_id, "sheet_index": sheet_index,
            "raw_text": result.raw_text if sheet_index == 0 else "",
            "normalized_text": result.normalized_text if sheet_index == 0 else "",
            "mean_confidence": result.mean_confidence,
            "word_count": result.word_count,
            "processed_image_path": str(rel_proc),
            # drug_name/dose_value/dose_unit deprecados desde 1.5: la lista real
            # vive en label_items (ver más abajo).
            "drug_name": None, "dose_value": None,
            "dose_unit": None, "needs_review": needs_review,
            "seam_side": sheet.seam_side,
        }
        ocr_result_id = repo.upsert_ocr(**ocr_row)
        repo.upsert_label_header(
            ocr_result_id,
            patient_name=sheet.header.patient_name,
            patient_location=sheet.header.patient_location,
            dose_weekday=sheet.header.dose_weekday,
            dose_date=sheet.header.dose_date,
            dose_slot=sheet.header.dose_slot,
        )
        repo.replace_label_items(ocr_result_id, [
            {
                "line_index": it.line_index, "quantity": it.quantity,
                "drug_name": it.drug_name, "dose_value": it.dose_value,
                "dose_unit": it.dose_unit, "raw_line": it.raw_line,
            }
            for it in sheet.items
        ])
        rows.append({
            **ocr_row,
            "item_count": len(sheet.items),
            "drug_names_preview": "; ".join(it.drug_name for it in sheet.items if it.drug_name),
        })
    return rows


def infer_side(stem: str, cfg: dict[str, Any]) -> str:
    side = cfg.get("video_sides", {}).get(stem, "unknown")
    if side == "unknown":
        print(
            f"AVISO: '{stem}' no está en video_sides (config YAML) -> se procesa como "
            f"'unknown'. Sus bolsas NUNCA pasarán por OCR ni por emparejamiento "
            f"(el pipeline solo hace OCR sobre side=='label_side'). Añade '{stem}: "
            f"pill_side' o '{stem}: label_side' a video_sides en tu config."
        )
    return side


def _write_csv(path: Path, rows: list[dict[str, Any]], append: bool = False) -> None:
    """Escribe un CSV de metadatos. Con append=True (frames/bags/tracks/ocr,
    que solo acumulan lo procesado en ESTA ejecución), si el fichero ya
    existe de una ejecución anterior se combinan sus filas con las nuevas,
    en vez de perder el historial de vídeos ya procesados y saltados esta
    vez (ver dataset/builder.py::is_video_completed / cuaderno 3.5).
    track_pairs.csv no usa append: se recalcula entero cada vez a partir de
    toda la base, ya es acumulativo por diseño.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    combined = rows
    if append and path.exists():
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                existing = list(csv.DictReader(f))
            combined = existing + rows
        except Exception:
            combined = rows  # CSV previo corrupto/vacío: mejor no perder las filas nuevas
    if not combined:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in combined:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(combined)


def _compute_and_store_pan_distances(repo: Repository, output_dir: Path, video_filename: str) -> int:
    """Calcula y guarda la distancia de paneo acumulada de cada frame de un
    vídeo YA PROCESADO, a partir de los frames ya muestreados y guardados en
    disco — sin releer el vídeo original ni repetir detección/OCR. Devuelve
    cuántos frames se actualizaron. Ver docs/cuaderno_ingenieria_3.13.md/3.14.md.
    """
    video_frame_rows = repo.get_frames_for_video(video_filename)
    if len(video_frame_rows) < 2:
        return 0
    frame_images = []
    valid_rows = []
    for fr in video_frame_rows:
        img_path = output_dir / str(fr["image_path"])
        img = cv2.imread(str(img_path))
        if img is not None:
            frame_images.append(img)
            valid_rows.append(fr)
    if len(frame_images) < 2:
        return 0
    cumulative = compute_cumulative_pan_distances(frame_images)
    for fr, cum_px in zip(valid_rows, cumulative):
        repo.set_frame_cumulative_pan(int(fr["id"]), cum_px)
    return len(valid_rows)


def _build_pairs(repo: Repository, cfg: dict[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    """Bloque de emparejamiento: agrupado por cabecera/costura +
    emparejamiento directo (por cabecera compartida) + ordinal de
    respaldo + persistencia (track_pairs, pair_group_members,
    paired_dataset/).

    Opera solo sobre datos ya presentes en `repo` (bags, ocr_results,
    label_headers, label_items) — no repite detección ni OCR, así que se
    puede volver a llamar sobre un dataset ya procesado sin repetir el
    trabajo caro (ver rebuild_pairs() más abajo y
    docs/cuaderno_ingenieria_3.1.md).
    """
    pair_rows: list[dict[str, Any]] = []
    video_pairs = cfg.get("video_pairs", [])
    for pair_cfg in video_pairs:
        pair_key = str(pair_cfg["pair_key"])
        pill_stem = str(pair_cfg["pill_video"])
        label_stem = str(pair_cfg["label_video"])
        direction = str(pair_cfg.get("direction", "direct"))
        # El lado pastilla puede tener texto legible (reflejado por
        # transparencia desde el reverso, confirmado con foto real —
        # ver docs/cuaderno_ingenieria_2.9.md). Si su cabecera OCR
        # coincide EXACTAMENTE con la de una bolsita del lado etiqueta,
        # se emparejan directamente por contenido — no por posición.
        # Mucho más fiable que adivinar: dos grabaciones independientes
        # no garantizan el mismo orden de bolsitas (ver 2.5), pero una
        # cabecera idéntica sí es una bolsita real idéntica.
        pill_ocr_observations = repo.get_ocr_observations_for_video(pill_stem)
        pill_header_groups = group_label_bags_by_header(pill_ocr_observations)

        # El lado etiqueta NO se agrupa por track visual: el tracker de
        # bags/tracker.py enlaza por aspecto (histograma de color), y todas
        # las bolsitas de esta tira se parecen entre sí -> puede juntar
        # bolsitas reales DISTINTAS en un mismo track (visto con datos
        # reales, ver docs/cuaderno_ingenieria_1.9.md). Se agrupan en su
        # lugar por cabecera OCR (paciente/fecha/toma).
        label_observations = repo.get_ocr_observations_for_video(label_stem)
        label_groups = group_label_bags_by_header(label_observations)
        for grp in label_groups:
            repo.replace_label_items(grp.representative_ocr_result_id, grp.merged_items)

        pill_sig_to_group = {g.signature: g for g in pill_header_groups if g.signature}
        label_sig_to_group = {g.signature: g for g in label_groups if g.signature}
        matched_signatures = sorted(set(pill_sig_to_group) & set(label_sig_to_group))

        pill_by_key: dict[str, dict[str, Any]] = {}
        label_by_key: dict[str, dict[str, Any]] = {}
        direct_paired: list[PairResult] = []
        matched_pill_bag_ids: set[int] = set()
        for order_i, sig in enumerate(matched_signatures):
            pg, lg = pill_sig_to_group[sig], label_sig_to_group[sig]
            matched_pill_bag_ids.update(pg.bag_ids)
            pk = f"{pill_stem}:pill_side:direct:{order_i:04d}"
            lk = f"{label_stem}:label_side:direct:{order_i:04d}"
            pill_by_key[pk] = {"crop_path": pg.representative_crop_path, "bag_ids": pg.bag_ids,
                                "ocr_result_id": pg.representative_ocr_result_id}
            label_by_key[lk] = {"crop_path": lg.representative_crop_path, "bag_ids": lg.bag_ids,
                                 "ocr_result_id": lg.representative_ocr_result_id}
            direct_paired.append(PairResult(
                pair_key=pair_key, pill_track_key=pk, label_track_key=lk,
                pill_best_bag_id=pg.representative_bag_id,
                label_best_bag_id=lg.representative_bag_id,
                order_index=order_i, match_score=1.0, status="paired",
            ))

        # Lo que no encontró pareja exacta por cabecera (OCR ilegible en
        # algún lado, o de verdad no hay bolsita correspondiente) intenta
        # primero un emparejamiento por POSICIÓN FÍSICA: dos grabaciones
        # independientes de la misma tira recorren una distancia física
        # comparable (aunque no idéntica — encuadre/velocidad de paneo
        # distintos), así que la posición relativa de una bolsita dentro de
        # esa distancia total sirve de referencia razonable para localizarla
        # en la otra grabación — validado con datos reales (5 de 6 aciertos
        # en 2 sesiones de prueba), ver docs/cuaderno_ingenieria_3.13.md.
        # NO es una coincidencia verificada por contenido como la de arriba,
        # así que se marca con su propio status y siempre pide revisión.
        pill_pan_range = repo.get_pan_range_for_video(pill_stem, "pill_side")
        label_pan_range = repo.get_pan_range_for_video(label_stem, "label_side")
        position_matched: list[PairResult] = []
        still_unmatched_label_groups = []
        for grp in [g for g in label_groups if g.signature not in matched_signatures]:
            # Solo se ofrecen para emparejar por posición los grupos con AL
            # MENOS un fármaco reconocido. Una lectura vacía (pie de
            # farmacia, código QR mal leído como si fuera cabecera) no
            # aporta nada que confirmar y, peor, gasta una foto de pastilla
            # que podría servir para una bolsita real — visto con datos
            # reales, el 57% de los primeros emparejamientos por posición
            # caían en lecturas vacías (ver docs/cuaderno_ingenieria_3.15.md).
            if not grp.merged_items:
                still_unmatched_label_groups.append(grp)
                continue
            matched_by_position = False
            if pill_pan_range and label_pan_range and grp.representative_bag_id is not None:
                label_pos = repo.get_pan_distance_for_bag(grp.representative_bag_id)
                lo_l, hi_l = label_pan_range
                lo_p, hi_p = pill_pan_range
                if label_pos is not None and hi_l > lo_l:
                    fraction = (label_pos - lo_l) / (hi_l - lo_l)
                    target_pill_pos = lo_p + fraction * (hi_p - lo_p)
                    tolerance = 0.08 * (hi_p - lo_p)  # margen validado con datos reales
                    candidate = repo.find_closest_bag_by_pan_distance(
                        pill_stem, "pill_side", target_pill_pos, tolerance,
                        exclude_bag_ids=matched_pill_bag_ids,
                    )
                    if candidate is not None:
                        order_i = len(matched_signatures) + len(position_matched)
                        pk = f"{pill_stem}:pill_side:position:{order_i:04d}"
                        lk = f"{label_stem}:label_side:position:{order_i:04d}"
                        pill_by_key[pk] = {"crop_path": candidate["crop_path"], "bag_ids": [int(candidate["bag_id"])]}
                        label_by_key[lk] = {
                            "crop_path": grp.representative_crop_path, "bag_ids": grp.bag_ids,
                            "ocr_result_id": grp.representative_ocr_result_id,
                        }
                        matched_pill_bag_ids.add(int(candidate["bag_id"]))
                        position_matched.append(PairResult(
                            pair_key=pair_key, pill_track_key=pk, label_track_key=lk,
                            pill_best_bag_id=int(candidate["bag_id"]),
                            label_best_bag_id=grp.representative_bag_id,
                            order_index=order_i, match_score=0.75, status="position_matched",
                        ))
                        matched_by_position = True
            if not matched_by_position:
                still_unmatched_label_groups.append(grp)

        # Lo que tampoco encontró pareja por posición cae al mecanismo
        # anterior: costura para identidad del lado pastilla + emparejamiento
        # ordinal. Se excluyen las bolsas de pastilla ya usadas (directo o
        # por posición), para no procesarlas dos veces.
        remaining_label_groups = still_unmatched_label_groups
        pill_observations = repo.get_pill_observations_for_video(pill_stem)
        pill_seam_groups = group_pill_bags_by_seam(pill_observations)
        pill_tracks = [
            {
                "track_key": f"{pill_stem}:pill_side:seam:{i:04d}",
                "best_bag_id": grp.representative_bag_id,
                "best_quality": grp.best_quality,
                "center_norm": grp.center_norm,
                "crop_path": grp.representative_crop_path,
                "bag_ids": grp.bag_ids,
            }
            for i, grp in enumerate(pill_seam_groups)
            if not grp.in_transition and not (set(grp.bag_ids) & matched_pill_bag_ids)
        ]
        label_tracks = [
            {
                "track_key": f"{label_stem}:label_side:header:{i:04d}",
                "best_bag_id": grp.representative_bag_id,
                "best_quality": grp.best_quality,
                "center_norm": grp.center_norm,
                "crop_path": grp.representative_crop_path,
                "bag_ids": grp.bag_ids,
                "ocr_result_id": grp.representative_ocr_result_id,
            }
            for i, grp in enumerate(remaining_label_groups)
        ]
        offset = len(direct_paired) + len(position_matched)
        ordinal_paired = [
            dataclass_replace(p, order_index=p.order_index + offset)
            for p in pair_tracks(pill_tracks, label_tracks, pair_key, direction)
        ]
        paired = direct_paired + position_matched + ordinal_paired
        pill_by_key.update({str(x["track_key"]): x for x in pill_tracks})
        label_by_key.update({str(x["track_key"]): x for x in label_tracks})
        for item in paired:
            ocr = None
            label_items: list[dict[str, Any]] = []
            header = None
            ltrack_all = label_by_key.get(item.label_track_key or "")
            ptrack_all = pill_by_key.get(item.pill_track_key or "")
            ocr_result_id_hint = (ltrack_all or {}).get("ocr_result_id")
            if ocr_result_id_hint is not None:
                # Camino correcto: ya sabemos exactamente qué lectura (de las
                # posibles varias bolsitas de una misma foto, ver 3.2) es la
                # representante de este grupo — no hay que adivinar por bag_id.
                rows = repo.export_query_params(
                    "SELECT * FROM ocr_results WHERE id=?", (ocr_result_id_hint,)
                )
                ocr = rows[0] if rows else None
            elif item.label_best_bag_id is not None:
                # Respaldo: sin ocr_result_id conocido (no debería pasar en la
                # práctica), se busca por bag_id. Si esa bolsa tiene más de una
                # lectura (sheet_index>0), esto puede coger la equivocada — de
                # ahí que el camino de arriba sea siempre preferible.
                rows = repo.export_query_params(
                    "SELECT * FROM ocr_results WHERE bag_id=? ORDER BY sheet_index LIMIT 1",
                    (item.label_best_bag_id,),
                )
                ocr = rows[0] if rows else None
            if ocr:
                label_items = repo.get_label_items(int(ocr["id"]))
                header = repo.get_label_header(int(ocr["id"]))
            needs_review = int(
                item.status != "paired" or not ocr or not label_items
                or float(ocr.get("mean_confidence") or 0.0) < cfg.get("pairing", {}).get("auto_accept_ocr_confidence", 70)
            )
            row = {
                "pair_key": pair_key,
                "pill_track_key": item.pill_track_key,
                "label_track_key": item.label_track_key,
                "pill_best_bag_id": item.pill_best_bag_id,
                "label_best_bag_id": item.label_best_bag_id,
                "label_ocr_result_id": int(ocr["id"]) if ocr else None,
                "pill_ocr_result_id": (ptrack_all or {}).get("ocr_result_id"),
                "order_index": item.order_index,
                "match_score": item.match_score,
                "status": item.status,
                # drug_name/dose_value/dose_unit deprecados desde 1.5: el detalle
                # real vive en label_items, consultado arriba.
                "drug_name": None, "dose_value": None, "dose_unit": None,
                "ocr_confidence": ocr.get("mean_confidence") if ocr else None,
                "needs_review": needs_review,
            }
            track_pair_id = repo.upsert_track_pair(**row)
            repo.replace_pair_group_members(
                track_pair_id, "pill",
                (ptrack_all or {}).get("bag_ids") or ([item.pill_best_bag_id] if item.pill_best_bag_id else []),
            )
            repo.replace_pair_group_members(
                track_pair_id, "label",
                (ltrack_all or {}).get("bag_ids") or ([item.label_best_bag_id] if item.label_best_bag_id else []),
            )
            csv_row = {
                **row,
                "item_count": len(label_items),
                "drug_names_preview": "; ".join(
                    li["drug_name"] for li in label_items if li.get("drug_name")
                ),
                "patient_name": header.get("patient_name") if header else None,
                "dose_slot": header.get("dose_slot") if header else None,
                "dose_date": header.get("dose_date") if header else None,
            }
            pair_rows.append(csv_row)

            # Materialize a reviewable paired sample without altering raw crops.
            sample_dir = output_dir / "paired_dataset" / pair_key / f"item_{item.order_index:03d}"
            sample_dir.mkdir(parents=True, exist_ok=True)
            ptrack = ptrack_all
            ltrack = ltrack_all
            if ptrack:
                source = output_dir / str(ptrack["crop_path"])
                if source.exists():
                    import shutil
                    shutil.copy2(source, sample_dir / "pill_side.jpg")
            if ltrack:
                source = output_dir / str(ltrack["crop_path"])
                if source.exists():
                    import shutil
                    shutil.copy2(source, sample_dir / "label_side.jpg")
            (sample_dir / "metadata.json").write_text(
                json.dumps(
                    {**csv_row, "label_items": label_items, "header": header},
                    ensure_ascii=False, indent=2, default=str,
                ),
                encoding="utf-8",
            )

    return pair_rows


def rebuild_pairs(output_dir: Path, config_path: Path) -> dict[str, Any]:
    """Vuelve a agrupar y emparejar sobre un dataset ya procesado, sin
    repetir detección ni OCR (la parte lenta — horas con 100+ vídeos, ver
    docs/cuaderno_ingenieria_2.8.md). Útil cuando cambia la lógica de
    agrupado/emparejamiento (o el esquema de las tablas que la sostienen,
    como pair_group_members en 3.0) pero no la extracción en sí.

    Requiere que `output_dir` ya tenga un `medvision.sqlite` de una
    ejecución anterior de build-dataset — no crea vídeos, frames ni bolsas
    nuevas, solo relee lo que ya hay.
    """
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    db_path = output_dir / cfg.get("database", "medvision.sqlite")
    if not db_path.exists():
        raise FileNotFoundError(
            f"No existe {db_path}. rebuild-pairs necesita un dataset ya generado "
            "por build-dataset — no puede crear uno desde cero."
        )

    with Repository(db_path) as repo:
        run_id = repo.create_run(str(config_path), "(rebuild-pairs, sin re-procesar vídeos)", str(output_dir))
        try:
            # Vídeos completados con una versión anterior a la 3.13 no tienen
            # cumulative_pan_px calculado. Se rellena aquí, sobre los frames
            # ya guardados en disco (no hace falta --fresh solo para esto —
            # ver docs/cuaderno_ingenieria_3.14.md).
            missing = repo.get_completed_videos_missing_pan_distance()
            if missing:
                print(f"Calculando distancia de paneo para {len(missing)} vídeo(s) sin ese dato todavía...")
                for filename in missing:
                    _compute_and_store_pan_distances(repo, output_dir, filename)

            # Bases generadas con el bug de 3.28 (numpy.float32 sin
            # convertir, guardado como BLOB en vez de número) pueden tener
            # bolsas con seam_prominence corrompido — se repara aquí, antes
            # de que _build_pairs() intente leerlo, en vez de fallar de
            # nuevo con el mismo error (ver docs/cuaderno_ingenieria_3.29.md).
            repaired = repo.repair_corrupted_seam_prominence()
            if repaired:
                print(f"Reparadas {repaired} bolsa(s) con seam_prominence corrompido (bug de 3.28).")

            pair_rows = _build_pairs(repo, cfg, output_dir)
            selected = repo.mark_best_bags(cfg.get("selection", {}).get("limit_per_video_side", 20))
            count = lambda sql: int(repo.export_query_params(sql, ())[0]["c"])  # noqa: E731
            summary = {
                "version": "1.2.0",
                "videos": count("SELECT COUNT(*) AS c FROM videos"),
                "frames": count("SELECT COUNT(*) AS c FROM frames"),
                "bag_observations": count("SELECT COUNT(*) AS c FROM bags"),
                "bag_tracks": count("SELECT COUNT(*) AS c FROM bag_tracks"),
                "multi_observation_tracks": count(
                    "SELECT COUNT(*) AS c FROM bag_tracks WHERE observation_count>1"
                ),
                "ocr_results": count("SELECT COUNT(*) AS c FROM ocr_results"),
                "selected_bags": selected,
                "track_pairs": len(pair_rows),
                "paired_with_label": sum(bool(r["pill_track_key"]) and bool(r["label_track_key"]) for r in pair_rows),
                "pairs_needing_review": sum(int(r["needs_review"]) for r in pair_rows),
                "database": str(db_path),
            }
            repo.finish_run(run_id, "completed", summary)
        except Exception as exc:
            repo.finish_run(run_id, "failed", {"error": str(exc)})
            raise

    _write_csv(output_dir / "metadata" / "track_pairs.csv", pair_rows)
    (output_dir / "reports").mkdir(parents=True, exist_ok=True)
    (output_dir / "reports" / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def build_dataset(
    videos_dir: Path, output_dir: Path, config_path: Path, allow_unknown_side: bool = False,
) -> dict[str, Any]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / cfg.get("database", "medvision.sqlite")
    frame_rows: list[dict[str, Any]] = []
    bag_rows: list[dict[str, Any]] = []
    ocr_rows: list[dict[str, Any]] = []
    track_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []

    videos = sorted(p for p in videos_dir.iterdir() if p.suffix.lower() in VIDEO_EXTS)
    video_sides = cfg.get("video_sides", {})
    # Comprobación previa, ANTES de procesar nada: un vídeo sin lado asignado
    # nunca pasa por OCR ni emparejamiento (side='unknown'), y si ya se
    # procesó así una vez, el salto de vídeos completados (3.5) lo da por
    # bueno para siempre — visto en uso real dos veces (cuaderno 3.6): la
    # sesión no se regeneró antes de lanzar el pipeline, y el aviso por
    # vídeo se perdía en mitad de un log de cientos de líneas. Mejor parar
    # aquí, una vez, con un mensaje que no se pueda pasar por alto.
    missing = [p.stem for p in videos if p.stem not in video_sides]
    if missing and not allow_unknown_side:
        raise RuntimeError(
            f"{len(missing)} vídeo(s) sin lado asignado en video_sides: {', '.join(missing[:10])}"
            f"{'...' if len(missing) > 10 else ''}\n"
            "Regenera la sesión antes de lanzar build-dataset:\n"
            f"  medvision-ai plan-sessions --videos-dir {videos_dir} --output <sessions.yaml>\n"
            "Si de verdad quieres procesarlos igualmente como 'unknown' (sin OCR ni "
            "emparejamiento), pasa --allow-unknown-side."
        )

    with Repository(db_path) as repo:
        run_id = repo.create_run(str(config_path), str(videos_dir), str(output_dir))
        try:
            for video_path in videos:
                side_now = infer_side(video_path.stem, cfg)
                if repo.is_video_completed(video_path.name, side_now):
                    print(f"'{video_path.name}' ya procesado en una ejecución anterior con el mismo "
                          f"lado ({side_now}), saltando (usa --fresh para reprocesar todo desde cero).")
                    continue
                try:
                    side = side_now
                    tracker_cfg = cfg.get("tracking", {})
                    tracker = BagTracker(video_path.stem, side, **tracker_cfg)

                    with VideoReader(video_path) as vr:
                        info = vr.info
                        video_id = repo.upsert_video(
                            path=str(video_path.resolve()), filename=video_path.name, side=side,
                            fps=info.fps, width=info.width, height=info.height,
                            frame_count=info.frame_count, duration_seconds=info.duration_seconds,
                        )
                        iterator = vr.iter_sampled(
                            seconds_between_frames=cfg["sampling"]["seconds_between_frames"],
                            max_frames=cfg["sampling"].get("max_frames_per_video"),
                        )
                        rotate_degrees = int(cfg["sampling"].get("rotate_degrees", 0))
                        for frame_index, ts, frame in tqdm(list(iterator), desc=video_path.stem):
                            if rotate_degrees == 90:
                                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                            elif rotate_degrees in (-90, 270):
                                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                            elif rotate_degrees == 180:
                                frame = cv2.rotate(frame, cv2.ROTATE_180)
                            q = frame_quality(frame)
                            score = quality_score(q)
                            rel_frame = Path("frames") / side / video_path.stem / f"f{frame_index:06d}.jpg"
                            abs_frame = output_dir / rel_frame
                            abs_frame.parent.mkdir(parents=True, exist_ok=True)
                            cv2.imwrite(str(abs_frame), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])

                            det = detect_bag_strip(
                                frame,
                                threshold_value=cfg["bag_detection"]["threshold_value"],
                                min_area_ratio=cfg["bag_detection"]["min_area_ratio"],
                            )
                            frame_id = repo.upsert_frame(
                                video_id=video_id, frame_index=frame_index, timestamp_seconds=ts,
                                image_path=str(rel_frame), sharpness=q["sharpness_laplacian"],
                                brightness=q["mean_brightness"], contrast=q["contrast_std"],
                                overexposed_ratio=q["overexposed_ratio"], quality_score=score,
                                strip_detected=int(det is not None),
                            )
                            frame_rows.append({
                                "frame_id": frame_id, "video": video_path.name, "side": side,
                                "frame_index": frame_index, "timestamp_seconds": round(ts, 3),
                                "quality_score": score, "strip_detected": int(det is not None),
                                "image_path": str(rel_frame),
                            })
                            if det is None:
                                continue

                            segments = split_vertical_strip_into_bags(
                                det["crop"],
                                min_segment_height=cfg["bag_splitting"]["min_segment_height"],
                                max_segments=cfg["bag_splitting"]["max_segments"],
                                margin=cfg["bag_splitting"]["margin"],
                            )
                            observations: list[BagObservation] = []
                            rows_by_bag_id: dict[int, dict[str, Any]] = {}
                            for seg in segments:
                                rel_bag = Path("bags") / side / video_path.stem / f"f{frame_index:06d}_bag{seg.index:02d}.jpg"
                                abs_bag = output_dir / rel_bag
                                abs_bag.parent.mkdir(parents=True, exist_ok=True)
                                cv2.imwrite(str(abs_bag), seg.crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
                                seam_prominence = seam_position = None
                                if side == "pill_side":
                                    # El lado pastilla no tiene texto propio del que derivar
                                    # identidad (a diferencia de la cabecera OCR del lado
                                    # etiqueta); se usa la banda de costura como señal física
                                    # real en su lugar. Ver docs/cuaderno_ingenieria_2.4.md/2.5.md.
                                    seam_found, seam_position, seam_prominence = detect_seam_band(seg.crop)
                                bag_id = repo.upsert_bag(
                                    frame_id=frame_id, bag_index_in_frame=seg.index, side=side,
                                    crop_path=str(rel_bag), y1=seg.y1, y2=seg.y2,
                                    segment_confidence=seg.confidence, quality_score=score,
                                    track_key=None, track_match_score=0.0, is_track_best=0,
                                    seam_prominence=seam_prominence, seam_position=seam_position,
                                )
                                row = {
                                    "bag_id": bag_id, "frame_id": frame_id, "video": video_path.name,
                                    "side": side, "frame_index": frame_index,
                                    "bag_index_in_frame": seg.index, "quality_score": score,
                                    "segment_confidence": seg.confidence, "crop_path": str(rel_bag),
                                    "track_key": None, "track_match_score": 0.0, "is_track_best": 0,
                                }
                                bag_rows.append(row)
                                rows_by_bag_id[bag_id] = row
                                observations.append(BagObservation(
                                    bag_id=bag_id, frame_id=frame_id, frame_index=frame_index,
                                    timestamp_seconds=ts, bag_index_in_frame=seg.index, crop=seg.crop,
                                    y1=seg.y1, y2=seg.y2, frame_height=det["crop"].shape[0],
                                    quality_score=score, segment_confidence=seg.confidence,
                                ))

                                # OCR en los dos lados: etiqueta siempre, pastilla cuando el
                                # texto reflejado por transparencia es legible (ver
                                # docs/cuaderno_ingenieria_2.9.md). pill_side_enabled permite
                                # desactivarlo si en algún lote concreto no aporta (p.ej.
                                # plástico demasiado opaco) sin tocar código.
                                ocr_wanted = cfg["ocr"].get("enabled", False) and (
                                    side == "label_side"
                                    or (side == "pill_side" and cfg["ocr"].get("pill_side_enabled", True))
                                )
                                if ocr_wanted:
                                    try:
                                        csv_rows = _run_ocr_and_persist(
                                            seg.crop, side, cfg, repo, bag_id, output_dir,
                                            video_path.stem, frame_index, seg.index,
                                        )
                                        ocr_rows.extend(csv_rows)
                                    except Exception as exc:
                                        ocr_row = {
                                            "bag_id": bag_id, "sheet_index": 0, "raw_text": f"OCR_ERROR: {exc}",
                                            "normalized_text": "", "mean_confidence": 0.0,
                                            "word_count": 0, "processed_image_path": None,
                                            "drug_name": None, "dose_value": None,
                                            "dose_unit": None, "needs_review": 1,
                                        }
                                        repo.upsert_ocr(**ocr_row)
                                        ocr_rows.append({**ocr_row, "item_count": 0, "drug_names_preview": ""})

                            for assignment in tracker.update(observations):
                                repo.update_bag_tracking(
                                    assignment.bag_id, assignment.track_key,
                                    assignment.match_score, int(assignment.is_best),
                                )
                                row = rows_by_bag_id[assignment.bag_id]
                                row["track_key"] = assignment.track_key
                                row["track_match_score"] = round(assignment.match_score, 6)
                                row["is_track_best"] = int(assignment.is_best)

                    current_track_rows, best_map = tracker.finalize()
                    repo.set_track_best_flags(best_map)
                    for row in bag_rows:
                        if row["video"] == video_path.name and row["bag_id"] in best_map:
                            row["is_track_best"] = int(best_map[row["bag_id"]])
                    for track_row in current_track_rows:
                        repo.upsert_track(
                            video_id=video_id, side=side,
                            track_key=str(track_row["track_key"]),
                            observation_count=int(track_row["observation_count"]),
                            best_bag_id=int(track_row["best_bag_id"]),
                            best_quality=float(track_row["best_quality"]),
                        )
                        track_rows.append(track_row)

                    # Distancia de paneo acumulada por frame — base del
                    # emparejamiento por posición física (ver
                    # docs/cuaderno_ingenieria_3.13.md). Se calcula sobre los
                    # frames ya muestreados y guardados (no hace falta releer
                    # el vídeo). Barato comparado con el OCR: una llamada a
                    # phaseCorrelate por par de frames consecutivos.
                    _compute_and_store_pan_distances(repo, output_dir, video_path.name)

                    repo.mark_video_completed(video_id)
                except Exception as exc:
                    print(
                        f"AVISO: no se pudo procesar '{video_path.name}' ({exc}). "
                        "Video saltado, continuando con el resto del lote."
                    )
                    continue


            # Associate recordings of the transparent and printed sides of the same strip.
            pair_rows = _build_pairs(repo, cfg, output_dir)

            selected = repo.mark_best_bags(cfg.get("selection", {}).get("limit_per_video_side", 20))
            # Recuentos contra la base, no contra las listas de esta ejecución: con
            # videos saltados (ya procesados antes, ver is_video_completed), esas
            # listas solo reflejan lo nuevo de HOY, no el total acumulado real.
            count = lambda sql: int(repo.export_query_params(sql, ())[0]["c"])  # noqa: E731
            summary = {
                "version": "1.2.0",
                "videos": count("SELECT COUNT(*) AS c FROM videos"),
                "frames": count("SELECT COUNT(*) AS c FROM frames"),
                "bag_observations": count("SELECT COUNT(*) AS c FROM bags"),
                "bag_tracks": count("SELECT COUNT(*) AS c FROM bag_tracks"),
                "multi_observation_tracks": count(
                    "SELECT COUNT(*) AS c FROM bag_tracks WHERE observation_count>1"
                ),
                "ocr_results": count("SELECT COUNT(*) AS c FROM ocr_results"),
                "selected_bags": selected,
                "track_pairs": len(pair_rows),
                "paired_with_label": sum(bool(r["pill_track_key"]) and bool(r["label_track_key"]) for r in pair_rows),
                "pairs_needing_review": sum(int(r["needs_review"]) for r in pair_rows),
                "database": str(db_path),
            }
            repo.finish_run(run_id, "completed", summary)
        except Exception as exc:
            repo.finish_run(run_id, "failed", {"error": str(exc)})
            raise

    _write_csv(output_dir / "metadata" / "frames.csv", frame_rows, append=True)
    _write_csv(output_dir / "metadata" / "bags.csv", bag_rows, append=True)
    _write_csv(output_dir / "metadata" / "tracks.csv", track_rows, append=True)
    _write_csv(output_dir / "metadata" / "ocr.csv", ocr_rows, append=True)
    _write_csv(output_dir / "metadata" / "track_pairs.csv", pair_rows)
    (output_dir / "reports").mkdir(parents=True, exist_ok=True)
    (output_dir / "reports" / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
