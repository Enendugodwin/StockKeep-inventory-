"""User accounts, first-run setup and login.

Passwords are never stored in plain text: `security.hash_password` produces a
salted PBKDF2-SHA256 digest.  Audit entries record account changes but never
passwords or password hashes.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import security
from ..errors import NotFoundError, ValidationError
from ..models import User
from ..timeutil import utc_now
from . import audit, roles_service


def _clean_username(value: str) -> str:
    username = str(value or "").strip()
    if not username:
        raise ValidationError("Username is required.", "username")
    if len(username) > 80:
        raise ValidationError("Username is too long (maximum 80 characters).", "username")
    if any(ch.isspace() for ch in username):
        raise ValidationError("Username cannot contain spaces.", "username")
    return username


def _clean_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValidationError("Full name is required.", "name")
    if len(name) > 120:
        raise ValidationError("Full name is too long (maximum 120 characters).", "name")
    return name


def validate_password(password: str) -> str:
    password = str(password or "")
    if len(password) < security.MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {security.MIN_PASSWORD_LENGTH} characters.",
            "password",
        )
    if len(password) > 200:
        raise ValidationError("Password is too long (maximum 200 characters).", "password")
    return password


def _validate_role(role: str) -> str:
    if not security.is_known_role(role):
        raise ValidationError("Unknown role.", "role")
    return role


def _assert_can_handle_admin_account(target_role: str) -> None:
    """Only an administrator may create, reset or edit an administrator account."""
    actor = security.current_actor()
    if actor is None or actor.role == security.ROLE_ADMIN:
        return
    if target_role == security.ROLE_ADMIN:
        raise security.PermissionDenied(
            "Only an administrator can manage an administrator account."
        )


def _find_username(session: Session, username: str, *, exclude_id: int | None = None) -> User | None:
    query = session.query(User).filter(func.lower(User.username) == username.lower())
    if exclude_id is not None:
        query = query.filter(User.id != exclude_id)
    return query.first()


def _assert_username_free(session: Session, username: str, *, exclude_id: int | None = None) -> None:
    if _find_username(session, username, exclude_id=exclude_id) is not None:
        raise ValidationError("That username is already in use.", "username")


def _active_admin_count(session: Session) -> int:
    return (
        session.query(User)
        .filter(
            User.role == security.ROLE_ADMIN,
            User.is_active.is_(True),
            User.password_hash.isnot(None),
        )
        .count()
    )


def needs_setup(session: Session) -> bool:
    """True when no usable administrator account exists yet."""
    return _active_admin_count(session) == 0


def list_users(session: Session) -> list[User]:
    return session.query(User).order_by(User.name.asc(), User.id.asc()).all()


def get_user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError("User account not found.")
    return user


def authenticate(session: Session, username: str, password: str) -> User | None:
    """Return the matching active user, or None for invalid credentials."""
    roles_service.sync_security(session)
    username = str(username or "").strip()
    user = (
        session.query(User)
        .filter(func.lower(User.username) == username.lower())
        .one_or_none()
    )
    if user is None:
        security.verify_dummy(password)
        return None
    if not security.verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    user.last_login_at = utc_now()
    audit.record(
        session,
        "auth.login",
        "user",
        user.id,
        operator_id=user.id,
        details={"username": user.username, "role": user.role},
    )
    return user


def create_initial_admin(
    session: Session,
    *,
    username: str,
    name: str,
    password: str,
) -> User:
    """Create (or claim) the first administrator during first-run setup."""
    if not needs_setup(session):
        raise ValidationError(
            "An administrator account already exists. Sign in instead.",
            "setup",
        )
    username = _clean_username(username)
    name = _clean_name(name)
    validate_password(password)

    user = _find_username(session, username)
    if user is None:
        user = User(username=username, role=security.ROLE_ADMIN, is_active=True)
        session.add(user)
    user.name = name
    user.username = username
    user.role = security.ROLE_ADMIN
    user.is_active = True
    user.password_hash = security.hash_password(password)
    user.last_login_at = utc_now()
    session.flush()

    # Legacy databases seeded a passwordless "operator" account.  Retire any
    # account that was never given a password so the user list stays clean.
    for other in session.query(User).filter(User.password_hash.is_(None)).all():
        if other.id != user.id:
            other.is_active = False

    audit.record(
        session,
        "auth.setup",
        "user",
        user.id,
        operator_id=user.id,
        details={"username": user.username, "role": user.role},
    )
    return user


def create_user(
    session: Session,
    *,
    username: str,
    name: str,
    role: str,
    password: str,
    is_active: bool = True,
    operator_id: int | None = None,
) -> User:
    security.require(security.P_USERS_MANAGE)
    username = _clean_username(username)
    name = _clean_name(name)
    role = _validate_role(role)
    _assert_can_handle_admin_account(role)
    validate_password(password)
    _assert_username_free(session, username)

    user = User(
        username=username,
        name=name,
        role=role,
        is_active=bool(is_active),
        password_hash=security.hash_password(password),
    )
    session.add(user)
    session.flush()
    audit.record(
        session,
        "user.created",
        "user",
        user.id,
        operator_id=operator_id,
        details={"username": user.username, "role": user.role, "active": user.is_active},
    )
    return user


def update_user(
    session: Session,
    user_id: int,
    *,
    username: str,
    name: str,
    role: str,
    is_active: bool,
    operator_id: int | None = None,
) -> User:
    security.require(security.P_USERS_MANAGE)
    user = get_user(session, user_id)
    username = _clean_username(username)
    name = _clean_name(name)
    role = _validate_role(role)
    _assert_can_handle_admin_account(user.role)
    _assert_can_handle_admin_account(role)
    _assert_username_free(session, username, exclude_id=user.id)

    if user.id == operator_id and not is_active:
        raise ValidationError("You cannot deactivate your own account.", "is_active")
    if user.id == operator_id and role != security.ROLE_ADMIN and user.role == security.ROLE_ADMIN:
        raise ValidationError("You cannot change your own administrator role.", "role")

    losing_admin = (
        user.role == security.ROLE_ADMIN
        and user.is_active
        and (role != security.ROLE_ADMIN or not is_active)
    )
    if losing_admin and _active_admin_count(session) <= 1:
        raise ValidationError("At least one active administrator must remain.", "role")

    before = {
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "active": user.is_active,
    }
    user.username = username
    user.name = name
    user.role = role
    user.is_active = bool(is_active)
    session.flush()
    audit.record(
        session,
        "user.updated",
        "user",
        user.id,
        operator_id=operator_id,
        details={
            "before": before,
            "after": {
                "username": user.username,
                "name": user.name,
                "role": user.role,
                "active": user.is_active,
            },
        },
    )
    return user


def reset_password(
    session: Session,
    user_id: int,
    password: str,
    *,
    operator_id: int | None = None,
) -> None:
    security.require(security.P_USERS_MANAGE)
    user = get_user(session, user_id)
    _assert_can_handle_admin_account(user.role)
    validate_password(password)
    user.password_hash = security.hash_password(password)
    audit.record(
        session,
        "user.password_reset",
        "user",
        user.id,
        operator_id=operator_id,
        details={"username": user.username},
    )


def change_own_password(
    session: Session,
    user_id: int,
    current_password: str,
    new_password: str,
) -> None:
    """Self-service password change used by the signed-in user."""
    user = get_user(session, user_id)
    if not security.verify_password(current_password, user.password_hash):
        raise ValidationError("The current password is incorrect.", "current_password")
    validate_password(new_password)
    user.password_hash = security.hash_password(new_password)
    audit.record(
        session,
        "user.password_changed",
        "user",
        user.id,
        operator_id=user.id,
        details={"username": user.username},
    )
