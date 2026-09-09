# Cuaderno de ingeniería 3.47

## Motivación

El usuario probó con un vídeo de validación nuevo (`MVI_2853.MOV`) y solo
obtuvo 1 bolsita de las varias que contiene. El registro con `--debug`
mostró texto mucho más degradado que en pruebas anteriores: "FARMACIA"
aparecía como "FARMALIAMARALSIN", "FARMSACARA", "FA 101" o simplemente
"FA" en distintos fotogramas — ninguna de las 3 variantes conocidas
(`FARMACIA`/`FARMAOIA`/`FARMAGIA`) las reconocía, así que esas bolsitas
se descartaban por falta de pie de página detectado.

## Arreglo aplicado

`FOOTER_KEYWORDS` gana una cuarta variante: `"FARMA"` — el prefijo se
mantiene legible en más casos que la palabra completa. Confirmado con los
patrones reales exactos del registro del usuario: reconoce
"FARMALIAMARALSIN" y "FARMA" (antes no), sigue sin poder con "FARMSACARA"
(la S extra rompe hasta el prefijo) ni "FA 101"/"FA" a secas (demasiado
corto para ser un prefijo fiable sin arriesgar falsos positivos).

## Diagnóstico honesto: el arreglo no basta para este vídeo en concreto

Se probó el arreglo contra los fotogramas 120 y 300 completos del propio
registro del usuario, y en ninguno de los dos se llegó a formar una
bolsita completa:

- Fotograma 120: el pie de página relevante era literalmente "FA 101" —
  demasiado degradado incluso para "FARMA".
- Fotograma 300: la propia línea de día de la semana estaba degradada
  ("martos." en vez de "martes", sin la e) — sin cabecera reconocible, no
  hay inicio de bolsita, independientemente del pie de página.

Se extrajo el fotograma 120 real del vídeo para inspección visual, y se
confirmó a simple vista: este vídeo tiene notablemente más desenfoque de
movimiento que el usado en pruebas anteriores (probablemente un paneo más
rápido durante la grabación). No es un fallo del código — es una
diferencia real de calidad entre grabaciones, y ninguna variante de
palabra clave adicional la va a compensar del todo si tanto la cabecera
como el pie llegan igual de degradados.

## Recomendación práctica

Para vídeos con este nivel de desenfoque, reducir `--paso` (muestrear más
fotogramas) aumenta las posibilidades de que alguno salga con calidad
suficiente para leerse. De cara a futuras grabaciones de validación,
mantener un paneo más lento y constante ayudaría a evitar este problema
de raíz, en vez de compensarlo después.

## Validado

- Los 3 patrones reales exactos del registro del usuario, probados en
  aislado: "FARMALIAMARALSIN" y "FARMA" ahora se reconocen,
  "FARMSACARA" sigue sin reconocerse (correctamente, no se puede forzar
  sin arriesgar falsos positivos con un prefijo aún más corto).
- Suite completa: 132 tests, todos en verde (sin regresiones).

## Pendiente

No se ha podido confirmar con PaddleOCR real si `--paso` más pequeño
recupera las bolsitas perdidas de este vídeo en concreto — la
recomendación se basa en el razonamiento (más muestras = más
oportunidades), no en una prueba directa, dado que no hay PaddleOCR
disponible en este entorno.
