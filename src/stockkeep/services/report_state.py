"""Report job state helpers used by sales, stock and import services."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ..models import REPORT_COMPLETED, REPORT_PENDING, REPORT_STALE, ReportJob


def mark_daily_dirty(session: Session, day: date) -> None:
    """Mark an existing completed daily report for regeneration.

    A missing job needs no action: catch-up scanning treats the absence of a
    completed report as work to do.
    """
    jobs = (
        session.query(ReportJob)
        .filter(
            ReportJob.report_type == "daily",
            ReportJob.period_start <= day,
            ReportJob.period_end >= day,
        )
        .all()
    )
    for job in jobs:
        if job.status == REPORT_COMPLETED:
            job.status = REPORT_STALE


def mark_all_daily_stale(session: Session) -> None:
    for job in session.query(ReportJob).filter(ReportJob.report_type == "daily").all():
        if job.status == REPORT_COMPLETED:
            job.status = REPORT_STALE


def ensure_daily_job(session: Session, day: date) -> ReportJob:
    job = (
        session.query(ReportJob)
        .filter(
            ReportJob.report_type == "daily",
            ReportJob.period_start == day,
            ReportJob.period_end == day,
            ReportJob.format == "bundle",
        )
        .one_or_none()
    )
    if job is None:
        job = ReportJob(
            report_type="daily",
            period_start=day,
            period_end=day,
            format="bundle",
            status=REPORT_PENDING,
        )
        session.add(job)
        session.flush()
    return job
