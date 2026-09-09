# Cuaderno de ingeniería 1.4

## Motivación

El stack original del proyecto especificaba PaddleOCR, no Tesseract. La versión
1.0-1.3 usaba `pytesseract` como solución provisional. Al ejecutar la demo de 4
vídeos, el resultado real en `output/metadata/track_pairs.csv` mostraba texto no
utilizable en varios pares (ejemplos reales, no hipotéticos):

- `"PEDRO FRANICIOSSRS AMNMCROOINIS-"`
- `"MARC AAAR VTIAIAC"`
- La misma palabra ("MICROGRAMO") reconocida de tres formas distintas en tres
  lecturas del mismo lote.

Consecuencia medible: `pairs_needing_review` = `track_pairs` (8 de 8, 100%) en
`reports/summary.json`. El cuello de botella no era el emparejamiento ni el
tracking (ambos funcionaban), sino la calidad del reconocimiento de texto.

## Decisión

Sustituir `pytesseract` por el pipeline `PaddleOCR` (paquete `paddleocr`,
API 3.x). Se descarta mantener ambos motores en paralelo (uno "de respaldo"):
duplicar rutas de código no probadas en producción no es coherente con el
objetivo de mantenibilidad del proyecto.

## Cambios de API relevantes (documentados porque han cambiado entre versiones)

`paddleocr` 3.x sustituye el método `ocr()` (que devolvía listas de
`[bbox, (texto, confianza)]`) por `predict()`, que devuelve objetos de
resultado con acceso a `rec_texts` y `rec_scores`. La forma exacta de acceso
(indexado directo vs. propiedad `.json` anidada bajo `"res"`) ha variado entre
releases recientes de la biblioteca, así que `_extract_texts_and_scores()` en
`ocr/label_ocr.py` prueba ambas formas en lugar de asumir una sola, para que un
cambio menor de versión no rompa el pipeline en silencio.

## Contrato mantenido

`OCRResult` conserva exactamente los mismos campos que la versión con
Tesseract, y `mean_confidence` se sigue expresando en escala 0-100 (aunque
PaddleOCR devuelve 0-1 internamente). Esto evita tener que tocar
`auto_accept_confidence` en `config/*.yaml` ni la lógica de `needs_review` en
`dataset/builder.py`.

## Idioma

PP-OCRv6 (modelo por defecto de PaddleOCR 3.x) usa un modelo latino unificado
para varios idiomas europeos, incluido español. No existe un equivalente
directo al `"spa+eng"` combinado que se usaba con Tesseract; se ha fijado
`lang: es` en la configuración.

## Pendiente explícito (fuera de alcance de este incremento)

El emparejamiento anverso/reverso sigue leyendo `video_sides` y `video_pairs`
por nombre exacto de fichero. Es válido para los 4 vídeos actuales (mismo
protocolo de captura: anverso y reverso grabados de forma consecutiva), pero
no escala a fuentes de vídeo mixtas (cámara + iPhone) con convenciones de
nombre distintas. Próximo incremento: emparejamiento automático por sesión de
captura (orden/proximidad temporal), con posibilidad de corrección manual vía
un manifiesto editable — no hardcodeado en la configuración general.

## Pruebas

`tests/test_label_ocr.py` cubre: normalización de texto, escalado de
resolución mínima, y extracción de `rec_texts`/`rec_scores` bajo las dos formas
de resultado observadas (indexado directo y `.json` anidado), incluyendo el
caso de un formato de resultado desconocido (debe degradar a lista vacía, no
lanzar una excepción no controlada). También se comprueba que la ausencia de
`paddleocr` produce un `RuntimeError` explicativo en vez de un `ImportError`
críptico en mitad del pipeline.

No se han podido ejecutar pruebas de inferencia real contra imágenes de la
demo en este entorno (sin acceso a red para instalar `paddlepaddle`/
`paddleocr`); queda pendiente que el propio equipo del proyecto corra
`medvision-ai build-dataset` con los 4 vídeos y compare
`reports/summary.json` (`pairs_needing_review`) antes/después como validación
empírica final.
