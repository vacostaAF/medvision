# Cuaderno de ingeniería 2.6

## Motivación

Con `video_sides`/`video_pairs` a mano en `config/default.yaml`, cada zip
nuevo del proyecto pisaba silenciosamente lo que el usuario había añadido
para sus vídeos reales — pasó dos veces en esta misma validación (cuaderno
1.7 y una repetición posterior con `cli.py`). Con 108 vídeos, además, editar
esto a mano deja de ser viable sea cual sea el mecanismo de entrega.

El usuario confirmó el protocolo real de grabación: siempre se graba primero
la tira de pastillas, inmediatamente después la misma tira por el lado de
la etiqueta, en ese orden, sin excepción.

## Diseño

`acquisition/session_planner.py`:

- `read_capture_time(video_path)`: lee el metadato `creation_time` del
  vídeo vía `ffprobe`. Si no está disponible, usa la fecha de modificación
  del fichero como respaldo (menos fiable — se pierde si el fichero se
  copia o mueve). Validado contra los 2 vídeos reales de la validación:
  ambos tienen `creation_time` correcto vía metadato, con 32s de diferencia
  entre pastilla y etiqueta.
- `plan_sessions(video_paths, max_gap_seconds)`: ordena por instante real de
  captura (no por nombre de fichero — distintas cámaras usan convenciones
  distintas, `IMG_XXXX` vs `MVI_XXXX`) y empareja consecutivos en sesiones
  (pastilla, etiqueta). Marca para revisión: huecos anómalos (> `max_gap_seconds`,
  por defecto 120s) o negativos (etiqueta grabada antes que la pastilla), y
  un número impar de vídeos (el último se queda sin pareja).
- `sessions_to_config_dict()`: convierte el plan a la misma estructura
  `video_sides`/`video_pairs` que ya consumía `dataset/builder.py` — cero
  cambios en la lógica de emparejamiento en sí, solo en de dónde sale la
  configuración.

## CLI nuevo

```bash
medvision-ai plan-sessions --videos-dir videos --output config/sessions.yaml
medvision-ai build-dataset --videos-dir videos --output-dir output \
    --config config/default.yaml --sessions config/sessions.yaml
```

`build-dataset --sessions` combina `config/default.yaml` (ajustes generales:
muestreo, umbrales...) con el `video_sides`/`video_pairs` de
`config/sessions.yaml`, dando prioridad a este último. La combinación se
escribe en `output/_merged_config.yaml` para poder inspeccionar exactamente
qué configuración se usó en cada ejecución (trazabilidad, no solo
conveniencia).

`config/default.yaml` deja de tener `video_sides`/`video_pairs` — pasan a
vivir exclusivamente en `config/sessions.yaml`, que el usuario genera y
controla, y que yo no vuelvo a tocar entre entregas. Resuelve la causa raíz
del problema de las dos rondas anteriores, no solo el síntoma.

De paso: el import de `build_dataset` en `cli.py` se hizo perezoso (solo se
carga dentro de `build-dataset`, no al importar el módulo). `plan-sessions`
no necesita `cv2`/`paddleocr`/`tqdm` — solo `ffprobe` y `yaml` — así que no
debería fallar por dependencias pesadas no instaladas si se ejecuta antes
de tener todo el entorno completo listo.

## Validado

- Contra los 2 vídeos reales (`MVI_2713`/`MVI_2714`): identifica
  correctamente cuál es pastilla y cuál etiqueta por tiempo real, incluso
  pasados en orden contrario en la lista de entrada.
- Tests con ficheros sintéticos (fecha de modificación controlada, sin
  depender de vídeos reales ni de que `ffprobe` esté instalado en CI):
  varias sesiones consecutivas, hueco anómalo marcado para revisión, número
  impar de vídeos marcado para revisión.
- CLI probado de punta a punta (`plan-sessions` genera el YAML, formato
  correcto) contra los vídeos reales.

## Pendiente

Probar `plan-sessions` contra un subconjunto mayor de los 108 vídeos reales
en cuanto estén todos grabados, para confirmar que el hueco típico entre
pastilla y etiqueta (los 32s medidos aquí) es representativo, y ajustar
`max_gap_seconds` si hace falta.
