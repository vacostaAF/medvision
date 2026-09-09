# Cuaderno de ingeniería 3.25

## Motivación

El usuario planteó una duda razonable: los pares `unmatched_label` con
fármacos reales pero sin foto (`asociación 0.00`) no se pueden aceptar a
ciegas igual que las lecturas vacías (3.17) — la lista de texto en sí
puede tener errores de OCR (confirmado con un caso real, "OMEPRAZOL 20
**MO** CAPSULA"). Pero revisarlos con la pantalla actual, pensada para
comparar foto contra lista, es mucho más lento de lo necesario cuando no
hay ninguna foto que cargar ni comparar.

## Arreglo

Nueva casilla "Vista rápida (solo texto, sin fotos)" en la barra lateral.
Activada, el bloque de imágenes (`get_pair_group_images()`, carga y
renderizado de fotos con costura) se salta por completo — ni siquiera se
consulta la base de datos para eso, no solo se oculta visualmente. En su
lugar, un aviso recuerda qué comprobar (que la lista tenga sentido) antes
de pasar directamente a la tabla editable de fármacos, que sigue
funcionando igual (edición, guardado, avance automático de 3.23/3.24).

## Validado

Compilación y suite completa (90 tests) sin regresiones. Comprobado que no
quedan referencias a `pill_images`/`label_images` fuera del bloque
condicional (no rompe si `quick_mode=True` deja esas listas vacías).

## Uso previsto

Pensada específicamente para los pares con `asociación 0.00`
(`unmatched_label` con fármacos reales, sin ninguna foto candidata) — para
esos, cargar imágenes no aporta nada. Para el resto (`paired`,
`position_matched`), lo normal seguirá siendo la vista con fotos, donde sí
hay algo que comparar visualmente.
