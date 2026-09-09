# Cuaderno de ingeniería 3.9

## Motivación

El usuario preguntó cómo revisar específicamente los pares `paired`
(coincidencia directa) para poder tomar una muestra en vez de mirar los 145
uno a uno, como se había recomendado. La app solo filtraba por decisión de
revisión humana (pendiente/aceptado/...), no por el estado que pone el
propio pipeline (`paired`/`review`/`unmatched_label`/`unmatched_pill`).

## Bug encontrado de paso: mismo problema de 3.8, en la consulta de la app

Al tocar `list_pairs_for_review()` para añadir el filtro, se encontró que
su consulta tenía el MISMO bug que 3.8 arregló en el pipeline:
`LEFT JOIN ocr_results orl ON orl.bag_id=lb.id` — sin distinguir
`sheet_index`, en una foto con más de una bolsita (3.2) podía traer la
lectura equivocada a la app de revisión, aunque el pipeline internamente
ya tuviera resuelto cuál era la correcta.

## Arreglo

- `database/schema.py`: nueva columna `track_pairs.label_ocr_result_id` —
  el identificador exacto de la lectura representante, ya resuelto por el
  agrupado, en vez de tener que volver a adivinarlo por `bag_id` en
  cualquier sitio que lo necesite (pipeline, app, o lo que venga después).
- `dataset/builder.py`: se guarda `int(ocr["id"])` (ya calculado
  correctamente desde 3.8) al escribir cada `track_pairs` fila.
- `database/repository.py::list_pairs_for_review()`:
  - Usa `tp.label_ocr_result_id` directamente — sin JOIN por `bag_id`.
  - Nuevo parámetro `status_filter`: filtra por el estado del pipeline
    (`paired`/`review`/`unmatched_label`/`unmatched_pill`/`all`).
  - Nuevo parámetro `sample_size`: si se da, elige esa cantidad al azar del
    resultado ya filtrado (con `random.sample`, sin fallar si se pide más
    de lo que hay disponible).
- `app/review_app.py`: nuevo selector "Estado del pipeline" en la barra
  lateral, y checkbox "Muestra aleatoria" con tamaño configurable.

## Validado

Dos tests de integración con SQL real: (1) filtro por status del pipeline
+ muestreo — 10 pares (6 `paired`, 4 `unmatched_label`), confirmado que
cada filtro devuelve exactamente lo esperado y que pedir una muestra mayor
que el total disponible no falla, se queda con lo que hay; (2) regresión
específica del bug de `sheet_index` — una foto con 2 bolsitas (2
`ocr_result_id` distintos) usada en 2 pares distintos, confirmado que cada
uno muestra su propio `label_ocr_result_id`, no el mismo para los dos.

## Nota

Como con 3.0/3.5, esto añade una columna nueva — hace falta `--fresh` o, si
solo se quiere aplicar sobre el emparejamiento sin repetir detección/OCR,
`rebuild-pairs` (la columna se rellena de nuevo al reconstruir los pares).
