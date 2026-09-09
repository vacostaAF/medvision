"""
Prototipo end-to-end: "le paso una bolsa nueva y me dice qué pastillas pueden ser".

Entrada:
  - una foto del lado pastilla (ya procesada por el Dataset Builder)
  - la lista de fármacos candidatos de esa bolsita (de label_items, lado etiqueta)

Pipeline:
  1. Segmentar con el modelo YOLO11-seg entrenado (best.pt) -> una máscara por pastilla
  2. Por cada máscara: extraer color (HSV) y forma (redondo/ovalado/alargado)
  3. Para cada fármaco candidato: consultar CIMA en vivo, extraer color/forma de la
     descripción de cada presentación posible (distintos fabricantes)
  4. Puntuar cada máscara contra cada candidato, devolver un ranking

Requiere conexión a internet (consulta CIMA en vivo) y el modelo entrenado
(best.pt) en la misma carpeta, o indicar su ruta en MODEL_PATH.

Uso:
    python prototipo.py --imagen bolsa_nueva.jpg --farmacos "Omeprazol:20 mg" "Levotiroxina:100 microgramos"
"""
import argparse
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests
from ultralytics import YOLO

MODEL_PATH = Path(__file__).parent / "best.pt"
CIMA_BASE = "https://cima.aemps.es/cima/rest"
TIMEOUT = 10

# --- Reutilizado y validado en sesiones anteriores (match_prototype.py) ---
COLOR_WORDS = {
    "blanco": "blanco", "blanquecino": "blanco", "blancos": "blanco",
    "azul": "azul", "amarillo": "amarillo", "amarillos": "amarillo",
    "rojo": "rojo", "naranja": "naranja", "anaranjado": "naranja",
    "rosa": "rosa", "rosado": "rosa", "gris": "gris",
    "beige": "beige", "crema": "beige",
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
    # Corregido en sesión anterior: con S baja, clasificar por V sin exigir
    # un umbral de brillo alto -- ver conversación previa para el porqué.
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
        return "redondo", 1.0
    c = max(contours, key=cv2.contourArea)
    if len(c) < 5:
        return "redondo", 1.0
    (_, _), (w, h), _ = cv2.minAreaRect(c)
    aspect = max(w, h) / max(1.0, min(w, h))
    if aspect > 1.6:
        return "alargado", aspect
    elif aspect > 1.15:
        return "ovalado", aspect
    return "redondo", aspect


def extraer_color_forma_mascara(img_bgr, mask):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    pix = hsv[mask]
    if len(pix) == 0:
        return "desconocido", "redondo"
    h, s, v = np.median(pix[:, 0]), np.median(pix[:, 1]), np.median(pix[:, 2])
    color = color_bucket_desde_hsv(h, s, v)
    forma, _ = region_aspect_forma(mask)
    return color, forma


# --- Reutilizado y validado en sesiones anteriores (cima_retrieval.py) ---
def _limpiar_html(texto: str) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    return re.sub(r"\s+", " ", texto).strip()


def buscar_apariencias_farmaco(nombre: str, dosis: str = None, max_presentaciones: int = 8):
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

    # Fallback para combinaciones (nombre con "/"): CIMA registra cada
    # principio activo por separado, no la cadena combinada -- si la
    # búsqueda normal no encontró nada, buscamos cada principio por
    # separado y nos quedamos solo con lo que aparece en TODAS las
    # búsquedas (así nos aseguramos de que sea la combinación real, no
    # solo uno de los principios sueltos). Esto es lo que rescata casos
    # como Sacubitrilo/Valsartán (Entresto), donde ni el nombre comercial
    # ni la búsqueda combinada por practiv1 encuentran nada.
    if not combinados and "/" in nombre:
        partes = [p.strip() for p in nombre.split("/") if p.strip()]
        if len(partes) >= 2:
            por_parte = []
            for parte in partes:
                try:
                    resultados_parte = {m["nregistro"]: m for m in _consultar("practiv1", parte)}
                    por_parte.append(resultados_parte)
                except requests.RequestException as e:
                    print(f"  aviso: fallo buscando principio '{parte}' de '{nombre}': {e}")
                    por_parte.append({})
            if all(por_parte):
                nregistros_comunes = set(por_parte[0].keys())
                for resultados_parte in por_parte[1:]:
                    nregistros_comunes &= set(resultados_parte.keys())
                for nreg in nregistros_comunes:
                    combinados[nreg] = por_parte[0][nreg]
                if combinados:
                    print(f"  ('{nombre}' encontrado buscando cada principio por separado: "
                          f"{' + '.join(partes)})")

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--imagen", required=True, help="Foto del lado pastilla")
    ap.add_argument("--farmacos", nargs="+", required=True,
                     help="Fármacos candidatos, formato 'Nombre:dosis', ej. 'Omeprazol:20 mg'")
    ap.add_argument("--conf", type=float, default=0.5, help="Umbral de confianza de segmentación")
    args = ap.parse_args()

    farmacos = []
    for f in args.farmacos:
        if ":" in f:
            nombre, dosis = f.split(":", 1)
        else:
            nombre, dosis = f, None
        farmacos.append((nombre.strip(), dosis.strip() if dosis else None))

    print(f"Segmentando {args.imagen} ...")
    model = YOLO(str(MODEL_PATH))
    img = cv2.imread(args.imagen)
    if img is None:
        print(f"ERROR: no se pudo leer la imagen {args.imagen}")
        sys.exit(1)
    h, w = img.shape[:2]
    results = model(args.imagen, imgsz=960, conf=args.conf, device="cpu", verbose=False)
    r = results[0]
    if r.masks is None:
        print("No se detectó ninguna pastilla.")
        return
    print(f"{len(r.masks.data)} pastillas detectadas.\n")

    print("Consultando apariencia real en CIMA para cada fármaco candidato...")
    banco = {}
    for nombre, dosis in farmacos:
        apariencias = buscar_apariencias_farmaco(nombre, dosis)
        banco[nombre] = apariencias
        print(f"  {nombre}: {len(apariencias)} presentaciones encontradas")
    print()

    for i, m in enumerate(r.masks.data.cpu().numpy()):
        mask = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST) > 0.5
        color_img, forma_img = extraer_color_forma_mascara(img, mask)
        print(f"--- Pastilla #{i} (color detectado: {color_img}, forma: {forma_img}) ---")
        ranking = []
        for nombre, apariencias in banco.items():
            for nombre_presentacion, texto in apariencias:
                colores_txt, formas_txt = extraer_colores_forma_texto(texto)
                score = puntuar(color_img, forma_img, colores_txt, formas_txt)
                ranking.append((score, nombre, nombre_presentacion))
        ranking.sort(key=lambda x: -x[0])
        vistos = set()
        top = []
        for score, nombre, presentacion in ranking:
            if nombre in vistos:
                continue
            vistos.add(nombre)
            top.append((score, nombre, presentacion))
            if len(top) >= 3:
                break
        for score, nombre, presentacion in top:
            etiqueta = "posible" if score > 0 else "sin match de color/forma"
            print(f"    [{score}] {nombre} ({presentacion}) -- {etiqueta}")
        print()


if __name__ == "__main__":
    main()
