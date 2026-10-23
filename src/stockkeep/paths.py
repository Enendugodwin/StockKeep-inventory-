"""Filesystem locations for StockKeep.

StockKeep is portable: the database, reports, backups, logs, config and exports
live in the application folder (next to `StockKeep.exe`, or at the project root
when running from source).  Nothing is written to AppData or the user profile.
Set `STOCKKEEP_HOME` to override the location.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "StockKeep"
log = logging.getLogger(__name__)


def _application_dir() -> Path:
    """The folder that contains the executable (or the project root)."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # When running the built exe from a source checkout's dist folder, keep
        # using the project root so the source and packaged apps share one
        # portable data folder.  A copied/distributed exe uses its own folder.
        if exe_dir.name.lower() == "dist" and (exe_dir.parent / "run.py").is_file():
            return exe_dir.parent
        return exe_dir
    # paths.py -> stockkeep -> src -> project root
    return Path(__file__).resolve().parents[2]


def _legacy_home() -> Path | None:
    """The old 1.0 data location, kept only for one-time migration."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return (Path(base) / APP_DIR_NAME) if base else None
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) / APP_DIR_NAME) if base else Path.home() / ".local" / "share" / APP_DIR_NAME


def legacy_home() -> Path | None:
    """The old 1.0 data location, used only to normalise migrated settings."""
    return _legacy_home()


def _migrate_legacy_home(target: Path) -> None:
    """Move data from the old AppData location into the portable folder once.

    The move only happens when the destination has no database yet, so an
    existing portable installation is never overwritten.
    """
    legacy = _legacy_home()
    if legacy is None or not legacy.is_dir():
        return
    try:
        if legacy.resolve() == target.resolve():
            return
    except OSError:
        return
    if (target / "database" / "stockkeep.db").exists():
        return
    if not (legacy / "database" / "stockkeep.db").exists():
        return
    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(legacy, target, dirs_exist_ok=True)
        shutil.rmtree(legacy)
        log.info("Moved data from %s to %s", legacy, target)
    except OSError as exc:
        log.warning("Could not move old data from %s: %s", legacy, exc)


def _default_home() -> Path:
    override = os.environ.get("STOCKKEEP_HOME")
    if override:
        return Path(override).expanduser()
    return _application_dir()


@dataclass(frozen=True)
class AppPaths:
    home: Path
    database_dir: Path
    reports_dir: Path
    backups_dir: Path
    logs_dir: Path
    config_dir: Path
    exports_dir: Path

    @property
    def db_path(self) -> Path:
        return self.database_dir / "stockkeep.db"

    @property
    def log_path(self) -> Path:
        return self.logs_dir / "stockkeep.log"

    @property
    def config_path(self) -> Path:
        return self.config_dir / "config.json"


def ensure_dirs(home: Path | str | None = None) -> AppPaths:
    if home:
        root = Path(home).expanduser()
    else:
        root = _default_home()
        _migrate_legacy_home(root)
    paths = AppPaths(
        home=root,
        database_dir=root / "database",
        reports_dir=root / "reports",
        backups_dir=root / "backups",
        logs_dir=root / "logs",
        config_dir=root / "config",
        exports_dir=root / "exports",
    )
    for directory in (
        paths.home,
        paths.database_dir,
        paths.reports_dir,
        paths.backups_dir,
        paths.logs_dir,
        paths.config_dir,
        paths.exports_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def resolve_dir(value: str | Path, *, base: Path) -> Path:
    """Resolve a user-supplied directory, relative to the app home."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
