# Cuaderno de ingeniería 3.12

## Motivación

Tras el arreglo de 3.11 (parseo consciente de posición), el usuario
preguntó si el resultado sería "una bolsa por foto" para simplificar la
revisión. Respuesta: no — las fotos con dos bolsitas seguirán mostrando
las dos, eso es un hecho físico del encuadre, no algo que el parseo del
texto pueda cambiar. Pero sí se puede ayudar visualmente: ya que ahora se
conoce la posición exacta de la costura (usada para decidir qué texto
pertenece a qué bolsita), esa misma información sirve para señalar en la
propia imagen qué mitad es la relevante.

## Arreglo

- `database/schema.py`: `ocr_results.seam_side` ('above'/'below'/NULL) —
  de qué lado de la costura salió esta bolsita concreta. Añadido a la
  auto-reparación de esquema (3.10), no requiere `--fresh`.
- `ocr/parser.py`: `LabelSheet` tiene un campo nuevo, `seam_side` (por
  defecto `None`, no rompe compatibilidad). `parse_label_sheets_by_position()`
  marca cada bolsita resultante con el lado del que vino.
- `dataset/builder.py`: se guarda `seam_side` en cada `ocr_results`, y se
  actualiza `bags.seam_position`/`seam_prominence` con el valor calculado en
  el momento del parseo (antes solo se guardaba para el lado pastilla, en
  el momento de crear la bolsa) — así la app dibuja exactamente la misma
  costura que decidió el reparto de líneas, no un cálculo aparte que
  podría no coincidir.
- `database/repository.py`: `list_pairs_for_review()` trae también
  `label_seam_position`/`label_seam_side`. Nuevo método
  `get_pair_group_images()` (variante de `get_pair_group_image_paths()`)
  que además devuelve la costura de cada foto del grupo.
- `app/review_app.py`: nueva función `render_with_seam()` — cuando se
  conoce la costura, dibuja una línea en esa posición y atenúa (al 35% de
  brillo) la mitad de la foto que NO corresponde a la bolsita que se está
  revisando. Se aplica solo al lado etiqueta (donde vive el arreglo de
  3.11); el lado pastilla se sigue mostrando sin modificar.

## Alcance, honesto

El lado (`above`/`below`) se calcula una vez por par, no foto a foto dentro
del grupo — se asume que la bolsita se mantiene en el mismo lado físico a
lo largo del paneo (razonable en general, pero no garantizado en todos los
casos). Si en algún caso el paneo cambia de sentido o la bolsita cambia de
posición relativa entre fotos del mismo grupo, el sombreado podría no
acertar en alguna de las fotos del grupo aunque sí en la mayoría.

## Validado

- `render_with_seam()`: test con imagen sintética (mitad clara/mitad
  oscura) — confirmado que `seam_side='above'` atenúa la parte de abajo y
  `seam_side='below'` atenúa la de arriba, y que sin costura conocida
  devuelve la imagen sin tocar.
- Test de integración con SQL real: costura y lado guardados vía
  `update_bag_seam()`/`upsert_ocr(seam_side=...)` se recuperan correctamente
  tanto por `list_pairs_for_review()` como por `get_pair_group_images()`.

## Pendiente

No he podido probar la app en sí (Streamlit no está disponible en mi
entorno) — la lógica de dibujo está validada de forma aislada, pero la
integración visual completa (¿se ve bien en la interfaz real?) queda
pendiente de que el usuario la pruebe tras el reproceso.
