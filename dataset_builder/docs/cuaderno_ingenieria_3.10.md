# Cuaderno de ingeniería 3.10

## Motivación

El usuario, con razón, se preocupó por si tenía que "sobrescribir" algo al
actualizar a 3.9. Repasando el histórico: la base de datos real del
proyecto lleva desde la 2.8 en uso incremental, sin `--fresh` salvo en
puntos concretos (cambio de `threshold_value` a 80, y el cambio de
restricción `UNIQUE` de `ocr_results` en 3.2). Cada ronda desde entonces
(3.5 `videos.status`, 3.9 `track_pairs.label_ocr_result_id`, y `bags.
seam_prominence/seam_position` de más atrás si la base viniera de antes de
2.5) añadió columnas nuevas a tablas que `CREATE TABLE IF NOT EXISTS` ya no
vuelve a tocar, porque la tabla ya existe.

Sin comprobar esto, `rebuild-pairs` habría fallado con un error de SQL
("no such column: label_ocr_result_id") a mitad de ejecución.

## Arreglo

`Repository.__init__` llama a `_migrate_missing_columns()` tras crear el
esquema base: para cada tabla con columnas añadidas en rondas anteriores,
comprueba con `PRAGMA table_info()` cuáles faltan y las añade con
`ALTER TABLE ... ADD COLUMN`. No requiere que el usuario sepa ni recuerde
qué cambió en qué versión — se repara sola, cada vez que se abre la base,
sin coste si ya está al día (no hace nada si las columnas ya existen).

**Excepción explícita, no oculta**: `ocr_results.sheet_index` (3.2) no se
puede migrar así, porque ese cambio también modificó la restricción
`UNIQUE` de la tabla (de `bag_id` a `(bag_id, sheet_index)`), y SQLite no
permite alterar restricciones `UNIQUE` existentes sin recrear la tabla
entera. Si falta, `Repository.__init__` lanza un `RuntimeError` claro
explicando por qué y pidiendo `--fresh` — en vez de fallar más adelante con
un error de SQL confuso a mitad de una operación.

## Validado

Dos tests de integración con SQL real: (1) una base construida a mano con
el esquema de antes de 3.5/3.9 (sin `videos.status`, `bags.
seam_prominence/seam_position`, `track_pairs.label_ocr_result_id`) se abre
sin error y las columnas aparecen — confirmado además que los DATOS que ya
había antes de migrar (un vídeo, un par) siguen intactos, no se pierden ni
se sobrescriben; (2) una base de antes de 3.2 (sin `sheet_index`) lanza el
`RuntimeError` esperado, con el mensaje correcto.

## Para el usuario, en una frase

No hay que sobrescribir nada especial ni recordar qué versión introdujo qué
columna — actualizar el código y ejecutar `rebuild-pairs` (o `build-
dataset` sin `--fresh`) basta; la base se pone al día sola la primera vez
que se abre con el código nuevo.
