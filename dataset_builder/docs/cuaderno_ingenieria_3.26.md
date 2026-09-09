# Cuaderno de ingeniería 3.26

## Motivación

Investigando `session_0002 · posición 3` (5 fármacos guardados de 6
reales), se encontró el mismo patrón de asignación cruzada del cuaderno
3.11 — pese a que 3.11 ya estaba aplicado. Medido con datos reales antes
de decidir si merecía la pena arreglarlo: **547 fotos con 3+ lecturas
distintas, 433 de 734 pares del dataset (59%) las usan** — incluidos 10
pares ya `accepted` por un humano. No era un caso raro, era la mayoría del
dataset.

## Diagnóstico

`parse_label_sheets_by_position()` (3.11) y `detect_seam_band()` (2.4)
solo contemplan **una** costura — dos tramos. Con 3+ bolsitas en el mismo
frame (2+ costuras), el detector encuentra solo la más marcada, y todo lo
que cae al tramo "más grande" de las dos mitades resultantes se sigue
repartiendo por el método antiguo (orden de lectura) — el mismo bug de
3.11, escondido dentro de un tramo en vez de entre dos.

## Arreglo

- `bags/seam_band.py::detect_seam_bands()` (nueva, plural): encuentra
  TODOS los picos suficientemente marcados en la misma señal de
  brillo+tinte azulado ya validada (no solo el máximo global), con una
  separación mínima entre picos para no contar ruido alrededor de uno
  mismo como dos costuras distintas.
- `ocr/parser.py::parse_label_sheets_by_multi_position()` (nueva):
  generaliza la versión de una costura a N costuras / N+1 tramos. Cada
  tramo se parsea de forma independiente (mismo principio que 3.11: el
  orden de lectura SÍ es de fiar dentro de un mismo tramo, no entre
  tramos). Con 1 sola costura, mantiene el nombrado `above`/`below` ya
  existente por compatibilidad; con 2+, usa `segment_0`, `segment_1`...
- `database/schema.py`: `bags.seam_positions_json` — todas las costuras
  encontradas (antes solo se guardaba la primera en `seam_position`).
  Añadido a la auto-reparación de esquema (**se corrigió de paso un bug
  real**: la migración tenía dos entradas `"bags"` duplicadas en el mismo
  diccionario Python, la segunda pisaba a la primera sin que nada
  avisara — fusionadas en una).
- `dataset/builder.py`: usa `detect_seam_bands()` (todas) en vez de
  `detect_seam_band()` (una) para el lado etiqueta.
- `app/review_app.py::render_with_seam()`: dibuja TODAS las líneas de
  costura, y sombrea el tramo correcto tanto en el caso de 1 costura
  (`above`/`below`) como en el de 2+ (`segment_N`, calculando sus límites
  reales a partir de las posiciones ordenadas).

## Validado

- `detect_seam_bands()`: 0, 1 y 2 costuras sintéticas, posiciones
  correctas en los 3 casos.
- `parse_label_sheets_by_multi_position()`: reproducido el caso real
  exacto (3 bolsitas, 2 costuras) — con el método antiguo se pierden 2 de
  5 fármacos, con el nuevo quedan los 5 completos. Además: compatibilidad
  con 1 costura (mantiene `above`/`below`), sin costuras (igual que el
  parseo normal), y tramo vacío (cae al parseo normal sin partir).
- `render_with_seam()`: los 4 casos de 3 segmentos (cada segmento
  individual sin atenuar + el resto atenuado, y sin lado conocido con las
  2 líneas dibujadas sin atenuar nada).
- Integración con SQL real: guardado/recuperación de varias costuras de
  punta a punta, y compatibilidad con bolsas guardadas por el método
  antiguo (solo `seam_position`, sin `seam_positions_json`).
- Extremo a extremo con vídeo real: pipeline completo sin errores con
  todo el código nuevo integrado.
- 95 tests en total, todos en verde.

## Pendiente

Necesita `--fresh` — como con 3.11, este cambio afecta al PARSEO del OCR
en sí, no solo al emparejamiento; `rebuild-pairs` no basta. No se ha
podido validar `detect_seam_bands()` contra una foto real de 3 bolsitas
(solo con datos sintéticos) — pendiente de confirmar con una imagen real
tras el reproceso.
