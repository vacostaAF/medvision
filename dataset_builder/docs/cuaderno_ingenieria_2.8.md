# Cuaderno de ingeniería 2.8

## Primera ejecución real contra el lote completo

77 de 78 vídeos procesados sin caerse (el corrupto se saltó tal como se
diseñó en 2.7). Análisis agregado de `ocr.csv` (865 filas) y
`track_pairs.csv` (574 pares) vía pandas, no a ojo — a esta escala ya no es
práctico.

## Confirmado: hay varios pacientes en el lote, no solo uno

`patient_name` en `track_pairs.csv` muestra al menos 3 pacientes reales
distintos ("PELAYO PEINADO JOSEFA", "MORALES BARRIOS CONCEPCIÓN", "LUNA
AGUDO JUAN", con variantes de lectura de cada uno). Responde a la pregunta
pendiente sobre cómo repartir entrenamiento/validación más adelante: por
paciente completo, no por vídeo ni por sesión suelta — evita que el mismo
paciente aparezca en ambos lados del reparto.

## Dos bugs de parser nuevos, con evidencia de más de 100 vídeos reales

**"MO" como truncado de "MG"** (64 filas de 865 con este patrón —
`"OMEPRAZOL 30 MO CAFSULA"`, `"AMANTARINA 188 MO BAFRI"`). Consecuencia
doble: se perdía el fármaco Y, al no reconocerse como línea de medicación,
esa línea caía en el mecanismo de repliegue de `_parse_header_line()` y
contaminaba `patient_name` con texto de fármaco en vez de dejarlo vacío.
Añadido "MO" a `ITEM_DOSE_RE`/`UNIT_NORMALIZE`, mismo patrón que "MC"→"MCG"
del cuaderno 2.2 (solo se acepta con `\b` detrás, no puede colarse dentro de
"MG").

**Franjas horarias sin reconocer: "Ayunas" y "Merienda"**. Búsqueda
sistemática de qué palabra aparece justo después del patrón día+fecha en
las 865 filas reales: además de las franjas ya cubiertas, aparecían
`AYUNA(S)` (12 filas) y `MERIEN(DA)` — coherente clínicamente: la
Levotiroxina (vista en varias bolsitas) se prescribe habitualmente en
ayunas. Sin reconocerlas, `header_signature()` devolvía `None` para esas
bolsitas — nunca se fusionaban aunque hubiera varias vistas de la misma.
Añadidas a `SLOT_PREFIXES`/`SLOT_CANONICAL`.

## Lo que NO es un bug, es la limitación ya conocida a escala real

`paired_with_label: 24` de `574` (≈4%), `pairs_needing_review: 574` (100%).
Coherente con el emparejamiento ordinal pastilla↔etiqueta sin señal
compartida (cuaderno 2.5): con recuento de grupos muy descompensado entre
ambos lados, casi ningún `match_score` supera el umbral de 0.70 para
marcarse `paired`. No es una regresión de esta ejecución — es la misma
limitación estructural, vista ahora con datos reales de 108 vídeos en vez
de 2.

## Dato práctico sobre tiempos

Varios vídeos del lado etiqueta tardaron 15-20 minutos cada uno en OCR
(hasta 20:49 el más lento). La ejecución completa del lote probablemente
llevó varias horas. A tener en cuenta al planificar cuándo lanzar el
proceso completo (no es un "espera 10 minutos y ya está").

## Pendiente

- Repetir el lote completo (`--fresh`) con los arreglos de "MO" y
  "Ayunas/Merienda", y comprobar si sube la proporción de bolsitas con
  cabecera completa (148/574 antes del arreglo) y si baja el número de
  `patient_name` contaminados con texto de fármaco.
- Revisar `session_0005` (`MVI_2613`+`MVI_2614`, 176s de hueco) a mano.
- Decidir con el usuario si construir un mecanismo de reparto
  train/val/test por paciente ahora o dejarlo para la fase de
  entrenamiento (fuera del alcance del Dataset Builder en sí).
