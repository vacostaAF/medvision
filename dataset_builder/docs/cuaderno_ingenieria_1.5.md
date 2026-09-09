# Cuaderno de ingeniería 1.5

## Motivación

Al revisar los 2 primeros vídeos grabados con cámara (MVI_2713 / MVI_2714,
108 en total) se confirma que el objeto real es una **tira SPD (sistema
personalizado de dosificación)**: bolsitas termoselladas en acordeón, cada
una correspondiente a un momento de toma concreto (día + franja horaria) y
que lista **varios fármacos por bolsita** (hasta 7 en la muestra vista), no
uno. El código 1.0-1.4 asumía un fármaco por bolsa en tres sitios a la vez:
`ocr/parser.py::parse_label()` (se quedaba con el primero y descartaba el
resto), y las columnas singulares `drug_name`/`dose_value`/`dose_unit` en
`ocr_results` y `track_pairs`.

## Bug encontrado de paso (no relacionado con lo anterior)

Al diseñar el parser de bolsita completa se detectó que
`PaddleLabelOCR.read()` unía las líneas detectadas con `' '.join(words)` en
vez de `'\n'.join(words)`, perdiendo la separación por línea que
`normalize_label_text()` necesita para reconstruir los separadores `|`. No
afectaba a la demo 1.4 (validaba con un texto de una sola línea) pero habría
producido un blob sin estructura en cualquier bolsita real. Corregido.

También se detectó que PaddleOCR no garantiza devolver `rec_texts` en orden
de lectura. Para una bolsita, donde el orden top-to-bottom es la única señal
que distingue "cabecera" de "primer fármaco", esto es crítico. Se añadió
reordenado explícito por la coordenada Y del centro de cada caja detectada
(`rec_polys`), con test de regresión.

## Modelo de datos nuevo

- `label_headers` (1:1 con `ocr_results`): paciente, ubicación, día, fecha,
  franja horaria de la toma.
- `label_items` (1:N con `ocr_results`): un fármaco por fila —
  cantidad, nombre, dosis, unidad, línea cruda original.
- `pair_review_items` (1:N con `track_pairs`): la corrección humana de la
  lista de fármacos de una bolsita, en la misma línea de diseño que ya
  existía para `pair_reviews` frente a `ocr_results` — **nunca se sobrescribe
  el OCR crudo**, la corrección vive en una tabla aparte.
- `ocr_results.drug_name/dose_value/dose_unit` y las mismas tres columnas en
  `track_pairs`: **deprecadas**, se mantienen nullable por compatibilidad
  pero no se escriben en registros nuevos. La fuente de verdad es
  `label_items`.

## Parser (`ocr/parser.py::parse_label_sheet`)

`parse_label()` (una sola lectura, un fármaco) se deja intacta —la usan
tests existentes y sigue siendo válida como utilidad suelta. Se añade
`parse_label_sheet(lines: list[str])`, que opera sobre la lista de líneas
(no un blob aplanado) y:

1. Reconoce la cabecera (nombre de día, patrón de fecha `DD/MM/AA`, prefijos
   de franja horaria `DESAY-/COMI-/CEN-/...`) y, por descarte, las dos
   primeras líneas no reconocidas como paciente/ubicación.
2. A partir de ahí, cada línea se intenta parsear como fármaco: cantidad al
   inicio + nombre + dosis + unidad. **Solo se acepta como fármaco si hay una
   unidad reconocible** (MG/MCG/MICROGRAMOS/...) — esto es lo que evita que
   el pie de la farmacia (nombre, teléfono, URL) se cuele como fármaco falso;
   se probó explícitamente con el texto real transcrito del vídeo.
3. Dosis compuestas de fármacos combinados (p. ej. "Lisinopril/Hidroclorotiazida
   20/12,5 MG") no se adivinan: `dose_value` queda en `None` con `dose_unit`
   reconocido, para que quede marcado y lo resuelva un humano en la revisión.

Validado contra las líneas reales transcritas del vídeo (7 fármacos, cabecera
completa, pie de farmacia correctamente ignorado) — ver `tests/test_parser.py`.

## Revisión humana (`app/review_app.py`)

La UI pasa de 3 campos de texto (un fármaco) a una tabla editable
(`st.data_editor`) con una fila por fármaco, precargada con lo ya revisado
si existe o si no con el OCR crudo. Se muestra también la cabecera
(paciente/fecha/toma) como contexto, porque para el caso de uso real
("esto lo utilizaremos para el tratamiento") esa información es tan
relevante como la lista de fármacos y antes se descartaba por completo.

## `bag_detection.threshold_value` recalibrado con datos reales

Medido contra frames reales de MVI_2713/2714: el valor anterior (205,
calibrado para el iPhone de la demo) no detectaba la bolsita en **ningún**
frame de la cámara nueva (más oscura, con reflejo de foco LED azulado). A
partir de threshold≈80-100 la detección funciona con confianza plena. Se
deja en 100 como valor conservador; **pendiente validar contra una muestra
mayor de los 108 vídeos** antes de darlo por definitivo — 2 vídeos no son
representativos de todas las condiciones de grabación que pueda haber.

## Explícitamente fuera de alcance de este incremento

- **Emparejamiento por nombre de fichero.** Con 108 vídeos `MVI_XXXX` reales
  (no `IMG_XXXX` de la demo), `video_sides`/`video_pairs` hardcoded en YAML
  ya no es viable a mano. Es la generalización por sesión de captura que se
  dejó pendiente en el cuaderno 1.4; toca ahora.
- **Nitidez/nivel de calidad recalibrado.** Se midió `sharpness_laplacian`
  consistentemente bajo (4-20 frente a la referencia de 800 en
  `quality_score`) en ambos vídeos nuevos; no se ha tocado la fórmula porque
  es una calibración relativa (afecta a qué frame se elige como "mejor", no
  bloquea nada), pero convendría revisarla con más muestra.
