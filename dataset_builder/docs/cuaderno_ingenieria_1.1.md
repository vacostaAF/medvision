# Cuaderno de ingeniería — Dataset Builder 1.1

## Hito

Se incorpora seguimiento temporal para evitar tratar como muestras independientes varias apariciones de una misma bolsa.

## Diseño

Cada recorte se representa mediante un descriptor compacto formado por histograma HSV y una miniatura en escala de grises. La asociación entre frames usa una puntuación ponderada de:

- similitud de apariencia;
- proximidad vertical normalizada;
- consistencia débil del orden dentro de la tira;
- límite temporal máximo.

La asignación es greedy uno-a-uno. Para cada track se conserva la observación con mejor combinación de calidad de frame y confianza de segmentación.

## Justificación

El método evita añadir dependencias pesadas y permite validar el concepto con los vídeos existentes. También deja explícitas sus decisiones, lo que facilita el análisis de errores y la defensa académica.

## Limitaciones

- Las bolsas visualmente muy parecidas pueden fusionarse.
- Un muestreo temporal demasiado espaciado dificulta la asociación.
- La separación heurística de bolsas condiciona el tracking.
- Todavía no se estima de forma explícita la dirección y velocidad de avance.

## Próxima iteración

Generar una vista de revisión de tracks, medir duplicados/fusiones con anotación humana y asociar anverso y reverso de la misma posición en la tira.
