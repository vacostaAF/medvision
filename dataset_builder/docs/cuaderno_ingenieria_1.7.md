# Cuaderno de ingeniería 1.7

## Motivación

El usuario corrió el pipeline completo (`build-dataset`) contra los 2 vídeos
reales por primera vez. Resultado: `pairs_needing_review: 3/3`,
`paired_with_label: 1/3`. Los 7 `ocr_results` generados eran todos
fragmentos — como mucho 1-3 fármacos reconocidos, nunca los 6-7 reales de una
bolsita completa (`ocr.csv`). Se pidieron las imágenes de recorte reales
(`output/ocr/MVI_2714/f0000XX_bagYY.png`) para diagnosticar con evidencia
visual, no solo con texto.

## Diagnóstico (confirmado visualmente)

`f000000_bag00/01/02` resultaron ser **3 franjas horizontales de la misma
bolsita física** — no 3 bolsitas: la tira del asa (arriba), la marca "51" +
un trozo de "PELAYO PEINADO JOSEFA" (medio), y cabecera + CALCIFEDIOL cortado
a media frase de BISOPROLOL (abajo).

Causa raíz en `bags/splitter.py::estimate_horizontal_seams()`: busca costuras
de termosellado mediante gradiente Sobel-Y. Con la cámara del iPhone (demo
1.0-1.3), varias bolsitas pequeñas cabían en un mismo frame, así que había
costuras reales que detectar. Con la cámara nueva (mucho más cerca, para que
el texto se lea), **cada frame apenas contiene una bolsita**, a veces ni eso
completa. Sin costura real que encontrar, `estimate_horizontal_seams()`
devuelve <2 candidatos y el código cae a `fallback_equal_splits()`, que
reparte la altura visible en bandas iguales **sin ningún criterio de
contenido** — cortando una bolsita entera en 2-3 trozos arbitrarios.

Confirmado con una franja sintética de 900px (proporción similar a las
reales): con `max_segments=12` (config anterior) se generaban 2 segmentos de
igual altura sin motivo; con `max_segments=1`, un único segmento con la
franja completa.

## Arreglo (solo configuración, sin tocar código)

`max_segments` ya existía como parámetro y limita cuántos cortes como máximo
se aplican (`seams[:max_segments-1]`). Con `max_segments=1`, esa lista queda
vacía sin importar lo que haya encontrado `estimate_horizontal_seams()`, y el
segmento resultante es la franja detectada completa. Cambiado en
`config/default.yaml` y `config/demo_fast.yaml`.

## Lo que esto NO resuelve todavía

Si una bolsita entera (cabecera + 6-7 fármacos + pie de farmacia) no cabe
dentro de un único frame por el zoom de esta cámara, `max_segments=1` evita
el corte arbitrario pero seguirá capturando solo la parte visible en ese
frame concreto — coherente, pero potencialmente incompleta. El pipeline ya
seguía la misma bolsita física a lo largo de varios frames
(`multi_observation_tracks: 3` en el summary.json real), pero hoy solo se
queda con el frame de "mejor calidad" y descarta el resto — no fusiona el
texto de varios frames de la misma bolsa entre sí.

Esto no se ha tocado en este incremento a propósito: es un cambio de arquitectura
mayor (agregar/fusionar OCR de varias observaciones de un mismo track, no solo
elegir una) y antes de construirlo hace falta saber si hace falta —
`max_segments=1` puede ser suficiente si la cámara suele capturar la bolsita
casi entera en algún frame del paneo. Pendiente: volver a correr el pipeline
con este cambio y mirar `item_count` en `ocr.csv` antes de decidir si se
necesita.
