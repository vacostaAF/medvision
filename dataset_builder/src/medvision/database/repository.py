from __future__ import annotations
import json
import random
import sqlite3
from pathlib import Path
from typing import Any
from .schema import SCHEMA_SQL, REVIEW_SCHEMA_SQL

class Repository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self.conn.executescript(REVIEW_SCHEMA_SQL)
        self._migrate_missing_columns()
        self.conn.commit()

    def _migrate_missing_columns(self) -> None:
        """Añade columnas de rondas anteriores que puedan faltar en una base
        ya existente de una ejecución vieja.

        `CREATE TABLE IF NOT EXISTS` crea tablas NUEVAS pero no añade
        columnas a tablas que YA existen — con una base real que lleva
        semanas de uso incremental (sin `--fresh` en cada ronda de cambios),
        cada columna añadida en un cuaderno de ingeniería posterior a la
        primera vez que se creó esa tabla puede faltar. Se comprueba y
        arregla sola en vez de fallar con un error de SQL a mitad de
        `rebuild-pairs` o de la app de revisión (visto real, ver
        docs/cuaderno_ingenieria_3.10.md).

        `ocr_results.sheet_index` es la única excepción que NO se puede
        arreglar así: cambió también la restricción UNIQUE de la tabla
        (de `bag_id` a `(bag_id, sheet_index)`), y SQLite no permite
        modificar restricciones UNIQUE con ALTER TABLE — si falta, hace
        falta `--fresh` de verdad, no hay atajo seguro.
        """
        expected: dict[str, dict[str, str]] = {
            "videos": {"status": "TEXT NOT NULL DEFAULT 'in_progress'"},
            "bags": {"seam_prominence": "REAL", "seam_position": "REAL", "seam_positions_json": "TEXT"},
            "track_pairs": {"label_ocr_result_id": "INTEGER", "pill_ocr_result_id": "INTEGER"},
            "ocr_results": {"seam_side": "TEXT"},
            "frames": {"cumulative_pan_px": "REAL"},
        }
        for table, columns in expected.items():
            existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            for col, ddl in columns.items():
                if col not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

        ocr_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(ocr_results)")}
        if "sheet_index" not in ocr_columns:
            raise RuntimeError(
                "La base de datos es de una versión anterior a la 3.2 (sin "
                "'sheet_index' en ocr_results) y no se puede reparar automáticamente: "
                "ese cambio también modificó una restricción UNIQUE, que SQLite no "
                "permite alterar sin recrear la tabla. Hace falta 'build-dataset "
                "--fresh' para esta base."
            )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.close()

    def create_run(self, config_path: str, videos_dir: str, output_dir: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs(config_path,videos_dir,output_dir,status) VALUES(?,?,?,?)",
            (config_path, videos_dir, output_dir, "running"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, summary: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=CURRENT_TIMESTAMP,status=?,summary_json=? WHERE id=?",
            (status, json.dumps(summary, ensure_ascii=False), run_id),
        )
        self.conn.commit()

    def upsert_video(self, **v: Any) -> int:
        self.conn.execute(
            """INSERT INTO videos(path,filename,side,fps,width,height,frame_count,duration_seconds)
               VALUES(:path,:filename,:side,:fps,:width,:height,:frame_count,:duration_seconds)
               ON CONFLICT(path) DO UPDATE SET
               filename=excluded.filename,side=excluded.side,fps=excluded.fps,width=excluded.width,
               height=excluded.height,frame_count=excluded.frame_count,duration_seconds=excluded.duration_seconds"""
            , v)
        row = self.conn.execute("SELECT id FROM videos WHERE path=?", (v["path"],)).fetchone()
        return int(row["id"])

    def is_video_completed(self, filename: str, side: str) -> bool:
        """True si este vídeo (por nombre de fichero) ya se procesó entero
        en una ejecución anterior sin cortarse a medias CON EL MISMO LADO
        que se le asigna ahora — permite saltarlo en la siguiente ejecución
        (ver dataset/builder.py) sin reprocesar vídeos ya grabados en
        sesiones de trabajo previas.

        Se exige que coincida también `side`, no solo el nombre: si un
        vídeo se procesó como 'unknown' (por olvidar regenerar
        sessions.yaml antes de lanzar el pipeline — visto en uso real) y
        luego se corrige la sesión, debe reprocesarse con el lado correcto,
        no darse por bueno tal cual quedó.
        """
        row = self.conn.execute(
            "SELECT 1 FROM videos WHERE filename=? AND status='completed' AND side=?", (filename, side)
        ).fetchone()
        return row is not None

    def mark_video_completed(self, video_id: int) -> None:
        self.conn.execute("UPDATE videos SET status='completed' WHERE id=?", (video_id,))
        self.conn.commit()

    def upsert_frame(self, **f: Any) -> int:
        self.conn.execute(
            """INSERT INTO frames(video_id,frame_index,timestamp_seconds,image_path,sharpness,brightness,contrast,
               overexposed_ratio,quality_score,strip_detected)
               VALUES(:video_id,:frame_index,:timestamp_seconds,:image_path,:sharpness,:brightness,:contrast,
               :overexposed_ratio,:quality_score,:strip_detected)
               ON CONFLICT(video_id,frame_index) DO UPDATE SET
               timestamp_seconds=excluded.timestamp_seconds,image_path=excluded.image_path,
               sharpness=excluded.sharpness,brightness=excluded.brightness,contrast=excluded.contrast,
               overexposed_ratio=excluded.overexposed_ratio,quality_score=excluded.quality_score,
               strip_detected=excluded.strip_detected""", f)
        row = self.conn.execute("SELECT id FROM frames WHERE video_id=? AND frame_index=?", (f["video_id"], f["frame_index"])).fetchone()
        return int(row["id"])

    def get_frames_for_video(self, filename: str) -> list[dict[str, Any]]:
        """Todos los frames de un vídeo (por nombre de fichero), ordenados
        por frame_index — para calcular la distancia acumulada de paneo
        (ver acquisition/motion.py) sin tener que releer el vídeo original.
        """
        return self.export_query_params(
            """SELECT f.id, f.frame_index, f.image_path, f.strip_detected
               FROM frames f JOIN videos v ON v.id=f.video_id
               WHERE v.filename=? ORDER BY f.frame_index""",
            (filename,),
        )

    def get_completed_videos_missing_pan_distance(self) -> list[str]:
        """Nombres de vídeo ya completados (detección/OCR hechos) que
        todavía no tienen `cumulative_pan_px` calculado — para poder
        rellenarlo a posteriori sin reprocesar nada (ver
        docs/cuaderno_ingenieria_3.14.md), en vídeos procesados con una
        versión anterior a la 3.13.
        """
        rows = self.export_query_params(
            """SELECT DISTINCT v.filename
               FROM videos v
               JOIN frames f ON f.video_id=v.id
               WHERE v.status='completed'
               AND v.filename NOT IN (
                   SELECT DISTINCT v2.filename FROM videos v2
                   JOIN frames f2 ON f2.video_id=v2.id
                   WHERE f2.cumulative_pan_px IS NOT NULL
               )""",
            (),
        )
        return [str(r["filename"]) for r in rows]

    def repair_corrupted_seam_prominence(self) -> int:
        """Repara bolsas con `seam_prominence` guardado como BLOB en vez de
        número — el bug real de 3.28 (un `numpy.float32` sin convertir a
        `float` nativo antes de guardarse en SQLite). El valor original NO
        se pierde: son los 4 bytes crudos de un float32, se decodifican tal
        cual en vez de descartarlos. Devuelve cuántas bolsas se repararon.
        Idempotente — no hace nada si no hay ninguna corrompida (bases ya
        limpias, o generadas con el código ya corregido).
        """
        import struct

        rows = self.conn.execute(
            "SELECT id, seam_prominence FROM bags WHERE seam_prominence IS NOT NULL"
        ).fetchall()
        repaired = 0
        for row in rows:
            value = row["seam_prominence"]
            if isinstance(value, bytes):
                try:
                    decoded = struct.unpack("<f", value)[0]
                except struct.error:
                    decoded = None  # no son 4 bytes de un float32 -- no se puede recuperar, se limpia
                self.conn.execute("UPDATE bags SET seam_prominence=? WHERE id=?", (decoded, row["id"]))
                repaired += 1
        if repaired:
            self.conn.commit()
        return repaired

    def set_frame_cumulative_pan(self, frame_id: int, cumulative_pan_px: float) -> None:
        self.conn.execute(
            "UPDATE frames SET cumulative_pan_px=? WHERE id=?", (cumulative_pan_px, frame_id)
        )

    def get_pan_distance_for_bag(self, bag_id: int) -> float | None:
        row = self.conn.execute(
            "SELECT f.cumulative_pan_px FROM bags b JOIN frames f ON f.id=b.frame_id WHERE b.id=?",
            (bag_id,),
        ).fetchone()
        return float(row["cumulative_pan_px"]) if row and row["cumulative_pan_px"] is not None else None

    def get_pan_range_for_video(self, video_stem: str, side: str) -> tuple[float, float] | None:
        """(mínimo, máximo) de distancia de paneo acumulada de un vídeo, o
        None si no hay datos. Se usa para escalar posiciones entre el lado
        pastilla y el lado etiqueta de una sesión (ver
        docs/cuaderno_ingenieria_3.13.md)."""
        row = self.export_query_params(
            """SELECT MIN(f.cumulative_pan_px) AS lo, MAX(f.cumulative_pan_px) AS hi
               FROM frames f JOIN videos v ON v.id=f.video_id
               WHERE v.filename LIKE ? AND f.strip_detected=1 AND f.cumulative_pan_px IS NOT NULL""",
            (video_stem + ".%",),
        )
        if not row or row[0]["lo"] is None or row[0]["hi"] is None:
            return None
        return float(row[0]["lo"]), float(row[0]["hi"])

    def find_closest_bag_by_pan_distance(
        self, video_stem: str, side: str, target_pan_px: float, tolerance_px: float,
        exclude_bag_ids: set[int] | None = None,
    ) -> dict[str, Any] | None:
        """Bolsa del lado/vídeo dado cuya distancia de paneo acumulada esté
        más cerca de `target_pan_px`, dentro de `tolerance_px` — la consulta
        central del emparejamiento por posición (ver
        docs/cuaderno_ingenieria_3.13.md). None si ninguna bolsa de ese
        vídeo tiene distancia calculada, o ninguna cae dentro del margen.

        `exclude_bag_ids`: bolsas a ignorar (ya usadas por otro grupo) —
        para que, si la más cercana está ocupada, se pruebe con la
        siguiente más cercana dentro del margen en vez de rendirse del
        todo (bug real encontrado con datos reales: con pocas bolsas de
        pastilla por sesión, varias bolsitas distintas competían por la
        misma foto cercana, y solo la primera se la quedaba — ver
        docs/cuaderno_ingenieria_3.16.md).
        """
        exclude_bag_ids = exclude_bag_ids or set()
        rows = self.export_query_params(
            """SELECT b.id AS bag_id, b.crop_path, f.cumulative_pan_px
               FROM bags b
               JOIN frames f ON f.id=b.frame_id
               JOIN videos v ON v.id=f.video_id
               WHERE v.filename LIKE ? AND b.side=? AND f.cumulative_pan_px IS NOT NULL""",
            (video_stem + ".%", side),
        )
        best = None
        best_dist = None
        for r in rows:
            if int(r["bag_id"]) in exclude_bag_ids:
                continue
            d = abs(float(r["cumulative_pan_px"]) - target_pan_px)
            if d <= tolerance_px and (best_dist is None or d < best_dist):
                best, best_dist = r, d
        return best

    def upsert_bag(self, **b: Any) -> int:
        b.setdefault("track_match_score", 0.0)
        b.setdefault("is_track_best", 0)
        b.setdefault("seam_prominence", None)
        b.setdefault("seam_position", None)
        self.conn.execute(
            """INSERT INTO bags(frame_id,bag_index_in_frame,side,crop_path,y1,y2,segment_confidence,quality_score,track_key,track_match_score,is_track_best,seam_prominence,seam_position)
               VALUES(:frame_id,:bag_index_in_frame,:side,:crop_path,:y1,:y2,:segment_confidence,:quality_score,:track_key,:track_match_score,:is_track_best,:seam_prominence,:seam_position)
               ON CONFLICT(frame_id,bag_index_in_frame) DO UPDATE SET
               side=excluded.side,crop_path=excluded.crop_path,y1=excluded.y1,y2=excluded.y2,
               segment_confidence=excluded.segment_confidence,quality_score=excluded.quality_score,
               track_key=excluded.track_key,track_match_score=excluded.track_match_score,
               is_track_best=excluded.is_track_best,seam_prominence=excluded.seam_prominence,
               seam_position=excluded.seam_position""", b)
        row = self.conn.execute("SELECT id FROM bags WHERE frame_id=? AND bag_index_in_frame=?", (b["frame_id"], b["bag_index_in_frame"])).fetchone()
        return int(row["id"])

    def update_bag_tracking(self, bag_id: int, track_key: str, match_score: float, is_track_best: int = 0) -> None:
        self.conn.execute(
            "UPDATE bags SET track_key=?,track_match_score=?,is_track_best=? WHERE id=?",
            (track_key, match_score, is_track_best, bag_id),
        )

    def set_track_best_flags(self, best_map: dict[int, bool]) -> None:
        if not best_map:
            return
        self.conn.executemany(
            "UPDATE bags SET is_track_best=? WHERE id=?",
            [(1 if flag else 0, bag_id) for bag_id, flag in best_map.items()],
        )

    def upsert_track(self, video_id: int, side: str, track_key: str, observation_count: int, best_bag_id: int, best_quality: float) -> None:
        self.conn.execute(
            """INSERT INTO bag_tracks(video_id,side,track_key,observation_count,best_bag_id,best_quality)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(track_key) DO UPDATE SET observation_count=excluded.observation_count,
               best_bag_id=excluded.best_bag_id,best_quality=excluded.best_quality""",
            (video_id, side, track_key, observation_count, best_bag_id, best_quality),
        )

    def upsert_ocr(self, **o: Any) -> int:
        o.setdefault("sheet_index", 0)
        o.setdefault("seam_side", None)
        self.conn.execute(
            """INSERT INTO ocr_results(bag_id,sheet_index,raw_text,normalized_text,mean_confidence,word_count,
               processed_image_path,drug_name,dose_value,dose_unit,needs_review,seam_side)
               VALUES(:bag_id,:sheet_index,:raw_text,:normalized_text,:mean_confidence,:word_count,
               :processed_image_path,:drug_name,:dose_value,:dose_unit,:needs_review,:seam_side)
               ON CONFLICT(bag_id,sheet_index) DO UPDATE SET
               raw_text=excluded.raw_text,normalized_text=excluded.normalized_text,
               mean_confidence=excluded.mean_confidence,word_count=excluded.word_count,
               processed_image_path=excluded.processed_image_path,drug_name=excluded.drug_name,
               dose_value=excluded.dose_value,dose_unit=excluded.dose_unit,needs_review=excluded.needs_review,
               seam_side=excluded.seam_side""", o)
        row = self.conn.execute(
            "SELECT id FROM ocr_results WHERE bag_id=? AND sheet_index=?", (o["bag_id"], o["sheet_index"])
        ).fetchone()
        return int(row["id"])

    def update_bag_seam(
        self, bag_id: int, seam_prominence: float | None, seam_position: float | None,
        all_seam_positions: list[float] | None = None,
    ) -> None:
        """Actualiza la costura detectada de una bolsa con el valor calculado
        en el momento del OCR (sobre la misma imagen que usó el parseo, ver
        3.11) — para que la app de revisión pueda dibujar exactamente la
        misma línea que decidió el reparto de líneas, no un cálculo aparte
        que podría no coincidir.

        `all_seam_positions`: TODAS las costuras encontradas (no solo la
        primera/más marcada de `seam_position`) — necesario para fotos con
        3+ bolsitas (2+ costuras). Ver docs/cuaderno_ingenieria_3.26.md.
        """
        self.conn.execute(
            "UPDATE bags SET seam_prominence=?, seam_position=?, seam_positions_json=? WHERE id=?",
            (seam_prominence, seam_position, json.dumps(all_seam_positions or []), bag_id),
        )

    def get_bag_seam_positions(self, bag_id: int) -> list[float]:
        """Todas las costuras detectadas para una bolsa (lista, puede tener
        0, 1 o varias). Antes de 3.26 solo existía `seam_position` (la
        primera); esto es compatible con bolsas antiguas sin
        `seam_positions_json` (devuelve lista vacía o con 1 elemento según
        lo que haya)."""
        row = self.conn.execute(
            "SELECT seam_position, seam_positions_json FROM bags WHERE id=?", (bag_id,)
        ).fetchone()
        if not row:
            return []
        if row["seam_positions_json"]:
            try:
                positions = json.loads(row["seam_positions_json"])
                if positions:
                    return [float(p) for p in positions]
            except (ValueError, TypeError):
                pass
        return [float(row["seam_position"])] if row["seam_position"] is not None else []

    def upsert_label_header(self, ocr_result_id: int, **h: Any) -> None:
        h["ocr_result_id"] = ocr_result_id
        for key in ("patient_name", "patient_location", "dose_weekday", "dose_date", "dose_slot"):
            h.setdefault(key, None)
        self.conn.execute(
            """INSERT INTO label_headers(ocr_result_id,patient_name,patient_location,dose_weekday,dose_date,dose_slot)
               VALUES(:ocr_result_id,:patient_name,:patient_location,:dose_weekday,:dose_date,:dose_slot)
               ON CONFLICT(ocr_result_id) DO UPDATE SET
               patient_name=excluded.patient_name,patient_location=excluded.patient_location,
               dose_weekday=excluded.dose_weekday,dose_date=excluded.dose_date,dose_slot=excluded.dose_slot""", h)

    def replace_label_items(self, ocr_result_id: int, items: list[dict[str, Any]]) -> None:
        """Sustituye por completo los fármacos OCR de una bolsita (delete+insert).

        Más simple y seguro que intentar diferenciar altas/bajas/cambios línea
        a línea: cada ejecución del pipeline sobre un mismo bag_id relee el
        crop entero, así que el conjunto de items siempre se recalcula desde
        cero, no se parchea incrementalmente.
        """
        self.conn.execute("DELETE FROM label_items WHERE ocr_result_id=?", (ocr_result_id,))
        if not items:
            return
        self.conn.executemany(
            """INSERT INTO label_items(ocr_result_id,line_index,quantity,drug_name,dose_value,dose_unit,raw_line)
               VALUES(:ocr_result_id,:line_index,:quantity,:drug_name,:dose_value,:dose_unit,:raw_line)""",
            [{**item, "ocr_result_id": ocr_result_id} for item in items],
        )

    def get_pill_observations_for_video(self, video_stem: str) -> list[dict[str, Any]]:
        """Todas las observaciones (lado pastilla) de un vídeo, ordenadas por
        frame_index, con su prominencia de costura precalculada — la materia
        prima para agrupar por zona de transición en vez de por track visual
        (ver pairing/seam_grouping.py)."""
        rows = self.export_query_params(
            """SELECT b.id AS bag_id, b.quality_score, b.crop_path, b.seam_prominence, b.seam_position,
                      f.frame_index
               FROM bags b
               JOIN frames f ON f.id=b.frame_id
               JOIN videos v ON v.id=f.video_id
               WHERE v.filename LIKE ? AND b.side='pill_side'
               ORDER BY f.frame_index""",
            (video_stem + ".%",),
        )
        max_frame_index = max([int(r["frame_index"]) for r in rows] or [1])
        for r in rows:
            r["center_norm"] = float(r["frame_index"]) / max(1, max_frame_index)
        return rows

    def get_ocr_observations_for_video(self, video_stem: str) -> list[dict[str, Any]]:
        """Todas las observaciones OCR de un vídeo (cualquier lado — desde
        2.9 el lado pastilla también puede tener OCR, del texto reflejado
        por transparencia), con su posición en el frame y calidad. Materia
        prima para agrupar por cabecera (ver pairing/header_grouping.py).
        """
        rows = self.export_query_params(
            """SELECT b.id AS bag_id, o.id AS ocr_result_id, o.mean_confidence,
                      ((b.y1+b.y2)/2.0) AS center_value, b.quality_score, b.crop_path,
                      f.frame_index
               FROM bags b
               JOIN frames f ON f.id=b.frame_id
               JOIN videos v ON v.id=f.video_id
               JOIN ocr_results o ON o.bag_id=b.id
               WHERE v.filename LIKE ?
               ORDER BY center_value""",
            (video_stem + ".%",),
        )
        max_center = max([float(r["center_value"]) for r in rows] or [1.0])
        max_frame_index = max([int(r["frame_index"]) for r in rows] or [1])
        for r in rows:
            # Con bag_splitting.max_segments=1, cada bolsa ocupa casi todo el
            # frame -> la posición Y dentro del frame (y1+y2)/2 es casi
            # idéntica siempre y ya no sirve para ordenar. El número de frame
            # sí refleja el orden real en el que la cámara pasó por cada
            # bolsita a lo largo del vídeo (ver docs/cuaderno_ingenieria_2.0.md).
            r["center_norm"] = float(r["frame_index"]) / max(1, max_frame_index)
            r["y_center_norm"] = float(r["center_value"]) / max_center
            ocr_id = int(r["ocr_result_id"])
            r["header"] = self.get_label_header(ocr_id)
            r["items"] = self.get_label_items(ocr_id)
        return rows

    def get_label_items(self, ocr_result_id: int) -> list[dict[str, Any]]:
        return self.export_query_params(
            "SELECT * FROM label_items WHERE ocr_result_id=? ORDER BY line_index", (ocr_result_id,)
        )

    def get_label_header(self, ocr_result_id: int) -> dict[str, Any] | None:
        rows = self.export_query_params(
            "SELECT * FROM label_headers WHERE ocr_result_id=?", (ocr_result_id,)
        )
        return rows[0] if rows else None

    def mark_best_bags(self, limit_per_video_side: int = 20) -> int:
        self.conn.execute("UPDATE bags SET selected=0")
        rows = self.conn.execute(
            """SELECT b.id,v.id AS video_id,b.side,b.is_track_best,
                      (0.55*b.quality_score+0.30*b.segment_confidence+0.15*b.track_match_score) AS score
               FROM bags b JOIN frames f ON f.id=b.frame_id JOIN videos v ON v.id=f.video_id
               ORDER BY v.id,b.side,b.is_track_best DESC,score DESC"""
        ).fetchall()
        counts: dict[tuple[int,str], int] = {}
        selected: list[int] = []
        for row in rows:
            key=(int(row["video_id"]), str(row["side"]))
            if counts.get(key,0) < limit_per_video_side:
                selected.append(int(row["id"])); counts[key]=counts.get(key,0)+1
        self.conn.executemany("UPDATE bags SET selected=1 WHERE id=?", [(x,) for x in selected])
        self.conn.commit()
        return len(selected)

    def upsert_track_pair(self, **p: Any) -> int:
        p.setdefault("label_ocr_result_id", None)
        p.setdefault("pill_ocr_result_id", None)
        self.conn.execute(
            """INSERT INTO track_pairs(pair_key,pill_track_key,label_track_key,pill_best_bag_id,
               label_best_bag_id,label_ocr_result_id,pill_ocr_result_id,order_index,match_score,status,
               drug_name,dose_value,dose_unit,ocr_confidence,needs_review)
               VALUES(:pair_key,:pill_track_key,:label_track_key,:pill_best_bag_id,:label_best_bag_id,
               :label_ocr_result_id,:pill_ocr_result_id,:order_index,:match_score,:status,:drug_name,
               :dose_value,:dose_unit,:ocr_confidence,:needs_review)
               ON CONFLICT(pair_key,order_index) DO UPDATE SET
               pill_track_key=excluded.pill_track_key,label_track_key=excluded.label_track_key,
               pill_best_bag_id=excluded.pill_best_bag_id,label_best_bag_id=excluded.label_best_bag_id,
               label_ocr_result_id=excluded.label_ocr_result_id,pill_ocr_result_id=excluded.pill_ocr_result_id,
               match_score=excluded.match_score,status=excluded.status,drug_name=excluded.drug_name,
               dose_value=excluded.dose_value,dose_unit=excluded.dose_unit,
               ocr_confidence=excluded.ocr_confidence,needs_review=excluded.needs_review""", p)
        row = self.conn.execute(
            "SELECT id FROM track_pairs WHERE pair_key=? AND order_index=?",
            (p["pair_key"], p["order_index"]),
        ).fetchone()
        return int(row["id"])

    def replace_pair_group_members(self, track_pair_id: int, side: str, bag_ids: list[int]) -> None:
        """Guarda TODAS las bolsas (fotos) que contribuyeron a un lado de un
        par, no solo la representante — para que la revisión humana pueda
        ver cada vista parcial que aportó texto/fármacos al grupo fusionado.
        """
        self.conn.execute(
            "DELETE FROM pair_group_members WHERE track_pair_id=? AND side=?", (track_pair_id, side)
        )
        if bag_ids:
            self.conn.executemany(
                "INSERT OR IGNORE INTO pair_group_members(track_pair_id,side,bag_id) VALUES(?,?,?)",
                [(track_pair_id, side, bag_id) for bag_id in bag_ids],
            )

    def get_pair_group_images(self, track_pair_id: int, side: str) -> list[dict[str, Any]]:
        """Como get_pair_group_image_paths(), pero con la costura de cada
        foto (si la tiene) para poder dibujarla en la app de revisión
        (3.12). Desde 3.26 incluye TODAS las costuras encontradas
        (`seam_positions`, lista), no solo la primera — necesario para
        fotos con 3+ bolsitas.
        """
        rows = self.export_query_params(
            """SELECT b.crop_path, b.seam_position, b.seam_positions_json FROM pair_group_members m
               JOIN bags b ON b.id=m.bag_id
               WHERE m.track_pair_id=? AND m.side=?
               ORDER BY b.id""",
            (track_pair_id, side),
        )
        result = []
        for r in rows:
            positions: list[float] = []
            if r["seam_positions_json"]:
                try:
                    positions = [float(p) for p in json.loads(r["seam_positions_json"])]
                except (ValueError, TypeError):
                    positions = []
            if not positions and r["seam_position"] is not None:
                positions = [float(r["seam_position"])]
            result.append({
                "crop_path": str(r["crop_path"]), "seam_position": r["seam_position"],
                "seam_positions": positions,
            })
        return result

    def get_pair_group_image_paths(self, track_pair_id: int, side: str) -> list[str]:
        rows = self.export_query_params(
            """SELECT b.crop_path FROM pair_group_members m
               JOIN bags b ON b.id=m.bag_id
               WHERE m.track_pair_id=? AND m.side=?
               ORDER BY b.id""",
            (track_pair_id, side),
        )
        return [str(r["crop_path"]) for r in rows]


    def list_pairs_for_review(
        self, decision_filter: str | None = None, status_filter: str | None = None,
        sample_size: int | None = None, hide_empty: bool = True,
    ) -> list[dict[str, Any]]:
        """Lista de pares para la app de revisión.

        `decision_filter`: por decisión humana ya tomada (pending/all/
        accepted/corrected/rejected) — el filtro que ya existía.
        `status_filter`: por el estado que puso el propio pipeline
        (paired/review/unmatched_label/unmatched_pill) — para poder revisar
        solo, por ejemplo, los `unmatched_label` (donde de verdad hace
        falta ojo humano) sin mezclarlos con los `paired` (coincidencia
        directa ya verificada por contenido).
        `sample_size`: si se da, devuelve como mucho esa cantidad elegida al
        azar del resultado filtrado — para poder revisar una MUESTRA de los
        `paired` (p.ej. 20-25) en vez de los cientos que puede haber,
        cuando la certeza estructural ya es alta y no hace falta revisar
        cada uno.
        `hide_empty`: por defecto True — oculta lecturas sin NINGÚN fármaco
        reconocido (ruido de OCR: un trozo de pie de farmacia o de código
        QR mal leído como si fuera una cabecera). No hay nada que revisar
        ahí — con datos reales, más de la mitad de los pares marcados
        "necesita revisión" no tenían ningún contenido que confirmar (ver
        docs/cuaderno_ingenieria_3.17.md).
        """
        sql = """
        SELECT tp.id AS track_pair_id,tp.pair_key,tp.order_index,tp.status,tp.match_score,
               tp.ocr_confidence,tp.needs_review,
               pb.crop_path AS pill_image_path,lb.crop_path AS label_image_path,
               lb.seam_position AS label_seam_position,
               pb.seam_position AS pill_seam_position,
               tp.label_ocr_result_id,tp.pill_ocr_result_id,
               orl.seam_side AS label_seam_side,
               orp.seam_side AS pill_seam_side,
               (SELECT COUNT(*) FROM label_items li WHERE li.ocr_result_id=tp.label_ocr_result_id) AS item_count,
               pr.decision,pr.reviewer_notes,pr.reviewed_at
        FROM track_pairs tp
        LEFT JOIN bags pb ON pb.id=tp.pill_best_bag_id
        LEFT JOIN bags lb ON lb.id=tp.label_best_bag_id
        LEFT JOIN ocr_results orl ON orl.id=tp.label_ocr_result_id
        LEFT JOIN ocr_results orp ON orp.id=tp.pill_ocr_result_id
        LEFT JOIN pair_reviews pr ON pr.track_pair_id=tp.id
        """
        conditions: list[str] = []
        params: list[Any] = []
        if decision_filter == "pending":
            conditions.append("(pr.decision IS NULL OR pr.decision='pending')")
        elif decision_filter and decision_filter != "all":
            conditions.append("pr.decision=?")
            params.append(decision_filter)
        if status_filter and status_filter != "all":
            conditions.append("tp.status=?")
            params.append(status_filter)
        if hide_empty:
            conditions.append(
                "(SELECT COUNT(*) FROM label_items li WHERE li.ocr_result_id=tp.label_ocr_result_id) > 0"
            )
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY tp.pair_key,tp.order_index"
        rows = self.export_query_params(sql, tuple(params))
        if sample_size is not None and len(rows) > sample_size:
            rows = random.sample(rows, sample_size)
            rows.sort(key=lambda r: (r["pair_key"], r["order_index"]))
        return rows

    def save_pair_review(self, track_pair_id: int, decision: str, notes: str = "") -> None:
        self.conn.execute(
            """INSERT INTO pair_reviews(track_pair_id,decision,reviewer_notes,reviewed_at)
               VALUES(?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(track_pair_id) DO UPDATE SET decision=excluded.decision,
                   reviewer_notes=excluded.reviewer_notes,reviewed_at=CURRENT_TIMESTAMP""",
            (track_pair_id, decision, notes),
        )
        final_review = 0 if decision in {"accepted", "corrected"} else 1
        # No se toca track_pairs.status aquí -- antes se sobrescribía con la
        # propia decisión ("accepted"/"corrected"/...), perdiendo el origen
        # real del pipeline (paired/position_matched/review/...). La
        # decisión ya vive en pair_reviews.decision, por separado; status
        # debe seguir reflejando SIEMPRE de dónde vino el par, no si ya se
        # revisó (ver docs/cuaderno_ingenieria_3.34.md).
        self.conn.execute(
            "UPDATE track_pairs SET needs_review=? WHERE id=?",
            (final_review, track_pair_id),
        )
        self.conn.commit()

    def save_pair_review_items(self, track_pair_id: int, items: list[dict[str, Any]]) -> None:
        """Guarda la lista de fármacos corregida por el humano para un par.

        No sobrescribe label_items (el OCR crudo, ver replace_label_items):
        es una capa de corrección aparte, consistente con cómo pair_reviews ya
        trataba a ocr_results antes de este cambio.
        """
        self.conn.execute("DELETE FROM pair_review_items WHERE track_pair_id=?", (track_pair_id,))
        if items:
            self.conn.executemany(
                """INSERT INTO pair_review_items(track_pair_id,line_index,quantity,drug_name,dose_value,dose_unit)
                   VALUES(:track_pair_id,:line_index,:quantity,:drug_name,:dose_value,:dose_unit)""",
                [{**item, "track_pair_id": track_pair_id} for item in items],
            )
        self.conn.commit()

    def export_reviews(self) -> list[dict[str, Any]]:
        """Exporta TODAS las decisiones de revisión humana ya guardadas
        (`pair_reviews` + `pair_review_items`), con suficiente contexto de
        CONTENIDO (vídeo de etiqueta + cabecera: día/fecha/franja) para
        poder volver a emparejarlas después de un `--fresh` — que borra la
        base entera, incluidos `track_pair_id`, así que esos identificadores
        no sirven para volver a encontrar el mismo par tras reprocesar (ver
        docs/cuaderno_ingenieria_3.27.md).

        Se ancla por el vídeo de ETIQUETA + cabecera, no por el de
        pastilla: la etiqueta es la que de verdad identifica qué bolsita
        real es (misma paciente, misma fecha, misma franja), mientras que
        qué foto de pastilla se le asigna puede cambiar de una ejecución a
        otra sin que la bolsita en sí haya cambiado.
        """
        rows = self.export_query_params(
            """SELECT pr.track_pair_id, pr.decision, pr.reviewer_notes, pr.reviewed_at,
                      lv.filename AS label_video_filename,
                      h.dose_weekday, h.dose_date, h.dose_slot
               FROM pair_reviews pr
               JOIN track_pairs tp ON tp.id = pr.track_pair_id
               LEFT JOIN bags lb ON lb.id = tp.label_best_bag_id
               LEFT JOIN frames lf ON lf.id = lb.frame_id
               LEFT JOIN videos lv ON lv.id = lf.video_id
               LEFT JOIN label_headers h ON h.ocr_result_id = tp.label_ocr_result_id""",
            (),
        )
        result = []
        for r in rows:
            items_rows = self.export_query_params(
                "SELECT line_index, quantity, drug_name, dose_value, dose_unit "
                "FROM pair_review_items WHERE track_pair_id=? ORDER BY line_index",
                (r["track_pair_id"],),
            )
            result.append({
                "label_video_filename": r["label_video_filename"],
                "dose_weekday": r["dose_weekday"], "dose_date": r["dose_date"], "dose_slot": r["dose_slot"],
                "decision": r["decision"], "reviewer_notes": r["reviewer_notes"], "reviewed_at": r["reviewed_at"],
                "items": [dict(it) for it in items_rows],
            })
        return result

    def import_reviews(self, records: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
        """Reaplica decisiones de revisión exportadas con `export_reviews()`
        sobre la base actual (normalmente tras un `--fresh` +
        `rebuild-pairs`) — buscando el par NUEVO cuyo vídeo de etiqueta y
        cabecera (día/fecha/franja) coincidan con los del registro
        exportado, no por `track_pair_id` (que ya no es el mismo).

        Devuelve (encontrados, lista de no encontrados) — los no
        encontrados no se pierden silenciosamente, para poder avisar de
        cuáles no se pudieron reaplicar (p.ej. una bolsita que antes se
        leía con una cabecera y ahora, tras el reproceso, se lee de otra
        forma).
        """
        matched = 0
        unmatched: list[dict[str, Any]] = []
        for rec in records:
            if not rec.get("label_video_filename"):
                unmatched.append(rec)
                continue
            row = self.conn.execute(
                """SELECT tp.id FROM track_pairs tp
                   LEFT JOIN bags lb ON lb.id = tp.label_best_bag_id
                   LEFT JOIN frames lf ON lf.id = lb.frame_id
                   LEFT JOIN videos lv ON lv.id = lf.video_id
                   LEFT JOIN label_headers h ON h.ocr_result_id = tp.label_ocr_result_id
                   WHERE lv.filename=? AND h.dose_weekday IS ? AND h.dose_date IS ? AND h.dose_slot IS ?""",
                (rec["label_video_filename"], rec.get("dose_weekday"), rec.get("dose_date"), rec.get("dose_slot")),
            ).fetchone()
            if not row:
                unmatched.append(rec)
                continue
            new_track_pair_id = int(row["id"])
            self.save_pair_review(new_track_pair_id, rec["decision"], rec.get("reviewer_notes") or "")
            if rec.get("items"):
                self.save_pair_review_items(new_track_pair_id, rec["items"])
            matched += 1
        return matched, unmatched

    def get_pair_review_items(self, track_pair_id: int) -> list[dict[str, Any]]:
        return self.export_query_params(
            "SELECT * FROM pair_review_items WHERE track_pair_id=? ORDER BY line_index", (track_pair_id,)
        )

    def export_training_dataset(
        self, exclude_rejected: bool = True, exclude_empty: bool = True,
    ) -> list[dict[str, Any]]:
        """Exporta el dataset final para el módulo de segmentación de
        pastilla — un registro por bolsita real (`track_pair`), con TODAS
        sus fotos de pastilla (no solo la representante), su lista de
        fármacos final (la corregida por un humano si existe, si no la del
        OCR), y la procedencia completa (estado del pipeline + decisión
        humana). Formato acordado con el chat del módulo de segmentación,
        ver docs/cuaderno_ingenieria_3.34.md.

        `exclude_rejected`: no incluye bolsitas que un humano marcó como
        `rejected` en la revisión — el propio revisor decidió que esos
        datos no son de fiar.
        `exclude_empty`: no incluye bolsitas sin ningún fármaco en su
        lista final (ni corregido, ni de OCR) — no aportan nada al
        entrenamiento, mismo criterio que "Ocultar lecturas sin ningún
        fármaco" en la app de revisión (3.17).
        """
        rows = self.export_query_params(
            """SELECT tp.id AS track_pair_id, tp.pair_key, tp.order_index, tp.status, tp.match_score,
                      tp.label_ocr_result_id,
                      h.dose_weekday, h.dose_date, h.dose_slot, h.patient_name,
                      pr.decision, pr.reviewer_notes, pr.reviewed_at
               FROM track_pairs tp
               LEFT JOIN label_headers h ON h.ocr_result_id = tp.label_ocr_result_id
               LEFT JOIN pair_reviews pr ON pr.track_pair_id = tp.id
               ORDER BY tp.pair_key, tp.order_index""",
            (),
        )
        result = []
        for r in rows:
            decision = r["decision"]
            if exclude_rejected and decision == "rejected":
                continue

            review_items = self.get_pair_review_items(int(r["track_pair_id"]))
            if review_items:
                label_items = [
                    {"drug_name": it["drug_name"], "quantity": it["quantity"],
                     "dose_value": it["dose_value"], "dose_unit": it["dose_unit"]}
                    for it in review_items
                ]
                label_source = "human_corrected"
            else:
                ocr_items = self.get_label_items(int(r["label_ocr_result_id"])) if r["label_ocr_result_id"] else []
                label_items = [
                    {"drug_name": it["drug_name"], "quantity": it["quantity"],
                     "dose_value": it["dose_value"], "dose_unit": it["dose_unit"]}
                    for it in ocr_items
                ]
                label_source = "ocr_raw"

            if exclude_empty and not label_items:
                continue

            pill_photos = self.get_pair_group_images(int(r["track_pair_id"]), "pill")
            result.append({
                "pair_key": r["pair_key"],
                "order_index": r["order_index"],
                "pipeline_status": r["status"],
                "match_score": r["match_score"],
                "review": {
                    "decision": decision,
                    "reviewer_notes": r["reviewer_notes"],
                    "reviewed_at": r["reviewed_at"],
                },
                "patient_context": {
                    "patient_name": r["patient_name"],
                    "weekday": r["dose_weekday"],
                    "date": r["dose_date"],
                    "slot": r["dose_slot"],
                },
                "label_items": label_items,
                "label_source": label_source,
                "pill_photos": [
                    {
                        "crop_path": p["crop_path"],
                        "seam_position": p["seam_position"],
                        "seam_positions": p["seam_positions"],
                    }
                    for p in pill_photos
                ],
            })
        return result

    def review_summary(self) -> dict[str, int]:
        rows=self.conn.execute("SELECT decision,COUNT(*) AS n FROM pair_reviews GROUP BY decision").fetchall()
        result={str(r['decision']): int(r['n']) for r in rows}
        total=int(self.conn.execute("SELECT COUNT(*) AS n FROM track_pairs").fetchone()['n'])
        reviewed=sum(result.values())
        result['total']=total; result['reviewed']=reviewed; result['pending']=total-reviewed+result.get('pending',0)
        return result

    def export_query_params(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def export_query(self, sql: str) -> list[dict[str, Any]]:
        return self.export_query_params(sql)
