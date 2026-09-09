import json
import zipfile
from pathlib import Path

import cv2
import numpy as np

from medvision.dataset.packaging import collect_referenced_pill_photos, package_dataset


def _write_fake_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.full((50, 50, 3), 180, dtype=np.uint8))


def test_collect_referenced_pill_photos_dedupes_and_keeps_order():
    manifest = [
        {"pill_photos": [{"crop_path": "a.jpg"}, {"crop_path": "b.jpg"}]},
        {"pill_photos": [{"crop_path": "b.jpg"}, {"crop_path": "c.jpg"}]},  # b.jpg repetida
        {"pill_photos": []},
    ]
    paths = collect_referenced_pill_photos(manifest)
    assert paths == ["a.jpg", "b.jpg", "c.jpg"]  # sin duplicar b.jpg, orden de aparición


def test_package_dataset_copies_referenced_files_and_warns_on_missing(tmp_path):
    """Integración real (3.35): reproduce el escenario exacto -- fotos
    reales en disco, una referenciada que falta a propósito -- confirma
    que se copian las que existen y se avisa de la que falta, sin fallar."""
    output_dir = tmp_path / "output_vertical"
    _write_fake_image(output_dir / "bags/pill_side/MVI_2736/f000230_bag00.jpg")
    _write_fake_image(output_dir / "bags/pill_side/MVI_2736/f000240_bag00.jpg")
    _write_fake_image(output_dir / "bags/pill_side/MVI_2740/f000050_bag00.jpg")

    manifest_path = tmp_path / "dataset_final.json"
    manifest_path.write_text(json.dumps([
        {
            "pair_key": "session_0002", "order_index": 3,
            "pill_photos": [
                {"crop_path": "bags/pill_side/MVI_2736/f000230_bag00.jpg"},
                {"crop_path": "bags/pill_side/MVI_2736/f000240_bag00.jpg"},
            ],
        },
        {
            "pair_key": "session_0003", "order_index": 0,
            "pill_photos": [
                {"crop_path": "bags/pill_side/MVI_2740/f000050_bag00.jpg"},
                {"crop_path": "bags/pill_side/MVI_2740/f000060_bag00.jpg"},  # no existe
            ],
        },
    ]), encoding="utf-8")

    package_dir = tmp_path / "dataset_package"
    summary = package_dataset(output_dir, manifest_path, package_dir, make_zip=True)

    assert summary["referenced_photos"] == 4
    assert summary["copied"] == 3
    assert summary["missing"] == ["bags/pill_side/MVI_2740/f000060_bag00.jpg"]

    # Los ficheros de verdad estan en disco, con la misma estructura relativa
    assert (package_dir / "bags/pill_side/MVI_2736/f000230_bag00.jpg").exists()
    assert (package_dir / "bags/pill_side/MVI_2736/f000240_bag00.jpg").exists()
    assert (package_dir / "bags/pill_side/MVI_2740/f000050_bag00.jpg").exists()
    assert not (package_dir / "bags/pill_side/MVI_2740/f000060_bag00.jpg").exists()

    # El manifiesto se copio dentro del paquete
    assert (package_dir / "dataset_final.json").exists()
    packaged_manifest = json.loads((package_dir / "dataset_final.json").read_text())
    assert len(packaged_manifest) == 2

    # El zip contiene exactamente esos 4 ficheros (3 fotos + manifiesto)
    zip_path = Path(summary["zip_path"])
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert len(names) == 4
    assert any(n.endswith("f000230_bag00.jpg") for n in names)
    assert any(n.endswith("dataset_final.json") for n in names)


def test_package_dataset_no_zip_option(tmp_path):
    output_dir = tmp_path / "output_vertical"
    _write_fake_image(output_dir / "bags/pill_side/MVI_X/f0.jpg")
    manifest_path = tmp_path / "m.json"
    manifest_path.write_text(json.dumps([
        {"pill_photos": [{"crop_path": "bags/pill_side/MVI_X/f0.jpg"}]},
    ]), encoding="utf-8")
    summary = package_dataset(output_dir, manifest_path, tmp_path / "pkg", make_zip=False)
    assert summary["zip_path"] is None
    assert not (tmp_path / "pkg.zip").exists()
