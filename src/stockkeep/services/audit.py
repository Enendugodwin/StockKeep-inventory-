"""Audit trail helpers.  Audit rows are append-only from the UI's perspective."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditEvent


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items() if "password" not in str(k).lower()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def record(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    *,
    operator_id: int | None = None,
    reason: str | None = None,
    details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        operator_id=operator_id,
        reason=reason,
        details_json=json.dumps(_json_safe(details or {}), ensure_ascii=False, default=str),
    )
    session.add(event)
    return event


def list_events(
    session: Session,
    *,
    start=None,
    end=None,
    search: str = "",
    limit: int = 300,
    offset: int = 0,
) -> tuple[list[AuditEvent], int]:
    from sqlalchemy import func, or_

    query = session.query(AuditEvent)
    if start is not None:
        query = query.filter(func.date(AuditEvent.created_at) >= start.isoformat())
    if end is not None:
        query = query.filter(func.date(AuditEvent.created_at) <= end.isoformat())
    term = (search or "").strip()
    if term:
        pattern = f"%{term}%"
        query = query.filter(
            or_(
                AuditEvent.action.ilike(pattern),
                AuditEvent.entity_type.ilike(pattern),
                AuditEvent.entity_id.ilike(pattern),
                AuditEvent.reason.ilike(pattern),
                AuditEvent.details_json.ilike(pattern),
            )
        )
    total = query.count()
    rows = (
        query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset(max(0, offset))
        .limit(max(1, min(1000, limit)))
        .all()
    )
    return rows, total
