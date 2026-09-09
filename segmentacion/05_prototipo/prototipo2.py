"""
prototipo2.py -- igual que prototipo.py, pero soporta fotos con VARIAS
bolsitas en el mismo frame. Encuentra las costuras (varios picos, no solo
uno como el detect_seam_band original) y asigna cada pastilla detectada a
la bolsita que le corresponde por posición vertical.

Supuesto importante, a validar con datos reales: las listas de --bolsita
se dan en el mismo orden en que aparecen en la foto, de ARRIBA a ABAJO.
Si no coincide con la realidad, las asignaciones saldrán desplazadas.

Uso:
    python prototipo2.py --imagen foto.jpg \
        --bolsita "Eplerenona:50 mg" \
        --bolsita "Hidrocortisona:20 mg" "Furosemida:40 mg"

(cada --bolsita abre un grupo nuevo; los fármacos que le siguen, hasta el
próximo --bolsita, son los candidatos de esa bolsita)
"""
import argparse
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests
from scipy.signal import find_peaks
from ultralytics import YOLO

MODEL_PATH = Path(__file__).parent / "best.pt"
CIMA_BASE = "https://cima.aemps.es/cima/rest"
TIMEOUT = 10

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


# --- Segmentación de costuras (multi-pico) ---
# Reutiliza la MISMA señal que medvision.bags.seam_band.detect_seam_band
# (brillo * tinte azulado del reflejo), pero busca varios picos en vez de
# solo el máximo global -- necesario cuando hay 2-3 bolsitas en el frame.
def señal_costura(img_bgr: np.ndarray) -> np.ndarray:
    h, w = img_bgr.shape[:2]
    x1, x2 = int(0.1 * w), int(0.9 * w)
    region = img_bgr[:, x1:x2].astype(np.float32)
    b, g, r = region[..., 0], region[..., 1], region[..., 2]
    blue_tint = np.clip(b - (g + r) / 2.0, 0, None)
    hsv = cv2.cvtColor(img_bgr[:, x1:x2], cv2.COLOR_BGR2HSV)
    brightness = hsv[..., 2].astype(np.float32) / 255.0
    combined = (blue_tint * brightness).mean(axis=1)
    kernel = max(5, int(h * 0.02) | 1)
    return cv2.GaussianBlur(combined.reshape(-1, 1), (1, kernel), 0).ravel()


def detectar_costuras_multi(img_bgr: np.ndarray, min_prominence_ratio: float = 3.0,
                             distancia_min_frac: float = 0.08, margen_borde_frac: float = 0.10):
    """Devuelve las posiciones normalizadas (0-1) de todas las costuras
    encontradas, ordenadas de arriba a abajo. distancia_min_frac evita
    detectar la misma costura dos veces muy cerca. margen_borde_frac
    excluye una franja cerca de los bordes superior/inferior del frame,
    donde el brillo del borde produce picos falsos que no son costuras
    reales (visto con datos reales: una costura real entre dos bolsitas
    completamente visibles casi nunca cae justo en el borde del frame)."""
    h = img_bgr.shape[0]
    señal = señal_costura(img_bgr)
    margen = int(h * margen_borde_frac)
    señal_recortada = señal.copy()
    if margen > 0:
        señal_recortada[:margen] = -1  # fuera de rango para find_peaks, nunca gana
        señal_recortada[-margen:] = -1
    mediana = float(np.median(señal))
    umbral = mediana * min_prominence_ratio if mediana > 1e-6 else 1e-6
    distancia_min = max(1, int(h * distancia_min_frac))
    picos, _ = find_peaks(señal_recortada, height=umbral, distance=distancia_min)
    return sorted(p / h for p in picos)


def asignar_banda(centroide_y_norm: float, costuras: list) -> int:
    """¿En qué banda (0=arriba del todo, 1=siguiente...) cae esta posición,
    dadas las costuras que dividen la foto?"""
    banda = 0
    for c in costuras:
        if centroide_y_norm > c:
            banda += 1
    return banda


# --- Color/forma (igual que prototipo.py, ya validado) ---
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
        return "redondo", 1.0
    c = max(contours, key=cv2.contourArea)
    if len(c) < 5:
        return "redondo", 1.0
    (_, _), (w, hh), _ = cv2.minAreaRect(c)
    aspect = max(w, hh) / max(1.0, min(w, hh))
    if aspect > 1.6:
        return "alargado", aspect
    elif aspect > 1.15:
        return "ovalado", aspect
    return "redondo", aspect


def extraer_color_forma_mascara(img_bgr, mask):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    pix = hsv[mask]
    if len(pix) == 0:
        return "desconocido", "redondo", 0.5
    h, s, v = np.median(pix[:, 0]), np.median(pix[:, 1]), np.median(pix[:, 2])
    color = color_bucket_desde_hsv(h, s, v)
    forma, _ = region_aspect_forma(mask)
    ys, xs = np.where(mask)
    centroide_y_norm = float(ys.mean()) / mask.shape[0]
    return color, forma, centroide_y_norm


# --- CIMA (igual que prototipo.py, ya validado) ---
def _limpiar_html(texto: str) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    return re.sub(r"\s+", " ", texto).strip()


def buscar_apariencias_farmaco(nombre: str, max_presentaciones: int = 8):
    nombre_norm = nombre.strip().upper()

    def _consultar(param):
        time.sleep(0.2)
        params = {param: nombre, "comerc": 1}
        r = requests.get(f"{CIMA_BASE}/medicamentos", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("resultados", [])

    combinados = {}
    try:
        for m in _consultar("nombre"):
            if m.get("nombre", "").upper().startswith(nombre_norm):
                combinados[m["nregistro"]] = m
    except requests.RequestException as e:
        print(f"  aviso: fallo buscando '{nombre}' por nombre: {e}")
    try:
        for m in _consultar("practiv1"):
            combinados[m["nregistro"]] = m
    except requests.RequestException as e:
        print(f"  aviso: fallo buscando '{nombre}' por practiv1: {e}")

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
    ap.add_argument("--imagen", required=True)
    ap.add_argument("--bolsita", action="append", nargs="+", required=True,
                     help="Un grupo por bolsita, de ARRIBA a ABAJO en la foto. "
                          "Cada fármaco en formato 'Nombre:dosis'.")
    ap.add_argument("--conf", type=float, default=0.5)
    args = ap.parse_args()

    bolsitas = []
    for grupo in args.bolsita:
        farmacos = []
        for f in grupo:
            nombre = f.split(":", 1)[0].strip()
            farmacos.append(nombre)
        bolsitas.append(farmacos)

    img = cv2.imread(args.imagen)
    if img is None:
        print(f"ERROR: no se pudo leer la imagen {args.imagen}")
        sys.exit(1)
    h, w = img.shape[:2]

    print(f"Buscando costuras en la foto (esperamos {len(bolsitas)} bolsitas, "
          f"así que hasta {len(bolsitas) - 1} costuras)...")
    costuras = detectar_costuras_multi(img)
    print(f"  costuras encontradas: {[round(c, 3) for c in costuras]}")
    if len(costuras) != len(bolsitas) - 1:
        print(f"  AVISO: se esperaban {len(bolsitas)-1} costura(s) para {len(bolsitas)} bolsitas, "
              f"pero se encontraron {len(costuras)}. Las asignaciones por banda pueden no "
              f"corresponder a las bolsitas reales -- revisar a mano.")

    print(f"\nSegmentando {args.imagen} ...")
    model = YOLO(str(MODEL_PATH))
    results = model(args.imagen, imgsz=960, conf=args.conf, device="cpu", verbose=False)
    r = results[0]
    if r.masks is None:
        print("No se detectó ninguna pastilla.")
        return
    print(f"{len(r.masks.data)} pastillas detectadas.\n")

    print("Consultando apariencia real en CIMA para cada fármaco candidato de cada bolsita...")
    bancos_por_bolsita = []
    for i, farmacos in enumerate(bolsitas):
        banco = {}
        for nombre in farmacos:
            apariencias = buscar_apariencias_farmaco(nombre)
            banco[nombre] = apariencias
            print(f"  bolsita {i} - {nombre}: {len(apariencias)} presentaciones encontradas")
        bancos_por_bolsita.append(banco)
    print()

    for i, m in enumerate(r.masks.data.cpu().numpy()):
        mask = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST) > 0.5
        color_img, forma_img, centroide_y = extraer_color_forma_mascara(img, mask)
        banda = asignar_banda(centroide_y, costuras)
        banda_valida = banda < len(bolsitas)
        etiqueta_banda = f"bolsita {banda}" if banda_valida else f"bolsita {banda} (FUERA DE RANGO -- solo hay {len(bolsitas)})"
        print(f"--- Pastilla #{i} (color: {color_img}, forma: {forma_img}, "
              f"posición_y={centroide_y:.2f}) -> {etiqueta_banda} ---")
        if not banda_valida:
            print("    (sin banco de candidatos para esta banda, se omite el ranking)\n")
            continue
        banco = bancos_por_bolsita[banda]
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
