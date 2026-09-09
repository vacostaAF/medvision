# Cuaderno de ingeniería 3.24

## Motivación

3.23 introdujo "guardar avanza solo" tocando
`st.session_state.pair_index_1based` directamente dentro del manejador de
guardado — pero ese manejador se ejecuta DESPUÉS de que el
`number_input` con esa misma key ya se ha dibujado en la misma pasada del
script. Streamlit no permite modificar el `session_state` de una key una
vez que su widget ya se instanció en esa ejecución, y lanza
`StreamlitAPIException`. Error real, encontrado por el usuario al primer
uso — la ronda anterior no llegó a probarse de verdad antes de entregarse.

## Arreglo

Patrón estándar de Streamlit para este caso: en vez de tocar la key del
widget directamente desde el manejador de guardado, se dispara un aviso
(`st.session_state.pending_index_delta = 1`) y se hace `rerun()`. El
avance real se aplica al principio del script, en la pasada SIGUIENTE,
**antes** de que el `number_input` se vuelva a crear — momento en el que
sí está permitido tocar la key.

Los botones ◀ Anterior / Siguiente ▶ no tenían este problema — modifican
la key y llaman a `rerun()` **antes** de llegar al punto del script donde
se crea el `number_input`, así que nunca llegan a tocarla después de
instanciarse.

## Validado

No hay Streamlit instalable en este entorno (PyPI bloqueado por red) para
probarlo con un servidor real — en su lugar, se construyó una simulación
que reproduce la restricción exacta de Streamlit (lanzar la misma
excepción si se toca el `session_state` de una key ya instanciada en esa
pasada) y se ejecutó la lógica REAL del archivo (copiada literalmente,
línea a línea) contra ella: guardar 3 veces seguidas, mezclar botones con
guardar, y guardar en el último elemento — los 3 casos avanzan
correctamente sin ninguna excepción. Confirmado además que el código del
archivo coincide exactamente con lo simulado (comparación línea a línea).

## Nota honesta

Esta simulación cubre la lógica de estado con fidelidad — reproduce la
restricción exacta que causó el error real y prueba el mismo código, no
una reescritura aparte. Pero sigue sin ser una prueba de extremo a extremo
con Streamlit de verdad (yo no tengo forma de instalarlo aquí). Si al
probarlo en la práctica aparece cualquier otro comportamiento inesperado,
avisad de inmediato — prefiero que se pruebe con cuidado antes de que se
use para revisar de verdad, no que se descubra a medio camino otra vez.
