# Cuaderno de ingeniería 3.22

## Motivación

El usuario, revisando en la app, no tenía forma de ver de un vistazo ni el
estado que puso el pipeline (`paired`/`position_matched`/...) ni la
decisión humana que se guardó la última vez para ese par — el estado no se
mostraba en ningún sitio del detalle, y el botón de decisión siempre
arrancaba en "Aceptar" por defecto, sin reflejar lo ya guardado.

## Hallazgo de paso

Al añadir la etiqueta de estado, se encontró que `status='paired'` **no
siempre** viene de la coincidencia directa por cabecera (2.9, verificada
por contenido) — el mecanismo ordinal de respaldo
(`pairing/track_pairer.py`) también marca `status='paired'` cuando su
propia puntuación heurística supera 0.70, **sin ninguna verificación de
contenido real**. Ambos casos comparten el mismo nombre de estado pero
tienen una fiabilidad muy distinta — se distinguen por `match_score`
(exactamente 1.0 en la coincidencia directa; entre 0.70 y 1.0, sin llegar
a 1.0 casi nunca por casualidad, en el mecanismo de respaldo).

## Arreglo

- Nueva sección destacada en la vista de detalle, justo debajo de la
  barra de progreso: dos métricas, "Estado del pipeline" y "Decisión
  actual", con etiquetas en español y un color/icono por tipo.
- `_status_label()`: para `paired`, distingue por `match_score` — si es
  ≥0.999, "Coincidencia directa (verificada por contenido)"; si no,
  "Emparejado por el mecanismo de respaldo, puntuación X.XX (sin
  verificar por contenido)" — no se pinta como fiable algo que no lo es
  solo por compartir nombre de estado.
- El radio de "Decisión" ahora arranca en la decisión ya guardada
  (`item.get('decision')`), no siempre en "Aceptar" — usando el índice de
  la opción correspondiente en la lista, con reserva a "pendiente" si el
  valor es `None` o inesperado.

## Validado

Dos pruebas aisladas (sin depender de Streamlit, reproduciendo la lógica
exacta): `_status_label()` en los 4 casos (directa, respaldo con
puntuación, posición, sin pareja); resolución del índice del radio en 5
casos incluido un valor de decisión desconocido (no revienta, cae a
"pendiente"). Suite completa (90 tests) sin regresiones.
