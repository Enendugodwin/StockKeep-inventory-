"""Tests for portable data paths and one-time migration from AppData."""

from __future__ import annotations

from pathlib import Path

from stockkeep import paths as paths_module
from stockkeep.services import settings_service
from stockkeep.services.settings_service import load_settings, set_setting


def test_default_home_is_the_project_root(monkeypatch):
    monkeypatch.delenv("STOCKKEEP_HOME", raising=False)
    expected = Path(paths_module.__file__).resolve().parents[2]
    assert paths_module._default_home() == expected


def test_frozen_default_home_is_next_to_the_executable(monkeypatch, tmp_path):
    exe = tmp_path / "StockKeep.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(paths_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths_module.sys, "executable", str(exe))
    monkeypatch.delenv("STOCKKEEP_HOME", raising=False)
    assert paths_module._default_home() == tmp_path


def test_frozen_exe_in_a_source_checkout_uses_the_project_root(monkeypatch, tmp_path):
    (tmp_path / "run.py").write_text("", encoding="utf-8")
    exe = tmp_path / "dist" / "StockKeep.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    monkeypatch.setattr(paths_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths_module.sys, "executable", str(exe))
    monkeypatch.delenv("STOCKKEEP_HOME", raising=False)
    assert paths_module._default_home() == tmp_path


def test_legacy_appdata_home_is_migrated_once(monkeypatch, tmp_path):
    target = tmp_path / "app"
    legacy = tmp_path / "appdata-stockkeep"
    (legacy / "database").mkdir(parents=True)
    (legacy / "reports").mkdir()
    (legacy / "database" / "stockkeep.db").write_bytes(b"SQLite format 3\0legacy")
    (legacy / "reports" / "daily.csv").write_text("date,total\n", encoding="utf-8")

    monkeypatch.delenv("STOCKKEEP_HOME", raising=False)
    monkeypatch.setattr(paths_module, "_application_dir", lambda: target)
    monkeypatch.setattr(paths_module, "_legacy_home", lambda: legacy)

    result = paths_module.ensure_dirs()
    assert result.home == target
    assert (target / "database" / "stockkeep.db").read_bytes().startswith(b"SQLite")
    assert (target / "reports" / "daily.csv").exists()
    assert not legacy.exists()
    assert (target / "logs").is_dir()
    assert (target / "backups").is_dir()


def test_existing_portable_data_is_not_overwritten(monkeypatch, tmp_path):
    target = tmp_path / "app"
    legacy = tmp_path / "appdata-stockkeep"
    (target / "database").mkdir(parents=True)
    (target / "database" / "stockkeep.db").write_bytes(b"portable")
    (legacy / "database").mkdir(parents=True)
    (legacy / "database" / "stockkeep.db").write_bytes(b"legacy")

    monkeypatch.delenv("STOCKKEEP_HOME", raising=False)
    monkeypatch.setattr(paths_module, "_application_dir", lambda: target)
    monkeypatch.setattr(paths_module, "_legacy_home", lambda: legacy)

    paths_module.ensure_dirs()
    assert (target / "database" / "stockkeep.db").read_bytes() == b"portable"
    assert legacy.exists()


def test_legacy_report_and_backup_settings_move_to_the_app_folder(
    db, paths, tmp_path, monkeypatch
):
    legacy = tmp_path / "legacy-appdata"
    old_reports = legacy / "reports"
    old_backups = legacy / "backups"
    old_reports.mkdir(parents=True)
    old_backups.mkdir()
    monkeypatch.setattr(settings_service, "legacy_home", lambda: legacy)

    with db.session() as session:
        set_setting(session, "report_dir", str(old_reports))
        set_setting(session, "backup_dir", str(old_backups))
    with db.session() as session:
        settings = load_settings(session, paths)
        assert settings.report_root(paths) == paths.reports_dir.resolve()
        assert settings.backup_root(paths) == paths.backups_dir.resolve()
    with db.session() as session:
        settings = load_settings(session, paths)
        assert settings.get("report_dir") == str(paths.reports_dir)
        assert settings.get("backup_dir") == str(paths.backups_dir)
