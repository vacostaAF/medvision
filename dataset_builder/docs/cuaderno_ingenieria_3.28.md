# Cuaderno de ingeniería 3.28

## Motivación

Tras varias horas de `--fresh` real sobre los 104 vídeos (confirmado por
el usuario: ~24s/frame, la parte más lenta y cara del pipeline), la
ejecución falló en el ÚLTIMO paso (`_build_pairs()`), con:

```
ValueError: could not convert string to float: b'\xfe\x976A'
```

## Diagnóstico

`bags/seam_band.py::detect_seam_bands()` (nueva en 3.26) calculaba
`prominence = combined[i] / median_val` sin convertir explícitamente a
`float()` nativo de Python — `combined[i]` es un escalar de **numpy**
(`numpy.float32`), no un `float` normal, porque viene de un array de
numpy. `sqlite3` (el driver estándar de Python) no reconoce
`numpy.float32` como uno de sus tipos soportados y, en vez de fallar al
guardar, lo serializa como `BLOB` (bytes crudos) — el guardado "funciona"
sin avisar de nada raro, pero cualquier lectura posterior que intente
`float()` sobre ese valor revienta con exactamente el error visto.

**Por qué afectó también al lado pastilla**, aunque el cambio de 3.26 fue
pensado para el lado etiqueta: la detección de costura ORIGINAL del lado
pastilla (2.4-2.5, en el momento de crear la bolsa) usaba
`detect_seam_band()` (singular) — esa función siempre convirtió bien
(`float(combined[peak_row])`), nunca tuvo el bug. Pero 3.26 añadió una
SEGUNDA llamada a `update_bag_seam()` en el momento del OCR (para poder
guardar la costura de CUALQUIER lado que pase por ahí) — esa segunda
llamada SOBRESCRIBE el valor correcto inicial con el de
`detect_seam_bands()` (plural, con el bug), corrompiendo el dato aunque
el primer guardado hubiera sido perfecto.

## Arreglo

Una línea: `prominence = float(combined[i]) / median_val` — conversión
explícita a `float()` nativo antes de cualquier operación posterior,
igual que ya hacía la función original de una sola costura.

## Validado

- Reproducido el bug deliberadamente y en aislado: guardar un
  `numpy.float32` sin convertir en SQLite y releerlo da exactamente el
  mismo patrón de error que el real (`could not convert string to float:
  b'...'`) — confirma que el diagnóstico es correcto antes de dar por
  buena la explicación.
- Confirmado que `detect_seam_bands()` ya devuelve `float` nativo en
  ambos valores (posición y prominencia) — comprobado con `type() is
  float`, no solo `isinstance` (numpy scalars pasan `isinstance(x,
  float)` como `False` de todas formas, pero se comprobó explícito para
  no dejar dudas).
- **Prueba de integración con SQLite real**: el mismo camino exacto que
  reventó en producción — detectar con imagen sintética, guardar con
  `update_bag_seam()`, releer con `get_pill_observations_for_video()`, y
  convertir con `float()` (lo que hace `group_pill_bags_by_seam()` de
  verdad) — sin ningún error.
- Suite completa: 101 tests, todos en verde.

## Sobre lo ya procesado

La parte cara (detección + OCR de los 104 vídeos) debería haberse
guardado correctamente ANTES del fallo — el error salta en el paso final
de emparejamiento, no durante el procesado por vídeo. No hace falta
repetir el `--fresh`; con el código corregido debería bastar con
`rebuild-pairs` para completar lo que quedó a medias, reutilizando todo
el trabajo ya hecho.

## Lección

Cualquier valor que salga de un array de numpy (`combined[i]`, `np.median(...)`,
etc.) y vaya a parar a una escritura en SQLite debe convertirse
explícitamente con `float()`/`int()` antes de guardarse — numpy no
siempre lanza un error visible al pasar por sqlite3, a veces se serializa
en silencio como BLOB, y el fallo solo aparece más tarde, al intentar
usar ese dato — en este caso, horas después y al final de una ejecución
completa.
