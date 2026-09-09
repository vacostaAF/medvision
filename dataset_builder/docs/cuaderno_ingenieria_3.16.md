# Cuaderno de ingeniería 3.16

## Motivación

`session_0000` dio 0 emparejamientos por posición pese a tener 6 bolsitas
reales sin pareja. Dos diagnósticos previos (uno con un bug propio del
script, descartado al reproducirse igual tras corregirlo) llevaron a mirar
con lupa qué pasaba exactamente cuando el candidato "más cercano" ya estaba
ocupado por otro emparejamiento.

## Diagnóstico

`find_closest_bag_by_pan_distance()` devuelve la bolsa de pastilla más
cercana a una posición objetivo, sin más. La comprobación de "¿ya está
usada?" se hacía DESPUÉS, en el llamador — y si la más cercana resultaba
estar ya usada (por una coincidencia directa, o por otro emparejamiento de
posición anterior en la misma sesión), el código **se rendía del todo**
para ese grupo, sin intentar la segunda más cercana.

Con solo ~30 fotos de pastilla repartidas a lo largo de toda una sesión,
varias bolsitas reales distintas predicen con frecuencia una posición muy
próxima entre sí — y por tanto compiten por la MISMA foto más cercana. Solo
la primera en pedirla se la queda; el resto se pierde, aunque hubiera una
segunda foto perfectamente válida un poco más lejos, dentro del margen.

Confirmado con datos reales de `session_0000`: los 5 candidatos "más
cercanos" encontrados para los 6 grupos restantes coincidían exactamente
con bolsas ya consumidas por las 5 coincidencias directas de esa misma
sesión — ninguno tenía margen para caer a una segunda opción.

## Arreglo

`find_closest_bag_by_pan_distance()` acepta ahora `exclude_bag_ids` y las
descarta directamente en la búsqueda — así encuentra la más cercana **entre
las disponibles**, no la más cercana a secas. El llamador (`_build_pairs()`)
pasa `matched_pill_bag_ids` como exclusión desde el principio, en vez de
comprobar después y rendirse.

## Validado

Test de integración con SQL real: 2 bolsas de pastilla dentro del margen de
una posición objetivo (una más cerca, otra un poco más lejos). Sin
exclusiones, encuentra la más cercana. Excluyendo la más cercana (como si
ya estuviera usada), encuentra la segunda — antes del arreglo esto
devolvía `None` y se perdía el emparejamiento. Excluyendo las dos, sí
devuelve `None` de verdad (no hay más candidatas).

## Pendiente

Confirmar con `rebuild-pairs` sobre el dataset real cuánto sube
`position_matched` en sesiones como `session_0000`, que antes se quedaban
en 0 pese a tener bolsitas reales disponibles.
