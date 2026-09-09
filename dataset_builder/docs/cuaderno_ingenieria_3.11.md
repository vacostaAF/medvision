# Cuaderno de ingeniería 3.11

## Motivación

El usuario, revisando un par `paired` en la app, encontró una lista de
fármacos incompleta: faltaban "PENTOXIFILINA" y "EXTRACTO LIPIDICO DE
SERENOA", visibles claramente en la foto real de la bolsita. Investigado
con un script de diagnóstico contra la base real (`session_0002`, posición
3): esas 2 líneas se leían correctamente por el OCR, pero se asignaban a la
bolsita VECINA ("domingo 01/03/26 CENA") en vez de a la suya
("lunes 02/03/26 DESAYUNO"), en 3 de 6 fotos que capturaban ambas bolsitas
del mismo frame — siempre en el mismo sentido, no al azar.

## Diagnóstico

`parse_label_sheets()` (3.2) decide cuándo empieza una bolsita nueva
mirando el ORDEN de lectura: si aparece una cabecera completa después de
haber recogido fármacos, corta ahí. Esto asume que el OCR entrega las
líneas en el mismo orden en que están impresas — asunción razonable en
general, pero que puede fallar cuando dos bolsitas están muy pegadas: el
texto justo en la frontera entre ambas puede leerse ligeramente girado o
solapado, haciendo que el reconstructor de filas (`_cluster_into_rows()`,
`label_ocr.py`) entregue esas líneas concretas fuera de su posición real en
la secuencia — el parser, que solo confía en el orden, no tiene forma de
detectarlo.

El usuario propuso la idea clave: ya existe un detector de costura
(brillo+tinte azulado, `bags/seam_band.py`, cuadernos 2.4-2.5) — usado
hasta ahora solo para el lado pastilla (identidad temporal entre frames).
La misma señal puede usarse aquí para otra cosa: saber, DENTRO de una
foto, en qué posición Y está la costura entre dos bolsitas, y usar esa
posición para decidir a qué bolsita pertenece cada línea de texto — en vez
de fiarlo solo al orden de lectura del OCR.

## Arreglo

- `ocr/label_ocr.py`: `_cluster_into_rows()` ahora también calcula y
  devuelve la posición Y (centro de fila, en píxeles) de cada línea
  reconstruida — antes se calculaba internamente para el propio agrupado en
  filas, pero se descartaba al devolver el resultado. `OCRResult` tiene un
  campo nuevo, `word_y_norm` (posición Y normalizada 0-1 por línea, mismo
  índice que `words`).
- `ocr/parser.py`: nueva función `parse_label_sheets_by_position(lines_with_y,
  seam_y_norm)`. Si hay una costura conocida, separa las líneas en dos
  grupos por posición Y (por encima / por debajo de la costura) y parsea
  cada grupo de forma INDEPENDIENTE con la lógica ya existente — así
  ninguna línea de un lado puede colarse en el otro, sin importar en qué
  orden las haya entregado el OCR. Solo cubre el caso de 2 bolsitas (una
  costura); con 3+, cae a `parse_label_sheets()` basado en orden, como
  antes. Si no hay costura, o toda la lectura cae de un mismo lado, se
  comporta exactamente igual que antes (compatible).
- `dataset/builder.py::_run_ocr_and_persist()`: ejecuta `detect_seam_band()`
  sobre la imagen procesada (la misma que `word_y_norm` usa como
  referencia, para que las coordenadas cuadren) y, si encuentra costura,
  usa `parse_label_sheets_by_position()` en vez del parseo por orden.

## Validado

Reproducido el caso real exacto como test sintético (mismas líneas, mismo
desorden, misma posición de costura): con el método antiguo (por orden),
Pentoxifilina y Extracto lipídico se pierden de DESAYUNO; con el nuevo (por
posición), los 5 fármacos de DESAYUNO quedan completos y CENA se queda solo
con lo suyo. Confirmado también que sin costura detectada, o con toda la
lectura de un mismo lado, el comportamiento es idéntico al anterior (sin
regresión).

## Limitación honesta

No he podido probar esto con PaddleOCR real (no está instalado en mi
entorno) — la validación es con datos sintéticos que reproducen fielmente
el patrón encontrado en la base real, pero la confirmación final con OCR de
verdad queda pendiente de que el usuario lo pruebe. También: la posición Y
de una línea individual, tal como PaddleOCR/`_cluster_into_rows()` la
calcula, podría en algún caso quedar cerca del límite de la costura sin
ser un error claro de lado — vale la pena revisar con datos reales si el
umbral de la costura necesita algún margen, no solo una comparación exacta.

## Pendiente

Ejecutar `rebuild-pairs` **no sirve aquí** — a diferencia de los arreglos
anteriores de emparejamiento, este cambia el PARSEO del OCR en sí, así que
hace falta reprocesar (al menos las bolsitas con más de una en el mismo
frame; en la práctica, más simple relanzar `build-dataset` sin `--fresh`,
que solo reprocesará lo que haga falta si se identifican y "des-completan"
los vídeos afectados, o `--fresh` completo si se prefiere no complicarse).
