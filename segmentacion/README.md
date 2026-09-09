# MedVision AI — Módulo de segmentación de pastilla individual

TFE — Máster Universitario en Inteligencia Artificial (UNIR).
Esta carpeta contiene el código desarrollado en la fase de segmentación
de pastilla individual, continuación del Dataset Builder de MedVision AI
(carpeta hermana en la raíz del repositorio).

No incluye el dataset completo de imágenes (ver `datos/README.md`).

## Estructura

Cada carpeta corresponde a una etapa del desarrollo, en el orden en que se
usan realmente:

```
01_spikes_segmentacion/   Spikes de validación: filtro de falsos positivos
                            sobre FastSAM, y separación de pastillas
                            amontonadas mediante watershed clásico.
                            No forman parte del pipeline final -- quedan
                            documentados porque el resultado (y sus
                            limitaciones) motivó las decisiones posteriores.

02_retrieval_cima/         Consulta en vivo a la API pública de CIMA
                            (AEMPS) para obtener la apariencia visual
                            (forma, color, grabado) de un fármaco.

03_anotacion/              Selección del lote representativo de fotos a
                            anotar, y generación de las tareas de
                            Label Studio con las máscaras automáticas del
                            pipeline (FastSAM + filtro) precargadas como
                            predicción editable.

04_entrenamiento/          Conversión del export de Label Studio (COCO) a
                            formato YOLO, script de fine-tuning de
                            YOLO11n-seg, y el modelo ya entrenado (best.pt).

05_prototipo/              Prototipo final: dada una fotografía y la
                            lista de fármacos candidatos de su bolsita,
                            segmenta con el modelo entrenado e identifica
                            cada pastilla por apariencia visual contra
                            CIMA, mediante un reparto óptimo de conjunto.
                            prototipo3.py es la versión más completa y la
                            recomendada; prototipo.py y prototipo2.py se
                            conservan por ser pasos intermedios reales del
                            desarrollo (ver docstring de cada uno).

datos/                     No contiene el dataset en sí (ver su propio
                            README), solo metadatos ligeros como el lote
                            de anotación ya seleccionado.
```

## Orden de uso, de cero a prototipo funcionando

1. **Anotar el dataset** (`03_anotacion/`): `seleccionar_lote.py` elige las
   fotografías a anotar; `export_label_studio.py` genera las tareas de
   Label Studio con predicciones precargadas (importar la plantilla
   `label_studio_config.xml` en el proyecto antes de importar las tareas).
   Corregir en Label Studio, exportar en formato COCO.

2. **Entrenar** (`04_entrenamiento/`): `coco_a_yolo.py` convierte el export
   de Label Studio al formato que espera YOLO; `entrenar.py` hace el
   fine-tuning. Requiere GPU -- en local, sin GPU compatible, resulta
   inviable en tiempo razonable; se usó Google Colab (GPU T4 gratuita).
   El modelo ya entrenado (`best.pt`) se incluye en el repositorio.

3. **Usar el prototipo** (`05_prototipo/`): `prototipo3.py` recibe una
   fotografía y la lista de fármacos candidatos (con su cantidad esperada)
   y devuelve, por cada pastilla detectada, el reparto óptimo contra esos
   candidatos, más el detalle de puntuación libre por si hace falta
   revisión manual.

`01_spikes_segmentacion/` y `02_retrieval_cima/` no forman parte de esta
cadena de uso directo -- el primero documenta las técnicas descartadas
antes de entrenar un modelo propio, y `cima_retrieval.py` es el módulo del
que `prototipo3.py` reutiliza la lógica de consulta a CIMA (no se importa
directamente, sus funciones están duplicadas dentro de cada prototipo por
simplicidad; ver limitación anotada más abajo).

## Requisitos

```
pip install ultralytics opencv-python numpy requests scipy
```

`ultralytics` descarga automáticamente los pesos de FastSAM/YOLO11 que
necesite la primera vez que se ejecuta un script, si no los encuentra ya
en la carpeta.

## Limitaciones conocidas, sin resolver a fecha de esta entrega

- La separación automática de pastillas por bolsita cuando una misma
  fotografía contiene varias no es fiable (ver docstring de
  `prototipo2.py`); el prototipo recomendado (`prototipo3.py`) asume una
  única bolsita por fotografía.
- La búsqueda en CIMA no filtra por dosis ni por forma farmacéutica oral:
  puede devolver una presentación de dosis distinta a la indicada, o una
  forma no oral (inyectable, parche, solución) como candidato de
  comparación visual.
- No hay ninguna señal que distinga "esta pastilla encaja bien porque es
  el fármaco correcto" de "esta pastilla encaja bien porque, de la lista
  de candidatos dada, es la que menos mal queda" -- si la lista de
  candidatos de partida es incorrecta, el prototipo no lo detecta por sí
  solo.
- Comprimidos blancos redondos genéricos de distintos fabricantes pueden
  ser visualmente indistinguibles según la propia ficha técnica de CIMA;
  no es un fallo del sistema, es un límite de la información disponible.

Detalle completo de cada decisión, spike y limitación en la memoria del
TFE, apartados 4.15 a 4.25.
