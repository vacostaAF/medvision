# Cuaderno de ingeniería 3.7

## Motivación

Segunda vez (real, no hipotética) que se lanza `build-dataset` sin haber
regenerado `sessions.yaml` con los vídeos nuevos añadidos a la carpeta. El
aviso de 2.9 (una línea por vídeo) existía, pero en un log de cientos de
líneas (68 vídeos, decenas de "ya procesado, saltando") es fácil no verlo —
que es justo lo que pasó. El arreglo de 3.6 (no dar por completado un vídeo
si el lado cambió) funcionaba correctamente, pero no puede arreglar un caso
en el que el lado *nunca* llegó a corregirse antes de relanzar.

## Decisión de diseño

Dos avisos repetidos del mismo problema es señal de que el problema no es
"recordar mejor" — es que el flujo permite llegar a un estado silenciosamente
incorrecto (procesar como `unknown`) sin ninguna barrera real. Se cambia de
"avisar y seguir" a "parar antes de tocar nada".

## Arreglo

`build_dataset()` calcula ahora la lista de vídeos y comprueba, **antes de
abrir el `Repository` o tocar cualquier vídeo**, si todos tienen lado
asignado en `video_sides`. Si falta alguno, lanza `RuntimeError` con la
lista de vídeos afectados (hasta 10, con "..." si hay más) y el comando
exacto de `plan-sessions` a ejecutar. No se crea ni el `.sqlite`, no se abre
ningún vídeo, no se pierde tiempo de proceso en vano.

Parámetro nuevo `allow_unknown_side: bool = False` (CLI: `--allow-unknown-
side`) para el caso, poco frecuente pero legítimo, de querer procesar
vídeos sin lado a propósito.

`cli.py`: `_cmd_build_dataset` captura el `RuntimeError` y lo imprime como
`ERROR:` con salida no-cero, en vez de un traceback de Python.

## Validado

- Caso real reproducido: vídeo sin `video_sides` → `RuntimeError` con el
  mensaje esperado, **sin llegar a crear `medvision.sqlite`** (confirmado
  explícitamente en el test, no solo que lance la excepción).
- Caso normal (todos los vídeos con lado asignado): sin cambios de
  comportamiento, incluido el salto habitual de un vídeo corrupto.

## Nota

Con esto, el flujo correcto (`plan-sessions` antes de `build-dataset`) pasa
de ser "lo que hay que recordar hacer" a ser la única forma de que
`build-dataset` avance más allá del primer segundo si hay vídeos nuevos sin
clasificar. No debería volver a pasar un tercera vez.
