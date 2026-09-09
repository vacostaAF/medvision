# Cuaderno de ingeniería 3.3

## Motivación

Con el lote de prueba vertical (4 pares, 53 pares de track_pairs), el
usuario preguntó si había forma de mejorar el 35.8% de `paired_with_label`.
Revisando los datos reales del propio lote se encontró evidencia de
desenfoque residual afectando nombres de fármaco ("AMANTADINA" vs "AMANT
INA", misma bolsita, dos lecturas distintas). El día de la semana es una
palabra completa igual de vulnerable a ese mismo tipo de error, y forma
parte de la firma de identidad usada para el emparejamiento directo (2.9).

## Decisión

El día de la semana es matemáticamente redundante con la fecha — un
`12/03/26` siempre es jueves, sin excepción. Exigir que coincidan LOS DOS de
forma independiente no añade seguridad real: si la fecha ya coincide, el
día está determinado; lo único que puede pasar es que un error de OCR en el
día bloquee una coincidencia que fecha+franja ya identificaban sin
ambigüedad.

`header_signature()` pasa de `(día, fecha, franja)` a `(fecha, franja)`. No
se ha comprobado con un caso confirmado del lote real (no hay evidencia
directa de un fallo de emparejamiento causado específicamente por el día,
solo la sospecha razonada de que puede estar pasando dado que sí se ve el
mismo tipo de error en otros campos de texto) — es una mejora de bajo
riesgo justificada por diseño, no una corrección de un bug confirmado.

## Por qué es seguro, no solo cómodo

Dentro de un mismo vídeo de un mismo paciente, no puede haber dos bolsitas
reales con la misma fecha y la misma franja horaria — sería contradictorio
(una toma, un momento). `patient_name` ya estaba excluido de la firma por
el mismo motivo (constante en toda la tira, sin poder de discriminación).
El día de la semana se une a esa misma categoría: no añade seguridad,
solo redundancia con riesgo de fallo.

## Validado

Tests actualizados en `test_header_grouping.py`: la firma ahora se forma
con 2 campos, no 3; un día de la semana con error de OCR
(`"jueves"`/`"juebes"`) o directamente ausente ya no bloquea la
coincidencia si fecha+franja son iguales.

## Pendiente

Repetir el lote de prueba vertical (o completarlo con los 2 vídeos que
faltan) y comparar `paired_with_label` antes/después de este cambio, para
confirmar con datos si de verdad estaba bloqueando coincidencias reales o
si el efecto es marginal.
