from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass(frozen=True)
class ParsedLabel:
    drug_name: str | None
    dose_value: float | None
    dose_unit: str | None

DOSE_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(MG|G|MCG|UG|µG|ML)\b", re.IGNORECASE)
STOPWORDS = {"COMPRIMIDO","COMPRIMIDOS","CAPSULA","CAPSULAS","CÁPSULA","CÁPSULAS","MG","MCG","UG","ML","VIA","ORAL"}

def parse_label(text: str) -> ParsedLabel:
    normalized = " ".join(text.upper().replace("\n"," ").split())
    match = DOSE_RE.search(normalized)
    value = float(match.group(1).replace(",",".")) if match else None
    unit = match.group(2).upper().replace("µ","U") if match else None
    before = normalized[:match.start()] if match else normalized
    tokens = [re.sub(r"[^A-ZÁÉÍÓÚÜÑ-]", "", t) for t in before.split()]
    tokens = [t for t in tokens if len(t) >= 4 and t not in STOPWORDS]
    drug = " ".join(tokens[-3:]) if tokens else None
    return ParsedLabel(drug_name=drug, dose_value=value, dose_unit=unit)


# ---------------------------------------------------------------------------
# parse_label_sheet: parser de bolsita SPD completa (varios fármacos por
# bolsa + cabecera de paciente/fecha/toma).
#
# parse_label() de arriba asume un único fármaco por texto y se mantiene sin
# tocar (lo usan tests existentes y sigue siendo válido para una lectura
# suelta de una línea). Las bolsitas reales del proyecto (sistema
# personalizado de dosificación, SPD) listan varios fármacos bajo una
# cabecera compartida, así que necesitan un modelo de datos distinto: no es
# un fármaco más "confuso" de extraer, es una estructura distinta.
# ---------------------------------------------------------------------------

QUANTITY_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\b")

# A diferencia de DOSE_RE (arriba, solo abreviaturas), en las bolsitas reales
# la unidad a veces viene escrita en texto completo ("MICROGRAMOS", no "MCG"),
# y a veces truncada/confundida por el propio OCR ("MC" en vez de "MCG",
# "MO" en vez de "MG" -- ambos vistos en datos reales de más de 100 vídeos:
# RISPERIDONA se perdía por "MC", OMEPRAZOL/AMANTADINA por "MO"). Ambos solo
# se aceptan con \b detrás, así que no pueden colarse dentro de "MCG"/"MG".
ITEM_DOSE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?)\s*"
    r"(MG|MCG|MC|MO|UG|µG|ML|UI|G|MICROGRAMOS?|MILIGRAMOS?)\b",
    re.IGNORECASE,
)
UNIT_NORMALIZE = {"UG": "MCG", "µG": "MCG", "MC": "MCG", "MO": "MG",
                  "MICROGRAMO": "MCG", "MICROGRAMOS": "MCG",
                  "MILIGRAMO": "MG", "MILIGRAMOS": "MG"}
FORM_WORDS = {
    "COMPRIMIDO", "COMPRIMIDOS", "CAPSULA", "CAPSULAS", "CÁPSULA", "CÁPSULAS",
    "SOBRE", "SOBRES", "VIAL", "AMPOLLA", "AMPOLLAS", "PARCHE", "PARCHES",
    "BARNIZ", "GOTAS", "SUPOSITORIO", "SUPOSITORIOS", "INHALADOR", "PLUMA",
}
# Prefijos, no palabras exactas: el OCR trunca formas farmacéuticas con
# frecuencia (visto en datos reales: "COMPRIMID" sin la "O" final). Comparar
# por prefijo es más tolerante que la lista exacta de arriba, que se
# mantiene por compatibilidad y para lecturas ya completas.
FORM_WORD_STEMS = (
    "COMPRIMID", "CAPSUL", "SOBRE", "AMPOLL", "PARCHE",
    "BARNIZ", "GOTA", "SUPOSITORI", "INHALADOR", "PLUMA",
)
NOISE_TOKENS = {"Ø", "ø", "O", "·", "•", "■", "□", "-", "—"}
# Se guarda la forma canonica (sin tilde, mayusculas), no el texto crudo: con
# muestreo denso se ha visto el dia pegado a otro texto sin espacio
# ("sábado28/02/26CENA") o compartiendo linea con el nombre del paciente
# ("PELAYO PEINADO JOSEFA domingo 01/03/26..."), lo que rompia la deteccion
# por "primera palabra de la linea". Se busca como subcadena de toda la
# linea, igual que ya se hace con la franja horaria, y "sabado"/"sábado" se
# canonizan a la misma forma para que header_signature() los reconozca como
# la misma bolsita real.
WEEKDAY_CANONICAL = {
    "lunes": "LUNES", "martes": "MARTES", "miercoles": "MIERCOLES", "miércoles": "MIERCOLES",
    "jueves": "JUEVES", "viernes": "VIERNES", "sabado": "SABADO", "sábado": "SABADO",
    "domingo": "DOMINGO",
}
# Sin \b ni al principio ni al final a propósito: con día/franja pegados a
# la fecha sin espacio ("sábado28/02/26CENA", "28/02/26ALMUEI", visto en
# datos reales) no hay límite de palabra en ninguno de los dos lados (letra y
# dígito son ambos \w). El patrón con las barras "/" ya es lo bastante
# distintivo como para no necesitar límites de palabra.
DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})")
SLOT_PREFIXES = ("DESAY", "COMI", "ALMUE", "CEN", "MEDIOD", "NOCHE", "AYUNA", "MERIEN")
# Se guarda la categoria canonica, no el token OCR crudo: con muestreo denso
# se ha visto fecha+franja pegadas sin espacio ("28/02/26ALMUEI",
# "28/02/26DESAYL"), lo que rompia la busqueda por token suelto Y ademas
# distintos frames de la MISMA bolsita truncaban la franja de forma distinta
# ("DESAYL" vs "DESAYU" vs "DESAYUNO"), impidiendo que header_signature() las
# reconociera como la misma bolsita. Canonicalizar aqui arregla ambas cosas
# a la vez, en el origen, en vez de intentar comparacion difusa despues.
SLOT_CANONICAL = {
    "DESAY": "DESAYUNO", "COMI": "COMIDA", "ALMUE": "ALMUERZO",
    "CEN": "CENA", "MEDIOD": "MEDIODIA", "NOCHE": "NOCHE",
    "AYUNA": "AYUNAS", "MERIEN": "MERIENDA",
}


@dataclass(frozen=True)
class LabelItem:
    line_index: int
    raw_line: str
    quantity: float | None
    drug_name: str | None
    dose_value: float | None
    dose_unit: str | None


@dataclass(frozen=True)
class LabelHeader:
    patient_name: str | None = None
    patient_location: str | None = None
    dose_weekday: str | None = None
    dose_date: str | None = None
    dose_slot: str | None = None


@dataclass(frozen=True)
class LabelSheet:
    header: LabelHeader
    items: list[LabelItem]
    # 'above'/'below' si esta bolsita se separó de otra en el mismo frame por
    # posición de costura (ver parse_label_sheets_by_position); None si no
    # aplica (bolsita única, o separada por orden de lectura como antes).
    seam_side: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.items


def _find_weekday(line: str) -> str | None:
    lower = line.lower()
    for raw, canonical in WEEKDAY_CANONICAL.items():
        if raw in lower:
            return canonical
    return None


def _parse_header_line(line: str, header: dict[str, str]) -> None:
    upper_line = line.upper()
    date_match = DATE_RE.search(line)
    weekday = _find_weekday(line)
    if weekday:
        header["dose_weekday"] = weekday
    if date_match:
        header["dose_date"] = date_match.group(1)
    for prefix in SLOT_PREFIXES:
        if prefix in upper_line:
            header["dose_slot"] = SLOT_CANONICAL[prefix]
            break
    if weekday or date_match or header.get("dose_slot"):
        return
    if not re.search(r"[A-ZÁÉÍÓÚÜÑ]{2,}", upper_line):
        # Sin al menos 2 letras seguidas no es un nombre/ubicación real: descarta
        # marcas manuscritas sueltas (p.ej. el "51"/"15" en la esquina de la
        # bolsita, que PaddleOCR también detecta como texto) sin gastar el hueco
        # de patient_name/patient_location con ruido.
        return
    if header.get("patient_name") is None:
        header["patient_name"] = line.strip()
    elif header.get("patient_location") is None:
        header["patient_location"] = line.strip()


def _clean_drug_tokens(tokens: list[str]) -> str | None:
    cleaned = []
    for raw_tok in tokens:
        tok = raw_tok.strip()
        if not tok or tok in NOISE_TOKENS:
            continue
        stripped = re.sub(r"[^A-ZÁÉÍÓÚÜÑ/\-]", "", tok.upper())
        if not stripped or len(stripped) < 2:
            continue
        if stripped in FORM_WORDS or any(stripped.startswith(stem) for stem in FORM_WORD_STEMS):
            continue
        cleaned.append(stripped)
    return " ".join(cleaned) if cleaned else None


def _parse_item_line(line: str, start_index: int) -> list[LabelItem]:
    """Extrae uno o varios fármacos de una línea reconstruida.

    Normalmente una línea trae un solo fármaco. Pero el agrupado por fila de
    label_ocr.py no es perfecto (líneas de fármacos distintos con poco
    espaciado pueden fusionarse en una sola, visto con datos reales — ver
    docs/cuaderno_ingenieria_1.6.md). En vez de quedarnos solo con la primera
    dosis reconocida y perder el resto en silencio, se busca CADA coincidencia
    de dosis en la línea y se genera un item por cada una, usando el texto
    entre dos dosis consecutivas como nombre del siguiente fármaco.
    """
    qty_match = QUANTITY_RE.match(line)
    quantity = float(qty_match.group(1).replace(",", ".")) if qty_match else None
    search_start = qty_match.end() if qty_match else 0

    matches = list(ITEM_DOSE_RE.finditer(line, search_start))
    if not matches:
        # Sin una unidad reconocible (MG/MCG/MICROGRAMOS/...) no lo tratamos
        # como línea de medicación: evita falsos positivos con el pie de la
        # farmacia (teléfono, QR, código) que también puede empezar por dígitos.
        return []

    items: list[LabelItem] = []
    prev_end = search_start
    for offset, dose_match in enumerate(matches):
        dose_unit_raw = dose_match.group(2).upper().replace("µ", "U")
        dose_unit = UNIT_NORMALIZE.get(dose_unit_raw, dose_unit_raw)
        value_str = dose_match.group(1)
        dose_value: float | None
        if "/" in value_str:
            # Dosis compuestas ("20/12,5 MG" en combinaciones como
            # Lisinopril/Hidroclorotiazida): no asumimos cuál de los dos
            # números es el correcto, se deja para revisión humana.
            dose_value = None
        else:
            dose_value = float(value_str.replace(",", "."))

        name_part = line[prev_end:dose_match.start()]
        drug_name = _clean_drug_tokens(name_part.split())
        # La cantidad detectada al inicio de línea solo pertenece, con
        # certeza, al primer fármaco de la línea.
        items.append(LabelItem(
            line_index=start_index + offset, raw_line=line.strip(),
            quantity=quantity if offset == 0 else None,
            drug_name=drug_name, dose_value=dose_value, dose_unit=dose_unit,
        ))
        prev_end = dose_match.end()

    return items


def parse_label_sheets(lines: list[str]) -> list[LabelSheet]:
    """Como parse_label_sheet(), pero reconoce cuando la lectura contiene
    MÁS DE UNA bolsita completa (visto con grabación vertical: al entrar más
    tira en el encuadre, dos bolsitas caben enteras en el mismo frame — ver
    docs/cuaderno_ingenieria_3.2.md) y devuelve una LabelSheet por cada una,
    en vez de fusionarlas bajo la cabecera de la primera.

    Señal de corte: una cabecera nueva (día de la semana reconocido) que
    aparece DESPUÉS de que ya se hayan recogido fármacos en la bolsita
    actual solo puede significar que ha empezado una bolsita distinta — una
    cabecera real no se repite a mitad de su propia lista de fármacos.
    """
    sheets: list[LabelSheet] = []
    header: dict[str, str] = {}
    items: list[LabelItem] = []
    header_done = False
    item_index = 0

    def flush() -> None:
        nonlocal header, items, header_done, item_index
        if header or items:
            sheets.append(LabelSheet(header=LabelHeader(**header), items=items))
        header, items, header_done, item_index = {}, [], False, 0

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if items and _find_weekday(line):
            flush()

        if not header_done:
            if ITEM_DOSE_RE.search(line):
                header_done = True
            else:
                _parse_header_line(line, header)
                continue

        new_items = _parse_item_line(line, item_index)
        items.extend(new_items)
        item_index += len(new_items)

    flush()
    return sheets


def parse_label_sheets_by_position(
    lines_with_y: list[tuple[str, float]], seam_y_norm: float | None
) -> list[LabelSheet]:
    """Como parse_label_sheets(), pero cuando se conoce dónde está la
    costura entre dos bolsitas (posición Y normalizada 0-1, ver
    bags/seam_band.py), la usa para decidir a qué bolsita pertenece cada
    línea — en vez de fiarlo solo al orden en que el OCR entregó las líneas.

    Motivación (caso real, ver docs/cuaderno_ingenieria_3.11.md): cuando dos
    bolsitas están muy pegadas en el mismo frame, el texto cerca de la
    costura puede salir torcido y el OCR lo entrega en un orden que no es el
    físico real — parse_label_sheets() (basado solo en orden de lectura)
    puede entonces asignar líneas de una bolsita a la otra. La posición Y de
    cada línea, en cambio, no depende del orden de lectura del OCR: una
    línea impresa por encima de la costura está por encima, aunque el OCR la
    entregue después de la cabecera de la bolsita de abajo.

    Solo cubre el caso de 2 bolsitas (una costura) — `detect_seam_band()`
    encuentra como mucho una costura por foto; con 3+ bolsitas en un mismo
    frame, se cae a `parse_label_sheets()` (basado en orden), sin partir por
    posición.

    Si `seam_y_norm` es None, o no hay líneas por encima Y por debajo de esa
    posición (no hay realmente una segunda bolsita en esta lectura), se
    comporta exactamente igual que `parse_label_sheets()`.
    """
    if seam_y_norm is None:
        return parse_label_sheets([line for line, _ in lines_with_y])

    above = [line for line, y in lines_with_y if y < seam_y_norm]
    below = [line for line, y in lines_with_y if y >= seam_y_norm]
    if not above or not below:
        # No hay líneas a ambos lados: no hay una segunda bolsita real en
        # esta lectura pese a haber costura visible (p.ej. el resto de la
        # bolsita vecina cae fuera del encuadre). Camino normal.
        return parse_label_sheets([line for line, _ in lines_with_y])

    # Cada lado se parsea de forma INDEPENDIENTE, con su propio orden de
    # lectura relativo (que dentro de un mismo lado de la costura sí es de
    # fiar) — así ninguna línea de un lado puede colarse en el otro.
    above_sheets = [
        LabelSheet(header=s.header, items=s.items, seam_side="above") for s in parse_label_sheets(above)
    ]
    below_sheets = [
        LabelSheet(header=s.header, items=s.items, seam_side="below") for s in parse_label_sheets(below)
    ]
    return above_sheets + below_sheets


FOOTER_KEYWORDS = ("FARMACIA", "FARMAOIA", "FARMAGIA", "FARMA")  # variantes reales de OCR encontradas


def find_complete_pouch_boundaries(
    lines_with_y: list[tuple[str, float]], name_margin: float = 0.05,
    footer_keywords: tuple[str, ...] = FOOTER_KEYWORDS,
) -> list[tuple[float, float, str]]:
    """Encuentra los límites (inicio, fin, firma) de cada bolsita COMPLETA
    visible en una lectura — es decir, con las dos fronteras dentro del
    mismo fotograma. Descarta a propósito cualquier fragmento de bolsita
    que quede cortado por el borde del propio fotograma (su cabecera
    visible pero sin llegar a su pie, o su pie visible sin haber visto su
    cabecera) — el borde del fotograma NO es una frontera real de
    bolsita, es solo dónde empieza a grabar la cámara en ese instante
    concreto; tratarlo como frontera mezclaba la cola de una bolsita con
    la siguiente completa (caso real encontrado por el usuario, ver
    docs/cuaderno_ingenieria_3.37.md). Los fragmentos descartados se
    recuperan solos en un fotograma vecino que sí los contenga completos.

    El inicio se ancla en la línea de día de la semana (`_find_weekday`,
    ya validada en todo el proyecto para la cabecera) menos un margen
    fijo hacia arriba, para incluir también el nombre del paciente que la
    precede. El fin se ancla en la primera línea de pie de farmacia
    posterior a ese inicio.

    La `firma` devuelta (día+fecha+franja, normalizada) identifica a la
    bolsita real independientemente del fotograma — con un paneo lento
    respecto al paso de muestreo, la MISMA bolsita real aparece completa
    en muchos fotogramas seguidos (caso real, ver
    docs/cuaderno_ingenieria_3.40.md); esta firma es lo que permite
    deduplicar sin volver a correr el OCR ni comparar imágenes.
    """
    import re
    from medvision.pairing.header_grouping import header_signature

    all_lines = sorted(lines_with_y, key=lambda t: t[1])
    weekday_lines = [(y, line) for line, y in lines_with_y if _find_weekday(line)]
    weekday_lines.sort()
    footer_positions = sorted(find_footer_positions(lines_with_y, footer_keywords))

    boundaries = []
    for start_y, weekday_line in weekday_lines:
        candidates = [f for f in footer_positions if f > start_y]
        if not candidates:
            continue  # bolsita cortada por el borde inferior: se descarta, no completa
        footer_y = min(candidates)
        # El pie de página real tiene varias líneas más debajo de "FARMACIA
        # ..." (web, teléfono, código) que no llevan la palabra clave y por
        # tanto no forman parte de footer_positions -- si el fin se ancla
        # solo en esa primera línea, el margen en píxeles tiene que cubrir
        # todo ese bloque además del QR, y nunca es suficiente por mucho
        # que se suba (visto real con el usuario, ver
        # docs/cuaderno_ingenieria_3.44.md). Se extiende hasta la última
        # línea de texto cercana (mismo criterio de cercanía que
        # group_footer_positions), sea cual sea su contenido -- el próximo
        # día de la semana ya marca dónde empieza la SIGUIENTE bolsita, así
        # que no hay riesgo de extenderse de más hacia ella.
        next_weekday_y = min((y for y, _ in weekday_lines if y > footer_y), default=1.0)
        next_start_limit = max(footer_y, next_weekday_y - name_margin)
        end_y = footer_y
        for _line, y in all_lines:
            if footer_y <= y < next_start_limit and y - end_y <= 0.08:
                end_y = y
        # Firma por fecha+franja CANONICALIZADAS (reutiliza header_signature(),
        # ya validada en todo el proyecto contra el mismo problema real: el
        # texto crudo de un mismo fotograma a otro varía lo suficiente
        # -espacios, un carácter distinto- como para que comparar cadenas
        # exactas deje pasar la misma bolsita como si fueran dos distintas
        # -caso real encontrado por el usuario, ver
        # docs/cuaderno_ingenieria_3.42.md-. Si no se puede extraer fecha+
        # franja de esta línea concreta, se usa el texto crudo como
        # respaldo -- peor que la firma canónica, pero mejor que no poder
        # deduplicar en absoluto.
        header: dict[str, str] = {}
        date_match = DATE_RE.search(weekday_line)
        if date_match:
            header["dose_date"] = date_match.group(1)
        upper_line = weekday_line.upper()
        for prefix in SLOT_PREFIXES:
            if prefix in upper_line:
                header["dose_slot"] = SLOT_CANONICAL[prefix]
                break
        sig = header_signature(header)
        signature = "|".join(sig) if sig else re.sub(r"\s+", " ", weekday_line.strip().upper())
        boundaries.append((max(0.0, start_y - name_margin), end_y, signature))
    return boundaries


def find_footer_positions(lines_with_y: list[tuple[str, float]], footer_keywords: tuple[str, ...] = FOOTER_KEYWORDS) -> list[float]:
    """Encuentra las posiciones Y (normalizadas 0-1) de cada línea que
    contiene el pie de farmacia ("FARMACIA MARACENA...") — un texto fijo
    que se repite al final de CADA bolsita, a diferencia de la cabecera
    (que cambia de una bolsita a otra). Sirve como punto de corte por
    CONTENIDO en vez de por señal visual de costura (menos fiable, ver
    docs/cuaderno_ingenieria_3.26.md: 93% de inconsistencia entre fotos de
    una misma bolsita).

    Pensado para generar imágenes de una sola bolsita a partir de un vídeo
    de validación nunca visto por el sistema (ver
    docs/cuaderno_ingenieria_3.36.md) — no forma parte del pipeline
    principal de construcción del dataset.

    Devuelve las posiciones ordenadas de menor a mayor. Puede haber más de
    una línea del pie por bolsita (dirección web, teléfono, código de
    registro en líneas separadas) — se devuelven TODAS las coincidencias,
    no una por bolsita; agruparlas en una sola posición por bolsita es
    responsabilidad de quien llame (ver `group_footer_positions`).
    """
    positions = []
    for line, y in lines_with_y:
        upper = line.upper()
        if any(kw in upper for kw in footer_keywords):
            positions.append(y)
    return sorted(positions)


def group_footer_positions(positions: list[float], min_gap: float = 0.08) -> list[float]:
    """Agrupa posiciones de pie de página muy cercanas entre sí (varias
    líneas del mismo pie: web, teléfono, código) en una sola posición por
    bolsita — la media del grupo. `min_gap`: distancia mínima (fracción de
    la altura total) para considerar dos posiciones como pies de PÁGINAS
    DISTINTAS en vez de líneas del mismo pie.
    """
    if not positions:
        return []
    sorted_pos = sorted(positions)
    groups: list[list[float]] = [[sorted_pos[0]]]
    for p in sorted_pos[1:]:
        if p - groups[-1][-1] <= min_gap:
            groups[-1].append(p)
        else:
            groups.append([p])
    return [sum(g) / len(g) for g in groups]


def parse_label_sheets_by_multi_position(
    lines_with_y: list[tuple[str, float]], seam_positions: list[float]
) -> list[LabelSheet]:
    """Generalización de parse_label_sheets_by_position() para 2 o más
    costuras (3+ bolsitas en el mismo frame) — la versión de una sola
    costura solo separa en 2 tramos; con 3+ bolsitas, todo lo que cae al
    tramo "más grande" seguía repartiéndose por orden de lectura, con el
    mismo bug de siempre escondido dentro de ese tramo (caso real
    encontrado revisando el dataset: 433 de 734 pares lo tocaban, ver
    docs/cuaderno_ingenieria_3.26.md).

    `seam_positions`: posiciones Y normalizadas de TODAS las costuras
    detectadas en la foto (ver `bags/seam_band.py::detect_seam_bands()`),
    en cualquier orden. Se ordenan aquí. N costuras dan N+1 tramos.

    Cada bolsita resultante se marca con `seam_side` = `"segment_{i}"`
    (i=0 arriba del todo), salvo el caso de una sola costura (2 tramos),
    donde se mantiene `"above"/"below"` por compatibilidad con el
    sombreado ya existente en la app de revisión.

    Si no hay ninguna costura, o algún tramo se queda sin líneas (no hay
    de verdad tantas bolsitas como costuras+1 en esta lectura concreta),
    cae a `parse_label_sheets()` normal, igual que la versión de una sola
    costura.
    """
    if not seam_positions:
        return parse_label_sheets([line for line, _ in lines_with_y])

    sorted_seams = sorted(seam_positions)
    boundaries = [0.0] + sorted_seams + [1.0]
    segments: list[list[str]] = [[] for _ in range(len(boundaries) - 1)]
    for line, y in lines_with_y:
        for i in range(len(boundaries) - 1):
            lo, hi = boundaries[i], boundaries[i + 1]
            is_last = i == len(boundaries) - 2
            if lo <= y < hi or (is_last and y >= lo):
                segments[i].append(line)
                break

    if any(not seg for seg in segments):
        # Algún tramo se quedó sin líneas: no hay de verdad tantas bolsitas
        # distintas en esta lectura concreta pese a ver esa costura (p.ej.
        # el resto de una bolsita vecina cae fuera del encuadre). Camino
        # normal, sin partir.
        return parse_label_sheets([line for line, _ in lines_with_y])

    result: list[LabelSheet] = []
    use_above_below = len(segments) == 2  # 1 costura: mantiene el nombrado ya existente
    for i, seg_lines in enumerate(segments):
        side_label = ("above" if i == 0 else "below") if use_above_below else f"segment_{i}"
        for s in parse_label_sheets(seg_lines):
            result.append(LabelSheet(header=s.header, items=s.items, seam_side=side_label))
    return result


def parse_label_sheet(lines: list[str]) -> LabelSheet:
    """Compatibilidad hacia atrás: la primera bolsita reconocida, o una
    vacía si no hay ninguna. Preferir parse_label_sheets() en código nuevo —
    una lectura real puede contener más de una bolsita (ver arriba)."""
    sheets = parse_label_sheets(lines)
    return sheets[0] if sheets else LabelSheet(header=LabelHeader(), items=[])
