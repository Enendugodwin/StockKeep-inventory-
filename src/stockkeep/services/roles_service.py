"""Custom roles and permission sets.

Built-in roles live in :mod:`stockkeep.security` as defaults.  This service
copies them into the database on first run, loads all roles into the in-memory
registry used by permission checks, and implements the Admin-only role editor.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import security
from ..errors import NotFoundError, ValidationError
from ..models import Role, User
from . import audit


def _clean_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValidationError("Role name is required.", "name")
    if len(name) > 80:
        raise ValidationError("Role name is too long (maximum 80 characters).", "name")
    return name


def _clean_description(value: str | None) -> str:
    description = str(value or "").strip()
    if len(description) > 240:
        raise ValidationError(
            "Description is too long (maximum 240 characters).", "description"
        )
    return description


def _clean_permissions(values) -> frozenset[str]:
    permissions = security.normalize_permissions(values or ())
    if not permissions:
        raise ValidationError("Select at least one permission for the role.", "permissions")
    return permissions


def _serialize(permissions) -> str:
    return json.dumps(sorted(permissions), ensure_ascii=False)


def _deserialize(raw: str | None) -> frozenset[str]:
    try:
        values = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return frozenset()
    if not isinstance(values, list):
        return frozenset()
    return security.normalize_permissions(values)


def _definition(row: Role) -> security.RoleDefinition:
    return security.RoleDefinition(
        key=row.key,
        name=row.name,
        description=row.description,
        permissions=_deserialize(row.permissions_json),
        is_system=bool(row.is_system),
        editable=row.key != security.ROLE_ADMIN,
    )


def _assert_name_free(session: Session, name: str, *, exclude_key: str | None = None) -> None:
    query = session.query(Role).filter(func.lower(Role.name) == name.lower())
    if exclude_key is not None:
        query = query.filter(Role.key != exclude_key)
    if query.first() is not None:
        raise ValidationError("A role with that name already exists.", "name")


def _unique_key(session: Session, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "role"
    key = base
    suffix = 2
    while session.get(Role, key) is not None or key in security.BUILTIN_ROLES:
        key = f"{base[:34]}_{suffix}"
        suffix += 1
    return key


def seed_builtin_roles(session: Session) -> None:
    """Insert any missing built-in roles without overwriting customisations."""
    existing = {row.key for row in session.query(Role).all()}
    for key, definition in security.BUILTIN_ROLES.items():
        if key in existing:
            continue
        session.add(
            Role(
                key=key,
                name=definition.name,
                description=definition.description,
                permissions_json=_serialize(definition.permissions),
                is_system=True,
            )
        )
    session.flush()


def sync_security(session: Session) -> None:
    """Load every role row into the registry used by ``Actor.can``."""
    security.set_role_definitions(_definition(row) for row in session.query(Role).all())


def list_roles(session: Session) -> list[Role]:
    return (
        session.query(Role)
        .order_by(Role.is_system.desc(), Role.name.asc())
        .all()
    )


def get_role(session: Session, key: str) -> Role:
    role = session.get(Role, key)
    if role is None:
        raise NotFoundError("Role not found.")
    return role


def user_count(session: Session, key: str) -> int:
    return session.query(User).filter(User.role == key).count()


def role_permissions(session: Session, key: str) -> frozenset[str]:
    return _deserialize(get_role(session, key).permissions_json)


def create_role(
    session: Session,
    *,
    name: str,
    description: str = "",
    permissions,
    operator_id: int | None = None,
) -> Role:
    security.require(security.P_ROLES_MANAGE)
    name = _clean_name(name)
    description = _clean_description(description)
    permissions = _clean_permissions(permissions)
    _assert_name_free(session, name)
    key = _unique_key(session, name)

    role = Role(
        key=key,
        name=name,
        description=description,
        permissions_json=_serialize(permissions),
        is_system=False,
    )
    session.add(role)
    session.flush()
    sync_security(session)
    audit.record(
        session,
        "role.created",
        "role",
        key,
        operator_id=operator_id,
        details={
            "name": name,
            "permissions": sorted(permissions),
            "is_system": False,
        },
    )
    return role


def update_role(
    session: Session,
    key: str,
    *,
    name: str | None = None,
    description: str | None = None,
    permissions,
    operator_id: int | None = None,
) -> Role:
    security.require(security.P_ROLES_MANAGE)
    role = get_role(session, key)
    if role.key == security.ROLE_ADMIN:
        raise ValidationError(
            "The Admin role always has every permission and cannot be changed.", "role"
        )

    before_permissions = _deserialize(role.permissions_json)
    before = {
        "name": role.name,
        "description": role.description,
        "permissions": sorted(before_permissions),
    }

    if role.is_system:
        # Built-in Owner/Base role names and descriptions are fixed; only the
        # permission set is editable by an administrator.
        clean_name = role.name
        clean_description = role.description
    else:
        clean_name = _clean_name(name if name is not None else role.name)
        clean_description = _clean_description(
            description if description is not None else role.description
        )
        _assert_name_free(session, clean_name, exclude_key=role.key)

    permissions = _clean_permissions(permissions)
    actor = security.current_actor()
    if (
        actor is not None
        and actor.role == role.key
        and security.P_ROLES_MANAGE in before_permissions
        and security.P_ROLES_MANAGE not in permissions
    ):
        raise ValidationError(
            "You cannot remove role-management access from your own role. "
            "Ask another administrator to do it.",
            "permissions",
        )

    role.name = clean_name
    role.description = clean_description
    role.permissions_json = _serialize(permissions)
    session.flush()
    sync_security(session)
    audit.record(
        session,
        "role.updated",
        "role",
        role.key,
        operator_id=operator_id,
        details={
            "before": before,
            "after": {
                "name": role.name,
                "description": role.description,
                "permissions": sorted(permissions),
            },
        },
    )
    return role


def delete_role(
    session: Session,
    key: str,
    *,
    operator_id: int | None = None,
) -> None:
    security.require(security.P_ROLES_MANAGE)
    role = get_role(session, key)
    if role.is_system:
        raise ValidationError("Built-in roles cannot be deleted.", "role")
    assigned = user_count(session, role.key)
    if assigned:
        raise ValidationError(
            f"{assigned} account(s) still use this role. Move them to another role first.",
            "role",
        )
    details = {
        "name": role.name,
        "description": role.description,
        "permissions": sorted(_deserialize(role.permissions_json)),
    }
    session.delete(role)
    session.flush()
    sync_security(session)
    audit.record(
        session,
        "role.deleted",
        "role",
        key,
        operator_id=operator_id,
        details=details,
    )
