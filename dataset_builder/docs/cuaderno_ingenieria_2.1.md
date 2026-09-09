# Cuaderno de ingeniería 2.1

## Cambio

Solo configuración, sin tocar código: `sampling.seconds_between_frames`
2.0 → 0.4 (`max_frames_per_video` 20 → 30 para no capar antes de tiempo).

## Motivación

Con 2.0s de intervalo, un vídeo de ~11s solo daba ~6 frames muestreados, y
de esos el lado pastilla (`MVI_2713`) solo detectó la tira en 1 de 6. Con una
sola observación de pastilla, el emparejamiento contra varias bolsitas reales
del lado etiqueta no puede acertar más que 1 de N pase lo que pase en el
algoritmo (cuaderno 2.0). Antes de tocar más código de emparejamiento, se
prueba si dar más oportunidades de detección a ambos lados basta.

## Coste esperado (para que no sorprenda)

Con 0.4s de intervalo, un vídeo de ~11s pasa de ~6 a ~27 frames muestreados.
El OCR solo corre sobre frames del lado etiqueta donde se detectó la tira —
antes eran 3 llamadas a PaddleOCR por vídeo, ahora podrían ser 10-15. Cada
llamada tarda varios segundos (el smoke test midió 8-19s por frame completo
a 1920×1080; sobre el recorte de bolsa, más pequeño, debería ser menos, pero
no se ha medido todavía contra un recorte real). Para 2 vídeos de validación
es asumible; para los 106 restantes, este mismo ajuste multiplicaría bastante
el tiempo total de proceso — es una de las cosas a revisar antes de lanzar el
lote completo, no algo para dar por hecho sin medir.

## Pendiente

Ejecutar en limpio (`--fresh` o borrando `output/medvision.sqlite` a mano) y
revisar `summary.json` / `ocr.csv` / `track_pairs.csv`: ¿sube el número de
observaciones de pastilla? ¿mejora la proporción de pares con fármacos
reales frente a los que quedan sin pareja?
