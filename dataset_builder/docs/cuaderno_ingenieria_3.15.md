# Cuaderno de ingeniería 3.15

## Motivación

Primera ejecución real de 3.13-3.14 sobre el dataset completo (104
vídeos): 92 pares nuevos de `position_matched`, muy por debajo de la
estimación optimista dada antes de verlo (40-80% de los sin pareja). Al
analizar los propios resultados, la mediana de `item_count` entre esos 92
era **0** — la mayoría emparejaba fotos de pastilla con lecturas de
etiqueta vacías o de ruido (ejemplo real: `"GR473F181 22"` como
`patient_name`, un fragmento del código de registro de farmacia mal
interpretado como cabecera).

## Diagnóstico

El emparejamiento por posición (3.13) se ofrecía a **todos** los grupos de
etiqueta sin coincidencia directa, sin filtrar por si el grupo tenía algún
fármaco reconocido. Con datos reales: 52 de los 92 emparejamientos
(57%) caían en lecturas vacías — sin ningún valor para el dataset (no hay
lista de fármacos que confirmar), y **gastando una foto de pastilla que
podría haber servido para una de las 248 bolsitas reales que sí tenían
fármacos y seguían sin pareja**. El problema no era solo "resultados
inútiles" — activamente restaba oportunidades a los casos que sí importaban.

## Arreglo

`_build_pairs()`: los grupos de etiqueta sin ningún fármaco reconocido
(`grp.merged_items` vacío) ya no se ofrecen para el emparejamiento por
posición — se dejan directamente en `unmatched_label`, sin intentar
buscarles pareja ni consumir ninguna foto de pastilla.

## Validado

Test de integración con SQL real reproduciendo el caso exacto: con solo 1
foto de pastilla disponible en la sesión y 2 lecturas de etiqueta en la
misma posición relativa (una vacía, otra con fármacos reales), confirmado
que la lectura vacía **no** consume la foto — queda libre para la que sí
tiene contenido real.

## Efecto esperado, no confirmado todavía

Con esto, el recuento total de `position_matched` probablemente baje (ya
no se cuentan los 52 emparejamientos-ruido), pero el aprovechamiento real
(cuántas de las 248 bolsitas reales sin pareja consiguen una) debería
subir, al no competir ya por fotos de pastilla con lecturas vacías.
Pendiente confirmar con `rebuild-pairs` sobre el dataset real cuánto sube
de verdad.
