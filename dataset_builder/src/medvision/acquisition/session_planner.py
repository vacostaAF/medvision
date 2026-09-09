from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi"}


@dataclass
class VideoCaptureInfo:
    path: Path
    capture_time: datetime
    time_source: str  # "metadata" | "mtime"


@dataclass
class SessionPlan:
    pair_key: str
    pill_video: str
    label_video: str
    pill_capture_time: datetime
    label_capture_time: datetime
    gap_seconds: float
    status: str  # "ok" | "needs_review"
    time_source: str
    reason: str = ""


def read_capture_time(video_path: Path) -> VideoCaptureInfo:
    """Lee el instante real de captura de un vídeo vía el metadato
    `creation_time` (ffprobe). Si no está disponible (o ffprobe falla), usa
    la fecha de modificación del fichero como aproximación — funciona si los
    vídeos no se han copiado/movido desde que se grabaron, pero es menos
    fiable que el metadato real.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time",
             "-of", "json", str(video_path)],
            capture_output=True, text=True, timeout=15, check=True,
        )
        data = json.loads(result.stdout)
        tag = data.get("format", {}).get("tags", {}).get("creation_time")
        if tag:
            ts = datetime.fromisoformat(tag.replace("Z", "+00:00"))
            return VideoCaptureInfo(path=video_path, capture_time=ts, time_source="metadata")
    except Exception:
        pass
    mtime = datetime.fromtimestamp(video_path.stat().st_mtime)
    return VideoCaptureInfo(path=video_path, capture_time=mtime, time_source="mtime")


def plan_sessions(video_paths: list[Path], max_gap_seconds: float = 120.0) -> list[SessionPlan]:
    """Empareja vídeos consecutivos en sesiones (pastilla, etiqueta),
    siguiendo el protocolo de grabación confirmado: primero la tira de
    pastillas, inmediatamente después la misma tira por el lado de la
    etiqueta, siempre en ese orden.

    Se ordena por instante de captura REAL (metadato del vídeo), no por
    nombre de fichero: distintas cámaras usan convenciones de nombre
    distintas (IMG_XXXX, MVI_XXXX...), así que el nombre no es una señal de
    orden fiable entre lotes de grabación mixtos.
    """
    infos = [read_capture_time(p) for p in video_paths]
    infos.sort(key=lambda i: i.capture_time)

    sessions: list[SessionPlan] = []
    i = 0
    session_index = 0
    while i + 1 < len(infos):
        pill, label = infos[i], infos[i + 1]
        gap = (label.capture_time - pill.capture_time).total_seconds()
        time_source = "metadata" if pill.time_source == "metadata" and label.time_source == "metadata" else "mtime"
        if gap < 0:
            status, reason = "needs_review", "la etiqueta se grabó antes que la pastilla (orden inesperado)"
        elif gap > max_gap_seconds:
            status, reason = "needs_review", f"hueco de {gap:.0f}s entre pastilla y etiqueta (> {max_gap_seconds:.0f}s esperado)"
        else:
            status, reason = "ok", ""
        sessions.append(SessionPlan(
            pair_key=f"session_{session_index:04d}",
            pill_video=pill.path.stem, label_video=label.path.stem,
            pill_capture_time=pill.capture_time, label_capture_time=label.capture_time,
            gap_seconds=gap, status=status, time_source=time_source, reason=reason,
        ))
        session_index += 1
        i += 2

    if i < len(infos):
        # Numero impar de videos: uno se queda sin pareja.
        orphan = infos[i]
        sessions.append(SessionPlan(
            pair_key=f"session_{session_index:04d}_incompleta",
            pill_video=orphan.path.stem, label_video="",
            pill_capture_time=orphan.capture_time, label_capture_time=orphan.capture_time,
            gap_seconds=0.0, status="needs_review",
            time_source=orphan.time_source,
            reason="numero impar de vídeos: este se quedó sin pareja",
        ))

    return sessions


def sessions_to_config_dict(sessions: list[SessionPlan]) -> dict:
    """Convierte el plan a la misma estructura video_sides/video_pairs que
    ya consume dataset/builder.py."""
    video_sides: dict[str, str] = {}
    video_pairs: list[dict] = []
    for s in sessions:
        video_sides[s.pill_video] = "pill_side"
        if s.label_video:
            video_sides[s.label_video] = "label_side"
            video_pairs.append({
                "pair_key": s.pair_key,
                "pill_video": s.pill_video,
                "label_video": s.label_video,
                "direction": "direct",
            })
    return {"video_sides": video_sides, "video_pairs": video_pairs}


def find_videos(videos_dir: Path) -> list[Path]:
    return sorted(p for p in videos_dir.iterdir() if p.suffix.lower() in VIDEO_EXTS)
