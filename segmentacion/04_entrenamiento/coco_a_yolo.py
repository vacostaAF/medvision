"""
Convierte el export COCO de Label Studio (result.json) al formato que
espera YOLO11-seg para entrenar segmentación: una carpeta por split
(train/val) con imágenes + un .txt por imagen (una línea por instancia,
con el polígono normalizado 0-1), más un data.yaml apuntando a todo.

Uso:
    python coco_a_yolo.py

Ajusta las rutas de la sección "RUTAS A CONFIGURAR" a tu entorno antes
de lanzarlo.
"""
import json
import random
import shutil
from pathlib import Path

# --- RUTAS A CONFIGURAR ---
COCO_JSON = Path(__file__).parent / "result.json"          # el result.json del export COCO
DATASET_DIR = Path(__file__).parent / "dataset_package"     # la carpeta con bags/ (para resolver las imágenes reales)
OUT_DIR = Path(__file__).parent / "yolo_dataset"            # carpeta de salida, se crea sola
VAL_FRACTION = 0.15   # ~15% para validación, no entra en el entrenamiento
SEED = 42


def ruta_relativa_real(file_name_coco: str) -> str:
    """El file_name de Label Studio trae rutas largas tipo
    '..\\..\\..\\medvision\\...\\dataset_package\\bags\\pill_side\\X.jpg'
    -- nos quedamos solo con la parte que empieza en 'bags/'."""
    fn = file_name_coco.replace("\\", "/")
    idx = fn.find("bags/")
    return fn[idx:]


def poligono_normalizado(segmentation_flat: list, w: int, h: int) -> list:
    """[x1,y1,x2,y2,...] en píxeles -> normalizado 0-1, formato YOLO-seg."""
    puntos = []
    for i in range(0, len(segmentation_flat), 2):
        x, y = segmentation_flat[i], segmentation_flat[i + 1]
        puntos.append(x / w)
        puntos.append(y / h)
    return puntos


def main():
    coco = json.load(open(COCO_JSON, encoding="utf-8"))
    images_by_id = {im["id"]: im for im in coco["images"]}
    anns_by_image = {}
    for a in coco["annotations"]:
        anns_by_image.setdefault(a["image_id"], []).append(a)

    ids = list(images_by_id.keys())
    random.Random(SEED).shuffle(ids)
    n_val = max(1, int(len(ids) * VAL_FRACTION))
    val_ids = set(ids[:n_val])

    for split in ("train", "val"):
        (OUT_DIR / split / "images").mkdir(parents=True, exist_ok=True)
        (OUT_DIR / split / "labels").mkdir(parents=True, exist_ok=True)

    faltantes = 0
    for img_id, im in images_by_id.items():
        split = "val" if img_id in val_ids else "train"
        ruta_rel = ruta_relativa_real(im["file_name"])
        origen = DATASET_DIR / ruta_rel
        if not origen.is_file():
            faltantes += 1
            print(f"  aviso: no encontrada {origen}")
            continue

        # nombre de fichero plano (sin subcarpetas) para evitar colisiones
        nombre_plano = ruta_rel.replace("/", "__")
        destino_img = OUT_DIR / split / "images" / nombre_plano
        shutil.copy(origen, destino_img)

        lineas = []
        for a in anns_by_image.get(img_id, []):
            seg = a["segmentation"][0]  # un único polígono por instancia en nuestro caso
            puntos = poligono_normalizado(seg, im["width"], im["height"])
            puntos_str = " ".join(f"{p:.6f}" for p in puntos)
            lineas.append(f"0 {puntos_str}")  # clase 0 = 'pastilla', única clase

        destino_txt = OUT_DIR / split / "labels" / (Path(nombre_plano).stem + ".txt")
        destino_txt.write_text("\n".join(lineas), encoding="utf-8")

    data_yaml = f"""\
# Generado automáticamente por coco_a_yolo.py
path: {OUT_DIR.resolve()}
train: train/images
val: val/images
names:
  0: pastilla
"""
    (OUT_DIR / "data.yaml").write_text(data_yaml, encoding="utf-8")

    n_train = len(ids) - len(val_ids)
    print(f"\nListo. {n_train} imágenes en train, {len(val_ids)} en val.")
    if faltantes:
        print(f"AVISO: {faltantes} imágenes no se encontraron y se omitieron.")
    print(f"data.yaml escrito en: {OUT_DIR / 'data.yaml'}")


if __name__ == "__main__":
    main()
