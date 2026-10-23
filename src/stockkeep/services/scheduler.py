"""Report scheduling, catch-up generation and Windows Task Scheduler support.

The GUI calls `generate_missing` on startup and periodically; the same code is
reachable from the command line (`--generate-reports`), so reports are not
dependent on the main window staying open.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import REPORT_COMPLETED, ReportJob
from ..timeutil import last_closed_business_date, today, utc_now
from . import reports
from .reports import ReportOutcome, daily_files_exist, generate_daily, report_status_rows
from .settings_service import AppSettings

log = logging.getLogger(__name__)

TASK_NAME = "StockKeep Daily Reports"
MAX_CATCHUP_DAYS = 400


@dataclass
class ReportConfig:
    report_root: Path
    tz_name: str = "Africa/Lagos"
    close_time: str = "23:59"
    currency_symbol: str = "\u20a6"
    business_name: str = "StockKeep"
    operator_id: int | None = None


def config_from_settings(settings: AppSettings, paths) -> ReportConfig:
    return ReportConfig(
        report_root=settings.report_root(paths),
        tz_name=settings.timezone,
        close_time=settings.close_time,
        currency_symbol=settings.currency_symbol,
        business_name=settings.business_name,
        operator_id=settings.operator_id,
    )


@dataclass
class ReportRunSummary:
    generated: int = 0
    skipped: int = 0
    failed: int = 0
    dates: list[date] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    locked: bool = False

    def message(self) -> str:
        if self.locked:
            return "Another report run is already in progress."
        return (
            f"{self.generated} generated, {self.skipped} already up to date, "
            f"{self.failed} failed."
        )


def due_dates(
    session: Session,
    *,
    tz_name: str,
    close_time: str,
    now: datetime | None = None,
) -> list[date]:
    """Business dates whose daily report should exist by `now`."""
    now = now or utc_now()
    last_closed = last_closed_business_date(now, tz_name, close_time)
    activity = reports.activity_dates(session)
    earliest = min(activity) if activity else last_closed
    if earliest > last_closed:
        earliest = last_closed
    if (last_closed - earliest).days + 1 > MAX_CATCHUP_DAYS:
        earliest = last_closed - timedelta(days=MAX_CATCHUP_DAYS - 1)
    days = []
    day = earliest
    while day <= last_closed:
        days.append(day)
        day += timedelta(days=1)
    return days


def missing_dates(
    database,
    config: ReportConfig,
    *,
    now: datetime | None = None,
) -> list[date]:
    now = now or utc_now()
    with database.session() as session:
        days = due_dates(
            session, tz_name=config.tz_name, close_time=config.close_time, now=now
        )
        jobs = {
            job.period_start: job
            for job in session.query(ReportJob)
            .filter(ReportJob.report_type == "daily")
            .all()
        }
    missing = []
    for day in days:
        job = jobs.get(day)
        if (
            job is None
            or job.status != REPORT_COMPLETED
            or not daily_files_exist(config.report_root, day)
        ):
            missing.append(day)
    return missing


@contextmanager
def report_lock(root: Path):
    """Best-effort cross-process lock preventing duplicate report jobs."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".report.lock"
    acquired = False
    handle = None
    try:
        try:
            if lock_path.exists() and (utc_now() - datetime.utcfromtimestamp(lock_path.stat().st_mtime)).total_seconds() > 1800:
                lock_path.unlink(missing_ok=True)
            handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(handle, f"{os.getpid()} {utc_now().isoformat()}".encode())
            acquired = True
        except FileExistsError:
            acquired = False
        yield acquired
    finally:
        if handle is not None:
            try:
                os.close(handle)
            except OSError:
                pass
        if acquired:
            lock_path.unlink(missing_ok=True)


def generate_missing(
    database,
    config: ReportConfig,
    *,
    now: datetime | None = None,
    progress=None,
    force: bool = False,
) -> ReportRunSummary:
    summary = ReportRunSummary()
    root = Path(config.report_root)
    with report_lock(root) as acquired:
        if not acquired:
            summary.locked = True
            return summary
        with database.session() as session:
            reports.recover_running_jobs(session)
            days = due_dates(
                session,
                tz_name=config.tz_name,
                close_time=config.close_time,
                now=now,
            )
            jobs = {
                job.period_start: job
                for job in session.query(ReportJob)
                .filter(ReportJob.report_type == "daily")
                .all()
            }
        targets = []
        for day in days:
            job = jobs.get(day)
            complete = (
                job is not None
                and job.status == REPORT_COMPLETED
                and daily_files_exist(root, day)
            )
            if force or not complete:
                targets.append(day)

        total = len(targets)
        for index, day in enumerate(targets, start=1):
            outcome = generate_daily(
                database,
                day,
                root,
                tz=config.tz_name,
                currency_symbol=config.currency_symbol,
                business_name=config.business_name,
                force=force,
                operator_id=config.operator_id,
            )
            summary.dates.append(day)
            if outcome.status == "generated":
                summary.generated += 1
            elif outcome.status == "skipped":
                summary.skipped += 1
            else:
                summary.failed += 1
                summary.errors.append(f"{day}: {outcome.error}")
            if progress:
                try:
                    progress(index, total)
                except Exception:
                    pass
        return summary


def run_for_date(
    database,
    config: ReportConfig,
    day: date,
    *,
    force: bool = True,
) -> ReportOutcome:
    return generate_daily(
        database,
        day,
        Path(config.report_root),
        tz=config.tz_name,
        currency_symbol=config.currency_symbol,
        business_name=config.business_name,
        force=force,
        operator_id=config.operator_id,
    )


def status_snapshot(database, config: ReportConfig, *, now: datetime | None = None) -> dict:
    with database.session() as session:
        jobs = report_status_rows(session, 90)
        last = reports.last_successful_report(session)
        last_closed = last_closed_business_date(
            now or utc_now(), config.tz_name, config.close_time
        )
    missing = missing_dates(database, config, now=now)
    return {
        "jobs": jobs,
        "last": last,
        "missing": missing,
        "last_closed": last_closed,
        "total_missing": len(missing),
    }


# ---------------------------------------------------------------------------
# Windows Task Scheduler
# ---------------------------------------------------------------------------
def _pythonw() -> str:
    executable = Path(sys.executable)
    candidate = executable.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else executable)


def _hidden_console() -> dict:
    """Keep helper processes (schtasks) from flashing a console window."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def scheduled_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --generate-reports'
    root = Path(__file__).resolve().parents[3]
    run_py = root / "run.py"
    if run_py.exists():
        return f'"{_pythonw()}" "{run_py}" --generate-reports'
    return f'"{_pythonw()}" -m stockkeep --generate-reports'


def install_scheduled_task(close_time: str = "23:59", task_name: str = TASK_NAME) -> tuple[bool, str]:
    if not sys.platform.startswith("win"):
        return False, "Windows Task Scheduler is only available on Windows."
    command = scheduled_command()
    try:
        completed = subprocess.run(
            [
                "schtasks",
                "/Create",
                "/F",
                "/SC",
                "DAILY",
                "/ST",
                close_time,
                "/TN",
                task_name,
                "/TR",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            **_hidden_console(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not run schtasks: {exc}"
    if completed.returncode == 0:
        return True, f"Scheduled task '{task_name}' will run daily at {close_time}."
    message = (completed.stderr or completed.stdout or "unknown error").strip()
    return False, f"Task could not be created: {message}"


def remove_scheduled_task(task_name: str = TASK_NAME) -> tuple[bool, str]:
    if not sys.platform.startswith("win"):
        return False, "Windows Task Scheduler is only available on Windows."
    try:
        completed = subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", task_name],
            capture_output=True,
            text=True,
            timeout=30,
            **_hidden_console(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not run schtasks: {exc}"
    if completed.returncode == 0:
        return True, "Scheduled task removed."
    return False, (completed.stderr or completed.stdout or "Task not found.").strip()


def scheduled_task_status(task_name: str = TASK_NAME) -> tuple[bool, str]:
    if not sys.platform.startswith("win"):
        return False, "Not supported on this operating system."
    try:
        completed = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST"],
            capture_output=True,
            text=True,
            timeout=30,
            **_hidden_console(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not query the task: {exc}"
    if completed.returncode == 0:
        details = completed.stdout.strip()
        return True, details or "Task installed."
    return False, "Daily report task is not installed."


def cli_generate(database, config: ReportConfig, *, force: bool = False, day: date | None = None) -> int:
    if day is not None:
        outcome = run_for_date(database, config, day, force=force)
        print(f"{day.isoformat()}: {outcome.status}")
        if outcome.error:
            print(f"  error: {outcome.error}")
        return 0 if outcome.ok else 1
    summary = generate_missing(database, config, force=force)
    print(summary.message())
    for error in summary.errors:
        print(f"  {error}")
    return 0 if summary.failed == 0 and not summary.locked else 1
