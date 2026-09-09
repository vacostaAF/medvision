# Cuaderno de ingeniería 2.3

## Motivación

Tras el arreglo 2.2 (franja horaria y fecha pegadas), `track_pairs` bajó de
15 a 12 — mejora real, pero no lo esperado (~4-6 grupos). Con
`track_pairs.csv` de la ejecución en limpio: `bag_id=9` y `bag_id=10` (misma
bolsita real, domingo desayuno) seguían en grupos separados, igual que
`bag_id=13/14/15` (sábado cena).

## Causa: mismo patrón de bug que 2.2, esta vez en el día de la semana

`_parse_header_line` detectaba el día de la semana solo si era la
**primera palabra de la línea** (`first_word in WEEKDAYS`). Con datos reales:

- `bag_id=10`: `"PELAYO PEINADO JOSEFA domingo 01/03/26..."` — nombre y día
  en la misma línea, sin salto. Primera palabra: "PELAYO", no "domingo".
- `bag_id=13`: `"sábado28/02/26CENA"` — día, fecha y franja los tres pegados
  sin ningún espacio.

En ambos casos, `dose_weekday` quedaba `None` → cabecera incompleta →
`header_signature()` devuelve `None` → cada observación se trataba como su
propia bolsita en vez de fusionarse con las demás lecturas de la misma
bolsita real.

De paso, se encontró que `DATE_RE` (arreglada en 2.2 solo por el lado final)
también fallaba por el lado inicial en este mismo caso: `"sábado28/02/26"`
tampoco tiene límite de palabra entre la "o" de "sábado" y el "2" de la
fecha (letra→dígito, ambos `\w`). Se quita el `\b` inicial también — las
barras `/` ya hacen el patrón lo bastante distintivo como para no
necesitarlo.

## Arreglo

Mismo patrón que en 2.2, aplicado ahora al día de la semana:
`_find_weekday()` busca cualquiera de los nombres de día como **subcadena**
de toda la línea, no como primera palabra — y devuelve directamente la forma
canónica sin tilde ("SABADO", no "sábado"/"sabado"), evitando además la
comparación difusa por acentos que hacía `header_signature()` (esa
normalización se mantiene igualmente, como red de seguridad adicional).

## Patrón general para el resto del proyecto

Van ya tres campos de cabecera (franja, fecha, día) que tenían la misma
clase de bug: asumir que un campo llega en su propia línea o en su propia
posición de palabra, cuando con más densidad de muestreo aparece pegado a
otro texto con más frecuencia de la que se pensaba. Si aparece un cuarto
campo con el mismo síntoma, aplicar directamente el mismo patrón (búsqueda
por subcadena + canonicalización en el origen) en vez de tratarlo como un
caso nuevo.

## Validado

Con el texto real exacto de `bag_id=9/10` (nombre+día en la misma línea) y
`bag_id=13/14/15` (día+fecha+franja los tres pegados): las firmas coinciden
y las tres observaciones de "sábado cena" fusionarían en un solo grupo.

## Pendiente

Repetir la ejecución en limpio y confirmar con `track_pairs.csv` cuántos
grupos reales quedan ahora — la expectativa es ~4-6 (las 4 bolsitas reales
identificadas hasta ahora: domingo desayuno, sábado almuerzo, sábado
desayuno, sábado cena, más algún singleton de frames con cabecera
genuinamente incompleta).
