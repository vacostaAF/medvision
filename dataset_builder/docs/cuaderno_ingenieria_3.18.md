# Cuaderno de ingeniería 3.18

## Motivación

El usuario, revisando en la app, notó que el sombreado de costura (3.12)
solo aparecía en el lado etiqueta — el lado pastilla, con el mismo
problema real (dos bolsitas cabiendo en un frame), se enseñaba sin ninguna
marca. Propuso además la razón de fondo por la que el detector de costura
es fiable ahí: la zona termosellada nunca tiene texto detrás — es
justamente la señal (brillo + reflejo, no texto) que ya usa
`detect_seam_band()` desde 2.4.

## Arreglo

- `database/schema.py`: `track_pairs.pill_ocr_result_id`, equivalente a
  `label_ocr_result_id` (3.9) pero para el lado pastilla. Añadido a la
  auto-reparación de esquema (3.10).
- `dataset/builder.py`: se rellena solo cuando se conoce con certeza — en
  el emparejamiento **directo** (cabecera compartida entre los dos lados,
  2.9), donde `pg.representative_ocr_result_id` ya está disponible. Para
  el emparejamiento por posición (3.13) y el mecanismo de respaldo por
  costura (2.4-2.5), no se rellena — no hay forma fiable de saber qué
  lectura concreta corresponde, igual que ya pasaba con el lado etiqueta
  antes de resolverse con la cabecera.
- `database/repository.py::list_pairs_for_review()`: trae también
  `pill_seam_position`/`pill_seam_side`.
- `app/review_app.py`: el lado pastilla usa ahora `get_pair_group_images()`
  (como ya hacía el lado etiqueta) y aplica el mismo `render_with_seam()`.
  Cuando no hay dato de costura conocido (posición/respaldo), se muestra
  un aviso explicando por qué, en vez de dejarlo sin explicación.

## Validado

Test de integración con SQL real: costura y lado guardados para AMBOS
lados de un mismo par (pastilla `seam_side='below'`, etiqueta
`seam_side='above'`, valores de posición distintos) — confirmado que
`list_pairs_for_review()` devuelve los cuatro valores correctos, sin
mezclarlos entre lados.

## Alcance, honesto

Como con el lado etiqueta (3.12), el lado (`above`/`below`) se calcula una
vez por par, no foto a foto dentro del grupo — mismo supuesto (la bolsita
se mantiene en el mismo lado físico a lo largo del paneo), misma
limitación si el paneo cambiara de sentido entre fotos del mismo grupo.
