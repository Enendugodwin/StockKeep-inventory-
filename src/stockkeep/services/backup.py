"""Consistent SQLite backups, validation and restoration."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..db import SCHEMA_VERSION, sqlite_file_is_valid
from ..errors import StockKeepError, ValidationError
from ..timeutil import today, utc_now
from . import audit
from .report_state import mark_all_daily_stale
from .settings_service import AppSettings, load_settings, set_setting

log = logging.getLogger(__name__)

BACKUP_PREFIX = "stockkeep_"
MANIFEST_VERSION = 1


@dataclass
class BackupInfo:
    path: Path
    created_at: datetime
    size: int
    schema_version: int
    counts: dict
    sha256: str
    label: str = ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counts(path: Path) -> dict:
    counts: dict[str, int] = {}
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            for table in ("products", "sales", "sale_items", "stock_movements", "audit_events"):
                try:
                    counts[table] = int(
                        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    )
                except sqlite3.DatabaseError:
                    counts[table] = 0
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        pass
    return counts


def backup_filename(label: str = "") -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(ch for ch in label if ch.isalnum() or ch in "-_")[:40]
    suffix = f"_{safe_label}" if safe_label else ""
    return f"{BACKUP_PREFIX}{stamp}{suffix}.db"


def create_backup(
    database,
    destination: Path | str,
    *,
    label: str = "manual",
    operator_id: int | None = None,
) -> BackupInfo:
    """Create a consistent copy using SQLite's online backup API."""
    destination = Path(destination)
    if destination.suffix.lower() != ".db":
        destination = destination.with_suffix(".db")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise StockKeepError(f"A backup already exists at {destination}.")
    if not database.db_path.exists():
        raise StockKeepError("The live database file does not exist.")

    database.checkpoint()
    source = sqlite3.connect(str(database.db_path), timeout=30)
    target = sqlite3.connect(str(destination), timeout=30)
    try:
        source.backup(target)
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        target.close()
        source.close()

    ok, detail = sqlite_file_is_valid(destination)
    if not ok:
        destination.unlink(missing_ok=True)
        raise StockKeepError(f"The backup failed integrity validation: {detail}")

    schema_version = 0
    try:
        connection = sqlite3.connect(f"file:{destination.as_posix()}?mode=ro", uri=True)
        try:
            schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        pass

    created = utc_now()
    info = BackupInfo(
        path=destination,
        created_at=created,
        size=destination.stat().st_size,
        schema_version=schema_version,
        counts=_counts(destination),
        sha256=_sha256(destination),
        label=label,
    )
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "created_at": created.isoformat(),
        "label": label,
        "schema_version": schema_version,
        "size": info.size,
        "sha256": info.sha256,
        "counts": info.counts,
    }
    destination.with_suffix(destination.suffix + ".json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    with database.session() as session:
        set_setting(session, "last_backup_date", created.date().isoformat())
        audit.record(
            session,
            "backup.created",
            "backup",
            destination.name,
            operator_id=operator_id,
            details={"path": str(destination), "size": info.size, "sha256": info.sha256},
        )
    return info


def list_backups(directory: Path | str) -> list[Path]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"{BACKUP_PREFIX}*.db"), key=lambda p: p.stat().st_mtime, reverse=True)


def prune_backups(directory: Path | str, keep: int = 14) -> list[Path]:
    keep = max(1, int(keep))
    backups = list_backups(directory)
    removed = []
    for path in backups[keep:]:
        path.unlink(missing_ok=True)
        path.with_suffix(path.suffix + ".json").unlink(missing_ok=True)
        removed.append(path)
    return removed


def verify_backup(path: Path | str) -> tuple[bool, str]:
    path = Path(path)
    ok, detail = sqlite_file_is_valid(path)
    if not ok:
        return False, detail
    manifest_path = path.with_suffix(path.suffix + ".json")
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = manifest.get("sha256")
            if expected and _sha256(path) != expected:
                return False, "The backup file's checksum does not match its manifest."
            version = int(manifest.get("schema_version") or 0)
            if version > SCHEMA_VERSION:
                return False, "The backup was created by a newer version of StockKeep."
        except (ValueError, TypeError) as exc:
            return False, f"The backup manifest is unreadable: {exc}"
    return True, "ok"


def restore_backup(
    database,
    backup_path: Path | str,
    *,
    backup_dir: Path | str,
    operator_id: int | None = None,
) -> BackupInfo:
    """Replace the live database with a validated backup.

    A pre-restore safety backup is always attempted first.  If reopening the
    restored database fails, the safety copy is put back.
    """
    backup_path = Path(backup_path)
    ok, detail = verify_backup(backup_path)
    if not ok:
        raise ValidationError(f"This backup cannot be restored: {detail}", "backup")
    pre_restore = create_backup(
        database, Path(backup_dir) / backup_filename("pre-restore"), label="pre-restore"
    )

    database.checkpoint()
    database.dispose()
    live = Path(database.db_path)
    temp_live = live.with_name(live.name + ".restore-tmp")
    try:
        shutil.copy2(backup_path, temp_live)
        for suffix in ("-wal", "-shm"):
            Path(str(live) + suffix).unlink(missing_ok=True)
        temp_live.replace(live)
        database.reopen()
        intact, integrity_detail = database.integrity_check()
        if not intact:
            raise StockKeepError(f"Restored database failed its integrity check: {integrity_detail}")
    except Exception:
        log.exception("Restore failed; attempting rollback to the pre-restore backup")
        try:
            shutil.copy2(pre_restore.path, temp_live)
            temp_live.replace(live)
            for suffix in ("-wal", "-shm"):
                Path(str(live) + suffix).unlink(missing_ok=True)
            database.reopen()
        except Exception:  # pragma: no cover
            log.exception("Rollback after a failed restore also failed")
        temp_live.unlink(missing_ok=True)
        raise

    with database.session() as session:
        mark_all_daily_stale(session)
        audit.record(
            session,
            "backup.restored",
            "backup",
            backup_path.name,
            operator_id=operator_id,
            details={
                "restored_from": str(backup_path),
                "pre_restore_backup": str(pre_restore.path),
            },
        )
    return pre_restore


def auto_backup_if_due(
    database,
    settings: AppSettings,
    backup_dir: Path,
    *,
    operator_id: int | None = None,
) -> Path | None:
    """Daily automatic backup on first start of the day, if enabled."""
    if not settings.backup_enabled:
        return None
    last = settings.get("last_backup_date", "")
    if last == today().isoformat():
        return None
    target = Path(backup_dir) / backup_filename("auto")
    info = create_backup(database, target, label="auto", operator_id=operator_id)
    prune_backups(backup_dir, settings.backup_retention)
    log.info("Automatic backup created at %s", info.path)
    return info.path
