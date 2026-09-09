# Cuaderno de ingeniería 2.5

## Motivación

El detector de costura (2.4) validado contra 3 imágenes reales resultó
prometedor pero incompleto: contra la secuencia completa de 8 observaciones
reales de `MVI_2713` (frames 80-190), la costura no aparece en un único
frame limpio — "parpadea" (detectada, no detectada, detectada) a lo largo de
varios frames seguidos, coherente con un paneo a pulso que se demora sobre
el pliegue físico en vez de cruzarlo en un instante.

```
f080: SÍ (14.4)   f090: SÍ (4.8)   f100: NO (1.9)   f110: SÍ (9.7)
f120: SÍ (8.4)    f130: NO (2.4)   f140: NO (2.5)   f190: SÍ (12.5)
```

## Decisión: zonas de transición con tolerancia a huecos, no un único frontera

En vez de tratar cada frame de forma independiente, `pairing/seam_grouping.py`
agrupa en tres tipos de tramo:

1. **Zona estable** (costura no detectada de forma sostenida): bolsita
   limpia, se ofrece para emparejar.
2. **Zona de transición** (costura detectada, con huecos cortos tolerados —
   `max_bridge_frames`, en frames, no en observaciones consecutivas, para no
   puentear a través de un hueco de detección real de varios segundos): se
   marca `in_transition=True` y **no se ofrece para emparejar**. Mismo
   criterio que ya se usó con cabeceras incompletas (1.9): mejor no agrupar
   con certeza que agrupar mal.

Con los datos reales: `[80,90,100,110,120]` (puenteando el hueco de f100) se
trata como una única zona de transición ambigua; `[130,140]` como bolsita
limpia; `[190]` como el inicio de la siguiente transición.

## Enganchado al pipeline

- `database/schema.py`: columnas nuevas `seam_prominence`, `seam_position`
  en `bags` (nullable — solo se rellenan para `pill_side`).
- `dataset/builder.py`: al crear cada bolsa del lado pastilla, se calcula
  `detect_seam_band()` sobre el recorte y se guarda junto al resto de
  metadatos del bag.
- `database/repository.py::get_pill_observations_for_video()`: trae las
  observaciones de un vídeo con su prominencia ya calculada, ordenadas por
  frame.
- En el emparejamiento, `pill_tracks` ya NO viene de `bag_tracks` (el track
  visual que confundía bolsitas distintas, ver 2.0). Viene de
  `group_pill_bags_by_seam()`, filtrando fuera los grupos en transición —
  solo las zonas estables se ofrecen para emparejar con el lado etiqueta.

Validado con test de integración con SQL real (no solo la función aislada),
reproduciendo la secuencia exacta de `MVI_2713`.

## Efecto esperado, honestamente

Esto reduce las bolsitas del lado pastilla candidatas a emparejar (las
zonas de transición quedan fuera), no las aumenta. El resultado esperado es
menos pares totales del lado pastilla, pero con más confianza en los que sí
se ofrecen — sustituye "emparejar con lo que sea, puede que mal" por
"emparejar solo lo que hay certeza razonable, dejar el resto para revisión
manual". Sigue sin resolver el caso de fondo (con solo 1-2 zonas estables
por vídeo, muchas bolsitas reales del lado etiqueta seguirán sin foto de
pastilla) — eso requeriría más densidad de muestreo específicamente
calibrada para capturar zonas estables más largas, no un cambio de
algoritmo.

## Pendiente

Ejecutar el pipeline completo con este cambio y confirmar con
`track_pairs.csv`: ¿cuántas zonas estables aparecen en total? ¿mejora
`paired_with_label` respecto al 1/10 anterior, aunque sea modestamente?
