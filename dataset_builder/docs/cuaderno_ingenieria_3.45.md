# Cuaderno de ingeniería 3.45

## Motivación

Tras el arreglo de 3.44 (extender `end_y` hasta la última línea real del
pie de página), el margen fijo de 400px que compensaba el problema
anterior se volvió redundante — y ahora se colaba en la bolsita
siguiente cuando el hueco real entre dos bolsitas es menor que ese
margen (caso real confirmado por el usuario con una imagen). Además, el
margen superior había bajado de 100 a 60 al separar los dos valores en
3.43, sin que se pretendiera reducirlo.

## Arreglo

- `--margen` (arriba) vuelto a 100 por defecto.
- `--margen-abajo` bajado de 400 a 60 por defecto — ahora que el punto de
  referencia (`end_y`) ya llega hasta el final real del pie de página
  (3.44), solo hace falta un margen pequeño de más, no uno grande que
  compense un punto de referencia corto.
- `bags/pouch_cropping.py::crop_complete_pouches()`: **límite de
  seguridad nuevo**, independiente del valor de margen que se use — el
  recorte de una bolsita nunca sobrepasa el INICIO de la siguiente
  bolsita en la lista, sea cual sea `margin_bottom_px`. Esto no depende
  de acertar con el número exacto de píxeles: aunque alguien vuelva a
  poner un margen grande por error, no puede colarse en la vecina.

## Validado

- Reproducido el caso real (dos bolsitas con un hueco pequeño entre
  ellas, margen deliberadamente exagerado de 400px) — confirmado que el
  límite de seguridad recorta correctamente sin invadir la siguiente.
- Caso de la ÚLTIMA bolsita de una lista (sin ninguna siguiente con la
  que limitarse): su margen se aplica con normalidad, sin recortarse de
  más por el nuevo límite.
- Suite completa: 132 tests, todos en verde.
