# Cuaderno de ingeniería 2.0

## Motivación

Ejecución en limpio (con `output/medvision.sqlite` borrado) confirmó que el
agrupado por cabecera (1.9) funciona exactamente como se esperaba: 3 bolsitas
reales, 3 grupos, sin fantasmas de ejecuciones anteriores. Pero
`track_pairs.csv` mostró algo inesperado: la única foto de pastilla
disponible se emparejó con la bolsita del pie de farmacia (0 fármacos),
dejando sin pareja las dos bolsitas con contenido real (3 y 4 fármacos).

## Causa raíz

`group_label_bags_by_header()` ordena los grupos por `center_norm` para el
emparejamiento ordinal posterior (`pairing/track_pairer.py`). Ese
`center_norm` venía de la posición vertical `(y1+y2)/2` dentro del frame —
tenía sentido cuando `bag_splitting.max_segments` cortaba varias bolsitas
visibles en un mismo frame (demo 1.0-1.3: la posición Y sí distinguía "la de
arriba" de "la de abajo"). Desde 1.7 (`max_segments=1`), cada bolsa ocupa
casi todo el frame detectado — la posición Y es casi idéntica en todas las
observaciones, así que ordenar por ella es en la práctica ruido, no señal.

## Arreglo

`get_label_observations_for_video()` calcula ahora `center_norm` a partir del
**número de frame** (`frame_index` normalizado dentro del vídeo), que sí
refleja el orden real en que la cámara pasó por cada bolsita durante el
paneo. La posición Y original se conserva aparte (`y_center_norm`) por si se
necesita en el futuro, pero ya no se usa para ordenar.

Validado con un test de integración que reproduce el caso real: 3 bolsitas
con la MISMA posición Y (como ocurre siempre con `max_segments=1`) pero
`frame_index` distinto (0, 50, 100) — la del frame 100 (footer) debe quedar
última, no primera.

## Limitación de fondo que este arreglo NO resuelve

Con solo 1 observación de pastilla en todo el vídeo (`MVI_2713` solo detectó
la tira en 1 de 6 frames muestreados) contra 3 bolsitas reales del lado
etiqueta, el emparejamiento ordinal 1:1 solo puede acertar como mucho 1 de 3
— ya no por elegir mal (eso está arreglado), sino porque **no hay suficientes
fotos de pastilla para emparejar con las 3 bolsitas reales**. Ningún cambio
en el algoritmo de ordenación puede inventar observaciones que nunca se
capturaron.

Recomendación concreta para el siguiente incremento: subir la densidad de
muestreo (`sampling.seconds_between_frames`, hoy en 2.0) para que el lado
pastilla también capture varias observaciones a lo largo del paneo — sin
eso, el emparejamiento pastilla↔etiqueta seguirá limitado
estructuralmente, sea cual sea el algoritmo de turno.
