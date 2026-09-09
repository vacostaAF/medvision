# Cuaderno de ingeniería 3.34

## Motivación

Con la revisión humana terminada, el chat del módulo de segmentación de
pastilla pidió el dataset final con un formato concreto: todas las fotos
`pill_side` por par, `seam_position`, estado+revisión, `label_items`.

## Arreglo previo necesario: status ya no se pierde al revisar

Antes de exportar, se encontró que aplicaba el "hallazgo de paso" que
quedó pendiente en 3.27: `save_pair_review()` sobrescribía
`track_pairs.status` con la propia decisión (`accepted`/`corrected`/...),
perdiendo el estado real del pipeline (`paired`/`position_matched`/...).
Con la revisión ya completa, esto habría hecho que el export perdiera
justo la información de procedencia que el otro chat pidió. Arreglado:
`save_pair_review()` ya no toca `status`, solo `needs_review` — la
decisión vive exclusivamente en `pair_reviews.decision`, por separado.

## Arreglo: el exportador

- `database/repository.py::export_training_dataset()`: un registro por
  bolsita real, con:
  - `pair_key`, `order_index`, `pipeline_status`, `match_score` (procedencia)
  - `review`: decisión humana, notas, fecha (o `null` si nunca se revisó)
  - `patient_context`: paciente/día/fecha/franja
  - `label_items`: la lista de fármacos corregida por un humano si existe
    (`label_source="human_corrected"`), si no la del OCR
    (`label_source="ocr_raw"`)
  - `pill_photos`: TODAS las fotos de pastilla del grupo (no solo la
    representante), cada una con su `seam_position` y `seam_positions`
    completas
  - Excluye por defecto (parámetros para incluirlas si hace falta):
    bolsitas marcadas `rejected` por un humano, y bolsitas sin ningún
    fármaco en su lista final — mismo criterio que "Ocultar lecturas sin
    ningún fármaco" de la app (3.17).
- CLI: `medvision-ai export-dataset --output-dir ... --output-file
  dataset_final.json` — además de escribir el JSON, imprime un resumen
  completo en pantalla (bolsitas totales, con/sin foto de pastilla, fotos
  totales, desglose por estado/origen/decisión) — las cifras que hacían
  falta para el otro chat, sin tener que contarlas a mano.

## Validado

- Test de regresión con SQL real: guardar una revisión no cambia
  `track_pairs.status`, solo `needs_review` — la decisión queda aparte en
  `pair_reviews.decision`.
- Test de integración con SQL real, 5 casos representativos a la vez:
  `paired` con 2 fotos (una con costura) corregido por humano,
  `position_matched` sin revisar (usa OCR), `unmatched_label` sin fotos de
  pastilla (se incluye igual, con lista vacía de fotos), `rejected`
  (excluido), y vacío sin fármacos (excluido) — confirmado que solo
  quedan los 3 casos correctos, con cada campo exacto (cantidad corregida
  0.5, costura 0.4 presente, `None` en la foto sin costura).
- **Extremo a extremo con el comando de CLI real**: mismo escenario de 5
  casos, ejecutado vía `medvision-ai export-dataset` de verdad — el
  resumen impreso en pantalla coincide exactamente con lo esperado
  (3 bolsitas, 2 con foto de pastilla, 3 fotos en total, desglose por
  estado/origen/decisión correcto), y el JSON exportado se inspeccionó
  campo a campo.
- Suite completa: 106 tests, todos en verde.
