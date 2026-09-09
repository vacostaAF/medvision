# Cuaderno de ingeniería — Dataset Builder 1.0

## Decisión principal
Se adopta SQLite como fuente de verdad de metadatos, manteniendo archivos de imagen y exportaciones CSV para inspección y compatibilidad.

## Entidades
- `Video`: origen y parámetros de captura.
- `Frame`: instante muestreado y métricas de calidad.
- `Bag`: recorte candidato de una bolsa dentro de un frame.
- `OCRResult`: texto bruto, normalizado y campos estructurados.
- `Run`: ejecución reproducible del pipeline.

## Limitaciones conocidas
- El índice de segmento dentro del frame todavía no equivale a una identidad temporal fiable.
- La asociación anverso/reverso requiere sincronización o una regla de correspondencia adicional.
- El OCR depende de la calidad de captura y necesita revisión cuando la confianza es baja.
- La detección de soldaduras debe sustituirse progresivamente por un detector aprendido o tracking robusto.

## Próximo hito
Implementar `BagTracker` con asociación temporal, consolidación de duplicados y selección del mejor frame por identidad física de bolsa.
