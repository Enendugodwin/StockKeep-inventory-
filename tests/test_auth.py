"""Tests for authentication, password hashing and role-based access."""

from __future__ import annotations

import pytest

from stockkeep import security
from stockkeep.errors import PermissionDenied, ValidationError
from stockkeep.models import AuditEvent, User
from stockkeep.services import auth_service


@pytest.fixture(autouse=True)
def reset_actor():
    security.set_actor(None)
    yield
    security.set_actor(None)


def _admin(db, username="admin", password="correct horse battery"):
    with db.session() as session:
        return auth_service.create_initial_admin(
            session, username=username, name="Administrator", password=password
        )


def test_fresh_database_needs_setup_and_seeds_admin(db):
    with db.session() as session:
        assert auth_service.needs_setup(session) is True
        admins = session.query(User).filter(User.role == security.ROLE_ADMIN).all()
        assert len(admins) == 1
        assert admins[0].username == "admin"
        assert admins[0].password_hash is None
    assert db.schema_version() == 4


def test_password_hash_round_trip():
    encoded = security.hash_password("s3cret-pass")
    assert encoded.startswith("pbkdf2_sha256$")
    assert security.verify_password("s3cret-pass", encoded)
    assert not security.verify_password("wrong", encoded)
    assert not security.verify_password("s3cret-pass", None)
    assert not security.verify_password("s3cret-pass", "garbage")


def test_create_initial_admin_and_authenticate(db):
    admin = _admin(db)
    with db.session() as session:
        assert auth_service.needs_setup(session) is False
        assert auth_service.authenticate(session, "ADMIN", "correct horse battery") is not None
        assert auth_service.authenticate(session, "admin", "wrong-password") is None
        assert auth_service.authenticate(session, "nobody", "whatever") is None

        stored = session.get(User, admin.id)
        assert stored.password_hash != "correct horse battery"
        assert stored.last_login_at is not None
        session.flush()
        actions = {row.action for row in session.query(AuditEvent).all()}
        assert {"auth.setup", "auth.login"} <= actions
        for event in session.query(AuditEvent).all():
            assert "correct horse battery" not in (event.details_json or "")


def test_short_password_is_rejected(db):
    with db.session() as session:
        with pytest.raises(ValidationError):
            auth_service.create_initial_admin(
                session, username="admin", name="Administrator", password="short"
            )


def test_inactive_account_cannot_authenticate(db):
    admin = _admin(db)
    with db.session() as session:
        user = session.get(User, admin.id)
        user.is_active = False
        session.flush()
        assert auth_service.authenticate(session, "admin", "correct horse battery") is None


def test_setup_retires_passwordless_legacy_accounts(db):
    with db.session() as session:
        session.add(User(name="Operator", username="operator", role="owner", is_active=True))
        session.flush()
    _admin(db)
    with db.session() as session:
        legacy = session.query(User).filter(User.username == "operator").one()
        assert legacy.is_active is False


def test_role_permission_matrix():
    assert security.ROLE_PERMISSIONS[security.ROLE_ADMIN] == security.ALL_PERMISSIONS
    owner = security.ROLE_PERMISSIONS[security.ROLE_OWNER]
    assert security.P_INVENTORY_EDIT in owner
    assert security.P_INVENTORY_IMPORT in owner
    assert security.P_SALES_CREATE in owner
    assert security.P_SALES_VIEW in owner
    assert security.P_SALES_REFUND in owner
    assert security.P_USERS_VIEW in owner
    assert security.P_ROLES_VIEW in owner
    assert security.P_SETTINGS_MANAGE not in owner
    assert security.P_AUDIT_VIEW not in owner
    assert security.P_USERS_MANAGE not in owner
    assert security.P_ROLES_MANAGE not in owner
    assert security.P_BACKUP_MANAGE not in owner
    staff = security.ROLE_PERMISSIONS[security.ROLE_STAFF]
    assert staff == {
        security.P_DASHBOARD,
        security.P_SALES_CREATE,
        security.P_SALES_VIEW,
    }
    assert security.P_SALES_REFUND not in staff
    assert security.P_SETTINGS_MANAGE not in staff


def test_owner_cannot_manage_users(db):
    admin = _admin(db)
    security.set_actor(
        security.Actor(id=2, username="owner", name="Owner", role=security.ROLE_OWNER)
    )
    with db.session() as session:
        with pytest.raises(PermissionDenied):
            auth_service.create_user(
                session,
                username="new",
                name="New User",
                role=security.ROLE_STAFF,
                password="password123",
                operator_id=2,
            )


def test_admin_accounts_cannot_remove_the_last_admin(db):
    admin = _admin(db)
    security.set_actor(
        security.Actor(id=admin.id, username="admin", name="Administrator", role=security.ROLE_ADMIN)
    )
    with db.session() as session:
        with pytest.raises(ValidationError):
            auth_service.update_user(
                session,
                admin.id,
                username="admin",
                name="Administrator",
                role=security.ROLE_OWNER,
                is_active=True,
                operator_id=None,
            )
        with pytest.raises(ValidationError):
            auth_service.update_user(
                session,
                admin.id,
                username="admin",
                name="Administrator",
                role=security.ROLE_ADMIN,
                is_active=False,
                operator_id=admin.id,
            )


def test_duplicate_usernames_are_case_insensitive(db):
    _admin(db)
    with db.session() as session:
        with pytest.raises(ValidationError):
            auth_service.create_user(
                session,
                username="ADMIN",
                name="Another",
                role=security.ROLE_STAFF,
                password="password123",
            )


def test_create_update_and_password_reset(db):
    admin = _admin(db)
    security.set_actor(
        security.Actor(id=admin.id, username="admin", name="Administrator", role=security.ROLE_ADMIN)
    )
    with db.session() as session:
        user = auth_service.create_user(
            session,
            username="ada",
            name="Ada Okafor",
            role=security.ROLE_STAFF,
            password="cashier-pass",
        )
        user_id = user.id
        auth_service.reset_password(session, user_id, "new-cashier-pass", operator_id=admin.id)
        session.flush()
        assert auth_service.authenticate(session, "ada", "cashier-pass") is None
        assert auth_service.authenticate(session, "ada", "new-cashier-pass") is not None
        auth_service.change_own_password(session, user_id, "new-cashier-pass", "third-pass-123")
        session.flush()
        assert auth_service.authenticate(session, "ada", "third-pass-123") is not None


def test_cannot_deactivate_self(db):
    admin = _admin(db)
    security.set_actor(
        security.Actor(id=admin.id, username="admin", name="Administrator", role=security.ROLE_ADMIN)
    )
    with db.session() as session:
        with pytest.raises(ValidationError):
            auth_service.update_user(
                session,
                admin.id,
                username="admin",
                name="Administrator",
                role=security.ROLE_ADMIN,
                is_active=False,
                operator_id=admin.id,
            )
