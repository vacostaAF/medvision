# Cuaderno de ingeniería 1.6

## Motivación

El usuario corrió `smoke_test_paddleocr.py` (v1) contra `MVI_2714.MOV` real,
con PaddleOCR de verdad instalado (no simulado). El texto reconocido tenía
confianza altísima (0.93-1.00 en la mayoría de líneas) — la decisión de
sustituir Tesseract por PaddleOCR (1.4) queda confirmada con datos reales, no
solo con la API verificada sobre el papel.

Pero al pasar esa salida real por `parse_label_sheet()` (1.5), el resultado
fue **0 fármacos reconocidos de 7**, con el nombre del paciente sustituido
por "51" (una marca manuscrita en la esquina de la bolsita que PaddleOCR
también detecta como texto). Esto no se vio en 1.5 porque el parser se validó
contra texto transcrito a mano por mí a partir de una imagen estática — y al
transcribir, humanamente reconstruí "1 CALCIFEDIOL 0,266 MG CAPSULA" como una
sola línea porque así se lee visualmente. PaddleOCR no lo hace así.

## Causa raíz

PaddleOCR detecta cada fragmento de texto como una caja independiente. En una
bolsita SPD, la columna de cantidad ("1", "2") está separada espacialmente de
la columna del nombre del fármaco, aunque compartan fila visual. Salida real
observada (`MVI_2714.MOV`, frame 0):

```
CALCIFEDIOL 0,266 MG CAPSULA
BISOPROLOL 5 MG COMPRIMIDO
...
1
LISINOPRIL/HIDROCLOROTIAZIDA
 PLUSVENT 25 MICROGRAMOS/1:
2
1
 ONY-TEC 80 MG/G BARNIZ DE UI
```

La condición de transición cabecera→items en `parse_label_sheet()` exigía que
la propia línea empezara por un dígito de cantidad (`QUANTITY_RE.match(line)
and ITEM_DOSE_RE.search(line)`). Como ninguna línea de fármaco real empieza
así (la cantidad vive en su propia caja), esa transición nunca se disparaba:
todo se enrutaba a `_parse_header_line()`, que fue rellenando
`patient_name`/`patient_location` con basura ("51", el nombre real
desplazado) y descartando el resto en silencio.

Se reprodujo el bug exacto con las líneas reales reportadas antes de tocar
nada (`tests/test_parser.py::test_parse_label_sheet_*`, usando el texto real
como fixture) y se confirmó 0 items — no fue una suposición.

## Arreglo (dos capas, no una sola)

**1. Reconstrucción de fila en el origen (`ocr/label_ocr.py`)**

`_cluster_into_rows()` sustituye al reordenado plano por Y de 1.5. Agrupa
detecciones por proximidad vertical (misma fila visual, con tolerancia
relativa a la altura de caja) y, dentro de cada fila, ordena por X
(izquierda→derecha) antes de unirlas en una sola línea. Esto reconstruye "1
CALCIFEDIOL 0,266 MG CAPSULA" tal y como se ve en la foto, en vez de dejar la
cantidad suelta. Validado con geometría sintética que reproduce la real
(columna de cantidad a la izquierda, mismo rango Y que el fármaco).

El filtrado por `min_score` se movió a *antes* de agrupar filas (no después,
como en 1.5): un fragmento de baja confianza no debe arrastrar hacia abajo la
confianza de toda la línea reconstruida ni colarse en el texto final.

**2. La transición cabecera→items ya no depende de que la reconstrucción acierte**

Aunque (1) debería resolver el caso normal, no podía verificar la
reconstrucción contra las coordenadas reales de PaddleOCR (el smoke test v1
no las imprimía). Por defensividad, `parse_label_sheet()` ahora dispara la
transición solo con `ITEM_DOSE_RE.search(line)` — basta con reconocer una
unidad de dosis en la línea, sin exigir que la cantidad esté pegada delante.
Se probó explícitamente el caso pesimista (sin reconstrucción posible,
cantidad suelta): recupera 6 de 7 fármacos en vez de 0. Con (1) funcionando,
debería ser 7 de 7.

**3. Guardia contra marcas manuscritas**

`_parse_header_line()` ya no acepta como candidato a patient_name/location
una línea sin al menos 2 letras seguidas — descarta "51" sin gastar el hueco
que debía ocupar el nombre real.

## Lo que no se pudo verificar en este entorno

Sigo sin poder ejecutar PaddleOCR aquí (sin red), así que la reconstrucción
por fila (1) está validada con geometría *sintética* que reproduce lo que se
observó, no con las coordenadas (`rec_polys`) reales de esa ejecución — el
smoke test v1 no las imprimía. El smoke test v2 (`smoke_test_paddleocr.py`,
reescrito para usar `PaddleLabelOCR`/`parse_label_sheet` reales del proyecto
en vez de una reimplementación aparte) muestra ahora las líneas ya
reconstruidas y los fármacos parseados por frame — con eso se podrá confirmar
si (1) funciona al 100% contra sus vídeos reales o si hace falta ajustar la
tolerancia de agrupado por fila.

## Segunda ronda: bug de encadenamiento en el clustering (encontrado con una tercera ejecución real)

La primera versión de `_cluster_into_rows()` (arriba) usaba una **media móvil**
del centro Y de la fila para decidir si una nueva detección pertenecía a ella.
Contra datos reales (segunda ejecución del usuario, con el fix de arriba ya
aplicado), esto produjo fusiones incorrectas de líneas de fármacos distintos:

```
SIMVASTATINA 40 MG COMPRIMID CINITAPRIDA 1 MG COMPRIMIDO      (2 fármacos, 1 línea)
1 LISINOPRIL/HIDROCLOROTIAZIDA AMLODIPINO 5 MG COMPRIMIDO CINITAPRIDA 1 MG COMPRIMIDO   (3 fármacos, 1 línea)
```

Causa: con una media que se recalcula en cada detección añadida, una fila
puede "encadenarse" hacia detecciones cada vez más lejanas sin que ninguna
comparación individual sea, por sí sola, motivo de fusión — problema clásico
de clustering incremental de enlace simple.

**Arreglo**: la pertenencia a una fila se compara ahora contra el rango
`[y_top, y_bottom]` de la **primera caja que abrió esa fila** (una referencia
fija, no una media móvil), usando solapamiento vertical real
(`_overlap_ratio`, ≥50% del más pequeño de los dos rangos) en vez de
distancia de centros. Validado con geometría sintética que reproduce
espaciado ajustado entre líneas (25px de alto, 28px entre filas): ya no
fusiona líneas distintas, y sigue fusionando cantidad+fármaco cuando de
verdad comparten fila.

**Capa de recuperación adicional** (`ocr/parser.py::_parse_item_line`): por
si una fusión se cuela de todos modos (con datos reales nunca vamos a poder
garantizar cero fusiones), la función ya no se queda con la primera dosis
reconocida de la línea — busca **todas** las coincidencias de dosis y genera
un fármaco por cada una, usando el texto entre dos dosis consecutivas como
nombre. Sobre las dos líneas reales fusionadas de arriba: la primera se
recupera completa (2/2 fármacos correctos); la segunda recupera 2 de 3 (el
tercero, Lisinopril/Hidroclorotiazida, nunca tuvo su propia dosis reconocida
en el texto fusionado — no es un caso que el parser pueda resolver
adivinando, es exactamente para esto que existe la revisión humana).

De paso, se detectó que el filtro de "palabra de forma farmacéutica"
(`FORM_WORDS`) no toleraba truncados de OCR reales ("COMPRIMID" sin la "O"
final se colaba en el nombre del fármaco). Cambiado a comparación por
prefijo (`FORM_WORD_STEMS`).

## Limitación que queda, honestamente

Ninguna de estas dos capas garantiza cero fusiones incorrectas — solo las
hace menos frecuentes y, cuando ocurren, recupera lo recuperable en vez de
perderlo todo. La revisión humana (tabla editable en `review_app.py`) sigue
siendo la red de seguridad real del pipeline, no un paso opcional: cada
bolsita parseada automáticamente debe tratarse como un borrador, no como un
hecho, hasta que se corrija con la app la primera vez que se vea. Al construir
el emparejamiento automático (siguiente paso pendiente) convendría además
añadir una señal de "número de fármacos sospechosamente bajo" al criterio de
`needs_review`, ya que hoy una fusión con confianza OCR alta no dispara
revisión automáticamente.

En la ejecución real reportada, cada frame completo a 1920×1080 tardó
8-18s en OCR. El pipeline real corre OCR sobre el recorte de la bolsa, no
sobre el frame completo, así que debería ser bastante más rápido — pero no se
ha medido todavía contra un recorte real. A tener en cuenta al planificar
cuánto tardarán los 108 vídeos.
