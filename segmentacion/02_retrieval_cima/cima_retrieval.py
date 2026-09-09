"""
Prototipo — banco de apariencias visuales por bolsita, vía CIMA (AEMPS).

Idea: para cada bolsita ya sabemos, por `label_items` (OCR de la etiqueta),
la lista corta de fármacos que contiene. Este módulo NO clasifica pastillas
todavía -- solo construye, para esa lista corta, el "banco de candidatos"
con la apariencia oficial de cada presentación posible (forma, color,
tamaño, grabado, y foto de la forma farmacéutica cuando exista). Ese banco
es la entrada de la siguiente pieza (comparar cada máscara segmentada
contra estos candidatos), que todavía no se ha construido -- deliberado,
para no acoplar ambos problemas antes de tener el primero validado.

Notas de diseño, por lo aprendido en los spikes anteriores:
  - Un mismo fármaco+dosis puede tener MUCHOS fabricantes con apariencia
    distinta (visto con Omeprazol 20mg: amarillo liso, azul/blanco,
    blanco/blanco "OM"/"20", rosa/marrón...). Por eso `buscar_presentaciones`
    devuelve TODAS las presentaciones comercializadas que matchean el
    nombre, no una sola -- la desambiguación por fabricante concreto es
    responsabilidad de la siguiente pieza (retrieval contra la foto real),
    no de esta.
  - La foto (`fotos.formafarmac`) es voluntaria y su cobertura es parcial.
    La descripción textual de la sección "FORMA FARMACÉUTICA" de la ficha
    técnica es obligatoria por ley y mucho más fiable -- se trata como la
    fuente primaria; la foto es un extra cuando existe.
  - La API de CIMA es pública y no requiere API key.

Requiere: `pip install requests`
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import requests

CIMA_BASE = "https://cima.aemps.es/cima/rest"
TIMEOUT = 10
PAUSE_BETWEEN_REQUESTS = 0.2  # cortesía con la API pública, sin justificación de rate limit oficial


@dataclass
class Apariencia:
    nregistro: str
    nombre: str
    laboratorio: str | None
    forma_farmaceutica: str | None
    descripcion_apariencia: str | None  # texto libre de la sección 3 de la ficha técnica
    foto_formafarmac: str | None
    comercializado: bool


def _limpiar_html(texto: str) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    return re.sub(r"\s+", " ", texto).strip()


def buscar_presentaciones(nombre_o_principio_activo: str, dosis: str | None = None,
                           solo_comercializados: bool = True) -> list[dict]:
    """Busca medicamentos por nombre (genérico o comercial) Y por principio
    activo (`practiv1`), y combina ambos.

    Por qué las dos: `nombre` encuentra bien los genéricos (que siguen el
    patrón "PrincipioActivo Laboratorio Dosis", ej. "Omeprazol Mabo 20mg"),
    pero se le escapan los medicamentos de marca cuyo nombre comercial no
    contiene el principio activo -- ej. "Hidroaltesona" es hidrocortisona
    oral, pero buscar "Hidrocortisona" por `nombre` nunca lo encuentra.
    `practiv1` busca sobre el campo de principio activo registrado, no
    sobre el nombre comercial, así que sí lo encuentra.
    """
    nombre_norm = nombre_o_principio_activo.strip().upper()

    def _consultar(param: str) -> list[dict]:
        time.sleep(PAUSE_BETWEEN_REQUESTS)
        params = {param: nombre_o_principio_activo}
        if solo_comercializados:
            params["comerc"] = 1
        r = requests.get(f"{CIMA_BASE}/medicamentos", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("resultados", [])

    combinados: dict[str, dict] = {}

    # Resultados por `nombre`: CIMA matchea por subcadena, no por prefijo
    # ("Omeprazol" también matchea "Esomeprazol"), así que aquí sí filtramos
    # a los que EMPIEZAN por el nombre buscado.
    try:
        res_nombre = _consultar("nombre")
        for m in res_nombre:
            if m.get("nombre", "").upper().startswith(nombre_norm):
                combinados[m["nregistro"]] = m
    except requests.RequestException as e:
        res_nombre = []
        print(f"  aviso: fallo buscando por nombre='{nombre_o_principio_activo}': {e}")

    # Resultados por `practiv1` (principio activo): aquí NO filtramos por
    # startswith sobre el nombre comercial -- ese es justo el caso que
    # buscamos rescatar (ej. "Hidroaltesona" no empieza por "Hidrocortisona"
    # pero su principio activo registrado sí es hidrocortisona).
    try:
        res_practiv1 = _consultar("practiv1")
        for m in res_practiv1:
            combinados[m["nregistro"]] = m
    except requests.RequestException as e:
        res_practiv1 = []
        print(f"  aviso: fallo buscando por practiv1='{nombre_o_principio_activo}': {e}")

    print(f"  [debug] {nombre_o_principio_activo}: nombre={len(res_nombre)} bruto "
          f"({sum(1 for m in res_nombre if m.get('nombre','').upper().startswith(nombre_norm))} tras filtro), "
          f"practiv1={len(res_practiv1)} bruto, combinados={len(combinados)}")

    resultados = list(combinados.values())
    if dosis:
        dosis_norm = dosis.lower().replace(" ", "")
        resultados = [m for m in resultados
                      if dosis_norm in (m.get("nombre", "").lower().replace(" ", ""))] or resultados
    return resultados


def obtener_apariencia(nregistro: str) -> Apariencia:
    """Descarga ficha del medicamento (foto) + ficha técnica completa en HTML
    (descripción de forma farmacéutica, sección 3)."""
    r = requests.get(f"{CIMA_BASE}/medicamento", params={"nregistro": nregistro}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()

    foto = next((f["url"] for f in data.get("fotos", []) if f.get("tipo") == "formafarmac"), None)

    descripcion = None
    doc_ft = next((d for d in data.get("docs", []) if d.get("tipo") == 1), None)  # tipo 1 = Ficha Técnica
    if doc_ft and doc_ft.get("urlHtml"):
        html = requests.get(doc_ft["urlHtml"], timeout=TIMEOUT).text
        # La sección 3 ("FORMA FARMACÉUTICA") suele empezar tras un encabezado
        # "3. FORMA FARMACÉUTICA" y terminar en el siguiente "4. ...".
        m = re.search(r"3\.\s*FORMA FARMAC[ÉE]UTICA(.*?)4\.\s*DATOS CL[ÍI]NICOS",
                       html, re.IGNORECASE | re.DOTALL)
        if m:
            descripcion = _limpiar_html(m.group(1))[:600]

    return Apariencia(
        nregistro=nregistro,
        nombre=data.get("nombre"),
        laboratorio=data.get("labtitular"),
        forma_farmaceutica=(data.get("formaFarmaceutica") or {}).get("nombre"),
        descripcion_apariencia=descripcion,
        foto_formafarmac=foto,
        comercializado=bool(data.get("comerc")),
    )


def banco_visual_para_bolsita(farmacos: list[dict], max_por_farmaco: int = 8) -> dict[str, list[Apariencia]]:
    """farmacos: [{'nombre': 'Omeprazol', 'dosis': '20 mg'}, ...] -- tal como
    vendría, en principio, de `label_items` para una bolsita concreta.
    Devuelve, por nombre de fármaco, la lista de apariencias candidatas."""
    banco: dict[str, list[Apariencia]] = {}
    for f in farmacos:
        nombre, dosis = f["nombre"], f.get("dosis")
        presentaciones = buscar_presentaciones(nombre, dosis)[:max_por_farmaco]
        apariencias = []
        for p in presentaciones:
            time.sleep(PAUSE_BETWEEN_REQUESTS)
            try:
                apariencias.append(obtener_apariencia(p["nregistro"]))
            except requests.RequestException as e:
                print(f"  aviso: fallo consultando nregistro={p['nregistro']} ({nombre}): {e}")
        banco[nombre] = apariencias
    return banco


if __name__ == "__main__":
    # Ejemplo real: la bolsita de session_0002 (caso 3.19), miércoles 11/03/26
    # -- Levotiroxina 100 microgramos + Omeprazol 20 mg.
    farmacos_bolsita = [
        {"nombre": "Levotiroxina", "dosis": "100 microgramos"},
        {"nombre": "Omeprazol", "dosis": "20 mg"},
    ]
    banco = banco_visual_para_bolsita(farmacos_bolsita)
    for nombre, apariencias in banco.items():
        print(f"\n=== {nombre} ({len(apariencias)} presentaciones) ===")
        for a in apariencias:
            print(f"- {a.nombre} [{a.laboratorio}]")
            print(f"  {a.descripcion_apariencia}")
            print(f"  foto: {a.foto_formafarmac}")
