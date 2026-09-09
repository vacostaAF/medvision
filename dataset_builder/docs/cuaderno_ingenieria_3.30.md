# Cuaderno de ingeniería 3.30

## Motivación

El usuario preguntó, con razón, contra qué podía comparar el texto en
"vista rápida" — la respuesta reveló un fallo de diseño real de 3.25: se
desactivaba la carga de **ambos** lados (pastilla y etiqueta), no solo el
de pastilla. Para los pares `unmatched_label` (asociación 0.00) es cierto
que no existe foto de pastilla — pero la foto de la ETIQUETA sí existe
siempre (es de ahí de donde salió la lista de fármacos por OCR), y es
exactamente la referencia que hace falta para comprobar que el texto se
leyó bien. Sin ella, "vista rápida" dejaba al usuario sin nada contra qué
comparar — el problema que motivó la casilla en 3.17 (revisar más rápido)
sin querer se convirtió en "revisar a ciegas".

## Arreglo

- `quick_mode` ahora solo salta la consulta del lado **pastilla**
  (`pill_images = []` directo, sin consultar — sabemos que sale vacío
  para estos casos). El lado **etiqueta** se consulta y muestra siempre,
  esté activada la casilla o no.
- Rediseño visual: en modo rápido, la foto de etiqueta ocupa el ancho
  completo (antes se repartía a la mitad con una columna de pastilla que
  siempre iba a salir vacía). Se extrajo el renderizado de la columna de
  etiqueta a una función compartida (`_render_label_column()`) para no
  duplicar el código entre el modo normal (dos columnas) y el rápido
  (ancho completo).
- Texto de la casilla y su ayuda corregidos para reflejar el
  comportamiento real: "sin foto de pastilla", no "sin fotos".

## Aclaración de uso, no solo de código

Para revisar seguidos todos los pares sin foto de pastilla: "Estado del
pipeline" → `unmatched_label` en la barra lateral (ya existía desde 3.9),
combinado con los botones ◀/▶ (3.23) — la vista rápida es un complemento
de rendimiento a esto (evita la consulta inútil del lado pastilla), no
un sustituto de poder comparar contra la foto real.

## Validado

Compilación y suite completa (103 tests) sin regresiones — el cambio es
solo de la app, no toca lógica del pipeline ni de la base de datos.
