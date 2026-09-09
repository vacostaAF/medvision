"""
Genera las tareas de Label Studio para el lote representativo, con las
máscaras candidatas de nuestro pipeline (FastSAM + filtro calibrado) ya
precargadas como "predictions" -- el humano corrige en vez de dibujar
desde cero, mismo patrón que la app de revisión de emparejamiento.

Import en Label Studio: Data Import -> subir el JSON que genera este script
(uno por lote, o el completo). El tipo de proyecto debe ser "Semantic
Segmentation with Polygons" (o Instance Segmentation si tenéis esa
plantilla), con una única etiqueta "pastilla".

Servir las imágenes: Label Studio necesita poder cargar los ficheros. Lo
más simple para un dataset local es activar "Local Storage" apuntando a
la carpeta `dataset_package/`, y las rutas de este export ya están en el
formato que Label Studio espera para eso
(`/data/local-files/?d=<ruta relativa>`). Ver:
https://labelstud.io/guide/storage.html#Local-storage

No requiere entrenar nada -- es el mismo filtro ya calibrado y validado
en sesiones anteriores (pill_filter.py), sin cambios.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from ultralytics import FastSAM

sys.path.insert(0, str(Path(__file__).parent))  # pill_filter.py debe estar en esta misma carpeta
from pill_filter import is_pill, mask_features  # filtro calibrado, sin cambios

# --- RUTAS A CONFIGURAR ---
# DATASET_DIR: la carpeta que contiene 'bags/' y 'dataset_final.json'
#              (la que sale de descomprimir dataset_package.zip). Por
#              defecto asume que está junto a este script -- si la tienes
#              en otro sitio, cambia esta línea.
DATASET_DIR = Path(__file__).parent / "dataset_package"
# LOTE_PATH y OUT_PATH: se guardan junto a este script, no hace falta tocarlos
LOTE_PATH = Path(__file__).parent / "lote_representativo.json"
OUT_PATH = Path(__file__).parent / "tareas_label_studio.json"
# MODEL_PATH: solo el nombre del fichero -- ultralytics lo descarga solo
# (a la carpeta actual) la primera vez que se ejecuta si no lo encuentra
MODEL_PATH = "FastSAM-s.pt"
ETIQUETA = "pastilla"


def mascara_a_poligono(mask: np.ndarray, epsilon_frac: float = 0.01):
    """Contorno de una máscara binaria -> polígono simplificado, como lista
    de puntos (x, y) en píxeles. epsilon_frac controla cuánto se simplifica
    (menos puntos = más fácil de corregir a mano en Label Studio)."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 10:
        return None
    perimetro = cv2.arcLength(c, True)
    aprox = cv2.approxPolyDP(c, epsilon_frac * perimetro, True)
    if len(aprox) < 3:
        return None
    return aprox.reshape(-1, 2)


def segmentar_foto(path_absoluta: Path, model: FastSAM):
    img = cv2.imread(str(path_absoluta))
    if img is None:
        return None, []
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    results = model(str(path_absoluta), device="cpu", retina_masks=True, imgsz=1024,
                     conf=0.35, iou=0.7, verbose=False)
    r = results[0]
    poligonos = []
    if r.masks is not None:
        for m in r.masks.data.cpu().numpy():
            mask = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST) > 0.5
            feat = mask_features(mask, gray, h * w)
            if feat is None or not is_pill(feat):
                continue
            poligono = mascara_a_poligono(mask)
            if poligono is not None:
                poligonos.append(poligono)
    return (h, w), poligonos


def poligono_a_resultado_ls(poligono, w, h, id_):
    """Un polígono en píxeles -> un 'result' de Label Studio (PolygonLabels,
    en formato de porcentaje 0-100 tal como lo requiere su API)."""
    puntos_pct = [[float(x) / w * 100, float(y) / h * 100] for x, y in poligono]
    return {
        "id": id_,
        "type": "polygonlabels",
        "from_name": "label",
        "to_name": "image",
        "original_width": w,
        "original_height": h,
        "value": {"points": puntos_pct, "polygonlabels": [ETIQUETA]},
    }


def descriptor_legible_bolsita(registro: dict) -> str:
    ctx = registro["patient_context"]
    farmacos = ", ".join(it["drug_name"] for it in registro["label_items"])
    clave = f"{registro['pair_key']}::{registro['order_index']}"
    return f"{clave} | {ctx.get('weekday','?')} {ctx.get('date','?')} | {farmacos}"


def construir_tarea(ruta_relativa: str, w: int, h: int, poligonos: list, cobertura_claves: list, bolsitas: dict):
    resultados = [poligono_a_resultado_ls(p, w, h, f"pastilla_{i}") for i, p in enumerate(poligonos)]
    descriptores = []
    for c in cobertura_claves:
        pair_key, order_index_str = c.split("::")
        descriptores.append(descriptor_legible_bolsita(bolsitas[(pair_key, int(order_index_str))]))
    return {
        "data": {
            "image": f"/data/local-files/?d={ruta_relativa}",
            # texto legible para mostrar en cabecera (Text tag)
            "bolsitas_texto": "\n".join(descriptores),
            # mismo contenido pero como lista de objetos {value: ...} --
            # formato que exige Choices con valor dinámico en Label Studio
            "bolsitas_asociadas": [{"value": d} for d in descriptores],
        },
        "predictions": [{
            "model_version": "fastsam_s_filtro_v1",
            "result": resultados,
        }],
    }


if __name__ == "__main__":
    lote = json.load(open(LOTE_PATH, encoding="utf-8"))
    fotos = lote["fotos_a_anotar"]
    cobertura = lote["cobertura_por_foto"]

    manifiesto = json.load(open(DATASET_DIR / "dataset_final.json", encoding="utf-8"))
    bolsitas = {(d["pair_key"], d["order_index"]): d for d in manifiesto}

    # DEMO: por tiempo de cómputo (≈17s/foto en CPU), aquí solo se procesan
    # las primeras N como validación real. Para el lote completo, correr
    # este mismo script sin este recorte en un entorno con más cómputo.
    N_DEMO = 12
    fotos_demo = fotos[:N_DEMO]

    model = FastSAM(MODEL_PATH)
    tareas = []
    for ruta in fotos_demo:
        (h, w), poligonos = segmentar_foto(DATASET_DIR / ruta, model)
        print(f"{ruta}: {len(poligonos)} pastillas candidatas")
        tareas.append(construir_tarea(ruta, w, h, poligonos, cobertura[ruta], bolsitas))

    json.dump(tareas, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nGuardado: {OUT_PATH} ({len(tareas)} tareas)")
