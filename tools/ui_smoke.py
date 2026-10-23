"""Headless UI smoke test: build the main window and visit every page.

Run from the project root:
    $env:PYTHONPATH="src"
    $env:QT_QPA_PLATFORM="offscreen"
    .venv\\Scripts\\python.exe tools\\ui_smoke.py [--home PATH]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", default=None)
    args = parser.parse_args()

    home = args.home or tempfile.mkdtemp(prefix="sk-ui-")
    os.environ["STOCKKEEP_HOME"] = home

    from PySide6.QtWidgets import QApplication

    from stockkeep.db import Database
    from stockkeep.paths import ensure_dirs
    from stockkeep.ui.main_window import MainWindow, NAV_ITEMS
    from stockkeep.ui.state import AppState
    from stockkeep.ui.theme import apply_theme

    paths = ensure_dirs(home)
    database = Database(paths.db_path)
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app, "light")

    state = AppState(database, paths)
    failures = 0
    try:
        window = MainWindow(state)
        window.show()
        app.processEvents()
        for key, label, _icon, _permission in NAV_ITEMS:
            try:
                window.go_to(key)
                app.processEvents()
                page = window.current_page()
                print(f"OK   {key:12s} {type(page).__name__}")
            except Exception as exc:
                failures += 1
                print(f"FAIL {key:12s} {type(exc).__name__}: {exc}")
                traceback.print_exc()
        # Theme switch round-trip.
        for theme in ("dark", "light"):
            try:
                window._toggle_theme() if False else apply_theme(app, theme)
                app.processEvents()
                print(f"OK   theme {theme}")
            except Exception as exc:
                failures += 1
                print(f"FAIL theme {theme}: {exc}")
                traceback.print_exc()
        window.close()
    finally:
        app.processEvents()
        database.dispose()

    print(f"\nUI smoke home: {home}")
    print(f"failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
