# Cuaderno de ingeniería 3.29

## Motivación

El arreglo de 3.28 evita que se vuelva a corromper `seam_prominence`, pero
la base de datos del usuario ya tenía valores corruptos guardados de la
ejecución `--fresh` que falló — `rebuild-pairs` no recalcula esa columna
(solo lee lo que ya hay), así que seguía reventando con el mismo error
exacto, aunque el código ya estuviera arreglado.

## Arreglo

- `database/repository.py::repair_corrupted_seam_prominence()`: recorre
  `bags.seam_prominence`, y para cada valor guardado como `bytes` (la
  firma de la corrupción — SQLite serializó un `numpy.float32` como BLOB),
  lo decodifica con `struct.unpack("<f", ...)` — son los 4 bytes crudos
  del float32 original, así que el valor **se recupera exacto**, no se
  pierde ni se sustituye por un valor por defecto. Idempotente: sobre una
  base ya limpia no hace nada.
- `dataset/builder.py::rebuild_pairs()`: llama a esta reparación
  automáticamente, antes de `_build_pairs()` — igual que ya hacía con la
  distancia de paneo pendiente (3.14), sin que el usuario tenga que
  acordarse de lanzar nada aparte.

## Validado

- Reproducido el mismo patrón de bytes corruptos exacto que salió en el
  error real del usuario (`b'\xfe\x976A'`) — la reparación lo decodifica
  al valor original correcto.
- Confirmado que tras reparar, `float()` sobre el valor ya no revienta
  (la misma operación que causaba el `ValueError` real).
- Idempotencia: reparar dos veces no falla ni cambia nada la segunda vez.
- No toca nada en una base ya limpia (sin datos corruptos).
- **Extremo a extremo con `rebuild_pairs()` real**: base con un valor
  corrupto exactamente como lo dejó el bug real → `rebuild_pairs()`
  completa sin reventar, con el aviso "Reparadas N bolsa(s)" visible.
- Suite completa: 103 tests, todos en verde.

## Para el usuario, en una frase

No hace falta hacer nada especial — actualizad al código de esta ronda y
lanzad `rebuild-pairs` otra vez, tal cual. La reparación de los datos ya
corrompidos ocurre sola, automáticamente, antes de reconstruir el
emparejamiento.
