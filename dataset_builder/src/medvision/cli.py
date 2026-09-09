from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path

import yaml

from medvision.acquisition.session_planner import find_videos, plan_sessions, sessions_to_config_dict


def _resolve_config(args: argparse.Namespace) -> Path:
    """Combina --config con --sessions si se indicó (video_sides/video_pairs
    de sessions.yaml tienen prioridad: es lo generado a partir del orden
    real de grabación, no una edición manual que pueda haber quedado
    desfasada en el config base). Devuelve la ruta al YAML combinado a usar.
    """
    if not args.sessions:
        return args.config
    if not args.sessions.exists():
        print(f"ERROR: no existe {args.sessions}. Genera primero con "
              f"'medvision-ai plan-sessions --videos-dir {args.videos_dir} --output {args.sessions}'.")
        sys.exit(1)
    base_cfg = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    sessions_cfg = yaml.safe_load(args.sessions.read_text(encoding="utf-8")) or {}
    merged = {**base_cfg, **sessions_cfg}
    merged_path = args.output_dir / "_merged_config.yaml"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    merged_path.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Config combinada ({args.config.name} + {args.sessions.name}) -> {merged_path}")
    return merged_path


def _cmd_build_dataset(args: argparse.Namespace) -> None:
    from medvision.dataset.builder import build_dataset  # perezoso: carga cv2/paddleocr

    if args.fresh and args.output_dir.exists():
        print(f"--fresh: borrando {args.output_dir} antes de empezar...")
        shutil.rmtree(args.output_dir)

    cfg_path = _resolve_config(args)
    try:
        summary = build_dataset(args.videos_dir, args.output_dir, cfg_path, allow_unknown_side=args.allow_unknown_side)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    print("Dataset Builder completado")
    for k, v in summary.items():
        print(f"- {k}: {v}")


def _cmd_rebuild_pairs(args: argparse.Namespace) -> None:
    from medvision.dataset.builder import rebuild_pairs  # perezoso

    cfg_path = _resolve_config(args)
    print(f"Re-emparejando sobre {args.output_dir} (sin repetir detección/OCR)...")
    summary = rebuild_pairs(args.output_dir, cfg_path)
    print("Emparejamiento completado")
    for k, v in summary.items():
        print(f"- {k}: {v}")


def _cmd_export_reviews(args: argparse.Namespace) -> None:
    import json
    from medvision.database.repository import Repository  # perezoso

    db_path = args.output_dir / "medvision.sqlite"
    if not db_path.exists():
        print(f"ERROR: no existe {db_path}")
        sys.exit(1)
    with Repository(db_path) as repo:
        records = repo.export_reviews()
    args.output_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(records)} decisión(es) de revisión exportadas a {args.output_file}")
    print("Guarda este fichero en un sitio seguro ANTES de lanzar --fresh — es tu única copia.")


def _cmd_import_reviews(args: argparse.Namespace) -> None:
    import json
    from medvision.database.repository import Repository  # perezoso

    db_path = args.output_dir / "medvision.sqlite"
    if not db_path.exists():
        print(f"ERROR: no existe {db_path}")
        sys.exit(1)
    if not args.input_file.exists():
        print(f"ERROR: no existe {args.input_file}")
        sys.exit(1)
    records = json.loads(args.input_file.read_text(encoding="utf-8"))
    with Repository(db_path) as repo:
        matched, unmatched = repo.import_reviews(records)
    print(f"{matched} decisión(es) reaplicadas correctamente.")
    if unmatched:
        print(f"AVISO: {len(unmatched)} no se pudieron reaplicar (la bolsita ya no se identifica igual "
              f"tras el reproceso — revisar a mano):")
        for u in unmatched:
            print(f"  vídeo={u.get('label_video_filename')}  "
                  f"{u.get('dose_weekday')} {u.get('dose_date')} {u.get('dose_slot')}  "
                  f"decisión_perdida={u.get('decision')}")


def _cmd_export_dataset(args: argparse.Namespace) -> None:
    import json
    from collections import Counter
    from medvision.database.repository import Repository  # perezoso

    db_path = args.output_dir / "medvision.sqlite"
    if not db_path.exists():
        print(f"ERROR: no existe {db_path}")
        sys.exit(1)
    with Repository(db_path) as repo:
        records = repo.export_training_dataset(
            exclude_rejected=not args.include_rejected, exclude_empty=not args.include_empty,
        )
    args.output_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    total_pill_photos = sum(len(r["pill_photos"]) for r in records)
    with_pill = sum(1 for r in records if r["pill_photos"])
    without_pill = len(records) - with_pill
    by_status = Counter(r["pipeline_status"] for r in records)
    by_source = Counter(r["label_source"] for r in records)
    by_decision = Counter(r["review"]["decision"] or "sin_revisar" for r in records)

    print(f"Dataset exportado a {args.output_file}")
    print()
    print(f"Bolsitas totales: {len(records)}")
    print(f"  con al menos 1 foto de pastilla: {with_pill}")
    print(f"  sin ninguna foto de pastilla: {without_pill}")
    print(f"Fotos de pastilla en total (sumando todas las bolsitas): {total_pill_photos}")
    print()
    print("Por estado del pipeline (procedencia):")
    for status, count in by_status.most_common():
        print(f"  {status}: {count}")
    print()
    print("Por origen de la lista de fármacos:")
    for source, count in by_source.most_common():
        print(f"  {source}: {count}")
    print()
    print("Por decisión de revisión humana:")
    for decision, count in by_decision.most_common():
        print(f"  {decision}: {count}")


def _cmd_package_dataset(args: argparse.Namespace) -> None:
    from medvision.dataset.packaging import package_dataset  # perezoso

    if not args.manifest.exists():
        print(f"ERROR: no existe {args.manifest} (¿ejecutaste export-dataset primero?)")
        sys.exit(1)
    summary = package_dataset(
        args.output_dir, args.manifest, args.package_dir, make_zip=not args.no_zip,
    )
    print(f"Fotos referenciadas en el manifiesto: {summary['referenced_photos']}")
    print(f"Copiadas correctamente: {summary['copied']}")
    if summary["missing"]:
        print(f"AVISO: {len(summary['missing'])} referenciadas en el manifiesto pero NO encontradas en disco:")
        for m in summary["missing"][:20]:
            print(f"  {m}")
        if len(summary["missing"]) > 20:
            print(f"  ... y {len(summary['missing']) - 20} más")
    print(f"Carpeta empaquetada: {summary['package_dir']}")
    if summary["zip_path"]:
        print(f"Zip listo para compartir: {summary['zip_path']}")


def _cmd_plan_sessions(args: argparse.Namespace) -> None:
    videos = find_videos(args.videos_dir)
    if not videos:
        print(f"No se encontraron vídeos en {args.videos_dir}")
        sys.exit(1)
    if len(videos) % 2 != 0:
        print(f"AVISO: número impar de vídeos ({len(videos)}). Al menos uno quedará sin pareja.")

    sessions = plan_sessions(videos, max_gap_seconds=args.max_gap_seconds)
    cfg = sessions_to_config_dict(sessions)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")

    ok_count = sum(1 for s in sessions if s.status == "ok")
    review = [s for s in sessions if s.status == "needs_review"]

    print(f"{len(sessions)} sesiones planificadas ({ok_count} ok, {len(review)} para revisar) -> {args.output}")
    if review:
        print("\nRevisar antes de usar:")
        for s in review:
            label = s.label_video or "(sin pareja)"
            print(f"  {s.pair_key}: {s.pill_video} + {label} -- {s.reason}")
    print(f"\nInspecciona {args.output} antes de usarlo. Para lanzar el pipeline con esto:")
    print(f"  medvision-ai build-dataset --videos-dir {args.videos_dir} --output-dir output "
          f"--config config/default.yaml --sessions {args.output}")


def main() -> None:
    p = argparse.ArgumentParser(prog="medvision-ai", description="Dataset Builder trazable para vídeos de bolsas de medicamentos")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build-dataset", help="Procesa vídeos y genera SQLite, imágenes y metadatos")
    b.add_argument("--videos-dir", type=Path, required=True)
    b.add_argument("--output-dir", type=Path, required=True)
    b.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    b.add_argument("--sessions", type=Path, default=None,
                    help="YAML generado por 'plan-sessions' (video_sides/video_pairs). "
                         "Si se indica, tiene prioridad sobre lo que haya en --config.")
    b.add_argument(
        "--fresh", action="store_true",
        help=(
            "Borra --output-dir antes de empezar. Sin esto, cada ejecucion se "
            "acumula sobre la anterior: filas de bolsas de ejecuciones viejas "
            "(con parametros distintos de deteccion/split) pueden quedar "
            "huerfanas en el SQLite y colarse en el resultado. Usar SIEMPRE "
            "que se cambie bag_detection/bag_splitting en la config, o al "
            "repetir una prueba desde cero."
        ),
    )
    b.add_argument(
        "--allow-unknown-side", action="store_true",
        help=(
            "Por defecto, si algun video de --videos-dir no tiene lado asignado "
            "en video_sides, el pipeline PARA antes de procesar nada (evita colarse "
            "en 'unknown' sin OCR ni emparejamiento sin que se note). Pasa esto solo "
            "si de verdad quieres procesarlos igualmente como 'unknown'."
        ),
    )

    s = sub.add_parser("plan-sessions", help="Empareja vídeos automáticamente por orden real de grabación")
    s.add_argument("--videos-dir", type=Path, required=True)
    s.add_argument("--output", type=Path, default=Path("config/sessions.yaml"))
    s.add_argument("--max-gap-seconds", type=float, default=120.0,
                    help="Hueco máximo esperado entre grabar la pastilla y la etiqueta (default: 120s)")

    r = sub.add_parser(
        "rebuild-pairs",
        help="Re-ejecuta solo el agrupado/emparejamiento sobre un dataset ya generado, sin repetir detección/OCR",
    )
    r.add_argument("--output-dir", type=Path, required=True,
                    help="Carpeta con el medvision.sqlite ya generado por build-dataset")
    r.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    r.add_argument("--sessions", type=Path, default=None)
    r.add_argument("--videos-dir", type=Path, default=None,
                    help="Solo necesario si --sessions no existe todavía y hay que generarlo primero")

    exp = sub.add_parser(
        "export-reviews",
        help="Exporta las decisiones de revisión humana ya guardadas, para poder recuperarlas tras un --fresh",
    )
    exp.add_argument("--output-dir", type=Path, required=True,
                      help="Carpeta con el medvision.sqlite del que exportar")
    exp.add_argument("--output-file", type=Path, default=Path("reviews_backup.json"),
                      help="Dónde guardar la copia (default: reviews_backup.json)")

    imp = sub.add_parser(
        "import-reviews",
        help="Reaplica decisiones de revisión exportadas con export-reviews, emparejando por contenido",
    )
    imp.add_argument("--output-dir", type=Path, required=True,
                      help="Carpeta con el medvision.sqlite (normalmente tras --fresh + rebuild-pairs)")
    imp.add_argument("--input-file", type=Path, default=Path("reviews_backup.json"),
                      help="Copia generada antes por export-reviews (default: reviews_backup.json)")

    ed = sub.add_parser(
        "export-dataset",
        help="Exporta el dataset final (fotos de pastilla + fármacos + procedencia) para el siguiente módulo",
    )
    ed.add_argument("--output-dir", type=Path, required=True)
    ed.add_argument("--output-file", type=Path, default=Path("dataset_final.json"),
                     help="Dónde guardar el dataset exportado (default: dataset_final.json)")
    ed.add_argument("--include-rejected", action="store_true",
                     help="Incluir también las bolsitas marcadas 'rejected' en la revisión (por defecto se excluyen)")
    ed.add_argument("--include-empty", action="store_true",
                     help="Incluir también bolsitas sin ningún fármaco en su lista (por defecto se excluyen)")

    pk = sub.add_parser(
        "package-dataset",
        help="Copia el manifiesto de export-dataset y las fotos que referencia a una carpeta autocontenida (+ zip)",
    )
    pk.add_argument("--output-dir", type=Path, required=True,
                     help="Carpeta con las fotos originales (bags/pill_side/...), la misma que usó export-dataset")
    pk.add_argument("--manifest", type=Path, default=Path("dataset_final.json"),
                     help="El JSON generado por export-dataset (default: dataset_final.json)")
    pk.add_argument("--package-dir", type=Path, default=Path("dataset_package"),
                     help="Carpeta nueva donde se copian el manifiesto y las fotos (default: dataset_package)")
    pk.add_argument("--no-zip", action="store_true", help="No comprimir el resultado en un .zip")

    args = p.parse_args()
    if args.command == "build-dataset":
        _cmd_build_dataset(args)
    elif args.command == "plan-sessions":
        _cmd_plan_sessions(args)
    elif args.command == "rebuild-pairs":
        _cmd_rebuild_pairs(args)
    elif args.command == "export-reviews":
        _cmd_export_reviews(args)
    elif args.command == "import-reviews":
        _cmd_import_reviews(args)
    elif args.command == "export-dataset":
        _cmd_export_dataset(args)
    elif args.command == "package-dataset":
        _cmd_package_dataset(args)


if __name__ == "__main__":
    main()
