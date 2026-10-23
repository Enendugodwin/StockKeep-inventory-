"""Entry point for `python -m stockkeep` and the packaged executable."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .db import Database
from .logging_util import configure_logging
from .paths import ensure_dirs
from .services.scheduler import (
    cli_generate,
    config_from_settings,
    install_scheduled_task,
    remove_scheduled_task,
    scheduled_task_status,
)
from .services.settings_service import load_settings, set_setting


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="StockKeep",
        description="Native desktop inventory management for Windows.",
    )
    parser.add_argument("--version", action="version", version=f"StockKeep {__version__}")
    parser.add_argument(
        "--generate-reports",
        action="store_true",
        help="Generate missing daily reports without opening the GUI.",
    )
    parser.add_argument(
        "--date",
        help="With --generate-reports: generate one business date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --generate-reports: regenerate reports even if they exist.",
    )
    parser.add_argument(
        "--install-task",
        action="store_true",
        help="Install a Windows Task Scheduler job for daily reports.",
    )
    parser.add_argument("--remove-task", action="store_true", help="Remove the scheduled report task.")
    parser.add_argument("--task-status", action="store_true", help="Show scheduled task status.")
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print database, report and integrity information.",
    )
    parser.add_argument("--home", help="Override the StockKeep data directory.")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = ensure_dirs(args.home)
    configure_logging(paths, verbose=args.verbose)
    database = Database(paths.db_path)

    if args.generate_reports:
        with database.session() as session:
            settings = load_settings(session, paths)
        config = config_from_settings(settings, paths)
        day = None
        if args.date:
            try:
                from datetime import date

                day = date.fromisoformat(args.date)
            except ValueError:
                print(f"Invalid --date value: {args.date!r} (expected YYYY-MM-DD)")
                database.dispose()
                return 2
        code = cli_generate(database, config, force=args.force, day=day)
        database.dispose()
        return code

    if args.install_task:
        with database.session() as session:
            settings = load_settings(session, paths)
        ok, message = install_scheduled_task(settings.close_time)
        if ok:
            with database.session() as session:
                set_setting(session, "scheduled_task_installed", "1")
        print(message)
        database.dispose()
        return 0 if ok else 1

    if args.remove_task:
        ok, message = remove_scheduled_task()
        if ok:
            with database.session() as session:
                set_setting(session, "scheduled_task_installed", "0")
        print(message)
        database.dispose()
        return 0 if ok else 1

    if args.task_status:
        ok, message = scheduled_task_status()
        print(message)
        database.dispose()
        return 0 if ok else 1

    if args.diagnostics:
        intact, detail = database.integrity_check()
        with database.session() as session:
            settings = load_settings(session, paths)
        from .models import Product, Sale

        with database.session() as session:
            products = session.query(Product).count()
            sales = session.query(Sale).count()
        lines = [
            f"StockKeep {__version__}",
            f"Data directory : {paths.home}",
            f"Database       : {paths.db_path}",
            f"Schema version : {database.schema_version()}",
            f"Reports        : {settings.report_root(paths)}",
            f"Backups        : {settings.backup_root(paths)}",
            f"Products       : {products}",
            f"Sales          : {sales}",
            f"Integrity      : {'ok' if intact else detail}",
        ]
        report = "\n".join(lines)
        # The packaged executable is windowed, so stdout may be unavailable.
        # Persist the report next to the data directory as well.
        try:
            (paths.home / "diagnostics.txt").write_text(report + "\n", encoding="utf-8")
        except OSError:  # pragma: no cover - best effort only
            pass
        try:
            print(report)
        except (OSError, AttributeError):  # pragma: no cover - windowed build
            pass
        database.dispose()
        return 0 if intact else 1

    # Default: launch the desktop application.
    try:
        from .ui.app import run_app
    except ImportError as exc:
        print(f"StockKeep GUI dependencies are unavailable: {exc}", file=sys.stderr)
        database.dispose()
        return 1
    return run_app(database, paths)


if __name__ == "__main__":
    raise SystemExit(main())
