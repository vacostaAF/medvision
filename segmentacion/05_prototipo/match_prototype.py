"""
Prototipo — conectar segmentación + retrieval.

Pipeline: imagen real -> FastSAM (candidatos) -> filtro calibrado (pill_filter.py)
-> por cada máscara que sobrevive, extraer color+forma de los píxeles reales
-> comparar contra el color+forma que se puede leer en el texto de apariencia
   de cada candidato del banco CIMA (ya extraído en sesiones anteriores)
-> puntuación de compatibilidad por candidato.

Esto es deliberadamente simple (diccionario de palabras de color/forma en
español, no un clasificador entrenado) -- el objetivo de este spike es ver
si la señal está ahí en absoluto antes de invertir en algo más sofisticado.
"""
import re
import cv2
import numpy as np
from pathlib import Path
from ultralytics import FastSAM

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "01_spikes_segmentacion"))  # pill_filter.py
from pill_filter import is_pill, mask_features  # filtro ya calibrado y validado

IMG_PATH = Path(__file__).parent / "ejemplos" / "MVI_2732_f000240_bag00.jpg"  # sustituye por tu propia imagen de prueba

# --- Banco CIMA real, tal cual lo devolvió el script del usuario (sesión anterior) ---
BANCO = {
    "Levotiroxina": [
        ("LEVOTIROXINA ARISTO 100MCG", "Comprimidos blancos, redondos, sin recubrimiento, abovedados, con marca de rotura."),
        ("LEVOTIROXINA SANOFI 100MCG", "Comprimidos redondos, blancos, con una ranura, inscripcion 2L 3L 4L."),
        ("LEVOTIROXINA SODICA TEVA 100MCG", "Blanco o blanquecino, redondo, plano por las dos caras, con impresion L3."),
        ("EUTIROX 100MCG", "Blanquecino, redondo, plano por las dos caras, biselado, con ranura, inscripcion EM 100."),
    ],
    "Omeprazol": [
        ("OMEPRAZOL CINFA 20MG", "Capsulas de gelatina dura, tamano 4, con tapa azul y cuerpo blanco."),
        ("OMEPRAZOL CINFALAB 20MG", "Capsulas duras de gelatina, blancas, opacas, marcadas OM en la tapa y 20 en el cuerpo."),
        ("OMEPRAZOL CINFAMED 20MG", "Capsulas de gelatina dura con cuerpo blanco marcado 20 y tapa opaca blanca marcada OM."),
        ("OMEPRAZOL NORMON 20MG", "Capsula de gelatina dura de color blanco/rojo."),
        ("OMEPRAZOL SANDOZ CARE 20MG", "Capsula dura gastrorresistente tamano 2 de color amarillo opaco."),
        ("OMEPRAZOL SANDOZ FARMACEUTICA 20MG", "Capsulas duras de gelatina tamano 4, tapa azul y cuerpo blanco."),
        ("OMEPRAZOL STADA 20MG", "Capsula dura de gelatina de color amarillo opaco."),
        ("OMEPRAZOL STADAPHARM 20MG", "Capsula dura de gelatina blanca opaca marcada OM 20."),
    ],
}

# --- Diccionario de color: palabra en español -> bucket canónico ---
COLOR_WORDS = {
    "blanco": "blanco", "blanquecino": "blanco", "blancos": "blanco",
    "azul": "azul",
    "amarillo": "amarillo", "amarillos": "amarillo",
    "rojo": "rojo",
    "naranja": "naranja", "anaranjado": "naranja",
    "rosa": "rosa", "rosado": "rosa",
    "gris": "gris",
    "beige": "beige", "crema": "beige",
}
SHAPE_WORDS = {
    "redondo": "redondo", "redondos": "redondo", "circular": "redondo",
    "ovalado": "ovalado", "oval": "ovalado", "elipt": "ovalado",
    "alargado": "alargado", "alargados": "alargado", "oblongo": "alargado",
    "capsula": "capsula", "cápsula": "capsula",
    "rombo": "rombo",
}


def extraer_colores_forma_texto(texto: str):
    t = texto.lower()
    colores = {v for k, v in COLOR_WORDS.items() if k in t}
    formas = {v for k, v in SHAPE_WORDS.items() if k in t}
    return colores, formas


# --- Extracción de color/forma de la imagen real ---
def color_bucket_desde_hsv(h, s, v):
    # Primero: ¿es acromático (blanco/gris/negro) o cromático (tiene un
    # matiz de color reconocible)? Lo decide la saturación, no el brillo.
    # Con S tan baja como la que vemos en estas fotos (glare + flash),
    # cualquier pastilla razonablemente iluminada ya es "blanco" -- no
    # hace falta que V llegue a un umbral alto como 200, eso es specific
    # a fotografía bien expuesta en estudio, no a estas condiciones reales.
    if s < 30:
        if v < 60:
            return "negro"
        if v < 120:
            return "gris"
        return "blanco"

    # A partir de aquí sí hay matiz de color real, se decide por H.
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


def extraer_color_forma_mascara(img_bgr, mask):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    pix = hsv[mask]
    h, s, v = np.median(pix[:, 0]), np.median(pix[:, 1]), np.median(pix[:, 2])
    color = color_bucket_desde_hsv(h, s, v)

    ys, xs = np.where(mask)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    w, hh = x1 - x0 + 1, y1 - y0 + 1
    aspect = max(w, hh) / max(1, min(w, hh))
    if aspect > 1.6:
        forma = "alargado"
    elif aspect > 1.15:
        forma = "ovalado"
    else:
        forma = "redondo"
    return color, forma, (h, s, v), aspect


def puntuar(color_img, forma_img, colores_txt, formas_txt):
    score = 0
    if color_img in colores_txt:
        score += 2
    if forma_img in formas_txt:
        score += 1
    # cápsula es compatible con alargado/ovalado, no es una "forma" geométrica pura
    if "capsula" in formas_txt and forma_img in ("alargado", "ovalado"):
        score += 1
    return score


if __name__ == "__main__":
    img = cv2.imread(str(IMG_PATH))
    model = FastSAM("FastSAM-s.pt")
    results = model(str(IMG_PATH), device="cpu", retina_masks=True, imgsz=1024,
                     conf=0.35, iou=0.7, verbose=False)
    r = results[0]
    h, w = img.shape[:2]
    img_area = h * w
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    candidatos_pill = []
    if r.masks is not None:
        confs = r.boxes.conf.cpu().numpy()
        for i, m in enumerate(r.masks.data.cpu().numpy()):
            mask = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST) > 0.5
            feat = mask_features(mask, gray, img_area)
            if feat is None:
                continue
            feat["conf"] = float(confs[i])
            if is_pill(feat):
                candidatos_pill.append((mask, feat))

    print(f"Máscaras que pasan el filtro: {len(candidatos_pill)}\n")

    for idx, (mask, feat) in enumerate(candidatos_pill):
        color_img, forma_img, hsv, aspect = extraer_color_forma_mascara(img, mask)
        print(f"--- Pastilla candidata #{idx} (bbox={feat['bbox']}, aspect={aspect:.2f}) ---")
        print(f"  color detectado: {color_img}   forma detectada: {forma_img}   (HSV mediana={tuple(round(x,1) for x in hsv)})")
        ranking = []
        for farmaco, presentaciones in BANCO.items():
            for nombre, texto in presentaciones:
                colores_txt, formas_txt = extraer_colores_forma_texto(texto)
                score = puntuar(color_img, forma_img, colores_txt, formas_txt)
                ranking.append((score, farmaco, nombre, colores_txt, formas_txt))
        ranking.sort(key=lambda x: -x[0])
        print("  top 3 candidatos del banco CIMA:")
        for score, farmaco, nombre, colores_txt, formas_txt in ranking[:3]:
            print(f"    [{score}] {nombre}  (colores={colores_txt}, formas={formas_txt})")
        print()
