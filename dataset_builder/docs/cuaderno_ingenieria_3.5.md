# Cuaderno de ingeniería 3.5

## Motivación

El usuario preguntó, antes de seguir grabando hacia las 108, si al añadir
vídeos nuevos tendría que "analizar" los ya procesados otra vez. Respuesta
honesta con el diseño de entonces: sí — `build_dataset()` recorre y
reprocesa (detección + OCR) **todos** los vídeos de la carpeta en cada
ejecución, sin distinguir los ya hechos de los nuevos. Con sesiones de
grabación repartidas en varios días y vídeos que ya hemos visto tardar
15-20 minutos cada uno en OCR, esto no es sostenible según se acerque a 108.

## Arreglo

- `database/schema.py`: columna `status` en `videos` (`'in_progress'` por
  defecto, `'completed'` solo al terminar de procesarse sin errores). No es
  un booleano simple a propósito: si un vídeo se corta a media detección/OCR
  por un fallo, debe quedar `in_progress` y reintentarse la próxima vez, no
  darse por bueno a medias.
- `database/repository.py`: `is_video_completed(filename)` /
  `mark_video_completed(video_id)`.
- `dataset/builder.py`: al principio del bucle por vídeo, si
  `is_video_completed()` es cierto, se salta con un aviso en consola. Se
  marca `completed` al final del bloque `try` de ese vídeo, justo antes del
  `except` que lo envuelve — solo si terminó sin lanzar excepción.

## Efecto colateral encontrado y arreglado de paso

Al implementar el salto, se detectó que el resumen final (`summary.json`) y
los CSV de metadatos (`frames.csv`, `bags.csv`, `tracks.csv`, `ocr.csv`)
contaban solo lo procesado en **esa** ejecución concreta — con vídeos
saltados, habrían mostrado recuentos parciales (p.ej. `frames: 0` aunque los
datos de ejecuciones anteriores siguen intactos en la base), dando la
impresión de que algo se había perdido.

Arreglado en dos partes:
- El resumen (`summary`) ahora cuenta contra la base de datos
  (`COUNT(*)` real sobre `videos`/`frames`/`bags`/`ocr_results`), no contra
  las listas acumuladas solo en memoria durante esta ejecución — mismo
  patrón que ya usaba `rebuild_pairs()` (3.1).
- `_write_csv()` admite un modo `append`: si el CSV de una ejecución
  anterior ya existe, se leen sus filas y se combinan con las nuevas, en vez
  de sobrescribir perdiendo el historial de vídeos ya procesados y saltados
  esta vez. `track_pairs.csv` no usa este modo — ya se recalcula entero cada
  vez a partir de toda la base, es acumulativo por diseño desde antes.

## Validado

Dos ejecuciones seguidas de `build_dataset()` sobre la misma carpeta, sin
`--fresh`: la segunda saltó el vídeo ya procesado (aviso en consola
confirmado) y el resumen mostró los mismos recuentos que la primera (no
ceros) — confirmado además que `ocr.csv` no duplicó la fila tras la segunda
ejecución (verificado con el propio parser de CSV, no con `wc -l`, que
cuenta mal si un campo tiene saltos de línea internos).

## Nota para el usuario

`--fresh` sigue siendo necesario cuando cambia algo que afecta a vídeos ya
procesados (como el cambio de `threshold_value` de esta misma sesión) — el
salto por `status='completed'` solo evita repetir trabajo cuando lo ya
hecho sigue siendo válido tal cual. `--fresh` borra toda la base, así que
tras usarlo todos los vídeos vuelven a `in_progress` y se reprocesan todos,
como es de esperar.
