# Cuaderno de ingeniería 1.2

## Hito
Asociación preliminar entre la cara transparente y la cara impresa de cada tira.

## Decisión
Se utiliza una asociación ordinal conservadora, configurable como directa o inversa. No se fuerza una correspondencia cuando un lado contiene más tracks que el otro.

## Riesgo conocido
El tracker actual puede dividir una bolsa real en varios tracks o fusionar observaciones. Por ello, los pares se exportan con puntuación y `needs_review`. La supervisión humana sigue siendo obligatoria antes de utilizar las etiquetas para entrenamiento.
