"""Backup, verification, restore and pruning tests."""

from __future__ import annotations

from stockkeep.models import Product
from stockkeep.services import backup, catalog


def _add_product(session, name: str, code: str) -> Product:
    return catalog.create_product(
        session, name=name, selling_price="10", quantity="2", product_code=code
    )


def test_backup_is_consistent_and_verifiable(db, tmp_path):
    with db.session() as session:
        _add_product(session, "Rice", "PRD-1")
    info = backup.create_backup(db, tmp_path / "stockkeep_manual.db", label="manual")
    assert info.path.is_file()
    assert info.counts.get("products") == 1
    assert info.schema_version >= 1
    assert info.path.with_suffix(".db.json").is_file()

    ok, detail = backup.verify_backup(info.path)
    assert ok, detail
    assert backup.list_backups(tmp_path) == [info.path]


def test_restore_replaces_live_data_and_makes_safety_copy(db, paths, tmp_path):
    with db.session() as session:
        _add_product(session, "Rice", "PRD-1")
    info = backup.create_backup(db, tmp_path / "stockkeep_before.db", label="before")

    with db.session() as session:
        _add_product(session, "Beans", "PRD-2")
        assert session.query(Product).count() == 2

    pre_restore = backup.restore_backup(
        db, info.path, backup_dir=paths.backups_dir, operator_id=None
    )
    assert pre_restore.path.is_file()
    assert pre_restore.label == "pre-restore"
    with db.session() as session:
        names = sorted(p.name for p in session.query(Product).all())
    assert names == ["Rice"]

    restored = backup.verify_backup(temp_path := pre_restore.path)
    assert restored[0], restored[1]
    assert temp_path.is_file()


def test_restore_rejects_tampered_backup(db, paths, tmp_path):
    with db.session() as session:
        _add_product(session, "Rice", "PRD-1")
    info = backup.create_backup(db, tmp_path / "stockkeep_before.db", label="before")
    # Flip bytes so the checksum no longer matches the manifest.
    data = bytearray(info.path.read_bytes())
    data[-1] ^= 0xFF
    info.path.write_bytes(data)

    ok, detail = backup.verify_backup(info.path)
    assert not ok
    try:
        backup.restore_backup(db, info.path, backup_dir=paths.backups_dir)
    except Exception as exc:
        assert "cannot be restored" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("tampered backup was restored")


def test_prune_keeps_newest_backups(db, tmp_path):
    with db.session() as session:
        _add_product(session, "Rice", "PRD-1")
    created = []
    for index in range(3):
        info = backup.create_backup(db, tmp_path / f"stockkeep_b{index}.db", label=f"b{index}")
        created.append(info.path)

    removed = backup.prune_backups(tmp_path, keep=2)
    remaining = backup.list_backups(tmp_path)
    assert len(remaining) == 2
    assert len(removed) == 1
    for path in remaining:
        assert path.with_suffix(".db.json").is_file()
