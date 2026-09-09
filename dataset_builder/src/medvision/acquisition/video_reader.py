from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import cv2

@dataclass(frozen=True)
class VideoInfo:
    path: Path
    fps: float
    frame_count: int
    width: int
    height: int
    duration_seconds: float

class VideoReader:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.cap = cv2.VideoCapture(str(self.path))
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir el vídeo: {self.path}")
        self.info = self._read_info()

    def _read_info(self) -> VideoInfo:
        fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = frame_count / fps if fps else 0.0
        return VideoInfo(self.path, fps, frame_count, width, height, duration)

    def read_frame(self, frame_index: int):
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = self.cap.read()
        if not ok:
            return None
        return frame

    def iter_sampled(self, seconds_between_frames: float = 1.0, max_frames: int | None = None):
        step = max(1, int(round(self.info.fps * seconds_between_frames))) if self.info.fps else 30
        count = 0
        for idx in range(0, self.info.frame_count, step):
            if max_frames is not None and count >= max_frames:
                break
            frame = self.read_frame(idx)
            if frame is None:
                continue
            yield idx, idx / self.info.fps if self.info.fps else 0.0, frame
            count += 1

    def close(self):
        self.cap.release()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
