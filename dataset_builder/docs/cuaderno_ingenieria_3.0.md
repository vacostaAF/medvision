# Cuaderno de ingeniería 3.0

## Motivación

El usuario, probando la app de revisión por primera vez contra datos
reales, señaló un problema concreto: como una bolsita no siempre cabe entera
en un solo frame (limitación conocida desde 1.7), y el agrupado por
cabecera/costura fusiona el texto de varias vistas parciales en una lista
completa (1.9, 2.5), cabía la duda de si al revisar solo se enseñaba una de
esas fotos — con el riesgo de que una pastilla o línea que solo aparece en
otra vista "desaparezca" para quien revisa.

## Confirmado

`track_pairs.pill_best_bag_id` / `label_best_bag_id` solo guardan **una**
bolsa representante por lado — la que más fármacos reconoció de por sí antes
de fusionar (ver `header_grouping.py::group_label_bags_by_header`). La app
de revisión solo consultaba esa única imagen. Si una bolsita se fusionó a
partir de 2-3 vistas parciales, cualquier pastilla o línea visible solo en
una vista que NO fue elegida como representante quedaba invisible durante
la revisión, aunque su fármaco sí estuviera en la lista fusionada.

## Arreglo

Nueva tabla `pair_group_members` (track_pair_id, side, bag_id): guarda
**todas** las bolsas que contribuyeron a un lado de un par, no solo la
representante.

- `dataset/builder.py`: tanto los pares directos (por cabecera compartida,
  2.9) como los del mecanismo de respaldo (costura + orden) ya tenían
  disponible `grp.bag_ids` (la lista completa de bolsas del grupo) — solo
  faltaba persistirla. Se guarda junto con cada par, vía
  `repo.replace_pair_group_members()`.
- `database/repository.py`: `upsert_track_pair()` ahora devuelve el id
  (antes no devolvía nada) — hace falta para enlazar los miembros del grupo
  al par recién creado.
- `app/review_app.py`: en vez de una imagen por lado, se consultan y
  muestran **todas** las fotos del grupo (`get_pair_group_image_paths()`),
  con un aviso cuando hay más de una ("no cupo entera en un solo frame,
  revisa todas").

## Validado

Dos tests de integración con SQL real: (1) un grupo de 2 bolsas guarda y
devuelve las 2 rutas, no solo la de la representante; (2) volver a llamar
`replace_pair_group_members` sobre el mismo par sustituye, no acumula
duplicados (relevante para reprocesados del pipeline).

## Nota

Este era un problema real de la app de revisión, no del pipeline de
extracción en sí — la lista de fármacos fusionada ya era correcta desde
1.9/2.5 (el texto de todas las vistas SÍ se combinaba bien). Lo que faltaba
era que la revisión humana pudiera *verificar visualmente* esa fusión contra
todas las fotos que la sustentan, no solo contra una.
