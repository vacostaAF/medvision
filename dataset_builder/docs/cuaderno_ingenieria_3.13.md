# Cuaderno de ingeniería 3.13

## Motivación

Con el emparejamiento aún por debajo del nivel que el usuario esperaba
(reproceso vertical en marcha, sin confirmar todavía), se propuso una idea
más ambiciosa: reconstruir la tira física completa a partir de cada vídeo
(mosaico) y usar el mapa de bolsitas del lado etiqueta para localizar las
mismas bolsitas en el lado pastilla.

## Investigación previa (sin cambios de código, solo validación)

Antes de construir nada, se hicieron pruebas de viabilidad con vídeos
reales ya disponibles:

1. **Reconstrucción de mosaico por correlación de fase**: viable, con
   ruido — el texto sale legible en la mayoría de la tira reconstruida,
   con algo de fantasma/costuras visibles en tramos de menor confianza. La
   confianza mejora mucho con muestreo denso (cada 2 frames) frente a
   disperso (cada 10) — el paso más espaciado no daba una señal fiable con
   el desenfoque de paneo real.
2. **Escalar por distancia total, no por tiempo**: la duración del paneo
   difiere entre pastilla y etiqueta (grabaciones independientes, distinta
   velocidad de mano), pero la DISTANCIA total recorrida (suma sin filtrar
   de desplazamientos verticales entre frames) resultó mucho más
   consistente entre las dos grabaciones de una misma sesión — proporción
   0.95 y 0.987 en dos sesiones de prueba distintas.
3. **Prueba de fuego con datos reales**: usando esa proporción para
   predecir dónde debería caer una bolsita del lado etiqueta en el lado
   pastilla, sin usar el texto reflejado para nada — **5 de 6 aciertos**
   en 2 sesiones (el sexto caso, en la bolsita justo vecina, con la
   correcta ya visible en el borde del frame).

Con esta evidencia, se decidió construirlo en serio.

## Diseño

Se integra como un **tercer nivel de emparejamiento** dentro de
`_build_pairs()`, entre la coincidencia directa por cabecera (2.9, la más
fiable — verificada por contenido) y el mecanismo ordinal de respaldo
(2.0, el menos fiable — sin ninguna señal real). No sustituye a ninguno de
los dos: cubre el hueco entre ambos.

- `acquisition/motion.py::compute_cumulative_pan_distances()`: distancia
  vertical acumulada entre frames consecutivos YA MUESTREADOS (no hace
  falta releer el vídeo original), por correlación de fase — sin filtrar
  por confianza (ver la investigación: filtrar introducía más sesgo del
  que quitaba).
- `database/schema.py`: `frames.cumulative_pan_px` (nullable). Calculado
  al final del procesado de cada vídeo, sobre los frames ya guardados en
  disco — coste bajo comparado con el OCR (una llamada a `phaseCorrelate`
  por par de frames, milisegundos).
- `database/repository.py`: `get_pan_range_for_video()` (rango min/max de
  un vídeo), `get_pan_distance_for_bag()`, `find_closest_bag_by_pan_distance()`
  (la consulta central: qué bolsa de un vídeo cae más cerca de una
  distancia objetivo, dentro de un margen).
- `dataset/builder.py::_build_pairs()`: para cada bolsita de etiqueta sin
  coincidencia directa, calcula su posición relativa dentro del rango de
  paneo de SU vídeo (0-1), la traduce a la posición equivalente en el
  rango del vídeo de pastilla, y busca la bolsa de pastilla más cercana a
  esa posición dentro de un margen del 8% del rango total (validado con
  los casos reales de la investigación, que cayeron dentro de ese margen).
- **Status propio, `position_matched`**, distinto de `paired` — no es una
  coincidencia verificada por contenido, así que `needs_review` es siempre
  1 y no se confunde en las cifras con las coincidencias directas.
- `app/review_app.py`: el filtro de estado del pipeline incluye el nuevo
  valor.

## Validado

- Test de integración con SQL real: una bolsita de etiqueta sin cabecera
  equivalente en pastilla (nunca podría emparejarse por contenido) se
  empareja correctamente por posición, con la bolsa de pastilla más
  cercana a la fracción de recorrido esperada, no con las otras dos bolsas
  de control situadas más lejos.
- Prueba de extremo a extremo con vídeo real (sin OCR disponible en este
  entorno, pero confirmando que el cálculo de distancia se integra sin
  romper el resto del pipeline): `cumulative_pan_px` se calcula y guarda
  correctamente para cada frame tras el procesado normal.

## Limitación honesta

La validación de la fórmula de escalado (proporción de distancia total) se
hizo con 2 sesiones y 6 puntos de prueba — sólida para justificar
construirlo, pero no es una validación exhaustiva a la escala de 108
vídeos. El margen del 8% se fijó con esos mismos 6 puntos; puede necesitar
ajuste al verlo funcionar sobre el lote completo real.

## Pendiente

Necesita `--fresh` para que `cumulative_pan_px` se calcule sobre los
vídeos ya procesados (es una columna nueva sin datos retroactivos, y el
cálculo requiere los frames ya guardados en disco del muestreo normal).
Confirmar con el resultado real cuánto sube `paired_with_label` +
`position_matched` combinados frente al 32.8% actual, y revisar en la app
una muestra de los `position_matched` para confirmar que el margen del 8%
es prudente a escala real, no solo en los 6 puntos de prueba.
