# Cuaderno de ingeniería 2.2

## Motivación

Con el muestreo denso (2.1, 0.4s), `track_pairs` subió a 15 — pero por el
contenido real (fármacos reconocidos) solo hay 3-4 bolsitas físicas
distintas en el vídeo. El agrupado por cabecera (1.9) dejó de fusionar casi
nada: cada frame acababa como su propio grupo aislado.

## Tres bugs encadenados, mismo síntoma

Con más muestreo aparece más variación real de cómo el OCR lee la misma
bolsita en distintos frames (motion blur, ángulo, enfoque). Tres problemas
en cómo se extraía la cabecera terminaban produciendo cabeceras "distintas"
para bolsitas físicamente idénticas:

1. **Fecha y franja pegadas sin espacio.** Con muestreo denso aparece a
   menudo `"28/02/26ALMUEI"`, `"28/02/26DESAYL"` (antes, con muestreo
   disperso, esto no se había visto). `DATE_RE` exigía un límite de palabra
   justo después del año (`\b...\b`), pero dígito→letra no es un límite de
   palabra en regex — la fecha no se reconocía en absoluto, `dose_date`
   quedaba `None`, cabecera incompleta, sin agrupar.
2. **Franja horaria buscada como token suelto.** `_parse_header_line`
   buscaba la franja como una palabra separada por espacios
   (`token.startswith(prefix)`); pegada a la fecha, nunca la encontraba.
3. **Truncado variable de la franja.** Aún reconociéndola, se guardaba el
   token OCR crudo ("DESAYL", "DESAYU", "DESAYUNO" según el frame) en vez de
   una categoría fija — misma bolsita real, cabeceras "distintas" según cómo
   la truncara el OCR ese frame.
4. **Tilde inconsistente.** "sábado" en un frame, "sabado" en otro (misma
   bolsita real) — comparación de cadenas exacta las trataba como firmas
   distintas.

## Arreglo

- `DATE_RE`: se quita el `\b` final (el inicial se mantiene, sigue evitando
  capturar solo el final de una cadena numérica más larga).
- `_parse_header_line`: la franja se busca como subcadena de toda la línea
  (`prefix in upper_line`), no como token separado por espacios.
- La franja se normaliza a una categoría fija (`SLOT_CANONICAL`: DESAYUNO,
  COMIDA, ALMUERZO, CENA, MEDIODIA, NOCHE) en vez de guardar el texto OCR
  crudo — se arregla en el origen, no con comparación difusa después.
- `header_signature()`: día de la semana y franja se normalizan sin tildes
  (`unicodedata`, forma NFD) antes de comparar.

Validado con el texto real exacto de `bag_id=17`/`18` (fecha+franja
pegadas, antes producían firma `None` cada una — ahora firma idéntica y se
fusionan) y con `sabado`/`sábado` (antes firmas distintas, ahora iguales).

## Nota

Estos bugs no estaban "escondidos" — simplemente no se manifestaban con las
3 observaciones dispersas de las rondas anteriores, que resultaron ser
frames limpios. Es la razón de fondo por la que aumentar la densidad de
muestreo (2.1) fue la decisión correcta antes de dar por buena la cabecera:
sin más volumen de datos reales, estos tres bugs no habrían aparecido antes
de lanzar el lote completo de 108 vídeos.

## Pendiente

Repetir la ejecución en limpio con estos arreglos y confirmar con
`track_pairs.csv` que las bolsitas repetidas (domingo desayuno, sábado
almuerzo, sábado desayuno, sábado cena) se fusionan en ~4 grupos reales en
vez de 15 fragmentados.
