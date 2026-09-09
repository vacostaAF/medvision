# Cuaderno de ingeniería 2.9

## Motivación

El usuario preguntó si se podía aprovechar que, en el lado pastilla, el
texto de la etiqueta se ve reflejado por transparencia desde el reverso —
ya lo habíamos visto en imágenes de validación anteriores sin atarlo. Se
comprobó volteando horizontalmente una foto real del lado pastilla
(`f000080_bag00.jpg`, MVI_2713): el texto reflejado es perfectamente legible
("...NADO JOSEFA", "28/02/26 ALMUE...", "...A 1 MG COMPRIMIDO"), de calidad
comparable a lo que ya se lee con éxito en el lado etiqueta.

## Implicación de fondo

Hasta ahora el lado pastilla se identificaba por costura física (2.4-2.5),
una señal razonable pero sin garantías: solo dice "esto probablemente es una
bolsita distinta a la anterior", no "esta es la MISMA bolsita que aquella
etiqueta". El emparejamiento final seguía siendo ordinal (por posición),
sin ninguna certeza de contenido — la causa de fondo del ~4% de pares
fiables visto en el lote real de 108 vídeos (cuaderno 2.8).

Si el lado pastilla también puede tener cabecera OCR (día+fecha+franja),
puede usar el **mismo mecanismo de agrupado por cabecera** que ya existía
para el lado etiqueta (`group_label_bags_by_header()`, sin cambios — es
genérico, no depende del lado). Con cabecera en ambos lados, el
emparejamiento deja de ser una suposición de orden: una cabecera idéntica en
los dos lados es, con certeza, la misma bolsita física.

## Implementación

- `dataset/builder.py::_run_ocr_and_persist()`: nueva función que extrae y
  reutiliza el bloque de OCR que antes solo corría para `label_side`. Si
  `side == "pill_side"`, voltea el recorte horizontalmente
  (`cv2.flip(crop, 1)`) antes de pasarlo a `read_label()` — el resto del
  tratamiento (parseo, persistencia) es idéntico para los dos lados, misma
  función, sin rutas de código separadas que puedan divergir.
- OCR en el lado pastilla activable/desactivable con
  `ocr.pill_side_enabled` (por defecto `true`) — por si en algún lote el
  plástico resulta demasiado opaco para que merezca la pena.
- `database/repository.py::get_label_observations_for_video()` renombrado a
  `get_ocr_observations_for_video()`: ya no es específico del lado etiqueta.
- Bloque de emparejamiento en `dataset/builder.py` reestructurado en dos
  fases:
  1. **Directo**: se agrupan ambos lados por cabecera OCR
     (`pill_header_groups`, `label_groups`). Donde la firma (día+fecha+
     franja) coincide EXACTAMENTE entre un grupo de cada lado, se
     construye un `PairResult` con `match_score=1.0`, `status="paired"` —
     emparejado por contenido verificado, no por posición.
  2. **Red de seguridad (sin cambios de lógica, solo de alcance)**: lo que
     no encontró pareja exacta por cabecera (OCR ilegible en algún lado,
     bolsita real sin correspondencia) cae al mecanismo anterior — costura
     para identidad del lado pastilla + emparejamiento ordinal
     (`pair_tracks()`) — excluyendo las bolsas de pastilla ya usadas en un
     emparejamiento directo, para no procesarlas dos veces. Los
     `order_index` del emparejamiento ordinal se desplazan para no chocar
     con los de los pares directos dentro de la misma `pair_key`.

## Validado

Test de integración con SQL real (`Repository` real, no solo la función
aislada): dos bags en vídeos distintos (uno `pill_side`, otro `label_side`)
con la misma cabecera OCR producen la misma firma y se identifican como la
misma bolsita — confirmando que el flujo completo (guardar cabecera →
consultar → agrupar) funciona igual en ambos lados.

## Lo que sigue sin resolver del todo

Depende de que el OCR del lado pastilla consiga leer la cabecera completa
(día+fecha+franja) — el texto reflejado, aunque legible en la foto
comprobada, es de menor calidad que el directo (visto a través de dos capas
de plástico, con motion blur añadido). Cuando el reflejo no se lea bien en
ninguno de los frames de una bolsita, esa bolsita sigue dependiendo del
mecanismo de costura + orden, con las mismas limitaciones ya conocidas.

## Pendiente

Ejecutar el lote completo (108 vídeos, `--fresh`) con esto activado y medir
si `paired_with_label` sube de forma significativa respecto al 4% (24/574)
del cuaderno 2.8. Dado que ahora se corre OCR también en el lado pastilla,
el tiempo total de ejecución probablemente aumente — a tener en cuenta al
planificar cuándo lanzarlo.
