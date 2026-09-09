from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any


def collect_referenced_pill_photos(manifest: list[dict[str, Any]]) -> list[str]:
    """Rutas (`crop_path`) únicas de todas las fotos de pastilla
    referenciadas en un manifiesto exportado por
    `Repository.export_training_dataset()`, en el orden en que aparecen."""
    paths: list[str] = []
    seen: set[str] = set()
    for record in manifest:
        for photo in record.get("pill_photos", []):
            cp = photo.get("crop_path")
            if cp and cp not in seen:
                seen.add(cp)
                paths.append(cp)
    return paths


def package_dataset(
    output_dir: Path, manifest_path: Path, package_dir: Path, make_zip: bool = True,
) -> dict[str, Any]:
    """Copia el manifiesto JSON y todas las fotos de pastilla que
    referencia a una carpeta autocontenida (`package_dir`) — para
    compartir con otro entorno que no tenga acceso directo a `output_dir`
    (p.ej. otra conversación/chat trabajando en un módulo distinto, ver
    docs/cuaderno_ingenieria_3.35.md).

    Solo copia los ficheros REALMENTE referenciados en el manifiesto (no
    la carpeta `output_dir` entera) — con 100+ vídeos procesados,
    `output_dir` puede tener miles de fotos que no forman parte del
    dataset final exportado.

    Las rutas dentro del manifiesto no se tocan: siguen siendo relativas
    (p.ej. `bags/pill_side/MVI_2736/f000230_bag00.jpg`) y funcionan igual
    dentro del paquete porque los ficheros se copian respetando esa misma
    estructura relativa.

    Devuelve un resumen (fotos referenciadas, copiadas, y cuáles no se
    encontraron — no debería pasar en un dataset sano, pero se avisa en
    vez de fallar silenciosamente).
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    crop_paths = collect_referenced_pill_photos(manifest)

    package_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    missing: list[str] = []
    for rel_path in crop_paths:
        src = output_dir / rel_path
        dst = package_dir / rel_path
        if not src.exists():
            missing.append(rel_path)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1

    shutil.copy2(manifest_path, package_dir / manifest_path.name)

    zip_path = None
    if make_zip:
        zip_path = package_dir.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(package_dir.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(package_dir.parent))

    return {
        "referenced_photos": len(crop_paths),
        "copied": copied,
        "missing": missing,
        "package_dir": str(package_dir),
        "zip_path": str(zip_path) if zip_path else None,
    }
