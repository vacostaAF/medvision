"""Genera una imagen por bolsita a partir de un vídeo de validación nunca
visto por el sistema, usando el pie de página de farmacia como punto de
corte por CONTENIDO (no la señal visual de costura, poco fiable a esta
precisión -- ver docs/cuaderno_ingenieria_3.36.md del proyecto).

Pensado para preparar el conjunto de prueba del módulo de segmentación,
no para el pipeline principal del Dataset Builder.

Requiere PaddleOCR instalado (mismo entorno que build-dataset).

Uso:
    python generar_bolsas_individuales.py <video.MOV> <carpeta_salida> [--rotar 90]
"""
import argparse
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from medvision.acquisition.video_reader import VideoReader
from medvision.ocr.label_ocr import read_label
from medvision.ocr.parser import find_complete_pouch_boundaries
from medvision.bags.pouch_cropping import crop_complete_pouches

_ROTATIONS = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE, -90: cv2.ROTATE_90_COUNTERCLOCKWISE}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("output_dir", type=Path)
    ap.add_argument("--rotar", type=int, default=90, help="Grados de rotación antes de leer (0 si no hace falta)")
    ap.add_argument("--paso", type=int, default=60,
                     help="Cada cuántos frames muestrear (60 por defecto -- con deduplicación por firma "
                          "de cabecera, un paso grande ya no arriesga perderse bolsitas, solo ahorra tiempo)")
    ap.add_argument("--flip", action="store_true", help="Voltear horizontalmente antes de OCR (lado pastilla)")
    ap.add_argument("--debug", action="store_true",
                     help="Imprime todo el texto y posiciones leídos por el OCR de cada fotograma, para diagnosticar")
    ap.add_argument("--margen", type=int, default=100,
                     help="Píxeles de margen arriba de cada recorte (100 por defecto)")
    ap.add_argument("--margen-abajo", type=int, default=200,
                     help="Píxeles de margen abajo de cada recorte (200 por defecto). Desde 3.45 hay un "
                          "límite de seguridad que impide colarse en la bolsita siguiente pase lo que pase "
                          "con este número, así que aquí se puede ser generoso sin riesgo")
    args = ap.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    reader = VideoReader(args.video)
    print(f"Vídeo: {reader.info.frame_count} fotogramas totales, {reader.info.fps:.1f} fps "
          f"({reader.info.duration_seconds:.1f}s) — muestreando cada {args.paso} fotogramas")

    total_bolsas = 0
    procesados = 0
    firmas_ya_guardadas: set[str] = set()
    for idx, _timestamp, frame in reader.iter_sampled(seconds_between_frames=args.paso / (reader.info.fps or 25.0)):
        procesados += 1
        print(f"  fotograma {idx}/{reader.info.frame_count} ({procesados} de la muestra): leyendo con OCR...",
              end="", flush=True)
        t0 = time.monotonic()
        if args.rotar:
            frame = cv2.rotate(frame, _ROTATIONS[args.rotar])
        ocr_input = cv2.flip(frame, 1) if args.flip else frame

        result = read_label(ocr_input)
        elapsed = time.monotonic() - t0
        print(f" {elapsed:.1f}s, {total_bolsas} bolsita(s) hasta ahora", flush=True)
        if args.debug:
            if not result.words:
                print("    [debug] el OCR no devolvió ninguna línea de texto en este fotograma")
            else:
                ys = result.word_y_norm or [None] * len(result.words)
                for line, y in zip(result.words, ys):
                    print(f"    [debug] y={y!r}  {line!r}")
        if result.word_y_norm and len(result.word_y_norm) == len(result.words):
            lines_with_y = list(zip(result.words, result.word_y_norm))
            boundaries = find_complete_pouch_boundaries(lines_with_y)
            nuevas = [b for b in boundaries if b[2] not in firmas_ya_guardadas]
            repetidas = len(boundaries) - len(nuevas)
            if args.debug:
                print(f"    [debug] {len(boundaries)} bolsita(s) completa(s) detectada(s) "
                      f"({repetidas} ya guardada(s) antes, se omiten): {boundaries}")
            elif repetidas:
                print(f"    ({repetidas} bolsita(s) repetida(s) de un fotograma anterior, omitida(s))")
            # Sobre la imagen ORIGINAL (sin el flip usado solo para el OCR),
            # para que el recorte se guarde tal y como se vería la bolsita.
            # Solo bolsitas COMPLETAS Y NUEVAS -- los fragmentos parciales
            # se descartan (ver docs/cuaderno_ingenieria_3.37.md), y las ya
            # guardadas antes se omiten para no repetir la misma bolsita
            # real decenas de veces con un paneo lento (ver
            # docs/cuaderno_ingenieria_3.40.md).
            crops = crop_complete_pouches(frame, nuevas, margin_px=args.margen, margin_bottom_px=args.margen_abajo)
            for crop, boundary in zip(crops, nuevas):
                firmas_ya_guardadas.add(boundary[2])
                out_path = args.output_dir / f"f{idx:06d}_bolsa{total_bolsas:04d}.jpg"
                cv2.imwrite(str(out_path), crop)
                total_bolsas += 1
        elif args.debug:
            print(f"    [debug] SALTADO: word_y_norm no disponible o de longitud distinta a words "
                  f"({len(result.word_y_norm or [])} posiciones vs {len(result.words)} líneas)")

    reader.close()
    print(f"{total_bolsas} imágenes de bolsita individual generadas en {args.output_dir}")


if __name__ == "__main__":
    main()
