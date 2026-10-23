# Contributing to StockKeep

Thanks for helping improve StockKeep.  This is a native Windows desktop app
(PySide6 + SQLite), not a web application.

## Development setup

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-dev.txt
python run.py
```

The development launcher uses the project root as its portable data folder.
Business data lives in `database/`, `reports/`, `backups/`, `logs/`, `config/`
and `exports/`; these directories are ignored by git.

## Tests

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m pytest tests -q

$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python.exe tools\ui_smoke.py
```

Please run both before opening a pull request.  Add or update tests for every
behaviour change.

## Database changes

- `src/stockkeep/db.py` owns the schema version and migrations.
- Bump `SCHEMA_VERSION` and add a migration for every schema change.
- Never edit an existing released migration; add a new step instead.
- Migrations run automatically when the database is opened.

## Roles and permissions

- Permission constants and the built-in defaults live in
  `src/stockkeep/security.py`.
- Custom roles are stored in the `roles` table and loaded into the in-memory
  registry by `src/stockkeep/services/roles_service.py`.
- Guard service functions with `security.require(...)`; hide or disable UI that
  the role cannot use.
- Role management is Admin-only by design.  Do not add a route that lets a
  non-admin grant themselves permissions.

## Commits

Keep commits focused.  Do not commit databases, reports, backups, logs,
generated bundles, installers, virtual environments or secrets.  The
`.gitignore` enforces this; please keep it that way.
