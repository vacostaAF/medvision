# Cuaderno de ingeniería 3.37

## Motivación

El usuario reportó que las imágenes generadas por 3.36 seguían mezclando
dos bolsitas en un mismo recorte. Con dos fotos reales enviadas, se
identificó la causa exacta: `crop_pouches_by_y_boundaries()` trataba el
borde superior/inferior del propio fotograma como si fuera una frontera
real entre bolsitas. Cuando el borde del fotograma cae en mitad de una
bolsita (muy habitual con paneo continuo y muestreo a intervalos fijos —
la cámara no para de grabar justo en las costuras), el segmento resultante
mezclaba la cola de esa bolsita con la totalidad de la siguiente.

## Diagnóstico confirmado con las dos fotos reales

- Foto 1: cola de una bolsita (pastillas + su propio pie de página) SIN su
  cabecera visible (quedó fuera del encuadre, por encima), seguida de una
  bolsita completa.
- Foto 2: pie de página de la bolsita anterior visible arriba (sin su
  cabecera en este fotograma, con la línea de sellado física entre medias
  — visible pero sin texto, no afecta al OCR), seguida de una bolsita
  completa.

En ambos casos, el patrón es el mismo: un fragmento sin una de sus dos
fronteras reales visibles en ESE fotograma concreto, que el código previo
recortaba igualmente usando el borde de la imagen como sustituto de la
frontera que faltaba.

## Arreglo

- `ocr/parser.py::find_complete_pouch_boundaries()` (nueva, sustituye el
  uso de `find_footer_positions()`/`group_footer_positions()` para este
  propósito): empareja cada línea de día de la semana (`_find_weekday()`,
  ancla ya validada en todo el proyecto para la cabecera) con el
  **siguiente** pie de página posterior. Si una cabecera no tiene ningún
  pie después en ese fotograma (cortada por el borde inferior), se
  descarta — no se convierte en una bolsita "completa" a medias. El
  inicio se retrasa un margen fijo (0.05 por defecto) para incluir
  también el nombre del paciente, que precede a la línea del día.
- `bags/pouch_cropping.py::crop_complete_pouches()` (nueva): recorta
  usando pares (inicio, fin) ya emparejados — nunca usa el borde de la
  imagen como frontera. Cualquier contenido antes del primer inicio
  detectado o después del último fin detectado se descarta sin más.
- `crop_pouches_by_y_boundaries()` (la de 3.36) se conserva para el caso
  en que SÍ se conocen todas las fronteras reales de antemano (p.ej.
  costuras ya validadas), documentado explícitamente que no es la función
  adecuada para el corte por contenido.

## Validado

- Reproducidos los dos patrones EXACTOS de las fotos reales enviadas por
  el usuario como tests permanentes — confirmado que el fragmento sin
  cabecera o sin pie se descarta, y que la bolsita completa se recorta
  con los límites correctos.
- Caso con 2 bolsitas completas en el mismo fotograma: las 2 se
  recuperan correctamente, cada una con su propio par inicio-fin.
- Caso sin ningún pie de página detectado: no genera ninguna bolsita
  (nada que emparejar), en vez de fallar o inventar un límite.
- `crop_complete_pouches()`: probado con datos sintéticos y con la
  fotografía real de dos bolsitas ya usada en 3.36, confirmando que un
  par (inicio, fin) real recorta exactamente esa bolsita sin arrastrar
  nada de la vecina.
- Suite completa: 124 tests, todos en verde.

## Nota honesta sobre la prueba de extremo a extremo

Se intentó validar el script completo contra un vídeo real
(`MVI_2733.MOV`) con el OCR simulado, pero el resultado de esa prueba
concreta no es representativo: al usar un texto simulado FIJO para todos
los fotogramas mientras el vídeo real muestra contenido distinto en cada
uno (el paneo avanza), el recorte no correspondía a los límites reales de
ESE fotograma — es un artefacto de la simulación, no del arreglo. La
validación real de la lógica está en los tests con los patrones de texto
exactos de las fotos reales del usuario, no en esa prueba con vídeo.

## Aviso pendiente, no resuelto en esta ronda

Al procesarse cada fotograma muestreado de forma independiente, una misma
bolsita completa puede aparecer en más de un fotograma consecutivo si el
paso de muestreo es pequeño en relación al tamaño de la bolsita en
pantalla — lo que generaría imágenes duplicadas de la misma bolsita real.
No se ha implementado deduplicación (por ejemplo, por coincidencia de
cabecera) porque no se ha confirmado si es un problema real en la
práctica; si al probar con datos reales aparecen muchos duplicados,
avisar para añadirla.
