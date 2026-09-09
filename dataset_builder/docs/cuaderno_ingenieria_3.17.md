# Cuaderno de ingeniería 3.17

## Motivación

Con 595 pares marcados "necesita revisión", el usuario pidió mejorar la
cifra. Antes de seguir exprimiendo el emparejamiento (que ya toca un
límite real de datos, no de código — ver 3.16), se desglosaron los 595 por
categoría real: **303 de los 595 (51%) no tenían ningún fármaco
reconocido** — ruido de OCR (un trozo de pie de farmacia o de código QR
mal leído como si fuera una cabecera). Revisar esas filas no tiene ningún
sentido: no hay ninguna lista de fármacos que confirmar o corregir.

## Arreglo

- `database/repository.py::list_pairs_for_review()`: nuevo parámetro
  `hide_empty` (por defecto `True`) — excluye pares sin ningún
  `label_item` asociado. Se añadió también `item_count` a la consulta
  (antes no se calculaba en el listado, solo al abrir el detalle de un
  par).
- `app/review_app.py`: casilla "Ocultar lecturas sin ningún fármaco" en la
  barra lateral, marcada por defecto. Debajo de las métricas, un aviso
  indica cuántas quedan ocultas, para que no parezca que faltan datos sin
  explicación.

## Efecto esperado

De 595 pares "necesita revisión" a ~292 que de verdad requieren juicio
humano (208 con fármacos sin foto + 80 emparejados por posición sin
verificar por contenido + 4 casos raros de coincidencia directa sin
items) — más de la mitad del trabajo de revisión desaparece sin perder
ningún dato: las 303 filas ruidosas siguen en la base (por si hiciera
falta depurar el pipeline más adelante), solo dejan de aparecer por
defecto en la cola de trabajo humano.

## Validado

Test de integración con SQL real: 3 pares (1 con fármaco real, 2 vacíos)
— por defecto (`hide_empty=True`) solo aparece 1; con `hide_empty=False`
aparecen los 3. Se actualizaron 7 llamadas de tests anteriores (3.9, 3.12)
que no rellenaban `label_items` en sus datos de prueba — no relacionadas
con contenido de fármacos, se les pasó `hide_empty=False` explícito para
que sigan probando lo que probaban sin verse afectadas por el nuevo filtro
por defecto.
