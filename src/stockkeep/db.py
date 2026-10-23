"""Database engine, schema initialization, migrations and pragma setup."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from . import security
from .errors import StockKeepError
from .models import Base, Role, SchemaVersion, Setting, User
from .paths import AppPaths, ensure_dirs
from .services import roles_service
from .timeutil import utc_now

log = logging.getLogger(__name__)

SCHEMA_VERSION = 4
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_OPERATOR_USERNAME = "operator"  # legacy seed name (pre-1.1 databases)


def default_settings(home: Path) -> dict[str, str]:
    return {
        "business_name": "My Business",
        "currency_code": "NGN",
        "currency_symbol": "\u20a6",
        "timezone": "Africa/Lagos",
        "daily_close_time": "23:59",
        "theme": "light",
        "report_dir": str(home / "reports"),
        "backup_dir": str(home / "backups"),
        "backup_enabled": "0",
        "backup_retention": "14",
        "operator_name": "Administrator",
        "page_size": "50",
        "last_backup_date": "",
        "scheduled_task_installed": "0",
    }


def _configure_connection(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.execute("PRAGMA temp_store = MEMORY")
        cursor.execute("PRAGMA cache_size = -65536")
        cursor.execute("PRAGMA mmap_size = 268435456")
        cursor.execute("PRAGMA journal_size_limit = 67108864")
    finally:
        cursor.close()


def create_db_engine(db_path: Path, *, echo: bool = False) -> Engine:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        future=True,
        echo=echo,
        connect_args={"timeout": 30, "check_same_thread": False},
        poolclass=NullPool,
    )
    event.listen(engine, "connect", _configure_connection)
    return engine


def read_user_version(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.exec_driver_sql("PRAGMA user_version").scalar() or 0)


def _set_user_version(conn, version: int) -> None:
    conn.exec_driver_sql(f"PRAGMA user_version = {int(version)}")


def _apply_baseline(engine: Engine) -> None:
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        version = int(conn.exec_driver_sql("PRAGMA user_version").scalar() or 0)
        if version < SCHEMA_VERSION:
            _set_user_version(conn, SCHEMA_VERSION)
            existing = conn.execute(
                text("SELECT COUNT(*) FROM schema_versions WHERE version = :v"), {"v": SCHEMA_VERSION}
            ).scalar()
            if not existing:
                conn.execute(
                    text(
                        "INSERT INTO schema_versions (version, applied_at, description) "
                        "VALUES (:v, :at, :desc)"
                    ),
                    {
                        "v": SCHEMA_VERSION,
                        "at": utc_now().isoformat(sep=" "),
                        "desc": "Baseline schema (products, sales, stock, reports, audit)",
                    },
                )


def migrate(engine: Engine) -> int:
    """Apply controlled, ordered schema migrations.

    New versions append a function to MIGRATIONS.  The baseline is created
    directly by SQLAlchemy metadata; later changes must be explicit SQL steps
    so existing installations upgrade safely.
    """
    current = read_user_version(engine)
    if current > SCHEMA_VERSION:
        raise StockKeepError(
            f"This database uses schema version {current}, but this build supports "
            f"version {SCHEMA_VERSION}. Please update StockKeep."
        )
    if current == 0:
        _apply_baseline(engine)
        current = SCHEMA_VERSION
    while current < SCHEMA_VERSION:
        current += 1
        migration = MIGRATIONS.get(current)
        if migration is None:
            raise StockKeepError(f"Missing migration for schema version {current}.")
        log.info("Applying database migration -> v%s", current)
        with engine.begin() as conn:
            migration(conn)
            _set_user_version(conn, current)
            conn.execute(
                text(
                    "INSERT INTO schema_versions (version, applied_at, description) "
                    "VALUES (:v, :at, :desc)"
                ),
                {"v": current, "at": utc_now().isoformat(sep=" "), "desc": migration.__doc__ or ""},
            )
    return read_user_version(engine)


# Ordered migrations for future releases.  Version 1 is the baseline.
def _migration_v2(conn) -> None:
    """Add user last-login tracking for role-based access."""
    columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)")}
    if "last_login_at" not in columns:
        conn.exec_driver_sql("ALTER TABLE users ADD COLUMN last_login_at DATETIME")


def _migration_v3(conn) -> None:
    """Add database-backed roles and seed the built-in permission sets."""
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS roles (
            key VARCHAR(40) NOT NULL PRIMARY KEY,
            name VARCHAR(80) NOT NULL,
            description VARCHAR(240) NOT NULL DEFAULT '',
            permissions_json TEXT NOT NULL DEFAULT '[]',
            is_system BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """
    )
    existing = {
        row[0] for row in conn.exec_driver_sql("SELECT key FROM roles").fetchall()
    }
    now = utc_now().isoformat(sep=" ")
    for key, definition in security.BUILTIN_ROLES.items():
        if key in existing:
            continue
        conn.execute(
            text(
                "INSERT INTO roles "
                "(key, name, description, permissions_json, is_system, created_at, updated_at) "
                "VALUES (:key, :name, :description, :permissions, :is_system, :created_at, :updated_at)"
            ),
            {
                "key": key,
                "name": definition.name,
                "description": definition.description,
                "permissions": json.dumps(sorted(definition.permissions)),
                "is_system": True,
                "created_at": now,
                "updated_at": now,
            },
        )


def _migration_v4(conn) -> None:
    """Give the built-in Owner read-only visibility of the Roles page."""
    row = conn.exec_driver_sql(
        "SELECT permissions_json FROM roles WHERE key = 'owner'"
    ).fetchone()
    if not row:
        return
    try:
        permissions = json.loads(row[0] or "[]")
    except (TypeError, ValueError):
        return
    if not isinstance(permissions, list) or security.P_ROLES_VIEW in permissions:
        return
    permissions.append(security.P_ROLES_VIEW)
    conn.execute(
        text(
            "UPDATE roles SET permissions_json = :permissions, "
            "updated_at = :updated_at WHERE key = 'owner'"
        ),
        {
            "permissions": json.dumps(sorted(set(permissions))),
            "updated_at": utc_now().isoformat(sep=" "),
        },
    )


MIGRATIONS: dict[int, object] = {2: _migration_v2, 3: _migration_v3, 4: _migration_v4}


def seed_database(engine: Engine, home: Path) -> None:
    with Session(engine, expire_on_commit=False) as session:
        if session.query(User).count() == 0:
            session.add(
                User(
                    name="Administrator",
                    username=DEFAULT_ADMIN_USERNAME,
                    role="admin",
                    is_active=True,
                )
            )
        existing = {row.key for row in session.query(Setting).all()}
        for key, value in default_settings(home).items():
            if key not in existing:
                session.add(Setting(key=key, value=value))
        roles_service.seed_builtin_roles(session)
        session.commit()
        roles_service.sync_security(session)


class Database:
    """Owns the SQLAlchemy engine and provides commit-or-rollback sessions."""

    def __init__(self, db_path: Path | str, *, echo: bool = False, initialize: bool = True):
        self.db_path = Path(db_path)
        self.echo = echo
        self.engine: Engine | None = None
        self.session_factory = None
        self._open(initialize=initialize)

    def _open(self, *, initialize: bool = True) -> None:
        self.engine = create_db_engine(self.db_path, echo=self.echo)
        if initialize:
            migrate(self.engine)
            seed_database(self.engine, self.db_path.parent.parent)
        self.session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, future=True, autoflush=False
        )

    def dispose(self) -> None:
        if self.engine is not None:
            self.engine.dispose()

    def close(self) -> None:
        self.dispose()

    def reopen(self) -> None:
        self.dispose()
        self._open(initialize=True)

    @contextmanager
    def session(self):
        if self.session_factory is None:
            raise StockKeepError("Database is not open.")
        session: Session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def connect(self):
        return self.engine.connect()

    def integrity_check(self) -> tuple[bool, str]:
        with self.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA integrity_check").scalar()
            fk = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        ok = str(result).lower() == "ok" and not fk
        detail = "ok" if ok else f"{result}; foreign key issues: {len(fk)}"
        return ok, detail

    def schema_version(self) -> int:
        return read_user_version(self.engine)

    def vacuum(self) -> None:
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql("VACUUM")

    def checkpoint(self) -> None:
        """Flush WAL into the main database file before a raw copy."""
        try:
            with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        except SQLAlchemyError:  # pragma: no cover - best effort
            log.warning("WAL checkpoint failed", exc_info=True)


def open_database(home: Path | str | None = None, *, db_path: Path | str | None = None) -> tuple[Database, AppPaths]:
    paths = ensure_dirs(home)
    target = Path(db_path) if db_path else paths.db_path
    database = Database(target)
    return database, paths


def sqlite_file_is_valid(path: Path) -> tuple[bool, str]:
    """Validate a candidate backup without touching the live database."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 512:
        return False, "The selected file is missing or too small to be a SQLite database."
    with open(path, "rb") as handle:
        header = handle.read(16)
    if header != b"SQLite format 3\x00":
        return False, "The selected file is not a SQLite database."
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        return False, f"SQLite could not read the file: {exc}"
    if result is None or str(result[0]).lower() != "ok":
        return False, f"Integrity check failed: {result[0] if result else 'unknown'}"
    required = {"products", "sales", "sale_items", "stock_movements", "settings"}
    if not required.issubset(tables):
        return False, "The file is a database but not a StockKeep database."
    return True, "ok"
