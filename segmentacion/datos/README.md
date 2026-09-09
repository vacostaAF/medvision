# Datos

El dataset de fotografías (`dataset_package/`, ~350 MB: `bags/` con las
fotografías del lado pastilla y `dataset_final.json` con el manifiesto de
bolsitas) **no se incluye en este repositorio** por tamaño y por no ser
practicable en un repositorio Git estándar.

## Cómo obtenerlo

El dataset es la salida del módulo Dataset Builder (repositorio/entrega
aparte) de MedVision AI. Para reproducir cualquiera de los scripts de este
repositorio que lo requieren (`03_anotacion/seleccionar_lote.py`,
`03_anotacion/export_label_studio.py`, `04_entrenamiento/coco_a_yolo.py`):

1. Generar o solicitar el export `dataset_package.zip` del Dataset Builder.
2. Descomprimirlo de forma que quede `dataset_package/` (con `bags/` y
   `dataset_final.json` dentro) en la misma carpeta que el script
   correspondiente, o ajustar la constante `DATASET_DIR` al principio de
   cada script si se prefiere otra ubicación.

## Lote de anotación ya generado

`lote_representativo.json` (generado por `seleccionar_lote.py`, 216 fotos
de 220 bolsitas con foto) sí se conserva como referencia, ya que es un
fichero de metadatos pequeño, no las imágenes en sí.

## Modelo entrenado

Los pesos del modelo de segmentación ya entrenado sí están incluidos en
`../04_entrenamiento/best.pt` (6 MB) -- no dependen del dataset
completo para usarse en inferencia, solo se usó el dataset para entrenar.
