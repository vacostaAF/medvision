# Cuaderno de ingeniería 3.42

## Motivación

El usuario confirmó, con 6 imágenes reales, que cada bolsita salía
duplicada (2 copias) pese a la deduplicación de 3.40. Y que el margen de
40px seguía siendo insuficiente — nombre pegado al borde superior, pie de
página cortado en el inferior.

## Diagnóstico de la deduplicación fallida

La firma usada en 3.40 comparaba el TEXTO CRUDO de la línea de
día/fecha/franja tal cual la devolvía el OCR. Entre fotogramas vecinos del
mismo paneo, esa línea varía lo suficiente (un espacio de más o de menos,
la franja truncada de forma distinta — "DESAYL" vs "DESAYU", visto en los
propios ficheros del usuario) como para que dos lecturas de la MISMA
bolsita real dieran cadenas de texto distintas, y la comparación exacta
las dejaba pasar como si fueran dos bolsitas diferentes.

Este problema exacto ya estaba resuelto en el pipeline principal:
`pairing/header_grouping.py::header_signature()` construye una firma a
partir de fecha+franja CANONICALIZADAS (no el texto crudo), con
comentarios en el propio código documentando este mismo caso real
("DESAYL" vs "DESAYU" vs "DESAYUNO") de una ronda muy anterior del
proyecto. No hacía falta inventar nada nuevo — solo reutilizar lo que ya
existía y estaba validado.

## Arreglo

- `ocr/parser.py::find_complete_pouch_boundaries()`: la firma ahora se
  construye extrayendo fecha (`DATE_RE`) y franja (`SLOT_PREFIXES` →
  `SLOT_CANONICAL`) de la línea de día de la semana, y llamando a
  `header_signature()` (reutilizada de `pairing/header_grouping.py`, sin
  duplicar lógica). Si por lo que sea no se puede extraer fecha+franja de
  esa línea concreta, cae al texto crudo como respaldo — peor que la
  firma canónica, pero mejor que no poder deduplicar en absoluto.
- `--margen` por defecto subido de 40 a 100 píxeles.

## Validado

- Reproducida la variación real de OCR de los ficheros del usuario
  ("DESAYL" con espacio vs "DESAYU" sin espacio) como test permanente —
  confirmado que ahora SÍ dan la misma firma canónica (`"26/02/26|DESAYUNO"`
  en ambos casos), a diferencia de antes.
- Nuevo test: dos bolsitas del mismo día pero franja distinta (desayuno
  vs cena) deben seguir dando firmas DISTINTAS — la robustez frente a
  ruido no debe hacer que se fusionen bolsitas genuinamente diferentes.
- **Extremo a extremo con el script completo**: 3 fotogramas con la
  variación de OCR real (no texto idéntico, que es justo lo que fallaba
  antes) → **1 solo fichero generado**, confirmando que la deduplicación
  ya funciona con el mismo tipo de ruido que se ve en la práctica, no
  solo con texto idéntico como en la prueba anterior.
- Suite completa: 126 tests, todos en verde.
