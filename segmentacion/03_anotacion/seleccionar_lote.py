"""
Selección del lote representativo para la primera ronda de anotación.

Criterio: una foto representativa por cada bolsita con foto (220), eligiendo
para cada una la de nº de costuras MEDIANO dentro de sus propias fotos (ni
la más simple ni un caso degenerado) -- así se cubre la variedad real del
dataset sin caer en el sesgo de "solo elijo la más fácil de anotar".
Cuando dos o tres bolsitas comparten una misma foto, anotarla una vez ya
cubre a todas -- así que el nº final de fotos a anotar será <= 220.
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

DATASET_DIR = Path(__file__).parent / "dataset_package"  # ver datos/README.md
MANIFEST = DATASET_DIR / "dataset_final.json"


def normalizar(ruta: str) -> str:
    return ruta.replace("\\", "/")


def cargar_indice_fotos():
    data = json.load(open(MANIFEST, encoding="utf-8"))
    por_foto = defaultdict(list)  # crop_path -> [(pair_key, order_index), ...]
    bolsitas = {}  # (pair_key, order_index) -> registro completo
    for d in data:
        clave = (d["pair_key"], d["order_index"])
        bolsitas[clave] = d
        for p in d["pill_photos"]:
            ruta = normalizar(p["crop_path"])
            por_foto[ruta].append(clave)
    return data, por_foto, bolsitas


def elegir_representante_por_bolsita(data, por_foto):
    """Para cada bolsita, elige la foto de nº de costuras mediano entre
    las suyas propias."""
    representante = {}  # (pair_key, order_index) -> crop_path elegido
    for d in data:
        if not d["pill_photos"]:
            continue
        clave = (d["pair_key"], d["order_index"])
        fotos = [(normalizar(p["crop_path"]), len(p["seam_positions"])) for p in d["pill_photos"]]
        fotos.sort(key=lambda x: x[1])
        n = len(fotos)
        mediana_idx = n // 2  # si hay empate, se queda con la de índice justo en/tras el medio
        representante[clave] = fotos[mediana_idx][0]
    return representante


if __name__ == "__main__":
    data, por_foto, bolsitas = cargar_indice_fotos()
    representante = elegir_representante_por_bolsita(data, por_foto)

    fotos_a_anotar = sorted(set(representante.values()))
    print(f"Bolsitas con foto: {len(representante)}")
    print(f"Fotos únicas a anotar en el lote representativo: {len(fotos_a_anotar)}")

    # cuántas bolsitas quedan cubiertas por cada foto elegida (a través de
    # TODAS sus bolsitas asociadas en el dataset, no solo la que la eligió)
    cobertura = defaultdict(set)
    for clave, ruta in representante.items():
        for otra_clave in por_foto[ruta]:
            cobertura[ruta].add(otra_clave)
    bolsitas_cubiertas = set()
    for ruta in fotos_a_anotar:
        bolsitas_cubiertas |= cobertura[ruta]
    print(f"Bolsitas cubiertas (incluyendo las que comparten foto con otra ya elegida): {len(bolsitas_cubiertas)}")

    # distribución de fármacos y costuras en el lote elegido, para comprobar
    # que sigue siendo representativo de la distribución real
    from collections import Counter
    n_farmacos = Counter(len(bolsitas[c]["label_items"]) for c in representante)
    n_costuras = Counter(len(next(p["seam_positions"] for p in bolsitas[c]["pill_photos"]
                                   if normalizar(p["crop_path"]) == representante[c]))
                          for c in representante)
    print(f"\nDistribución nº fármacos por bolsita en el lote: {dict(sorted(n_farmacos.items()))}")
    print(f"Distribución nº costuras de la foto elegida: {dict(sorted(n_costuras.items()))}")

    # guardar la lista para el siguiente paso (export a Label Studio)
    out = {
        "fotos_a_anotar": fotos_a_anotar,
        "cobertura_por_foto": {r: [f"{pk}::{oi}" for pk, oi in sorted(cobertura[r])] for r in fotos_a_anotar},
    }
    out_path = Path(__file__).parent / "lote_representativo.json"
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nGuardado en {out_path}")
