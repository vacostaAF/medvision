# Cuaderno de ingeniería 2.4

## Motivación

El lado pastilla no tiene texto propio del que derivar una identidad fiable
(a diferencia del lado etiqueta, resuelto en 1.9-2.3 vía cabecera OCR). El
usuario propuso usar la costura física del sellado entre bolsitas como señal
de identidad — una idea sólida: es una frontera física real, no una
suposición de parecido visual.

## Por qué no basta con el código existente

`bags/splitter.py::estimate_horizontal_seams()` ya existe y se usaba en la
demo 1.0-1.3 para separar bolsas dentro de un mismo frame. Probado contra 3
imágenes reales del lado pastilla (`f000080/140/190_bag00.jpg`), sus picos de
gradiente no coincidían con la costura visible a simple vista — con tanto
texto impreso en la imagen, cada línea de letras genera un gradiente
horizontal fuerte que compite con (y a menudo gana a) la señal de la propia
costura. Es un detector genérico de "borde horizontal fuerte", no específico
de costura.

## Detector nuevo: firma de color, no gradiente genérico

La costura tiene una firma visual distinta en estas fotos: banda de brillo
alto con tinte azulado (reflejo del foco/anillo LED usado al grabar — se
observa tanto en el lado etiqueta como en el pastilla). `bags/seam_band.py`
mide `brillo × tinte_azul` por fila y busca el pico más prominente respecto
a la mediana de la imagen, en vez de gradiente Sobel.

## Validación con datos reales

| imagen | costura detectada | posición | prominencia |
|---|---|---|---|
| f000080 (vista: seguía viéndose la costura arriba del todo) | Sí | 0.22 | 14.4 |
| f000140 (contenido medio de bolsita, sin costura visible) | No | — | 2.5 |
| f000190 (pie de farmacia + inicio de costura abajo) | Sí | 0.96 | 12.5 |

Separación clara entre el caso con costura (12-14) y sin ella (2.5) — con
solo 3 imágenes, pero el margen es amplio. De paso, el propio contenido de
las fotos confirmó independientemente que `f000190` es una bolsita distinta
a `f000080`/`f000140` (fármacos distintos, "sábado desayuno" vs "sábado
almuerzo" con CARBIMAZOL) — coherente con que haya una costura real entre
medias.

Tests con imágenes sintéticas (banda brillante+azul vs. uniforme, y banda
brillante SIN tinte azul para comprobar que no basta con brillo solo) en
`tests/test_seam_band.py` — no se han incluido las fotos reales como fixture
permanente por tamaño/portabilidad, pero la validación contra ellas queda
documentada aquí.

## Pendiente antes de enganchar esto al tracking

Solo se han probado 3 puntos de una secuencia de 8 observaciones reales
(frames 80 a 190). Falta:
1. Los 5 frames intermedios (90, 100, 110, 120, 130) para saber si la
   transición ocurre limpiamente entre 140 y 190, o si hay más de una
   costura en ese tramo (recordar: el lado etiqueta mostró al menos 4
   bolsitas reales distintas en un rango de tiempo similar).
2. Diseñar la regla exacta de qué lado de la costura pertenece a qué grupo
   quan se detecta un valor de `position_norm` intermedio (no siempre
   estará cerca del 0 o del 1 como en estos 2 ejemplos).
3. Una imagen que sirva de "seguro no hay costura aquí, en medio de una
   bolsita" adicional a f000140, para no calibrar el umbral de prominencia
   con un solo caso negativo.

No se ha construido todavía la función de agrupado por costura
(`group_pill_bags_by_seam`, análoga a `group_label_bags_by_header`) a
propósito: mejor validar el detector con la secuencia completa antes de
construir encima, mismo criterio que se ha seguido en todo el proyecto.
