# Cuaderno de ingeniería 1.3

Se incorpora revisión humana (*human-in-the-loop*) de pares anverso–reverso.

## Decisiones
- Ninguna asociación de baja confianza entra directamente al dataset final.
- Las decisiones se guardan en SQLite, sin sobrescribir el OCR original.
- Estados: aceptada, corregida, rechazada y pendiente.
- La corrección puede modificar medicamento, dosis y unidad.

## Ejecución
```bash
pip install -r requirements.txt
streamlit run app/review_app.py
```
La aplicación solicita la ruta de `medvision.sqlite` en la barra lateral.
