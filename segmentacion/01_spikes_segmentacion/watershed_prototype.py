"""
Ataque al problema de "pastillas que se tocan" -- caso conocido: el racimo
de 7 pastillas de la bolsita superior de f000200 (MARTIN RODRIGUEZ), que
FastSAM sobre-segmenta de forma inconsistente (9 máscaras fragmentadas
para 7 pastillas reales, ver spike anterior).

Enfoque: watershed clásico sobre transformada de distancia, NO depende de
entrenar nada. La idea: aunque FastSAM no separe bien los blobs tocándose,
sí sabe (más o menos) dónde está "algo" -- unimos sus máscaras individuales
como máscara binaria de foreground aproximada, y usamos watershed para
volver a separarla en instancias, basándonos en la geometría (cada pastilla
es un "pico" de distancia al fondo), no en lo que FastSAM ya decidió.
"""
import sys
import cv2
import numpy as np
from pathlib import Path
from scipy import ndimage as ndi
from skimage.feature import peak_local_max
from skimage.segmentation import watershed
from ultralytics import FastSAM

sys.path.insert(0, str(Path(__file__).parent))  # pill_filter.py debe estar en esta misma carpeta
from pill_filter import mask_features  # reutilizamos el extractor de features, no el filtro final

IMG_PATH = Path(__file__).parent / "ejemplos" / "MVI_2801_f000200_bag00.jpg"  # sustituye por tu propia imagen de prueba
OUT_DIR = Path(__file__).parent / "watershed_output"
OUT_DIR.mkdir(exist_ok=True)

# Racimo de 9 pastillas de GONZALEZ LOPEZ, no visto durante el ajuste de umbrales.
CLUSTER_BBOX = (0, 1600, 750, 2072)  # x0, y0, x1, y1


def foreground_desde_fastsam(img, model):
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    results = model(str(IMG_PATH), device="cpu", retina_masks=True, imgsz=1024,
                     conf=0.25, iou=0.6, verbose=False)
    r = results[0]
    fg = np.zeros((h, w), dtype=bool)
    fragmentos = []  # (ancho, cx, cy) por cada máscara individual conservada
    if r.masks is not None:
        for m in r.masks.data.cpu().numpy():
            mask = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST) > 0.5
            feat = mask_features(mask, gray, h * w)
            if feat is None:
                continue
            if 0.0005 <= feat["area_frac"] <= 0.06:
                fg |= mask
                _, _, ancho = region_aspect(mask)
                ys, xs = np.where(mask)
                if ancho > 0 and len(xs) > 0:
                    fragmentos.append((ancho, float(xs.mean()), float(ys.mean())))
    return fg, fragmentos


def separar_con_watershed(fg_mask, min_distance=12):
    # Apertura morfológica: limpia ruido de textura fino.
    kernel = np.ones((5, 5), np.uint8)
    fg_clean = cv2.morphologyEx(fg_mask.astype(np.uint8), cv2.MORPH_OPEN, kernel).astype(bool)

    # Nos quedamos solo con la componente conexa más grande. El racimo de
    # pastillas reales es una sola pieza conectada; el ruido de fondo
    # (textura de tela, bordes) aparece como fragmentos sueltos y pequeños
    # -- más robusto que intentar ajustar un rectángulo a mano.
    num_labels, comp_labels, stats, _ = cv2.connectedComponentsWithStats(fg_clean.astype(np.uint8))
    if num_labels > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        mayor = 1 + int(np.argmax(areas))
        fg_clean = comp_labels == mayor

    dist = ndi.distance_transform_edt(fg_clean)
    dist_smooth = ndi.gaussian_filter(dist, sigma=4)
    coords = peak_local_max(dist_smooth, min_distance=min_distance, labels=fg_clean)
    markers = np.zeros(dist.shape, dtype=int)
    for i, (y, x) in enumerate(coords, start=1):
        markers[y, x] = i
    labels = watershed(-dist, markers, mask=fg_clean)
    return labels, dist, coords


def region_aspect(mask_region):
    mask_u8 = mask_region.astype(np.uint8)
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 1.0, int(mask_region.sum()), 0.0
    c = max(contours, key=cv2.contourArea)
    if len(c) < 5:
        return 1.0, int(mask_region.sum()), 0.0
    (_, _), (w, h), _ = cv2.minAreaRect(c)  # rectángulo rotado -- invariante a la orientación
    aspect = max(w, h) / max(1.0, min(w, h))
    ancho_menor = min(w, h)
    return aspect, int(mask_region.sum()), ancho_menor


def vecinos_adyacentes(labels):
    """Pares de etiquetas que comparten borde (adyacentes en la imagen)."""
    pares = set()
    dif_h = labels[:, :-1] != labels[:, 1:]
    for a, b in zip(labels[:, :-1][dif_h], labels[:, 1:][dif_h]):
        if a > 0 and b > 0:
            pares.add(tuple(sorted((int(a), int(b)))))
    dif_v = labels[:-1, :] != labels[1:, :]
    for a, b in zip(labels[:-1, :][dif_v], labels[1:, :][dif_v]):
        if a > 0 and b > 0:
            pares.add(tuple(sorted((int(a), int(b)))))
    return pares


def fusionar_capsulas(labels, umbral_individual=1.7, umbral_combinado=1.8, ratio_area_min=0.15,
                       ancho_viruta_max=55):
    """Fusiona pares de regiones vecinas cuando: ninguna de las dos por
    separado ya parece una cápsula completa (aspect < umbral_individual),
    pero juntas sí (aspect combinado > umbral_combinado) -- el patrón
    exacto que vimos: cada mitad de una cápsula es un blob redondeado por
    separado, pero las dos juntas son claramente alargadas. No usamos
    color como criterio porque las cápsulas pueden ser bicolor.

    Excepción: si una región es muy estrecha en términos absolutos
    (ancho_menor < ancho_viruta_max), es casi seguro una "viruta" que dejó
    el watershed en el borde entre dos pastillas, no una pastilla alargada
    de verdad -- su aspect ratio alto no debe protegerla de fusionarse."""
    labels = labels.copy()
    cambiado = True
    while cambiado:
        cambiado = False
        for a, b in vecinos_adyacentes(labels):
            mask_a = labels == a
            mask_b = labels == b
            aspect_a, area_a, ancho_a = region_aspect(mask_a)
            aspect_b, area_b, ancho_b = region_aspect(mask_b)
            es_viruta_a = ancho_a < ancho_viruta_max
            es_viruta_b = ancho_b < ancho_viruta_max

            if es_viruta_a or es_viruta_b:
                # Regla 1: absorción de viruta. No exigimos nada sobre el
                # aspecto combinado -- una viruta pegada a un vecino más
                # grande casi siempre es un fragmento de ese vecino, no una
                # pastilla independiente. Basta con que sea claramente más
                # pequeña que el vecino.
                pequena, grande = (area_a, area_b) if area_a < area_b else (area_b, area_a)
                if pequena / grande < 0.6:
                    labels[mask_b if es_viruta_b else mask_a] = (a if es_viruta_b else b)
                    cambiado = True
                    break
                continue

            # Regla 2: dos mitades de cápsula genuinas. La señal real no es
            # "ninguna ya parece alargada" (un fragmento partido puede
            # salir ya bastante alargado él solo) sino que las dos tienen
            # una anchura parecida -- eso es lo que delata "son las dos
            # puntas de la misma cápsula" frente a "son dos objetos
            # distintos que se tocan".
            ratio_ancho = min(ancho_a, ancho_b) / max(ancho_a, ancho_b)
            if ratio_ancho < 0.6:
                continue
            ratio_area = min(area_a, area_b) / max(area_a, area_b)
            if ratio_area < ratio_area_min:
                continue
            aspect_combinado, _, _ = region_aspect(mask_a | mask_b)
            if aspect_combinado > umbral_combinado and \
               aspect_combinado > aspect_a + 0.3 and aspect_combinado > aspect_b + 0.3:
                labels[mask_b] = a
                cambiado = True
                break
    # renumerar 1..N sin huecos
    ids = sorted(set(labels[labels > 0].tolist()))
    remap = {old: new for new, old in enumerate(ids, start=1)}
    out = np.zeros_like(labels)
    for old, new in remap.items():
        out[labels == old] = new
    return out


if __name__ == "__main__":
    img = cv2.imread(str(IMG_PATH))
    model = FastSAM("FastSAM-s.pt")  # se descarga solo la primera vez si no existe

    fg_full, fragmentos = foreground_desde_fastsam(img, model)

    x0, y0, x1, y1 = CLUSTER_BBOX
    fg_cluster = np.zeros_like(fg_full)
    fg_cluster[y0:y1, x0:x1] = fg_full[y0:y1, x0:x1]

    anchos_cluster = [a for a, cx, cy in fragmentos if x0 <= cx < x1 and y0 <= cy < y1]
    escala = float(np.median(anchos_cluster)) if anchos_cluster else 60.0
    min_distance = max(6, int(escala * 0.55))
    ancho_viruta_max = max(15, int(escala * 0.35))
    print(f"Escala típica de pastilla EN EL RACIMO (ancho mediano, n={len(anchos_cluster)}): "
          f"{escala:.1f}px -> min_distance={min_distance}, ancho_viruta_max={ancho_viruta_max}")

    print(f"Píxeles de foreground en el racimo: {fg_cluster.sum()}")

    labels, dist, coords = separar_con_watershed(fg_cluster, min_distance=min_distance)
    n_antes = labels.max()
    labels = fusionar_capsulas(labels, ancho_viruta_max=ancho_viruta_max)
    n_instancias = labels.max()
    print(f"Watershed encontró {n_antes} instancias, tras fusionar cápsulas: {n_instancias} (ground truth real: 9)")

    # Visualización
    overlay = img.copy()
    rng = np.random.default_rng(0)
    colors = {i: tuple(int(c) for c in rng.integers(60, 255, 3)) for i in range(1, n_instancias + 1)}
    for i in range(1, n_instancias + 1):
        mask_i = labels == i
        overlay[mask_i] = (overlay[mask_i] * 0.4 + np.array(colors[i]) * 0.6).astype(np.uint8)
    for y, x in coords:
        cv2.drawMarker(overlay, (x, y), (0, 0, 255), cv2.MARKER_CROSS, 12, 2)
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 255, 255), 2)
    cv2.putText(overlay, f"watershed: {n_instancias} instancias (real: 7)", (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 3)
    cv2.putText(overlay, f"watershed: {n_instancias} instancias (real: 7)", (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 1)
    cv2.imwrite(str(OUT_DIR / "watershed_result.jpg"), overlay)

    # También guardamos la máscara de foreground bruta, para poder juzgar
    # si el problema (si lo hay) es la máscara de entrada o el watershed.
    fg_vis = img.copy()
    fg_vis[~fg_cluster] = fg_vis[~fg_cluster] // 3
    cv2.imwrite(str(OUT_DIR / "foreground_mask.jpg"), fg_vis)
