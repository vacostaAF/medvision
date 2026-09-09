"""Prueba de PaddleOCR + parser de bolsita SPD contra un vídeo completo,
usando el código REAL del proyecto (no una reimplementación aparte).

Requiere lanzarse desde dentro de medvision-ai-dataset-builder/ (necesita
importar el paquete src/medvision).

Uso:
    python smoke_test_paddleocr.py ruta/al/video.MOV
    python smoke_test_paddleocr.py ruta/al/video.MOV --every-seconds 1.5 --max-frames 12
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_path", help="Ruta al vídeo (.MOV/.mp4/...)")
    parser.add_argument("--every-seconds", type=float, default=2.0)
    parser.add_argument("--max-frames", type=int, default=8)
    parser.add_argument("--lang", default="es")
    parser.add_argument("--min-score", type=float, default=0.5)
    return parser.parse_args()


def sample_frames(video_path: str, every_seconds: float, max_frames: int):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"FALLO: no se pudo abrir el vídeo '{video_path}'.")
        sys.exit(1)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"   Vídeo: {fps:.1f} fps, {total_frames} frames, {total_frames / fps:.1f}s")
    step = max(1, int(round(fps * every_seconds)))
    frame_index, yielded = 0, 0
    while yielded < max_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            break
        yield frame_index, frame_index / fps, frame
        yielded += 1
        frame_index += step
    cap.release()


def main() -> None:
    args = parse_args()

    print("1) Importando el módulo OCR real del proyecto...")
    t0 = time.time()
    try:
        from medvision.ocr.label_ocr import PaddleLabelOCR
        from medvision.ocr.parser import parse_label_sheet
    except ImportError as exc:
        print(f"FALLO al importar: {exc}")
        print("-> ¿Estás lanzando esto desde dentro de medvision-ai-dataset-builder/?")
        print("-> ¿Está paddleocr instalado en el venv activo?")
        sys.exit(1)
    print(f"   OK ({time.time() - t0:.1f}s)")

    print("2) Inicializando PaddleOCR (descarga modelos la primera vez, necesita red)...")
    t0 = time.time()
    try:
        engine = PaddleLabelOCR.get(lang=args.lang)
    except Exception as exc:
        print(f"FALLO al inicializar: {exc}")
        sys.exit(1)
    print(f"   OK ({time.time() - t0:.1f}s)")

    print(f"3) Muestreando frames de {args.video_path} (cada {args.every_seconds}s, máx {args.max_frames})...")
    frames_ok = frames_failed = frames_with_items = 0
    total_time = 0.0

    for frame_index, ts, frame in sample_frames(args.video_path, args.every_seconds, args.max_frames):
        label = f"frame {frame_index} (t={ts:.1f}s)"
        t0 = time.time()
        try:
            result = engine.read(frame, min_score=args.min_score)
        except Exception as exc:
            frames_failed += 1
            print(f"\n--- {label}: FALLO en read(): {exc}")
            continue
        elapsed = time.time() - t0
        total_time += elapsed
        frames_ok += 1

        sheet = parse_label_sheet(result.words)
        print(f"\n--- {label}  ({elapsed:.1f}s, confianza {result.mean_confidence:.1f}) ---")
        print(f"    Líneas OCR reconstruidas: {result.words}")
        if sheet.header.patient_name or sheet.header.dose_slot:
            print(f"    Cabecera: {sheet.header}")
        if sheet.items:
            frames_with_items += 1
            print(f"    Fármacos reconocidos ({len(sheet.items)}):")
            for it in sheet.items:
                print(f"      - {it.drug_name}: {it.dose_value} {it.dose_unit} (cantidad={it.quantity})")
        else:
            print("    (sin fármacos reconocidos en este frame)")

    print("\n=== RESUMEN ===")
    print(f"Frames procesados: {frames_ok} OK, {frames_failed} con fallo")
    print(f"Frames con al menos 1 fármaco reconocido: {frames_with_items}/{frames_ok}")
    if frames_ok:
        print(f"Tiempo medio por frame: {total_time / frames_ok:.2f}s")
    if frames_failed:
        print("\nHubo fallos. Revisa los mensajes de arriba.")
    elif frames_with_items == 0:
        print("\nNingún frame dio fármacos reconocidos. Si el texto SÍ aparece en 'Líneas OCR "
              "reconstruidas' pero sheet.items sale vacío, mándame esa salida: es un caso que el "
              "parser no cubre todavía, no un problema de instalación.")
    else:
        print("\nFunciona de punta a punta con el código real del proyecto.")


if __name__ == "__main__":
    main()
