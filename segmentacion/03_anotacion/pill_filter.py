"""
Prototipo de filtro post-segmentación: separa candidatos "pastilla real" de
falsos positivos (QR, borde de bolsa, texto impreso) sobre las máscaras que
devuelve un segmentador class-agnostic (FastSAM aquí como proxy de SAM2).

Features por máscara (todas calculables sin entrenar nada):
  - area_frac: área de la máscara / área total de la imagen
  - aspect_ratio: lado largo / lado corto del bounding box
  - extent: área de la máscara / área del bounding box (qué tan "rellena" está
    la caja - una pastilla ovalada/redonda rellena bien su caja, un borde de
    bolsa muy fino no)
  - texture: varianza del Laplaciano en escala de grises, calculada SOLO
    dentro de la máscara. Un QR o un bloque de texto impreso tiene muchísimo
    detalle de alta frecuencia (blanco/negro alternando); la superficie de
    una pastilla, incluso con glare, es mucho más lisa.
"""
import cv2
import numpy as np
from pathlib import Path
from ultralytics import FastSAM


def mask_features(mask, img_gray, img_area):
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    w, h = (x1 - x0 + 1), (y1 - y0 + 1)
    bbox_area = w * h
    mask_area = mask.sum()
    aspect = max(w, h) / max(1, min(w, h))
    extent = mask_area / max(1, bbox_area)
    area_frac = mask_area / img_area
    region = img_gray[y0:y1 + 1, x0:x1 + 1]
    region_mask = mask[y0:y1 + 1, x0:x1 + 1]
    if region_mask.sum() < 10:
        texture = 0.0
    else:
        lap = cv2.Laplacian(region, cv2.CV_64F)
        texture = float(lap[region_mask].var())
    return dict(area_frac=area_frac, aspect=aspect, extent=extent, texture=texture,
                bbox=(x0, y0, x1, y1))


def run(path, label_hint=""):
    img = cv2.imread(str(path))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]
    img_area = h * w
    results = model(str(path), device="cpu", retina_masks=True, imgsz=1024,
                     conf=0.35, iou=0.7, verbose=False)
    r = results[0]
    rows = []
    if r.masks is not None:
        confs = r.boxes.conf.cpu().numpy()
        for i, m in enumerate(r.masks.data.cpu().numpy()):
            mask = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST) > 0.5
            feat = mask_features(mask, gray, img_area)
            if feat is None:
                continue
            feat["conf"] = float(confs[i])
            feat["mask"] = mask
            rows.append(feat)
    print(f"\n--- {path.name} {label_hint} ---")
    print(f"{'#':<3}{'conf':<7}{'area%':<8}{'aspect':<8}{'extent':<8}{'texture':<10}")
    for i, f in enumerate(rows):
        print(f"{i:<3}{f['conf']:<7.2f}{f['area_frac']*100:<8.2f}{f['aspect']:<8.2f}{f['extent']:<8.2f}{f['texture']:<10.1f}")
    return img, rows


def is_pill(f):
    return (0.0015 <= f["area_frac"] <= 0.05 and f["aspect"] <= 3.0
            and f["extent"] <= 0.93 and f["texture"] <= 15)


def draw(img, rows):
    kept = img.copy()
    rejected = img.copy()
    for f in rows:
        x0, y0, x1, y1 = f["bbox"]
        ok = is_pill(f)
        target = kept if ok else rejected
        color = (0, 200, 0) if ok else (0, 0, 255)
        cv2.rectangle(target, (x0, y0), (x1, y1), color, 3)
    n_kept = sum(is_pill(f) for f in rows)
    n_rej = len(rows) - n_kept
    combo = np.hstack([kept, rejected])
    cv2.putText(combo, f"FILTRADAS: quedan {n_kept} de {len(rows)} candidatas",
                (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 3)
    cv2.putText(combo, f"FILTRADAS: quedan {n_kept} de {len(rows)} candidatas",
                (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 1)
    return combo, n_kept, len(rows)


if __name__ == "__main__":
    img_dir_a = Path(__file__).parent / "ejemplos" / "images"  # coloca aquí tus propias imágenes de prueba
    img_dir_b = Path(__file__).parent / "ejemplos" / "images_v2"
    out_dir = Path(__file__).parent / "filter_overlay"
    out_dir.mkdir(exist_ok=True)
    model = FastSAM("FastSAM-s.pt")

    test_cases = [
        (img_dir_a / "f000190_bag00.jpg", "(calibracion: 2 reales + 8 FP)"),
        (img_dir_a / "f000200_bag00.jpg", "(no visto: 9 reales amontonadas/sueltas + FP)"),
        (img_dir_b / "MVI_2801_f000200_bag00.jpg", "(no visto: 9+1 reales, caso extremo)"),
        (img_dir_b / "MVI_2732_f000240_bag00.jpg", "(no visto: 2+2 reales, caso limpio)"),
    ]
    summary = []
    for path, hint in test_cases:
        img, rows = run(path, hint)
        combo, n_kept, n_total = draw(img, rows)
        out_path = out_dir / f"filtered_{path.stem}.jpg"
        cv2.imwrite(str(out_path), combo)
        summary.append((path.name, n_total, n_kept))
    print("\n=== resumen ===")
    for name, total, kept in summary:
        print(f"{name:<32} candidatas={total:<4} tras_filtro={kept}")
