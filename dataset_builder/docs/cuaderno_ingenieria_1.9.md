# Cuaderno de ingeniería 1.9

## Motivación

Antes de construir la fusión de fármacos entre varios frames de una misma
bolsita (pendiente del cuaderno 1.8), se comprobó `bags.csv` de una ejecución
real para confirmar que el tracker visual (`bags/tracker.py`) realmente
seguía la misma bolsita física entre frames. No era así.

## Hallazgo (grave, no cosmético)

Las 3 observaciones OCR de `MVI_2714.MOV` (frames 0, 50, 100) —con contenido
demostrablemente distinto: "domingo desayuno" (Calcifediol, Bisoprolol,
Cinitaprida), "sábado cena" (Cinitaprida, Simvastatina, Risperidona,
Plusvent), y una tercera solo con pie de farmacia— **cayeron las 3 en el
mismo `track_key` (`track0001`)**. El tracker decide identidad por aspecto
visual (histograma de color); como todas las bolsitas de esta tira se
parecen entre sí (fondo blanco, texto negro, tamaño similar), nunca detectó
que había cambiado de bolsita.

Consecuencia ya activa, no solo hipotética: `label_best_bag_id` de ese track
apuntaba a un único bag, así que las otras 2 bolsitas reales ya se estaban
descartando en silencio del `track_pairs` final, antes incluso de construir
ninguna fusión. Si se hubiera construido la fusión sobre este tracking sin
comprobar antes, el resultado habría sido mezclar la medicación de un
domingo con la de un sábado en un mismo registro — con el uso previsto
("esto lo utilizaremos para el tratamiento"), eso es un error de datos más
grave que el problema original de captura parcial.

## Decisión

No agrupar por track visual. Agrupar por la firma de identidad que ya se
extrae de forma fiable: cabecera OCR (día de semana + fecha + franja
horaria). Dos observaciones con cabecera idéntica son, con certeza, la misma
bolsita física; dos con cabecera distinta son, con certeza, bolsitas
distintas. No es una heurística de aspecto, es el contenido mismo.

`patient_name` se excluye deliberadamente de la firma: es constante en toda
la tira (mismo paciente) y no aporta poder de discriminación entre bolsitas
del mismo paciente.

Si falta cualquiera de los tres campos (día/fecha/franja), la observación
**no se agrupa con nada** — se trata como su propia bolsita aislada. Es más
seguro perder una oportunidad de fusión que arriesgarse a fusionar mal por
una cabecera incompleta.

## Implementación

Nuevo módulo `pairing/header_grouping.py` (con tests unitarios y un test de
integración con SQL real, no solo con diccionarios sueltos):

- `header_signature(header)`: la firma de 3 campos, o `None` si está incompleta.
- `merge_label_items(item_lists)`: fusiona listas de fármacos ya parseadas de
  varias observaciones, deduplicando por nombre. Si una observación no
  reconoció la dosis de un fármaco pero otra sí, se queda con la que sí la
  tiene. Deliberadamente NO intenta resolver conflictos de geometría de texto
  (eso ya se hace antes, en `label_ocr.py`/`parser.py`) — aquí solo se
  combinan listas ya limpias.
- `group_label_bags_by_header(observations)`: agrupa, elige un bag
  representante por grupo (el que más fármacos reconoció de por sí, empate
  por confianza), y calcula posición/calidad agregadas para el
  emparejamiento posterior.

`database/repository.py::get_label_observations_for_video()`: trae todas las
observaciones OCR (con cabecera e items ya cargados) de un vídeo concreto —
la materia prima para agrupar.

`dataset/builder.py`: en el bloque de emparejamiento, el lado etiqueta ya NO
usa la consulta de `bag_tracks` (track visual). Usa
`get_label_observations_for_video` + `group_label_bags_by_header`, y
persiste la lista fusionada de cada grupo en `label_items` del bag
representante (`replace_label_items`), reutilizando el almacenamiento
existente en vez de crear tablas nuevas. El lado pastilla (`pill_side`) sigue
usando el track visual — no tiene texto propio del que derivar una identidad
más fiable, sigue siendo un problema abierto.

## Validado con el caso real exacto

Los 3 tests de `test_header_grouping.py` y el de integración en
`test_repository_label_items.py` usan las 3 observaciones reales de
`bags.csv` (domingo desayuno / sábado cena / pie de farmacia) como fixture.
Con el agrupado nuevo: 3 grupos separados, cada uno con solo sus fármacos
reales — ninguno se cuela en el otro.

## Lo que sigue sin resolver

El emparejamiento pastilla↔etiqueta (`pairing/track_pairer.py`) sigue siendo
ordinal por posición entre el track visual de `pill_side` y los grupos por
cabecera de `label_side`. Si el número de bolsitas realmente distintas no
coincide entre ambos lados (por ejemplo, si `pill_side` solo detectó 1
observación pero `label_side` ahora identifica 3 bolsitas reales), el
emparejamiento 1:1 seguirá siendo incompleto — no porque el agrupado esté
mal, sino porque el lado pastilla no tiene una señal de identidad propia
equivalente a la cabecera. Sigue siendo, junto con el emparejamiento
automático por sesión de vídeo, uno de los frentes abiertos más importantes
del proyecto.
