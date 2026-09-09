# MedVision AI · Dataset Builder 2.6

Pipeline para generar y validar un dataset supervisado de medicamentos en bolsas.

## Novedad 2.6: emparejamiento automático de vídeos por sesión

Ya no hace falta editar `video_sides`/`video_pairs` a mano por cada vídeo
nuevo (con 108 vídeos, era inviable). Protocolo de grabación: siempre se
graba primero la tira de pastillas, inmediatamente después la misma tira
por el lado de la etiqueta.

```bash
medvision-ai plan-sessions --videos-dir videos --output config/sessions.yaml
medvision-ai build-dataset --videos-dir videos --output-dir output \
    --config config/default.yaml --sessions config/sessions.yaml
```

`plan-sessions` ordena los vídeos por su instante real de grabación
(metadato `creation_time`, no el nombre de fichero — distintas cámaras usan
convenciones distintas) y los empareja consecutivos. Marca para revisión
cualquier hueco anómalo entre pastilla y etiqueta, o un número impar de
vídeos. `config/sessions.yaml` es vuestro: no lo genero ni lo toco yo entre
entregas, así que no se puede volver a perder como pasó dos veces con
`video_sides` viviendo dentro de `default.yaml` (cuadernos 1.7 y previos).

Detalle en `docs/cuaderno_ingenieria_2.6.md`.

## Novedad 2.4-2.5: identidad del lado pastilla por costura

El lado pastilla no tiene texto propio del que derivar identidad (a
diferencia del lado etiqueta, resuelto vía cabecera OCR). Se usa en su lugar
la banda de costura entre bolsitas (brillo + tinte azulado del reflejo del
foco al grabar) como señal física real. Detalle en
`docs/cuaderno_ingenieria_2.4.md` y `2.5.md`.

## Novedad 1.5: varios fármacos por bolsita (tiras SPD reales)

Las bolsitas reales (sistema personalizado de dosificación) listan varios
fármacos por bolsa, no uno. `ocr/parser.py::parse_label_sheet()` sustituye al
antiguo "un fármaco por lectura" en el pipeline, con un modelo de datos nuevo
(`label_headers`, `label_items`) y una revisión humana con tabla editable en
vez de 3 campos de texto. Detalle y justificación en
`docs/cuaderno_ingenieria_1.5.md`.

**Pendiente para el siguiente incremento:** el emparejamiento anverso/reverso
sigue por nombre de fichero en `config/*.yaml`. Con 108 vídeos reales
(`MVI_XXXX`, no los `IMG_XXXX` de la demo) ya no es viable a mano — toca
sustituirlo por un emparejamiento por sesión de captura.

## Novedad 1.4: OCR con PaddleOCR

El OCR del reverso ya no usa Tesseract. En la demo con 4 vídeos, Tesseract
producía texto no utilizable (p. ej. `"PEDRO FRANICIOSSRS AMNMCROOINIS-"` en vez
de un nombre de fármaco) y el 100% de los pares generados quedaban marcados
`needs_review`. `ocr/label_ocr.py` usa ahora el pipeline `PaddleOCR` (API 3.x,
método `predict()`), manteniendo la misma interfaz (`OCRResult`, escala de
confianza 0-100) para no afectar al resto del pipeline. Detalle técnico y
justificación en `docs/cuaderno_ingenieria_1.4.md`.

**Pendiente para el siguiente incremento** (no bloquea esta entrega): el
emparejamiento anverso/reverso sigue configurado por nombre de fichero en
`config/*.yaml` (`video_sides`, `video_pairs`). Válido mientras se trabaje solo
con estos 4 vídeos; antes de grabar con fuentes mixtas (cámara + iPhone) hay que
sustituirlo por un emparejamiento por sesión de captura.

## Novedad 1.3: revisión humana

La aplicación Streamlit presenta juntos el lado transparente y el reverso. Permite:

- aceptar una asociación;
- corregir medicamento, dosis o unidad;
- rechazar el par;
- dejarlo pendiente;
- guardar observaciones y fecha de revisión en SQLite.

## Instalación

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

# 1) Motor de inferencia de PaddleOCR (paquete aparte, no viene con paddleocr).
#    CPU:
pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
#    GPU (CUDA 11.8, Linux):
# pip install paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/

# 2) Resto de dependencias, incluido paddleocr
pip install -r requirements.txt
```

La primera vez que se ejecute el OCR, PaddleOCR descargará los pesos de los
modelos de detección/reconocimiento (requiere red esa primera vez; luego
quedan cacheados localmente).

## Procesar vídeos

```bash
medvision-ai build-dataset --config config/default.yaml
```

## Abrir la revisión

```bash
streamlit run app/review_app.py
```

En la barra lateral introduce la ruta a la base, por ejemplo:

```text
C:\proyecto\output\medvision.sqlite
```

## Flujo

Vídeo → frames → bolsas → tracks → pares anverso/reverso → OCR → revisión humana → dataset validado.
