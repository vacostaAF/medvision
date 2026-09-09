from __future__ import annotations
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from medvision.database.repository import Repository

st.set_page_config(page_title='MedVision AI · Revisión', layout='wide')

# Tras guardar una revisión, sube la página al principio -- sin esto, cada
# guardado dejaba al usuario abajo del todo, con cientos de bolsitas por
# revisar era insostenible (ver docs/cuaderno_ingenieria_3.23.md). Es un
# truco a base de JavaScript, no una función oficial de Streamlit -- puede
# dejar de funcionar si cambia la estructura interna en una versión futura;
# si deja de subir la pantalla, no es grave, solo hay que hacer scroll a
# mano como antes.
if st.session_state.pop('scroll_to_top', False):
    components.html(
        "<script>window.parent.document.querySelector('section.main').scrollTo(0, 0);</script>",
        height=0,
    )

st.title('MedVision AI · Revisión supervisada')
st.caption(
    'Valida la lista de fármacos de cada bolsita frente a la foto antes de que entre '
    'en el dataset de entrenamiento. Cada bolsita puede listar varios medicamentos: '
    'revisa la tabla completa, no solo el primero.'
)


def resolve_image(path_value: str | None, db_path: Path) -> Path | None:
    if not path_value:
        return None
    p = Path(path_value)
    candidates = [p, db_path.parent / p, ROOT / p]
    for c in candidates:
        if c.exists():
            return c
    return None


def render_with_seam(
    image_path: Path, seam_positions: list[float] | None, seam_side: str | None
) -> np.ndarray | str:
    """Si se conocen las costuras de esta foto (3.11/3.12/3.26), dibuja una
    línea en CADA una. Si además se sabe qué tramo corresponde a la
    bolsita que se revisa (emparejamiento directo), atenúa todo lo que
    quede fuera de ese tramo. `seam_side` puede ser `"above"/"below"`
    (caso de 1 sola costura, compatibilidad con versiones anteriores) o
    `"segment_N"` (2+ costuras, 3+ bolsitas en la foto — ver
    docs/cuaderno_ingenieria_3.26.md). Si se detectaron costuras pero NO
    se sabe el tramo, se dibujan las líneas SIN atenuar nada: mejor marcar
    "aquí hay fronteras, decide tú" que no marcar nada. Sin ninguna
    costura, devuelve la ruta tal cual.
    """
    if not seam_positions:
        return str(image_path)
    img = cv2.imread(str(image_path))
    if img is None:
        return str(image_path)
    h, w = img.shape[:2]
    sorted_positions = sorted(seam_positions)
    seam_rows = [int(p * h) for p in sorted_positions]
    out = img.copy()

    if seam_side is not None:
        if seam_side == "above":
            lo, hi = 0, seam_rows[0] if seam_rows else h
        elif seam_side == "below":
            lo, hi = (seam_rows[-1] if seam_rows else 0), h
        elif seam_side.startswith("segment_"):
            idx = int(seam_side.split("_", 1)[1])
            boundaries = [0] + seam_rows + [h]
            lo, hi = (boundaries[idx], boundaries[idx + 1]) if 0 <= idx < len(boundaries) - 1 else (0, h)
        else:
            lo, hi = 0, h
        if (lo, hi) != (0, h):
            dim = out.copy()
            dim[:] = (dim.astype(np.float32) * 0.35).astype(np.uint8)  # atenuar
            out[:lo, :] = dim[:lo, :]
            out[hi:, :] = dim[hi:, :]

    for seam_row in seam_rows:
        cv2.line(out, (0, seam_row), (w, seam_row), (0, 220, 255), max(2, h // 250))
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


raw_db = st.sidebar.text_input('Base SQLite', value='output_vertical/medvision.sqlite')
db_path = Path(raw_db).expanduser().resolve()
filter_name = st.sidebar.selectbox('Decisión', ['pending', 'all', 'accepted', 'corrected', 'rejected'])
status_name = st.sidebar.selectbox(
    'Estado del pipeline',
    ['all', 'paired', 'position_matched', 'review', 'unmatched_label', 'unmatched_pill'],
    help=(
        "'paired' = coincidencia directa por cabecera, ya verificada por contenido. "
        "'position_matched' = emparejado por posición física en la tira (misma distancia "
        "relativa de paneo en los dos vídeos) — no verificado por contenido, revisar. "
        "'unmatched_label' = lista de fármacos sin foto emparejada, aquí es donde más "
        "hace falta ojo humano. 'review' = emparejamiento del mecanismo de respaldo, sin certeza."
    ),
)
use_sample = st.sidebar.checkbox(
    'Muestra aleatoria', value=False,
    help='Para revisar solo una parte (p.ej. de los "paired", donde no hace falta mirar cada uno).',
)
sample_size = st.sidebar.number_input('Tamaño de la muestra', min_value=1, value=25, step=5) if use_sample else None
hide_empty = st.sidebar.checkbox(
    'Ocultar lecturas sin ningún fármaco', value=True,
    help=(
        'Ruido de OCR (un trozo de pie de farmacia o de código QR mal leído como si fuera '
        'una cabecera) — no hay nada que revisar ahí. Con datos reales, más de la mitad de '
        'los pares "pendientes de revisión" no tenían ningún fármaco. Desmarcar solo para '
        'depurar el propio pipeline, no para el trabajo normal de revisión.'
    ),
)
quick_mode = st.sidebar.checkbox(
    'Vista rápida (sin foto de pastilla)', value=False,
    help=(
        'Para los pares sin foto de pastilla (asociación 0.00): esa foto no existe, así '
        'que no se consulta ni se muestra. La foto de la ETIQUETA sí se sigue mostrando '
        '— es contra la que hay que comparar el texto para comprobar que el OCR leyó '
        'bien. Con esta casilla se ahorra la consulta inútil del lado pastilla, nada más.'
    ),
)
narrow_mode = st.sidebar.checkbox(
    'Pantalla estrecha (apilar en vez de 4 columnas)', value=False,
    help=(
        'Streamlit no puede saber el ancho real del navegador — si las 4 columnas '
        '(pastilla / etiqueta / estado / revisión) salen demasiado apretadas, marca '
        'esta casilla para volver a un diseño apilado, más cómodo en pantallas estrechas.'
    ),
)
if not db_path.exists():
    st.warning(f'No se encuentra la base de datos: {db_path}')
    st.stop()

with Repository(db_path) as repo:
    summary = repo.review_summary()
    pairs = repo.list_pairs_for_review(filter_name, status_name, sample_size, hide_empty)

c1, c2, c3, c4 = st.columns(4)
c1.metric('Pares totales', summary.get('total', 0))
c2.metric('Revisados', summary.get('reviewed', 0))
c3.metric('Aceptados', summary.get('accepted', 0))
c4.metric('Pendientes', summary.get('pending', 0))

if hide_empty:
    with Repository(db_path) as repo_count:
        all_matching = repo_count.list_pairs_for_review(filter_name, status_name, None, hide_empty=False)
    hidden_count = len(all_matching) - len(pairs)
    if hidden_count > 0:
        st.caption(
            f'{len(pairs)} bolsitas para revisar — {hidden_count} más sin ningún fármaco '
            'reconocido quedan ocultas (casilla en la barra lateral).'
        )

if not pairs:
    st.success('No quedan elementos con este filtro.')
    st.stop()

# Una única clave de session_state (1-based, la misma que usa el propio
# widget) como fuente de verdad -- mezclar `value=` con `key=` sobre
# variables distintas es lo que causaba el bug original: el widget ignora
# `value=` en las recargas siguientes y se queda con su propio estado
# interno, así que los botones ◀▶ no lo sincronizaban de verdad y hacía
# falta pulsar dos veces (ver docs/cuaderno_ingenieria_3.23.md).
if 'pair_index_1based' not in st.session_state:
    st.session_state.pair_index_1based = 1
# Un cambio pendiente (de "guardar y avanzar") se resuelve aquí, ANTES de
# crear el widget de más abajo -- Streamlit no permite tocar el
# session_state de una key después de que su widget ya se haya
# instanciado en la misma ejecución (error real encontrado, ver
# docs/cuaderno_ingenieria_3.24.md). Los botones ◀/▶ de aquí abajo son
# distintos: modifican el estado y llaman a rerun() antes de que el
# número se dibuje en esa misma pasada, así que no tienen este problema.
if 'pending_index_delta' in st.session_state:
    st.session_state.pair_index_1based += st.session_state.pop('pending_index_delta')
st.session_state.pair_index_1based = max(1, min(st.session_state.pair_index_1based, len(pairs)))

nav_prev, nav_num, nav_next = st.columns([1, 3, 1])
with nav_prev:
    if st.button('◀ Anterior', disabled=st.session_state.pair_index_1based <= 1, use_container_width=True):
        st.session_state.pair_index_1based -= 1
        st.rerun()
with nav_next:
    if st.button('Siguiente ▶', disabled=st.session_state.pair_index_1based >= len(pairs), use_container_width=True):
        st.session_state.pair_index_1based += 1
        st.rerun()
with nav_num:
    st.number_input(
        'Elemento', min_value=1, max_value=len(pairs), step=1, key='pair_index_1based',
    )

index = st.session_state.pair_index_1based - 1
item = pairs[int(index)]
st.progress((int(index) + 1) / len(pairs), text=f'{int(index) + 1} de {len(pairs)}')

_STATUS_LABELS = {
    'position_matched': '🟡 Emparejado por posición (sin verificar por contenido)',
    'review': '🟠 Mecanismo de respaldo (sin certeza)',
    'unmatched_label': '⚪ Sin foto de pastilla emparejada',
    'unmatched_pill': '⚪ Foto de pastilla sin lista emparejada',
}
_DECISION_LABELS = {
    'accepted': '✅ Aceptado', 'corrected': '✏️ Aceptado con corrección',
    'rejected': '❌ Rechazado', 'pending': '⏳ Pendiente', None: '⏳ Pendiente (nunca revisado)',
}


def _status_label(status: str, match_score: float) -> str:
    if status == 'paired':
        # 'paired' puede venir de la coincidencia DIRECTA por cabecera
        # (match_score=1.0 exacto, verificada por contenido) o del
        # mecanismo ordinal de respaldo cuando su propia puntuación supera
        # 0.70 (pairing/track_pairer.py) — sin verificación real de
        # contenido pese a llamarse igual. Se distinguen por match_score.
        if match_score >= 0.999:
            return '🟢 Coincidencia directa (verificada por contenido)'
        return f'🟠 Emparejado por el mecanismo de respaldo, puntuación {match_score:.2f} (sin verificar por contenido)'
    return _STATUS_LABELS.get(status, status)


track_pair_id = int(item['track_pair_id'])
ocr_result_id = item.get('label_ocr_result_id')

with Repository(db_path) as repo:
    header = repo.get_label_header(int(ocr_result_id)) if ocr_result_id else None
    reviewed_items = repo.get_pair_review_items(track_pair_id)
    ocr_items = repo.get_label_items(int(ocr_result_id)) if ocr_result_id else []
    if quick_mode:
        # Sin foto de pastilla (asociación 0.00): esa consulta se salta,
        # sale vacía de todas formas. La de ETIQUETA se sigue pidiendo
        # SIEMPRE, aquí o abajo — es la única referencia real contra la
        # que comparar el texto (ver docs/cuaderno_ingenieria_3.30.md;
        # antes se saltaban las dos, dejando la lista sin nada que
        # comparar, un fallo real de diseño).
        pill_images = []
        label_images = repo.get_pair_group_images(track_pair_id, "label")
    else:
        # Todas las fotos que contribuyeron a este par, no solo la representante:
        # el agrupado por cabecera/costura fusiona texto de varias vistas
        # parciales de la misma bolsita (una no cabe entera en un frame — ver
        # docs/cuaderno_ingenieria_1.7.md/3.0.md), así que una pastilla o línea
        # puede estar solo en una foto que no sea la elegida como representante.
        pill_images = repo.get_pair_group_images(track_pair_id, "pill")
        label_images = repo.get_pair_group_images(track_pair_id, "label")

label_seam_side = item.get("label_seam_side")
pill_seam_side = item.get("pill_seam_side")

# Los items ya revisados (si existen) priman sobre el OCR crudo como punto de
# partida del editor; el OCR original nunca se sobrescribe (queda en label_items).
source_items = reviewed_items or ocr_items


def _render_label_column():
    st.subheader('Reverso impreso (lista de la bolsita)')
    if label_images:
        if len(label_images) > 1:
            st.caption(
                f'{len(label_images)} fotos de esta bolsita (no cupo entera en un solo frame) — '
                'revisa todas antes de dar por buena la lista.'
            )
        if label_seam_side is not None:
            st.caption(
                '🟨 La línea marca la costura con la bolsita vecina — la parte '
                'atenuada NO pertenece a esta bolsita.'
            )
        # Altura fija con scroll propio -- una bolsita con muchas fotos (se
        # han visto casos de 20+) empujaba el resto de la pantalla (estado,
        # formulario) fuera de la vista. Con esto, solo esta columna se
        # desplaza; el resto queda fijo (ver docs/cuaderno_ingenieria_3.32.md).
        with st.container(height=700):
            for entry in label_images:
                resolved = resolve_image(entry["crop_path"], db_path)
                if not resolved:
                    continue
                rendered = render_with_seam(resolved, entry.get("seam_positions"), label_seam_side)
                if isinstance(rendered, str):
                    st.image(rendered, use_container_width=True)
                else:
                    st.image(rendered, use_container_width=True, channels="RGB")
    else:
        st.info('Imagen no disponible')


def _render_pill_column():
    st.subheader('Cara transparente (pastillas)')
    if quick_mode:
        st.caption('Sin foto de pastilla para este par (asociación 0.00).')
        return
    if pill_images:
        if len(pill_images) > 1:
            st.caption(
                f'{len(pill_images)} fotos de esta bolsita (no cupo entera en un solo frame) — '
                'revisa todas antes de dar por buena la lista.'
            )
        pill_any_seam_position = any(e.get("seam_positions") for e in pill_images)
        if pill_seam_side is not None:
            st.caption(
                '🟨 La línea marca la costura con la bolsita vecina — la parte '
                'atenuada NO pertenece a esta bolsita.'
            )
        elif pill_any_seam_position:
            st.caption(
                '🟨 Se detectó una costura (línea), pero no se sabe con certeza de qué '
                'lado está esta bolsita — no se ha atenuado ningún lado, decide tú.'
            )
        elif len(pill_images) >= 1:
            st.caption('Sin costura detectada en esta foto.')
        with st.container(height=700):
            for entry in pill_images:
                resolved = resolve_image(entry["crop_path"], db_path)
                if not resolved:
                    continue
                rendered = render_with_seam(resolved, entry.get("seam_positions"), pill_seam_side)
                if isinstance(rendered, str):
                    st.image(rendered, use_container_width=True)
                else:
                    st.image(rendered, use_container_width=True, channels="RGB")
    else:
        st.info('Imagen no disponible')


def _render_status_column():
    st.markdown('**Estado del pipeline**')
    st.caption(_status_label(item['status'], float(item['match_score'])))
    st.markdown('**Decisión actual**')
    st.caption(_DECISION_LABELS.get(item.get('decision'), item.get('decision') or '⏳ Pendiente'))
    st.caption(
        f"Par: {item['pair_key']} · posición {item['order_index']} · "
        f"asociación {item['match_score']:.2f} · OCR {item.get('ocr_confidence') or 0:.2f}"
    )
    if header and any(header.get(k) for k in ('patient_name', 'dose_slot', 'dose_date')):
        st.info(
            f"**{header.get('patient_name') or '(paciente no reconocido)'}**"
            f"{' · ' + header['patient_location'] if header.get('patient_location') else ''} · "
            f"{header.get('dose_weekday') or ''} {header.get('dose_date') or ''} "
            f"{header.get('dose_slot') or ''}".strip()
        )
    else:
        st.warning('No se ha reconocido la cabecera de esta bolsita (paciente/fecha/toma). Revisa la foto.')


def _render_review_form():
    st.markdown('**Medicamentos de esta bolsita** — edita, añade o borra filas según lo que veas en la foto')

    df_source = pd.DataFrame(
        [
            {
                'cantidad': it.get('quantity'),
                'medicamento': it.get('drug_name') or '',
                'dosis': it.get('dose_value'),
                'unidad': it.get('dose_unit') or '',
            }
            for it in source_items
        ]
    ) if source_items else pd.DataFrame(columns=['cantidad', 'medicamento', 'dosis', 'unidad'])

    if not source_items:
        st.caption('El OCR no reconoció ningún fármaco en esta bolsita. Añade las filas a mano si la foto sí los muestra.')

    with st.form('review_form'):
        # La tabla va DENTRO del formulario a propósito: fuera, cada edición
        # de una celda disparaba una recarga completa de la página al
        # instante — con el foco perdido en cada cambio. Dentro del
        # formulario, nada se envía hasta pulsar "Guardar revisión" (ver
        # docs/cuaderno_ingenieria_3.33.md).
        edited_df = st.data_editor(
            df_source,
            num_rows='dynamic',
            use_container_width=True,
            key=f'items_editor_{track_pair_id}',
            column_config={
                'cantidad': st.column_config.NumberColumn(step=0.1, min_value=0, format="%.2f"),
                'dosis': st.column_config.NumberColumn(step=0.01, min_value=0),
            },
        )
        notes = st.text_area('Observaciones', value=item.get('reviewer_notes') or '')
        decision_options = ['accepted', 'corrected', 'rejected', 'pending']
        current_decision = item.get('decision') or 'pending'
        decision = st.radio(
            'Decisión', decision_options,
            index=decision_options.index(current_decision) if current_decision in decision_options else 3,
            horizontal=True,
            format_func=lambda x: {
                'accepted': 'Aceptar', 'corrected': 'Aceptar con corrección',
                'rejected': 'Rechazar', 'pending': 'Dejar pendiente',
            }[x],
        )
        submitted = st.form_submit_button('Guardar revisión', type='primary')

    if submitted:
        items_payload = []
        for line_index, row in enumerate(edited_df.to_dict('records')):
            name = str(row.get('medicamento') or '').strip()
            quantity = row.get('cantidad')
            dose = row.get('dosis')
            if not name and quantity in (None, '') and dose in (None, ''):
                continue  # fila vacía dejada por el editor, se ignora
            unit_raw = row.get('unidad')
            items_payload.append({
                'line_index': line_index,
                'quantity': quantity,
                'drug_name': name or None,
                'dose_value': dose,
                'dose_unit': (str(unit_raw).strip().upper() or None) if unit_raw else None,
            })
        with Repository(db_path) as repo:
            repo.save_pair_review(track_pair_id, decision, notes.strip())
            repo.save_pair_review_items(track_pair_id, items_payload)
        # Guardar avanza directamente al siguiente elemento -- sin esto, había
        # que guardar, subir arriba del todo de la pantalla y tocar el número a
        # mano para cada bolsita, con cientos por revisar era insostenible (ver
        # docs/cuaderno_ingenieria_3.23.md).
        if st.session_state.pair_index_1based < len(pairs):
            st.session_state.pending_index_delta = 1
            st.toast(f'Guardado. Pasando al {st.session_state.pair_index_1based + 1} de {len(pairs)}.', icon='✅')
        else:
            st.toast('Guardado. Era el último elemento de esta lista.', icon='✅')
        st.session_state.scroll_to_top = True
        st.rerun()


# 4 columnas de izquierda a derecha: pastilla | etiqueta | estado+decisión |
# formulario de revisión — en pantalla estrecha, se apilan verticalmente en
# su lugar (Streamlit no detecta el ancho real del navegador desde el
# servidor, así que la casilla "Pantalla estrecha" es manual).
if narrow_mode:
    _render_pill_column()
    _render_label_column()
    _render_status_column()
    _render_review_form()
else:
    col_pill, col_label, col_status, col_form = st.columns([3, 3, 2, 4])
    with col_pill:
        _render_pill_column()
    with col_label:
        _render_label_column()
    with col_status:
        _render_status_column()
    with col_form:
        _render_review_form()
