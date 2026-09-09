"""
prototipo3.py -- igual que prototipo.py (segmentación + retrieval CIMA),
pero antes de enseñar el ranking libre por pastilla, calcula el REPARTO
ÓPTIMO entre pastillas detectadas y fármacos esperados (asignación
húngara, scipy.optimize.linear_sum_assignment).

Por qué hace falta: puntuar cada pastilla contra cada fármaco por
separado (como hacía prototipo.py) deja que un fármaco "poco distintivo"
en apariencia (con generios de casi cualquier color, ej. Tramadol/
Paracetamol) parezca compatible con todas las pastillas a la vez, aunque
la etiqueta solo espere 1 unidad suya. El reparto óptimo busca la
asignación que maximiza la puntuación total del CONJUNTO, no pastilla a
pastilla -- así un fármaco solo se lleva tantas pastillas como su
cantidad esperada, no todas las que "podría" explicar.

Manejo de pastillas que faltan: cada fármaco aporta tantas "plazas" como
su cantidad esperada (--farmacos admite "Nombre:dosis:cantidad", cantidad
por defecto 1). Si hay más plazas que pastillas detectadas, el algoritmo
de asignación (rectangular) deja algunas plazas sin cubrir -- esas son,
precisamente, las candidatas a discrepancia física ("falta esta unidad").
Si sobran pastillas respecto a plazas, se marcan como "sin fármaco
esperado asociado".

Uso:
    python prototipo3.py --imagen foto.jpg \
        --farmacos "Omeprazol:20 mg:1" "Paracetamol:650 mg:2"
"""
import argparse
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests
from scipy.optimize import linear_sum_assignment
from ultralytics import YOLO

MODEL_PATH = Path(__file__).parent / "best.pt"
CIMA_BASE = "https://cima.aemps.es/cima/rest"
TIMEOUT = 10

COLOR_WORDS = {
    "blanco": "blanco", "blanquecino": "blanco", "blancos": "blanco",
    "azul": "azul", "amarillo": "amarillo", "amarillos": "amarillo",
    "rojo": "rojo", "naranja": "naranja", "anaranjado": "naranja",
    "rosa": "rosa", "rosado": "rosa", "gris": "gris",
    "beige": "beige", "crema": "beige", "violeta": "violeta", "lila": "violeta",
}
SHAPE_WORDS = {
    "redondo": "redondo", "redondos": "redondo", "circular": "redondo",
    "ovalado": "ovalado", "oval": "ovalado", "elipt": "ovalado",
    "alargado": "alargado", "alargados": "alargado", "oblongo": "alargado",
    "capsula": "capsula", "cápsula": "capsula", "rombo": "rombo",
}


def extraer_colores_forma_texto(texto: str):
    t = texto.lower()
    colores = {v for k, v in COLOR_WORDS.items() if k in t}
    formas = {v for k, v in SHAPE_WORDS.items() if k in t}
    return colores, formas


def color_bucket_desde_hsv(h, s, v):
    if s < 30:
        if v < 60:
            return "negro"
        if v < 120:
            return "gris"
        return "blanco"
    if h < 10 or h > 170:
        return "rojo"
    if 10 <= h < 20:
        return "naranja"
    if 20 <= h < 35:
        return "amarillo"
    if 130 <= h < 170:
        return "rosa"
    if 90 <= h < 130:
        return "azul"
    if 35 <= h < 90:
        return "verde"
    return "otro"


def region_aspect_forma(mask):
    mask_u8 = mask.astype(np.uint8)
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return "redondo"
    c = max(contours, key=cv2.contourArea)
    if len(c) < 5:
        return "redondo"
    (_, _), (w, h), _ = cv2.minAreaRect(c)
    aspect = max(w, h) / max(1.0, min(w, h))
    if aspect > 1.6:
        return "alargado"
    elif aspect > 1.15:
        return "ovalado"
    return "redondo"


def extraer_color_forma_mascara(img_bgr, mask):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    pix = hsv[mask]
    if len(pix) == 0:
        return "desconocido", "redondo"
    h, s, v = np.median(pix[:, 0]), np.median(pix[:, 1]), np.median(pix[:, 2])
    return color_bucket_desde_hsv(h, s, v), region_aspect_forma(mask)


def _limpiar_html(texto: str) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    return re.sub(r"\s+", " ", texto).strip()


def buscar_apariencias_farmaco(nombre: str, max_presentaciones: int = 8):
    nombre_norm = nombre.strip().upper()

    def _consultar(param, valor):
        time.sleep(0.2)
        params = {param: valor, "comerc": 1}
        r = requests.get(f"{CIMA_BASE}/medicamentos", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("resultados", [])

    combinados = {}
    try:
        for m in _consultar("nombre", nombre):
            if m.get("nombre", "").upper().startswith(nombre_norm):
                combinados[m["nregistro"]] = m
    except requests.RequestException as e:
        print(f"  aviso: fallo buscando '{nombre}' por nombre: {e}")
    try:
        for m in _consultar("practiv1", nombre):
            combinados[m["nregistro"]] = m
    except requests.RequestException as e:
        print(f"  aviso: fallo buscando '{nombre}' por practiv1: {e}")

    if not combinados and "/" in nombre:
        partes = [p.strip() for p in nombre.split("/") if p.strip()]
        if len(partes) >= 2:
            por_parte = []
            for parte in partes:
                try:
                    por_parte.append({m["nregistro"]: m for m in _consultar("practiv1", parte)})
                except requests.RequestException as e:
                    print(f"  aviso: fallo buscando principio '{parte}' de '{nombre}': {e}")
                    por_parte.append({})
            if all(por_parte):
                comunes = set(por_parte[0].keys())
                for r_parte in por_parte[1:]:
                    comunes &= set(r_parte.keys())
                for nreg in comunes:
                    combinados[nreg] = por_parte[0][nreg]

    apariencias = []
    for p in list(combinados.values())[:max_presentaciones]:
        try:
            time.sleep(0.2)
            r = requests.get(f"{CIMA_BASE}/medicamento", params={"nregistro": p["nregistro"]}, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            doc_ft = next((d for d in data.get("docs", []) if d.get("tipo") == 1), None)
            descripcion = ""
            if doc_ft and doc_ft.get("urlHtml"):
                html = requests.get(doc_ft["urlHtml"], timeout=TIMEOUT).text
                m = re.search(r"3\.\s*FORMA FARMAC[ÉE]UTICA(.*?)4\.\s*DATOS CL[ÍI]NICOS",
                               html, re.IGNORECASE | re.DOTALL)
                if m:
                    descripcion = _limpiar_html(m.group(1))[:600]
            apariencias.append((data.get("nombre", nombre), descripcion))
        except requests.RequestException as e:
            print(f"  aviso: fallo obteniendo detalle de {p.get('nregistro')}: {e}")
    return apariencias


def puntuar(color_img, forma_img, colores_txt, formas_txt):
    score = 0
    if color_img in colores_txt:
        score += 2
    if forma_img in formas_txt:
        score += 1
    if "capsula" in formas_txt and forma_img in ("alargado", "ovalado"):
        score += 1
    return score


def mejor_score_farmaco(color_img, forma_img, apariencias):
    """El mejor score de esta pastilla contra CUALQUIER presentación (fabricante)
    de este fármaco -- basta con que encaje con una para considerarlo compatible."""
    mejor = 0
    mejor_presentacion = None
    for nombre_presentacion, texto in apariencias:
        colores_txt, formas_txt = extraer_colores_forma_texto(texto)
        s = puntuar(color_img, forma_img, colores_txt, formas_txt)
        if s > mejor:
            mejor = s
            mejor_presentacion = nombre_presentacion
    return mejor, mejor_presentacion


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--imagen", required=True)
    ap.add_argument("--farmacos", nargs="+", required=True,
                     help="Formato 'Nombre:dosis' o 'Nombre:dosis:cantidad' (cantidad por defecto 1)")
    ap.add_argument("--conf", type=float, default=0.5)
    args = ap.parse_args()

    farmacos = []
    for f in args.farmacos:
        partes = f.split(":")
        nombre = partes[0].strip()
        cantidad = 1
        if len(partes) >= 3:
            try:
                cantidad = max(1, round(float(partes[2])))
            except ValueError:
                cantidad = 1
        farmacos.append((nombre, cantidad))

    img = cv2.imread(args.imagen)
    if img is None:
        print(f"ERROR: no se pudo leer la imagen {args.imagen}")
        sys.exit(1)
    h, w = img.shape[:2]

    print(f"Segmentando {args.imagen} ...")
    model = YOLO(str(MODEL_PATH))
    results = model(args.imagen, imgsz=960, conf=args.conf, device="cpu", verbose=False)
    r = results[0]
    if r.masks is None:
        print("No se detectó ninguna pastilla.")
        return
    masks = [cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST) > 0.5 for m in r.masks.data.cpu().numpy()]
    print(f"{len(masks)} pastillas detectadas.\n")

    print("Consultando apariencia real en CIMA para cada fármaco candidato...")
    banco = {}
    for nombre, cantidad in farmacos:
        apariencias = buscar_apariencias_farmaco(nombre)
        banco[nombre] = apariencias
        print(f"  {nombre} (x{cantidad}): {len(apariencias)} presentaciones encontradas")
    print()

    color_forma_pastillas = [extraer_color_forma_mascara(img, m) for m in masks]

    # --- Construir las "plazas": una por cada unidad esperada de cada fármaco ---
    plazas = []  # lista de (nombre_farmaco)
    for nombre, cantidad in farmacos:
        plazas.extend([nombre] * cantidad)

    n_pastillas = len(masks)
    n_plazas = len(plazas)

    # matriz de coste (para minimizar -> negamos el score, que queremos maximizar)
    matriz_score = np.zeros((n_plazas, n_pastillas))
    matriz_presentacion = [[None] * n_pastillas for _ in range(n_plazas)]
    for i, nombre_farmaco in enumerate(plazas):
        for j, (color_img, forma_img) in enumerate(color_forma_pastillas):
            score, presentacion = mejor_score_farmaco(color_img, forma_img, banco[nombre_farmaco])
            matriz_score[i, j] = score
            matriz_presentacion[i][j] = presentacion

    filas, columnas = linear_sum_assignment(-matriz_score)  # maximizar score = minimizar -score

    asignacion_pastilla = {}  # índice de pastilla -> (plaza_idx, farmaco, score, presentacion)
    plazas_cubiertas = set()
    for i, j in zip(filas, columnas):
        asignacion_pastilla[j] = (i, plazas[i], matriz_score[i, j], matriz_presentacion[i][j])
        plazas_cubiertas.add(i)

    print("=" * 70)
    print("REPARTO ÓPTIMO (asignación conjunta, no pastilla a pastilla suelta)")
    print("=" * 70)
    for j in range(n_pastillas):
        color_img, forma_img = color_forma_pastillas[j]
        if j in asignacion_pastilla:
            _, farmaco, score, presentacion = asignacion_pastilla[j]
            calidad = "buena" if score >= 3 else ("débil" if score > 0 else "SIN NINGÚN match de color/forma")
            print(f"Pastilla #{j} (color={color_img}, forma={forma_img}) -> {farmaco}  "
                  f"[score={score:.0f}, {calidad}] ({presentacion})")
        else:
            print(f"Pastilla #{j} (color={color_img}, forma={forma_img}) -> SIN FÁRMACO ASIGNADO "
                  f"(sobra respecto a lo esperado -- revisar)")

    plazas_sin_cubrir = [i for i in range(n_plazas) if i not in plazas_cubiertas]
    if plazas_sin_cubrir:
        print()
        print("⚠ UNIDADES ESPERADAS SIN NINGUNA PASTILLA ASIGNADA (posible discrepancia física):")
        for i in plazas_sin_cubrir:
            print(f"   - {plazas[i]}")
    print()

    print("=" * 70)
    print("Detalle por pastilla: top-3 candidatos libres (para revisión manual)")
    print("=" * 70)
    for j, (color_img, forma_img) in enumerate(color_forma_pastillas):
        print(f"--- Pastilla #{j} (color={color_img}, forma={forma_img}) ---")
        ranking = []
        for nombre, cantidad in farmacos:
            score, presentacion = mejor_score_farmaco(color_img, forma_img, banco[nombre])
            ranking.append((score, nombre, presentacion))
        ranking.sort(key=lambda x: -x[0])
        for score, nombre, presentacion in ranking[:3]:
            etiqueta = "posible" if score > 0 else "sin match"
            print(f"    [{score:.0f}] {nombre} ({presentacion}) -- {etiqueta}")
        print()


if __name__ == "__main__":
    main()
