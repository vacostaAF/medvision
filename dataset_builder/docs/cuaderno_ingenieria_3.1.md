# Cuaderno de ingeniería 3.1

## Motivación

El cambio de 3.0 (`pair_group_members`) solo afecta al bloque de
emparejamiento — no a detección ni OCR. Pero hasta ahora, la única forma de
regenerar esa tabla era `build-dataset --fresh`, que repite **todo**,
incluida la parte cara (horas con 100+ vídeos, ver cuaderno 2.8). Con la
velocidad a la que este proyecto sigue encontrando ajustes reales al
emparejamiento (1.9, 2.5, 2.9, 3.0...), forzar una repetición completa cada
vez no es sostenible.

## Arreglo

`dataset/builder.py::build_dataset()` se divide en dos funciones:

- `_build_pairs(repo, cfg, output_dir)`: el bloque de agrupado +
  emparejamiento + persistencia, extraído tal cual (mismo comportamiento,
  sin cambios de lógica) — opera solo sobre datos ya presentes en `repo`.
- `build_dataset()`: sin cambios de comportamiento, ahora simplemente llama
  a `_build_pairs()` después de procesar los vídeos, en vez de tener el
  bloque inline.

Nueva función `rebuild_pairs(output_dir, config_path)`: abre el
`medvision.sqlite` ya existente y llama a `_build_pairs()` directamente,
sin tocar vídeos, frames, bolsas ni OCR. Reconstruye un `summary.json`
completo (contando filas ya en la base) y regenera `track_pairs.csv`.

Nuevo comando de CLI:

```bash
medvision-ai rebuild-pairs --output-dir output --config config/default.yaml --sessions config/sessions.yaml
```

Mismo mecanismo de combinación `--config`+`--sessions` que `build-dataset`
(refactorizado a un helper compartido, `_resolve_config()`, en vez de
duplicar la lógica).

## Validado

Ejecución real de punta a punta: `build_dataset()` sobre un vídeo de
prueba, seguido de `rebuild_pairs()` sobre el mismo `output_dir` — mismos
recuentos de frames/bolsas/OCR (leídos de la base, no recalculados),
confirmando que no repite trabajo ya hecho.

## Nota

El recuento de "videos" en el summary de `rebuild_pairs()` puede diferir
ligeramente del de `build_dataset()`: éste cuenta filas ya guardadas en
`videos` (la tabla), aquél cuenta ficheros encontrados en `videos_dir`
(incluidos los que fallaron al procesar, como un vídeo corrupto). No afecta
al emparejamiento en sí, solo a ese número informativo concreto.
