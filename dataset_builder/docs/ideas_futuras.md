# Ideas pendientes para módulos futuros

No son tareas del Dataset Builder — se anotan aquí para no perderlas al
cerrar esta fase, y retomarlas cuando toque el módulo correspondiente.

## Usar la posición de costura para el módulo de segmentación de pastilla

**Contexto (agosto 2026):** en 3.11-3.12 se implementó la detección de
costura dentro de una foto (`bags/seam_band.py::detect_seam_band()`) para
saber, en el LADO ETIQUETA, qué línea de texto pertenece a qué bolsita
cuando dos caben en el mismo frame. Se guarda en `bags.seam_position`
(posición Y normalizada 0-1) y `ocr_results.seam_side` (de qué lado salió
cada bolsita).

**Idea pendiente:** el mismo problema físico existe en el LADO PASTILLA —
si una foto captura pastillas de dos bolsitas distintas a la vez, un
modelo de segmentación (SAM2/YOLO11-seg) entrenado con esa foto sin más
contexto no tiene forma de saber qué pastilla pertenece a qué bolsita. La
posición de costura ya calculada podría reutilizarse para:

- Recortar o marcar la región de la foto correspondiente a cada bolsita
  ANTES de pasarla al modelo de segmentación (en vez de darle la foto
  completa con pastillas de dos bolsitas mezcladas).
- O, como mínimo, usarla como metadato adicional en el dataset de
  segmentación (a qué bolsita pertenece cada región), para poder filtrar o
  ponderar durante el entrenamiento.

**No resuelto todavía:** `detect_seam_band()` está pensado y validado para
el lado etiqueta (usa el brillo+tinte azulado del reflejo, que también se
ve en el lado pastilla — ver cuaderno 2.4 — pero no se ha probado
específicamente para este uso). Habría que confirmar con fotos reales del
lado pastilla con dos bolsitas antes de asumir que funciona igual de bien
ahí.

**Cuándo retomar:** al empezar el diseño del módulo de segmentación de
pastilla, no antes.

## Llevar la procedencia del emparejamiento al dataset de entrenamiento

**Contexto (agosto 2026):** desde 3.13, un par puede llegar a
`track_pairs` por 3 caminos con fiabilidad muy distinta: `paired`
(coincidencia directa por cabecera, verificada por contenido — la más
fiable), `position_matched` (misma posición relativa de paneo en los dos
vídeos — no verificado por contenido, siempre pide revisión), y `review`
(mecanismo ordinal de respaldo — la menos fiable). A esto se suma la
decisión humana en la app de revisión (`pending`/`accepted`/`corrected`/
`rejected`).

**Idea pendiente:** cuando se exporte el dataset final para el
entrenamiento del módulo de segmentación de pastilla, no descartar esta
procedencia — llevarla como metadato de cada muestra (bag_id, imagen,
etiqueta, Y de dónde salió el emparejamiento + si un humano lo confirmó).
Motivos:

- Permite entrenar primero con lo más fiable (`paired` + `accepted`
  humano) y añadir el resto después, en vez de tratar todo el dataset como
  igual de fiable desde el principio.
- Si aparece un error raro en el modelo entrenado, poder rastrear si viene
  de una muestra con emparejamiento dudoso (`position_matched`/`review`)
  ayuda a diagnosticar sin tener que revisar todo el dataset de nuevo.
- `position_matched` en concreto es un mecanismo nuevo (3.13), validado con
  pocos casos reales todavía — tratarlo con más cautela que `paired` en el
  entrenamiento es prudente mientras no se acumule más evidencia de que es
  igual de fiable a escala.

**Cuándo retomar:** al diseñar el formato de exportación del dataset para
entrenamiento (fuera del alcance del Dataset Builder en sí).

