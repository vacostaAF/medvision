# Cuaderno de ingeniería 3.36

## Motivación

Para probar el prototipo con vídeos de validación nunca vistos por el
sistema, el usuario necesitaba imágenes de una sola bolsita por fichero.
Propuso usar el contenido de la propia etiqueta como referencia — nombre
de paciente al principio, código Bidi al final — en vez de la señal
visual de costura, que ya sabíamos poco fiable a esta precisión (93% de
inconsistencia, cuaderno 3.26).

## Investigación previa: ¿el código Bidi es detectable?

Antes de construir nada, se comprobó con imágenes reales si el código
visible en las etiquetas es legible por OCR o es un código de barras
2D que necesitaría un detector aparte. Inspección visual: el patrón de 3
cuadrados en las esquinas es característico de un **código QR**, no de un
DataMatrix/Bidi real (patrón en L). Probado con `cv2.QRCodeDetector`:

- Sobre las 7 imágenes reales disponibles, sin recortar: **0 detecciones**.
- Con búsqueda por ventanas a varias escalas: detecciones en las 7, pero
  con muchos falsos positivos — de 14 detecciones en una imagen, solo 1
  coincidía con la posición real conocida del QR (comprobado contra un
  recorte manual de referencia).

Mismo patrón que la detección de costura: prometedor en aislado, poco
fiable a escala real. Se descartó esta vía y, con el usuario, se optó por
usar el **texto** del pie de página de farmacia ("FARMACIA MARACENA..."),
ya legible de forma consistente por el OCR existente en todo el proyecto,
en vez de un detector visual nuevo sin validar a fondo.

## Aclaración importante

El lado pastilla ya se voltea horizontalmente (`cv2.flip`) antes de pasar
por OCR, desde el principio del proyecto (para leer el texto reflejado
por transparencia). Esto significa que el texto en ese lado sale YA del
derecho tras el OCR — no hace falta buscar el texto invertido, la misma
búsqueda de patrón de texto sirve para los dos lados sin cambios.

## Arreglo

- `ocr/parser.py::find_footer_positions()`: localiza las posiciones Y
  (normalizadas) de cada línea que contiene el pie de farmacia, con las
  variantes reales de OCR encontradas en este proyecto ("FARMAOIA",
  "FARMAGIA" por confusiones de caracteres).
- `ocr/parser.py::group_footer_positions()`: agrupa varias líneas del
  mismo pie (web, teléfono, código) en una sola posición por bolsita.
- `bags/pouch_cropping.py` (módulo nuevo): `crop_pouches_by_y_boundaries()`
  recorta una imagen en N+1 sub-imágenes según N puntos de corte — a
  diferencia de todo el reparto de TEXTO ya existente (que solo reparte
  líneas, nunca la imagen), esto genera una fotografía real por bolsita.
  El proyecto había descartado explícitamente partir imágenes por costura
  visual (cuadernos 1.7/2.4); el corte por contenido, al ser mucho más
  preciso, sí lo justifica.
- `generar_bolsas_individuales.py` (script independiente, en la raíz del
  proyecto, no integrado en el pipeline principal): dado un vídeo, genera
  una imagen por bolsita usando estas dos piezas. Reutiliza `VideoReader`
  y la misma convención de rotación (`sampling.rotate_degrees`) ya
  existentes en el pipeline principal, para consistencia.

## Validado

- `find_footer_positions()`/`group_footer_positions()`: probado con un
  patrón de texto+posiciones que reproduce exactamente lo visto en
  diagnósticos reales de este proyecto (cabecera, fármacos, 3 líneas de
  pie, siguiente bolsita) — agrupa correctamente 3 líneas de pie en 1
  posición por bolsita, y reconoce las variantes reales de OCR.
- `crop_pouches_by_y_boundaries()`: probado con datos sintéticos (franjas
  de brillo distinto) y, sobre todo, **con una fotografía real de dos
  bolsitas** — los dos recortes resultantes se inspeccionaron visualmente:
  cada uno contiene exactamente una bolsita completa (cabecera, lista de
  fármacos y pastillas), sin mezclarse con la vecina.
- **El script completo, de extremo a extremo, contra un vídeo real**
  (`MVI_2733.MOV`): lectura de vídeo, rotación y recorte reales:
  confirmado que el fotograma se lee, rota y recorta correctamente
  (inspeccionado visualmente: texto legible del derecho, contenido real
  de una bolsita). El propio OCR se simuló (no hay PaddleOCR instalado en
  este entorno), así que los puntos de corte de esta prueba concreta no
  vienen de un pie de página real — queda pendiente de confirmar con
  PaddleOCR de verdad en el entorno del usuario.
- Suite completa del proyecto: 116 tests, todos en verde.

## Pendiente

Confirmar con PaddleOCR real (entorno del usuario) que el pie de farmacia
se localiza con la posición Y correcta en la práctica — aquí solo se ha
podido validar la lógica de agrupación de posiciones y el recorte de
imagen, no la detección del texto en sí sobre un frame real sin simular.
