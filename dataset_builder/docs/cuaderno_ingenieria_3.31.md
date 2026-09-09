# Cuaderno de ingeniería 3.31

## Motivación

El usuario pidió reorganizar la pantalla de revisión en 4 columnas, de
izquierda a derecha: pastilla, etiqueta, estado+decisión, formulario de
revisión — para poder ver todo junto (foto, contexto y edición) sin
desplazarse por la página, dado el volumen de bolsitas por revisar.

## Arreglo

- Cada bloque de contenido se extrajo a su propia función
  (`_render_pill_column()`, `_render_label_column()`,
  `_render_status_column()`, `_render_review_form()`) — antes estaban
  mezclados inline con `st.columns(2)` para las fotos y el resto a ancho
  completo debajo. Separarlos en funciones permite colocarlos en
  cualquier disposición sin duplicar código.
- Disposición por defecto: `st.columns([3, 3, 2, 4])` — pastilla y
  etiqueta con espacio similar (para ver bien las fotos), estado/decisión
  más estrecha (son solo 2 métricas + una nota), formulario con más
  espacio (tiene que caber la tabla editable de fármacos).
- **Streamlit no puede saber el ancho real del navegador** desde el
  servidor — no hay forma de que "si hay suficiente ancho" se resuelva
  solo. En su lugar, nueva casilla "Pantalla estrecha" en la barra
  lateral: apila las 4 secciones verticalmente en vez de repartirlas en
  columnas, para cuando el monitor o la ventana sean estrechos.
- `_render_pill_column()` ahora comprueba `quick_mode` directamente y
  muestra un aviso corto ("Sin foto de pastilla para este par") en vez de
  dejar la columna vacía sin explicación.

## Validado

Compilación, análisis AST (confirma que las 7 funciones se definen sin
errores de sintaxis) y suite completa (103 tests) sin regresiones — el
cambio es de estructura visual, no toca lógica del pipeline ni de la base
de datos. Confirmado que no quedan referencias sueltas a las variables de
columnas antiguas (`left`/`right`/`s1`/`s2`) tras la reestructuración.
