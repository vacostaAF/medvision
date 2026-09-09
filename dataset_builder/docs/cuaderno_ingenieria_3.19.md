# Cuaderno de ingeniería 3.19

## Motivación

Caso real encontrado en revisión (`session_0002`, posición 1, `paired`,
`match_score=1.0`): la identidad del par es correcta (cabecera "DOMINGO
01/03/26 DESAYUNO" leída de forma independiente y coincidente en los dos
lados), pero la foto de pastilla representante no mostraba ninguna marca
de costura pese a tener dos bolsitas visibles sin separar — porque esa
lectura concreta tuvo 0 fármacos (`seam_side` nunca se rellenó, ver 3.11:
solo se marca cuando `parse_label_sheets_by_position` realmente separa
contenido).

## Arreglo

`render_with_seam()` distingue ahora 3 casos, no 2:
1. Costura detectada **y** se sabe de qué lado está la bolsita
   (emparejamiento directo con contenido en esa lectura): línea +
   atenuación, como ya hacía.
2. Costura detectada pero **no** se sabe el lado (la lectura de esa foto
   no tuvo cabecera/items propios, como en el caso real de arriba):
   se dibuja la línea igualmente, **sin atenuar ningún lado** — mejor
   marcar "aquí hay una frontera, decide tú" que no marcar nada, dejando
   al revisor sin ninguna pista.
3. Sin costura detectada en absoluto: foto sin tocar, como antes.

`bags.seam_position` se calcula en el momento del OCR (3.11) de forma
independiente a si esa lectura concreta encontró cabecera o fármacos — así
que el dato para el caso 2 ya existía, solo no se estaba aprovechando.

## Validado

Prueba aislada de `render_with_seam()` con los 3 casos: con lado conocido
(atenúa correctamente un lado), con costura pero sin lado (dibuja línea,
brillo similar en ambos lados — sin atenuar), sin costura (devuelve la
ruta sin modificar).

## Resuelto: el caso real que motivó este arreglo

**Identificación exacta**, para evitar la confusión que causó dejarlo como
"pendiente" sin más detalle (llevó a intentar reinvestigar con el vídeo
equivocado en otra conversación): el caso es `pair_key=session_0002`,
`order_index=1`, `track_pairs.id=35`. Vídeo pastilla `MVI_2736` (bolsas
`144` frame 230 y `145` frame 240), vídeo etiqueta `MVI_2737` (bolsa
representante `173`, frame 220). **No** es `MVI_2732`/`MVI_2733` — esa es
otra sesión distinta (`session_0000`, la del cuaderno 3.16).

**Diagnóstico con `diagnostico.py` sobre `session_0002 1`**: se revisaron
las 5 lecturas OCR distintas que se fusionaron en esta bolsita
("DOMINGO 01/03/26 DESAYUNO", bags 169, 170, 171, 173, 174) — en
**ninguna de las 5**, nunca, aparece "Extracto Lipídico" en el texto
crudo. No es un bug de fusión (no había nada que fusionar, porque no se
leyó en ninguna observación) ni de posición — es que el OCR nunca llegó a
leer esa línea con claridad en ningún frame muestreado de esta bolsita en
concreto. Consistente con lo visto en las fotos reales: la pastilla
correspondiente (marcada "M") queda cortada en el borde inferior en las
dos imágenes disponibles (`f000230_bag00.jpg`, `f000240_bag00.jpg`).

**Conclusión importante, que motivó un cambio de estrategia de revisión**:
este par tenía `status=paired`, `match_score=1.0` — la identidad estaba
perfectamente verificada (misma cabecera en los dos lados), y aun así
faltaba un fármaco. `paired` verifica IDENTIDAD, no COMPLETITUD de la
lista — no hay ninguna señal interna (todas las lecturas coincidían en los
mismos 5 fármacos, ninguna encontró un sexto) que hubiera permitido
detectar este caso sin revisión humana. Por eso se decidió revisar TODOS
los `paired`, no solo una muestra, hasta que se acumule evidencia de que
el riesgo real es bajo.

