# Cuaderno de ingeniería 3.6

## Motivación

Caso real: el usuario añadió vídeos nuevos (`MVI_2771`-`MVI_2774`) a
`videos_vertical` y lanzó `build-dataset` sin regenerar antes
`sessions_vertical.yaml` con `plan-sessions`. Resultado esperado dado el
aviso ya existente (2.9): esos vídeos se procesaron como `side='unknown'`,
sin OCR ni emparejamiento.

Pero el salto de vídeos ya procesados (3.5) tiene un efecto colateral no
previsto: esos vídeos quedan marcados `status='completed'` igualmente (el
bloque `try` termina sin error, aunque el lado sea `unknown`). Al corregir
`sessions.yaml` y volver a lanzar, `is_video_completed()` solo miraba el
nombre de fichero — los daba por buenos tal cual, arrastrando el error de
`unknown` para siempre en vez de reprocesarlos con el lado correcto.

## Arreglo

`is_video_completed(filename, side)` ahora exige también que el lado
coincida con el que se le asignaría en esta ejecución
(`WHERE filename=? AND status='completed' AND side=?`). Si `unknown` pasa a
`pill_side`/`label_side` tras corregir la sesión, deja de coincidir con lo
guardado y el vídeo se reprocesa — sin necesitar `--fresh` ni tocar la base
a mano.

`dataset/builder.py`: se calcula `side` (`infer_side()`) ANTES de decidir si
saltar el vídeo, no después — necesario para poder comparar.

## Validado

Test de integración con SQL real que reproduce el caso exacto: vídeo
completado con `side='unknown'`, mismo lado → sigue detectándose como
completado (se saltaría correctamente); lado corregido a `pill_side` → deja
de detectarse como completado (se reprocesa). Y una prueba end-to-end con
`build_dataset()` real en tres pasadas: 1) procesa como `unknown`,
2) mismo config, se salta, 3) config corregido, se reprocesa sin que aparezca
el aviso de salto.

## Recordatorio de flujo, para que no se repita

Al añadir vídeos nuevos a una carpeta ya en uso: **primero**
`plan-sessions` (para que `video_sides` los conozca), **después**
`build-dataset`. Si se hace al revés, ya no hace falta preocuparse — con
este arreglo, corregir la sesión y volver a lanzar reprocesa lo que haga
falta automáticamente.
