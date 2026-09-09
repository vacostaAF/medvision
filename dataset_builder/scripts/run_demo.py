from pathlib import Path
from medvision.dataset.builder import build_dataset

ROOT=Path(__file__).resolve().parents[1]
print(build_dataset(Path("videos"),Path("output"),ROOT/"config"/"default.yaml"))
