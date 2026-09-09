# Cuaderno de ingeniería 3.43

## Motivación

Con 8 imágenes reales, el usuario confirmó dos cosas: la deduplicación de
3.42 ya funciona razonablemente bien (alguna repetida suelta, no todas
como antes — no le preocupa), y el margen seguía sin ser suficiente en la
parte inferior del recorte (pie de página y código QR cortados en varias
fotos), mientras que arriba solo hacía falta un poco más.

## Arreglo

- `bags/pouch_cropping.py::crop_complete_pouches()`: nuevo parámetro
  `margin_bottom_px` opcional — si no se especifica, usa el mismo valor
  que `margin_px` (compatible con el uso anterior). Si se especifica,
  aplica un margen distinto abajo que arriba.
- `generar_bolsas_individuales.py`: `--margen` (arriba, 60px por defecto)
  y `--margen-abajo` (220px por defecto) como parámetros separados —
  bastante más generoso abajo, donde el pie de página y el QR quedan más
  pegados al límite detectado que la cabecera arriba.

## Validado

- Margen asimétrico probado con datos sintéticos y con la imagen real ya
  usada en rondas anteriores: 60px arriba + 220px abajo = 280px de
  diferencia total, medido con precisión sobre un recorte que no toca
  ningún borde de la imagen (para que el propio límite de la imagen no
  enmascare la medición).
- Compatibilidad: sin especificar `margin_bottom_px`, sigue usando el
  mismo margen arriba y abajo que antes (no rompe el uso previo).
- Suite completa: 128 tests, todos en verde.
