# Cuaderno de ingeniería 3.32

## Motivación

Con bolsitas de 20+ fotos (vistas reales en el dataset), la columna de
pastilla o etiqueta podía crecer mucho más que el resto — empujando la
columna de estado/decisión y el formulario de revisión fuera de la vista,
justo lo que el diseño de 4 columnas (3.31) quería evitar.

## Arreglo

Cada columna de fotos (`_render_pill_column()`, `_render_label_column()`)
envuelve ahora la lista de imágenes en `st.container(height=700)` — una
función nativa de Streamlit (no un truco de JavaScript como el del
scroll-al-guardar de 3.23) que crea una caja de altura fija con scroll
propio. La cabecera de la columna (subtítulo, avisos de costura) queda
fuera del contenedor, así que siempre se ve qué es cada columna aunque
haya que desplazarse dentro para ver todas las fotos.

## Validado

Compilación y suite completa (103 tests) sin regresiones — cambio de
estructura visual, no toca lógica del pipeline ni de la base de datos.

## Nota honesta

`st.container(height=...)` necesita una versión de Streamlit
relativamente reciente. No he podido probarlo en un navegador real (sigo
sin poder instalar Streamlit en este entorno) — si al abrirlo da un error
de argumento desconocido, es señal de que la versión instalada es más
antigua de lo que este código espera; avisad y lo resuelvo.
