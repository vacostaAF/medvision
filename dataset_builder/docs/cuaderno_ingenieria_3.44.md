# Cuaderno de ingeniería 3.44

## Motivación

Segunda vez que el usuario pedía más margen inferior (40→100→220px, y
seguía sin ser suficiente). Antes de subir el número una tercera vez a
ciegas, se investigó la causa de fondo.

## Diagnóstico

`find_complete_pouch_boundaries()` anclaba el fin de cada bolsita en la
primera línea que contiene la palabra "FARMACIA". Pero el pie de página
real tiene varias líneas MÁS debajo de esa (dirección web, teléfono,
código de registro) que no llevan esa palabra clave, y por tanto nunca
formaban parte de `footer_positions` — quedaban completamente fuera del
cálculo. El margen en píxeles tenía que cubrir todo ese bloque de texto
restante MÁS el código QR, y por eso nunca era suficiente por mucho que
se subiera: no era un problema de "cuántos píxeles", era que el punto de
referencia en sí se quedaba corto.

## Arreglo

`find_complete_pouch_boundaries()` ahora extiende `end_y` desde esa
primera línea "FARMACIA..." hasta la ÚLTIMA línea de texto cercana (hueco
máximo de 0.08 en Y normalizada entre una línea y la siguiente), sea cual
sea su contenido — ya no hace falta que lleve ninguna palabra clave. Con
cuidado de no colarse en el nombre de la bolsita SIGUIENTE si está cerca:
la extensión se detiene en `next_weekday_y - name_margin` (el mismo
margen que ya se usa para el propio inicio de esa bolsita siguiente).

Con esto, el margen en píxeles (`--margen-abajo`) solo tiene que cubrir el
hueco real final (el QR y el borde físico de la bolsa), no todo un bloque
de texto que antes se estaba ignorando por completo.

## Percance durante el desarrollo

Al escribir el bucle de extensión se desempaquetó la tupla en el orden
equivocado (`for y, _line in all_lines` en vez de `for _line, y in
all_lines`, dado que `lines_with_y` es `(texto, y)` no `(y, texto)`),
dando un `TypeError` inmediato al probarlo — detectado y corregido antes
de dar nada por bueno. Un segundo caso límite (la extensión colándose en
el nombre de la bolsita siguiente cuando está cerca) se encontró también
durante las propias pruebas, no lo reportó el usuario, y se corrigió en
el mismo pase.

## Validado

- Caso real (pie de página con 3 líneas adicionales sin "FARMACIA"): el
  fin se extiende correctamente hasta la última.
- Caso límite: con una bolsita siguiente cerca, la extensión NO se cuela
  en su nombre — se detiene en el margen ya usado para el propio inicio.
- Test existente actualizado: el caso que antes esperaba pararse en
  "FARMACIA" (0.92) ahora extiende correctamente hasta la última línea
  real del pie (0.94) — no es una regresión, es el comportamiento nuevo
  correcto.
- Suite completa: 130 tests, todos en verde.
