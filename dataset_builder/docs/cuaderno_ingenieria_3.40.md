# Cuaderno de ingeniería 3.40

## Motivación

El usuario, tras corregir el olvido de `--flip`, confirmó que la
detección ya funcionaba, pero señaló dos problemas: la misma bolsita real
se repetía en decenas de fotogramas consecutivos (paneo lento respecto al
paso de muestreo), y el proceso parecía más lento que en la versión 3.36.

## Bug real encontrado al revisar el propio código (no reportado por el usuario)

Al ponerme a corregir la deduplicación, se encontró que el bloque que
recorta y guarda las imágenes había quedado mal indentado en 3.38/3.39 —
colgando de la rama `elif args.debug:` en vez de ejecutarse siempre que
hubiera bolsitas detectadas. Esto significa que, en la ejecución real del
usuario, **probablemente no se guardó ningún fichero en disco**, pese a
que el registro mostraba "N bolsita(s) completa(s) detectada(s)"
correctamente — la detección funcionaba, el guardado no se ejecutaba
nunca. Error de no volver a probar el conjunto completo tras añadir el
modo `--debug` en la ronda anterior.

## Arreglo: deduplicación por firma

- `ocr/parser.py::find_complete_pouch_boundaries()`: ahora devuelve
  3-tuplas `(inicio, fin, firma)` en vez de solo `(inicio, fin)`. La
  firma es la línea de día+fecha+franja normalizada (mayúsculas, espacios
  colapsados) — identifica a la bolsita real independientemente de en qué
  fotograma o posición de pantalla se haya visto.
- `bags/pouch_cropping.py::crop_complete_pouches()`: acepta tanto
  2-tuplas como 3-tuplas (el tercer elemento, si está, se ignora para el
  recorte — es solo para deduplicar).
- `generar_bolsas_individuales.py`: mantiene un conjunto de firmas ya
  guardadas; antes de recortar y guardar, filtra las bolsitas cuya firma
  ya se haya visto en un fotograma anterior. Avisa en pantalla cuántas se
  omiten por repetidas.
- `--paso` por defecto subido de 15 a 60: con deduplicación, un paso
  grande ya no arriesga perderse bolsitas (solo hace falta que CADA
  bolsita real aparezca completa en AL MENOS un fotograma de la muestra,
  no en todos) — solo ahorra llamadas al OCR, que es donde se va todo el
  tiempo real.

## Sobre la velocidad reportada

No se ha podido confirmar una causa concreta de que 3.36 fuera más rápida
— el propio motor de OCR (`read_label()`) no se ha tocado entre esa
versión y esta. La variación de tiempo observada por el usuario en su
propia ejecución (18.9s a 41.6s, con tendencia al alza) es coherente con
lo ya visto en la ejecución completa del pipeline principal semanas
atrás, y podría deberse a factores fuera del control de este script
(carga del sistema, comportamiento interno de PaddleOCR con llamadas
repetidas). La mitigación real que sí se puede garantizar es reducir
cuántas veces se llama al OCR — de ahí el `--paso` más alto por defecto,
ahora seguro gracias a la deduplicación.

## Validado

- Los 4 tests existentes de `find_complete_pouch_boundaries()`
  actualizados al nuevo formato de 3 elementos, todos siguen pasando.
- Nuevo test: la MISMA bolsita real, leída en dos fotogramas con
  variación de posición Y realista (el paneo avanza) pero la misma línea
  de día/fecha/franja, da la MISMA firma — confirma que la deduplicación
  funcionaría con datos reales de este tipo.
- **Reproducido el caso real exacto del usuario end-to-end, con el
  script completo**: 3 fotogramas simulados con la firma de bolsita
  idéntica ("jueves 26/02/26CE") en posiciones Y distintas (paneo
  avanzando) → **exactamente 1 fichero generado**, no 3 — confirma a la
  vez que el bug de indentación quedó arreglado (antes no se habría
  generado NINGÚN fichero) y que la deduplicación funciona.
- Suite completa: 125 tests, todos en verde.

## Nota honesta

La imagen generada en la prueba de deduplicación no es representativa de
su CONTENIDO visual (mismo motivo que en 3.37: texto simulado fijo sobre
un fotograma real con contenido distinto en esas coordenadas) — lo que
valida esa prueba es el NÚMERO de ficheros generados (1, no 3), no lo que
se ve en la imagen.
