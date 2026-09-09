# Cuaderno de ingeniería 3.2

## Motivación

Primeros 2 vídeos de prueba en vertical (`MVI_2732`/`MVI_2733`, agosto
2026), antes de comprometerse a grabar los 108 de nuevo. Dos hallazgos
reales, ambos confirmados con las imágenes reales, no supuestos.

## Hallazgo 1: la cámara no rota los píxeles, solo el contenido

`ffprobe` reporta `1920x1080` (proporción horizontal) en los dos vídeos, sin
ningún metadato de rotación (`side_data`, `rotate` tag — ninguno presente).
Pero el contenido real está girado 90°: al extraer un frame y rotarlo por
software, con **90° en sentido horario** el texto se lee perfectamente (sin
volteo en `MVI_2733`, lado etiqueta; con volteo adicional en `MVI_2732`,
lado pastilla — coherente con ser reflejo por transparencia, ver 2.9).

Causa: la cámara no escribe metadato de rotación al grabar en vertical —
el sensor sigue produciendo fotogramas en orientación horizontal nativa, y
lo que cambia es el contenido dentro de ellos. Sin corregirlo, todo el
pipeline (detección, OCR) procesaría los frames "tumbados".

**Arreglo**: nuevo parámetro `sampling.rotate_degrees` en la config (0 por
defecto, no afecta a los vídeos horizontales ya procesados). Se aplica en
`dataset/builder.py`, justo después de leer cada frame y antes de cualquier
otro procesado — un único punto, así que detección, calidad y OCR reciben
ya el frame corregido sin tocar nada más. Probado con `cv2.rotate(...,
ROTATE_90_CLOCKWISE)` contra los 2 vídeos reales: texto perfectamente
legible, y la detección de bolsa (`detect_bag_strip`) funciona con el mismo
`threshold_value=100` que ya teníais, sin necesitar recalibrarlo.

## Hallazgo 2: dos bolsitas completas caben en un mismo frame

Con más resolución disponible a lo largo de la tira (1920px en vez de
1080px), confirmado visualmente: un mismo frame puede mostrar dos bolsitas
enteras, cabecera y fármacos incluidos. Con el parser de una sola bolsita
por lectura, esto fusionaba las dos bajo la cabecera de la primera —
comprobado con el texto real exacto de estas dos bolsitas: 4 fármacos (2
duplicados) bajo "jueves", con la bolsita de "miércoles" completamente
perdida.

**Arreglo, en dos capas:**

1. `ocr/parser.py::parse_label_sheets()` (plural, nueva): detecta cuando una
   cabecera completa (día de la semana reconocido) aparece DESPUÉS de que
   ya se han recogido fármacos en la bolsita actual — señal inequívoca de
   que ha empezado otra bolsita, no de que la cabecera se repite. Devuelve
   una `LabelSheet` por cada bolsita encontrada. `parse_label_sheet()`
   (singular) se mantiene para compatibilidad, devolviendo solo la primera.

   Limitación conocida y documentada: el nombre del paciente de la segunda
   bolsita (y siguientes) se pierde — las líneas de paciente/ubicación que
   preceden a esa cabecera ya se consumieron como "fármaco no reconocido"
   antes de detectar el corte. Día/fecha/franja (lo que de verdad importa
   para la identidad de la bolsita) sí se extraen correctamente en todas.

2. Esquema: `ocr_results` ya no tiene `UNIQUE(bag_id)` — pasa a
   `UNIQUE(bag_id, sheet_index)`. Una foto con dos bolsitas genera dos filas
   de `ocr_results` (sheet_index 0 y 1), cada una con su propia cabecera y
   lista de fármacos vía `label_headers`/`label_items` — no una fusionada.
   `repository.py::upsert_ocr()` acepta `sheet_index` (0 por defecto,
   compatible con datos ya existentes).

3. `dataset/builder.py::_run_ocr_and_persist()` ahora usa
   `parse_label_sheets()` y persiste todas las bolsitas encontradas,
   devolviendo una lista de filas en vez de una sola. El resto del pipeline
   (agrupado por cabecera, emparejamiento) no necesita cambios: ya opera
   sobre "observaciones" identificadas por `ocr_result_id`, y ahora
   simplemente puede haber más de una por `bag_id`.

## Validado

- Rotación: contra frame real de los 2 vídeos, texto legible + detección de
  bolsa con confianza 1.0.
- Parser: con el texto real exacto de las dos bolsitas del mismo frame, las
  separa correctamente (4 fármacos → 2+2, sin duplicar ni mezclar).
- Persistencia: test de integración con SQL real — dos filas de
  `ocr_results` para el mismo `bag_id`, cada una con su cabecera y fármacos
  propios, recuperables por separado vía `get_ocr_observations_for_video()`.

## Pendiente

Falta ver el comportamiento de punta a punta con PaddleOCR real (aquí no
disponible) contra vídeo vertical completo, y confirmar que el
emparejamiento directo por cabecera (2.9) funciona igual de bien cuando el
lado etiqueta puede aportar 2 bolsitas por frame en vez de 1. Recomendado
antes de comprometerse a los 108: correr estos 2 vídeos (y los que faltan
de los 10 de prueba) por el pipeline completo real, con
`rotate_degrees: 90` en la config.
