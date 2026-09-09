from __future__ import annotations

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    side TEXT NOT NULL,
    fps REAL NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    frame_count INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    -- 'in_progress' hasta que TERMINA de procesarse sin errores, luego
    -- 'completed'. Permite saltar en la siguiente ejecución los vídeos ya
    -- hechos (ver dataset/builder.py) sin arriesgarse a dar por bueno un
    -- vídeo que se cortó a media detección/OCR por un fallo.
    status TEXT NOT NULL DEFAULT 'in_progress',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    frame_index INTEGER NOT NULL,
    timestamp_seconds REAL NOT NULL,
    image_path TEXT NOT NULL,
    sharpness REAL NOT NULL,
    brightness REAL NOT NULL,
    contrast REAL NOT NULL,
    overexposed_ratio REAL NOT NULL,
    quality_score REAL NOT NULL,
    strip_detected INTEGER NOT NULL DEFAULT 0,
    -- Distancia vertical acumulada (px) respecto al primer frame del vídeo,
    -- estimada por correlación de fase entre frames consecutivos ya
    -- muestreados. Base del emparejamiento por posición física entre lado
    -- pastilla y lado etiqueta (ver docs/cuaderno_ingenieria_3.13.md). NULL
    -- hasta que se calcula (paso aparte tras el muestreo normal).
    cumulative_pan_px REAL,
    UNIQUE(video_id, frame_index)
);

CREATE TABLE IF NOT EXISTS bags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_id INTEGER NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
    bag_index_in_frame INTEGER NOT NULL,
    side TEXT NOT NULL,
    crop_path TEXT NOT NULL,
    y1 INTEGER NOT NULL,
    y2 INTEGER NOT NULL,
    segment_confidence REAL NOT NULL,
    quality_score REAL NOT NULL,
    selected INTEGER NOT NULL DEFAULT 0,
    track_key TEXT,
    track_match_score REAL NOT NULL DEFAULT 0,
    is_track_best INTEGER NOT NULL DEFAULT 0,
    -- Firma de la banda de costura (brillo+tinte azul, ver bags/seam_band.py).
    -- Se calcula para bolsas del lado pastilla, que no tienen texto propio
    -- del que derivar identidad como el lado etiqueta (cabecera OCR).
    seam_prominence REAL,
    seam_position REAL,
    -- Todas las costuras detectadas (JSON, lista de posiciones 0-1),
    -- no solo la primera/más marcada de seam_position -- necesario para
    -- fotos con 3+ bolsitas (2+ costuras). NULL o '[]' si no se detectó
    -- ninguna. Ver docs/cuaderno_ingenieria_3.26.md.
    seam_positions_json TEXT,
    UNIQUE(frame_id, bag_index_in_frame)
);

CREATE TABLE IF NOT EXISTS bag_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    side TEXT NOT NULL,
    track_key TEXT NOT NULL UNIQUE,
    observation_count INTEGER NOT NULL,
    best_bag_id INTEGER REFERENCES bags(id) ON DELETE SET NULL,
    best_quality REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ocr_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bag_id INTEGER NOT NULL REFERENCES bags(id) ON DELETE CASCADE,
    -- Una foto puede contener MÁS DE UNA bolsita completa (grabación
    -- vertical, más resolución a lo largo de la tira — ver
    -- docs/cuaderno_ingenieria_3.2.md). sheet_index distingue cada lectura
    -- lógica dentro de la misma foto; 0 en el caso normal (una bolsita).
    sheet_index INTEGER NOT NULL DEFAULT 0,
    -- 'above'/'below' si esta bolsita se separó de otra en el mismo frame
    -- usando la posición de la costura (3.11); NULL si no aplica (lectura
    -- de una sola bolsita, o costura no detectada). Permite a la app de
    -- revisión sombrear la mitad de la foto que no corresponde a esta
    -- bolsita (ver docs/cuaderno_ingenieria_3.12.md).
    seam_side TEXT,
    raw_text TEXT NOT NULL DEFAULT '',
    normalized_text TEXT NOT NULL DEFAULT '',
    mean_confidence REAL NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    processed_image_path TEXT,
    -- DEPRECADO desde 1.5: una bolsita SPD lista varios fármacos, no uno.
    -- Se mantienen nullable por compatibilidad con bases de datos antiguas,
    -- pero ya no se escriben en registros nuevos. La fuente de verdad es
    -- label_items (uno-a-varios), ver más abajo.
    drug_name TEXT,
    dose_value REAL,
    dose_unit TEXT,
    needs_review INTEGER NOT NULL DEFAULT 1,
    UNIQUE(bag_id, sheet_index)
);

-- Cabecera compartida de una bolsita: paciente, ubicación y momento de toma.
-- Uno-a-uno con ocr_results (una bolsita = una cabecera).
CREATE TABLE IF NOT EXISTS label_headers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ocr_result_id INTEGER NOT NULL UNIQUE REFERENCES ocr_results(id) ON DELETE CASCADE,
    patient_name TEXT,
    patient_location TEXT,
    dose_weekday TEXT,
    dose_date TEXT,
    dose_slot TEXT
);

-- Fármacos individuales listados dentro de una bolsita. Uno-a-varios con
-- ocr_results: esta es la fuente de verdad que sustituye a las columnas
-- singulares deprecadas de arriba.
CREATE TABLE IF NOT EXISTS label_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ocr_result_id INTEGER NOT NULL REFERENCES ocr_results(id) ON DELETE CASCADE,
    line_index INTEGER NOT NULL,
    quantity REAL,
    drug_name TEXT,
    dose_value REAL,
    dose_unit TEXT,
    raw_line TEXT NOT NULL,
    UNIQUE(ocr_result_id, line_index)
);


CREATE TABLE IF NOT EXISTS track_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_key TEXT NOT NULL,
    pill_track_key TEXT,
    label_track_key TEXT,
    pill_best_bag_id INTEGER REFERENCES bags(id) ON DELETE SET NULL,
    label_best_bag_id INTEGER REFERENCES bags(id) ON DELETE SET NULL,
    -- Identificador EXACTO de la lectura (bolsita) representante del lado
    -- etiqueta, ya resuelto por el agrupado. Desde que una foto puede tener
    -- más de una bolsita (3.2, UNIQUE(bag_id, sheet_index) en ocr_results),
    -- volver a buscar por label_best_bag_id a secas es ambiguo -- visto en
    -- datos reales, tanto en el pipeline (arreglado en 3.8) como en la app
    -- de revisión (arreglado aquí, 3.9). Guardarlo directamente evita tener
    -- que adivinar en cualquier sitio que necesite la cabecera/fármacos.
    label_ocr_result_id INTEGER REFERENCES ocr_results(id) ON DELETE SET NULL,
    -- Igual que label_ocr_result_id, pero para el lado pastilla — solo se
    -- rellena cuando se conoce con certeza (emparejamiento directo por
    -- cabecera compartida). Para el emparejamiento por posición o el
    -- mecanismo de respaldo queda NULL: no hay forma fiable de saber qué
    -- lectura concreta corresponde (ver docs/cuaderno_ingenieria_3.18.md).
    pill_ocr_result_id INTEGER REFERENCES ocr_results(id) ON DELETE SET NULL,
    order_index INTEGER NOT NULL,
    match_score REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    -- DEPRECADO desde 1.5, mismo motivo que ocr_results (ver arriba). El
    -- detalle real de fármacos de un par se consulta vía label_ocr_result_id
    -- -> label_items.
    drug_name TEXT,
    dose_value REAL,
    dose_unit TEXT,
    ocr_confidence REAL,
    needs_review INTEGER NOT NULL DEFAULT 1,
    UNIQUE(pair_key, order_index)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    config_path TEXT NOT NULL,
    videos_dir TEXT NOT NULL,
    output_dir TEXT NOT NULL,
    status TEXT NOT NULL,
    summary_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_frames_video ON frames(video_id);
CREATE INDEX IF NOT EXISTS idx_bags_frame ON bags(frame_id);
CREATE INDEX IF NOT EXISTS idx_bags_side ON bags(side);
CREATE INDEX IF NOT EXISTS idx_bags_track ON bags(track_key);
CREATE INDEX IF NOT EXISTS idx_tracks_video ON bag_tracks(video_id);
-- Todas las bolsas (fotos) que contribuyeron a un lado de un par, no solo la
-- representante guardada en track_pairs.pill_best_bag_id/label_best_bag_id.
-- Necesaria porque el agrupado por cabecera/costura fusiona texto de varias
-- vistas parciales (ver header_grouping.py/seam_grouping.py); sin esto, la
-- revisión humana solo veía una foto y podía no mostrar una pastilla o línea
-- que sí contribuyó a la lista fusionada (visto en revisión real, ver
-- docs/cuaderno_ingenieria_3.0.md).
CREATE TABLE IF NOT EXISTS pair_group_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_pair_id INTEGER NOT NULL REFERENCES track_pairs(id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK(side IN ('pill','label')),
    bag_id INTEGER NOT NULL REFERENCES bags(id) ON DELETE CASCADE,
    UNIQUE(track_pair_id, side, bag_id)
);
CREATE INDEX IF NOT EXISTS idx_pair_group_members_pair ON pair_group_members(track_pair_id);

CREATE INDEX IF NOT EXISTS idx_ocr_drug ON ocr_results(drug_name);
CREATE INDEX IF NOT EXISTS idx_pairs_pair_key ON track_pairs(pair_key);
CREATE INDEX IF NOT EXISTS idx_label_items_ocr ON label_items(ocr_result_id);
CREATE INDEX IF NOT EXISTS idx_label_items_drug ON label_items(drug_name);
"""

REVIEW_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pair_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_pair_id INTEGER NOT NULL UNIQUE REFERENCES track_pairs(id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK(decision IN ('accepted','corrected','rejected','pending')),
    -- DEPRECADO desde 1.5: sustituido por pair_review_items (uno-a-varios).
    reviewed_drug_name TEXT,
    reviewed_dose_value REAL,
    reviewed_dose_unit TEXT,
    reviewer_notes TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pair_reviews_decision ON pair_reviews(decision);

-- Lista de fármacos corregida por el humano para un par (bolsita) concreto.
-- Nunca sobrescribe label_items (el OCR crudo): es una capa de corrección
-- aparte, igual que ya se hacía con pair_reviews frente a ocr_results.
CREATE TABLE IF NOT EXISTS pair_review_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_pair_id INTEGER NOT NULL REFERENCES track_pairs(id) ON DELETE CASCADE,
    line_index INTEGER NOT NULL,
    quantity REAL,
    drug_name TEXT,
    dose_value REAL,
    dose_unit TEXT,
    UNIQUE(track_pair_id, line_index)
);
"""
