# Cuaderno de ingeniería 3.8

## Motivación

Primer análisis a fondo del dataset completo (104 vídeos, 442 pares).
Mirando los `item_count` más altos entre los pares, aparecieron casos como:

```
BI ERIDENO; BIPERIDENO; JUEVES BIERIDENO; EIPERIDENO; EI ERIDENO;
EIERIDENO; JUEVES EIERIDENO; EL ERIDENO; JUEVES EI ERIDENO
```

9 "fármacos" en una lista fusionada — en realidad, **1 fármaco real
(Biperideno) leído con distinto ruido en 9 observaciones distintas de la
misma bolsita**. Investigando esto se encontró un segundo bug, distinto,
que agravaba el primero.

## Bug 1: `merge_label_items()` deduplicaba por texto exacto

Diseñado así desde 1.9, funcionaba bien mientras el ruido de OCR entre
observaciones de la misma bolsita era bajo. Con vídeo vertical y muestreo
denso, una misma bolsita real puede acumular muchas observaciones (aquí, 9),
y cuantas más observaciones, más probabilidad de que el mismo fármaco se
lea con variantes que nunca coinciden carácter a carácter.

**Arreglo**: `merge_label_items()` ahora agrupa por **similitud** de texto
(`difflib.SequenceMatcher`, ignorando espacios), no por igualdad exacta,
con un umbral conservador (0.72) — se comprobó explícitamente que
`OMEPRAZOL` y `PARACETAMOL` (fármacos genuinamente distintos) NO se
fusionan, priorizando ese riesgo por encima de dejar algún duplicado
residual sin limpiar del todo.

**Limitación honesta, no oculta**: el representante elegido de cada grupo
fusionado (el de mayor similitud media con el resto — el "centro" del
grupo de lecturas ruidosas) no tiene por qué ser la grafía correcta. Con el
caso real de Biperideno, el resultado bajó de 9 entradas a 2, pero la que
"ganó" fue `EIERIDENO`, no `BIPERIDENO` — sin un diccionario de fármacos no
hay forma de saber cuál de las lecturas es la real. Sigue siendo mucho mejor
que 9 fármacos falsos, y la corrección final de la grafía exacta queda para
la revisión humana con la foto delante, no para el pipeline.

## Bug 2: la reconsulta por `bag_id` ignoraba `sheet_index`

Al construir la fila final de cada par (`_build_pairs()` en
`dataset/builder.py`), el código volvía a consultar `ocr_results` con
`WHERE bag_id=?` para sacar cabecera y fármacos — pero desde 3.2,
`ocr_results` ya no es única por `bag_id` (puede haber varias bolsitas por
foto, `UNIQUE(bag_id, sheet_index)`). Con `rows[0]`, esa consulta cogía
**la primera lectura que hubiera, sin importar cuál fuera la representante
real del grupo** — visto en datos reales: dos grupos de `session_0000` con
`label_track_key` distintos (`header:0003` y `header:0004`, genuinamente
bolsitas distintas) mostraban la MISMA fecha/franja/fármacos en el CSV,
porque ambos re-consultaban por el mismo `bag_id` y siempre caían en el
mismo `sheet_index`.

**Arreglo**: `pill_by_key`/`label_by_key` ahora guardan también el
`ocr_result_id` ya resuelto por el propio agrupado (`LabelGroup`/`PillGroup`
ya lo calculaban, solo faltaba propagarlo). La reconsulta usa
`WHERE id=?` con ese id exacto en vez de adivinar por `bag_id`. Se
mantiene una consulta de respaldo por `bag_id` (con `ORDER BY sheet_index
LIMIT 1`, al menos determinista) solo para el caso, no esperado en la
práctica, de que el id no estuviera disponible.

## Validado

- `merge_label_items`: caso real de 9 variantes de Biperideno → 2; caso de
  control con fármacos distintos (`OMEPRAZOL`/`PARACETAMOL`) → no se
  fusionan; caso de conservación de dosis cuando el representante elegido
  no la tenía pero otro miembro del grupo sí.
- Bug de `sheet_index`: test de integración con SQL real a través de
  `_build_pairs()` completo (no solo la función aislada) — una foto con 2
  bolsitas (sheet_index 0 y 1, cabeceras y fármacos distintos) que acaban
  siendo representantes de 2 pares distintos, cada uno mostrando su propia
  fecha/franja/fármacos — antes del arreglo, los dos habrían mostrado los
  datos del sheet_index 0.

## Pendiente

Repetir el emparejamiento (`rebuild-pairs`, no hace falta repetir
detección/OCR) sobre el dataset completo y comparar los `item_count`
extremos de antes/después — debería bajar el número de pares con más de
5-6 fármacos "distintos", que es la señal más visible de este problema.
