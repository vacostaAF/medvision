"""
Fine-tuning de YOLO11-seg sobre las 216 fotos anotadas.

Requiere GPU para ser viable en tiempo razonable -- en CPU, con un
dataset así de pequeño, podría llegar a funcionar pero muy lentamente
(no recomendado, ya lo comprobamos con FastSAM: ~17s solo de inferencia
por imagen en CPU, entrenar es bastante más caro que inferir).

Uso:
    python entrenar.py

Antes de lanzarlo: correr coco_a_yolo.py primero (genera yolo_dataset/
y data.yaml, que es lo que este script consume).
"""
from pathlib import Path
from ultralytics import YOLO

DATA_YAML = Path(__file__).parent / "yolo_dataset" / "data.yaml"

# Empezamos desde un checkpoint YOLO11-seg preentrenado en COCO (objetos
# genéricos), no desde cero -- con 216 imágenes, entrenar desde cero no
# daría buen resultado; fine-tuning sobre pesos ya entrenados en millones
# de imágenes generales sí es viable con un dataset de este tamaño.
MODELO_BASE = "yolo11n-seg.pt"  # 'n' = nano, el más rápido; si tienes GPU
                                  # potente y quieres más precisión, probar
                                  # 'yolo11s-seg.pt' o 'yolo11m-seg.pt'

EPOCHS = 100
IMGSZ = 960          # las fotos son verticales y bastante grandes; no bajar
                      # demasiado o se pierden pastillas pequeñas
BATCH = 8            # bajar si da error de memoria de GPU (4, 2...)
PATIENCE = 20        # early stopping si no mejora en 20 épocas seguidas


def main():
    model = YOLO(MODELO_BASE)
    model.train(
        data=str(DATA_YAML),
        epochs=EPOCHS,
        imgsz=IMGSZ,
        batch=BATCH,
        patience=PATIENCE,
        project="runs_medvision",
        name="pastillas_seg_v1",
        # Aumentado de datos moderado -- las fotos ya tienen bastante
        # variedad real (ángulo, iluminación), no hace falta forzarlo mucho
        degrees=15,
        fliplr=0.5,
        flipud=0.0,     # las bolsitas tienen una orientación con sentido
                         # (arriba/abajo), no volteamos verticalmente
    )
    print("\nEntrenamiento terminado.")
    print("Pesos del mejor modelo en: runs_medvision/pastillas_seg_v1/weights/best.pt")
    print("Revisa también runs_medvision/pastillas_seg_v1/ -- gráficas de")
    print("pérdida, matriz de confusión y ejemplos de validación con máscaras.")


if __name__ == "__main__":
    main()
