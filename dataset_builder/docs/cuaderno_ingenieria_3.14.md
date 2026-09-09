# Cuaderno de ingeniería 3.14

## Motivación

Al entregar 3.13 (emparejamiento por posición), el usuario tenía un
`--fresh` completo en marcha (con 3.11/3.12 ya aplicados) todavía sin
terminar. Pedir OTRO `--fresh` para incorporar 3.13 habría significado
tirar ese trabajo y repetir horas de detección/OCR — pero
`cumulative_pan_px` solo necesita los frames YA GUARDADOS en disco, no
repetir nada de eso.

## Arreglo

- `database/repository.py::get_completed_videos_missing_pan_distance()`:
  vídeos ya completados (`status='completed'`) que no tienen
  `cumulative_pan_px` en ninguno de sus frames — los procesados con una
  versión anterior a la 3.13.
- `dataset/builder.py::_compute_and_store_pan_distances()`: se extrajo el
  cálculo (antes solo inline dentro del bucle de `build_dataset()`) a una
  función reutilizable, para no duplicar la lógica.
- `rebuild_pairs()` ahora, antes de reconstruir el emparejamiento, rellena
  automáticamente la distancia de paneo de cualquier vídeo que la tenga
  pendiente — sin necesitar ningún flag nuevo, es automático.

## Validado

Prueba de extremo a extremo con vídeo real reproduciendo el escenario
exacto: `build_dataset()` normal (con 3.13, calcula distancia) → se anulan
manualmente los valores (simulando un dataset de una versión anterior) →
`rebuild_pairs()` los rellena solos, sin volver a llamar a
`build_dataset()`. Test permanente adicional con SQL real para
`get_completed_videos_missing_pan_distance()`.

## Para el usuario, en una frase

No hace falta un segundo `--fresh`. Dejad que termine la ejecución actual
(con los arreglos de costura de 3.11-3.12 ya incluidos), actualizad al
código de esta ronda, y lanzad `rebuild-pairs` — la distancia de paneo se
calcula sola sobre lo que ya tenéis, y con eso el emparejamiento por
posición (3.13) ya puede actuar sin haber repetido ni un minuto de
detección u OCR.
