# Cuaderno de ingeniería 1.8

## Primer resultado de punta a punta

Con `max_segments=1` (1.7) y `video_sides` restaurado, el pipeline produjo su
primer resultado limpio: 2 de 4 pares con fármacos correctos, confianza
>96%, sin necesitar revisión. Confirma que la cadena completa (detección de
bolsa → tracking → OCR real → parser multi-fármaco → emparejamiento →
persistencia) funciona de extremo a extremo contra vídeos reales.

## Arreglo puntual: unidad truncada "MC" → "MCG"

`ocr.csv` mostró RISPERIDONA perdida: el texto real era `"1 MC"`, no `"1
MCG"` — el propio OCR trunca la unidad. `ITEM_DOSE_RE` no la reconocía.
Añadido "MC" como alternativa, con `\b` obligatorio detrás (comprobado que no
coincide dentro de "MCG": la transición C→G es letra-letra, sin límite de
palabra ahí, así que "MC" nunca hace *match* parcial contra "MCG").

## Lo que confirma el patrón real (no una sorpresa, ya lo anticipaba el 1.7)

Cada bolsita se sigue capturando solo parcialmente — 3-4 de los 7 fármacos
reales por lectura. No es un fallo de segmentación (eso ya se arregló): es
que la bolsita entera es más alta que lo que cabe en un único frame con el
zoom de esta cámara. `max_segments=1` evita el corte artificial, pero no
puede inventar contenido que el frame no capturó.

## Pendiente de decidir, no de arreglar a ciegas

Dos caminos posibles para completar el resto de fármacos por bolsita:

1. **Muestreo más denso** (`sampling.seconds_between_frames` más pequeño):
   barato, sin cambios de arquitectura, pero no soluciona el fondo — si la
   bolsita nunca cabe entera en un frame, más frames no cambian eso, solo dan
   más oportunidades de capturar fragmentos distintos.
2. **Fusionar observaciones de un mismo track** (cambio de arquitectura
   real): el tracker ya sigue la misma bolsita física a lo largo de varios
   frames (`multi_observation_tracks` en el summary); hoy se queda con el
   "mejor" frame y descarta el resto. Fusionar el texto de varias
   observaciones de un mismo track (con deduplicación por nombre de fármaco)
   sí resolvería el fondo, pero es trabajo real de diseño, no un parámetro.

No se ha construido ninguno de los dos en este incremento: antes de invertir
en (2), que es la solución de fondo, tiene sentido decidir con el usuario si
merece la pena frente a seguir con el emparejamiento automático para los 106
vídeos restantes, que sigue siendo el otro bloqueante pendiente y no
depende de esto.
