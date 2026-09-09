# Cuaderno de ingeniería 3.27

## Motivación

El usuario preguntó, con razón, si `--fresh` (necesario para 3.26) borra
las decisiones de revisión humana ya guardadas. Comprobado en el código:
`--fresh` hace `shutil.rmtree()` de toda la carpeta de salida — sí, se
pierde todo, sin ninguna preservación selectiva, incluidas
`pair_reviews`/`pair_review_items`. Con trabajo de revisión real ya
invertido (al menos 10 `accepted` confirmados en el diagnóstico previo),
esto no era aceptable sin una forma de recuperarlo.

## Diseño

El obstáculo de fondo: `pair_reviews`/`pair_review_items` se referencian
por `track_pair_id`, un `AUTOINCREMENT` que no sobrevive a un `--fresh` —
tras reprocesar, los IDs son otros, aunque la bolsita real sea la misma.

Solución: anclar la exportación por **contenido**, no por ID — vídeo de
ETIQUETA (no el de pastilla: la etiqueta es la que de verdad identifica
qué bolsita real es; qué foto de pastilla se le asigna puede cambiar de
una ejecución a otra) + cabecera (día/fecha/franja). Esta combinación
identifica la misma bolsita real sea cual sea su `track_pair_id` en cada
ejecución.

## Arreglo

- `database/repository.py::export_reviews()`: vuelca todas las decisiones
  guardadas con su vídeo de etiqueta + cabecera + items corregidos, en
  formato portable (lista de diccionarios, sin ningún ID interno).
- `database/repository.py::import_reviews()`: para cada registro
  exportado, busca el par NUEVO con el mismo vídeo de etiqueta + cabecera
  y reaplica la decisión sobre su `track_pair_id` actual. Devuelve
  también qué registros no se pudieron reaplicar (no se pierden en
  silencio — puede pasar si el reproceso cambia cómo se lee esa cabecera
  en concreto).
- CLI: `medvision-ai export-reviews --output-dir ... --output-file
  reviews_backup.json` y `medvision-ai import-reviews --output-dir ...
  --input-file reviews_backup.json`.

## Hallazgo de paso

Al escribir `export_reviews()` se confirmó algo ya sospechado:
`save_pair_review()` sobrescribe `track_pairs.status` con la propia
decisión (`accepted`/`corrected`/...), perdiendo el estado original que
puso el pipeline (`paired`/`position_matched`/`review`). Es lo que
explicaba los "estado accepted" vistos en el diagnóstico de 3.26. No se
toca en esta ronda — es un problema aparte, anotado para más adelante.

## Percance durante el desarrollo, y cómo se detectó

Al insertar los métodos nuevos con una edición de texto, se cortó por
error el cuerpo de `save_pair_review_items()` a mitad de una llamada,
dejando código roto y una función duplicada. Se detectó de inmediato
porque la compilación falló y, tras corregirlo, se re-ejecutó la suite
completa (no solo los tests nuevos) — los 27 tests ya existentes de
`test_repository_label_items.py` sirvieron para confirmar que la
reparación no dejó nada más roto.

## Validado

- Test de integración con SQL real reproduciendo el escenario exacto:
  decisión guardada → fichero de base de datos borrado por completo →
  base reconstruida desde cero con una bolsita de la MISMA cabecera pero
  todos los IDs distintos → `import_reviews()` la encuentra y reaplica
  correctamente (decisión, notas, y fármacos corregidos).
- Caso de contenido que ya no coincide tras el reproceso: se reporta como
  no encontrado, no se pierde en silencio ni falla.
- **Extremo a extremo con los comandos de CLI reales** (no solo las
  funciones de Python): `export-reviews` → borrado real del fichero
  `.sqlite` (simulando `--fresh` de verdad) → reconstrucción con IDs
  nuevos → `import-reviews` → confirmado con una consulta SQL directa que
  la decisión y las notas sobrevivieron exactas.
- Suite completa: 97 tests, todos en verde.

## Para el usuario, en una frase

Antes de lanzar `--fresh`: `medvision-ai export-reviews --output-dir
output_vertical --output-file reviews_backup.json` (guardad ese fichero
en un sitio seguro, fuera de `output_vertical` — el `--fresh` también
borraría una copia que estuviera dentro). Después del `--fresh` +
`rebuild-pairs`: `medvision-ai import-reviews --output-dir output_vertical
--input-file reviews_backup.json`.
