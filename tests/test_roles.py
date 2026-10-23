"""Tests for database-backed roles, custom permissions and migration."""

from __future__ import annotations

import pytest

from stockkeep import security
from stockkeep.errors import PermissionDenied, ValidationError
from stockkeep.models import Role, User
from stockkeep.services import auth_service, roles_service


@pytest.fixture(autouse=True)
def reset_actor():
    security.set_actor(None)
    yield
    security.set_actor(None)


def _admin(db):
    with db.session() as session:
        user = auth_service.create_initial_admin(
            session,
            username="admin",
            name="Administrator",
            password="correct horse battery",
        )
        security.set_actor(
            security.Actor(
                id=user.id,
                username=user.username,
                name=user.name,
                role=user.role,
            )
        )
        user_id = user.id
    return user_id


def test_builtin_roles_are_seeded_and_loaded(db):
    with db.session() as session:
        roles = roles_service.list_roles(session)
        keys = {role.key for role in roles}
        assert keys == {security.ROLE_ADMIN, security.ROLE_OWNER, security.ROLE_STAFF}
        assert session.query(Role).count() == 3
        assert auth_service.needs_setup(session) is True

    assert security.role_label(security.ROLE_OWNER) == "Owner"
    owner = security.permissions_for(security.ROLE_OWNER)
    assert security.P_SALES_VIEW in owner
    assert security.P_SALES_CREATE in owner
    assert security.P_USERS_VIEW in owner
    assert security.P_ROLES_VIEW in owner
    assert security.P_ROLES_MANAGE not in owner
    assert security.P_SETTINGS_MANAGE not in owner
    assert security.P_AUDIT_VIEW not in owner
    staff = security.permissions_for(security.ROLE_STAFF)
    assert {security.P_DASHBOARD, security.P_SALES_CREATE, security.P_SALES_VIEW} == staff


def test_admin_can_create_a_custom_role_and_assign_it(db):
    admin_id = _admin(db)
    with db.session() as session:
        role = roles_service.create_role(
            session,
            name="Floor supervisor",
            description="Sees inventory and transaction history.",
            permissions=[security.P_INVENTORY_VIEW, security.P_SALES_VIEW],
            operator_id=admin_id,
        )
        key = role.key
        assert key == "floor_supervisor"
        assert security.is_known_role(key)
        assert security.role_label(key) == "Floor supervisor"
        assert security.permissions_for(key) == {
            security.P_INVENTORY_VIEW,
            security.P_SALES_VIEW,
        }

        user = auth_service.create_user(
            session,
            username="supervisor",
            name="Floor Supervisor",
            role=key,
            password="supervisor-pass",
        )
        assert user.role == key
        assert auth_service.authenticate(session, "supervisor", "supervisor-pass") is not None

    security.set_actor(
        security.Actor(id=user.id, username="supervisor", name="Floor Supervisor", role=key)
    )
    assert security.has_permission(security.P_INVENTORY_VIEW)
    assert not security.has_permission(security.P_INVENTORY_EDIT)
    assert not security.has_permission(security.P_USERS_VIEW)


def test_owner_and_staff_builtin_permissions_are_editable_but_names_are_fixed(db):
    admin_id = _admin(db)
    with db.session() as session:
        role = roles_service.update_role(
            session,
            security.ROLE_STAFF,
            name="Renamed",
            description="Changed",
            permissions=[security.P_DASHBOARD, security.P_SALES_VIEW],
            operator_id=admin_id,
        )
        assert role.name == "Base user"
        assert role.description == security.BUILTIN_ROLES[security.ROLE_STAFF].description
        assert security.permissions_for(security.ROLE_STAFF) == {
            security.P_DASHBOARD,
            security.P_SALES_VIEW,
        }
        assert security.role_label(security.ROLE_STAFF) == "Base user"


def test_admin_role_cannot_be_edited_or_deleted(db):
    admin_id = _admin(db)
    with db.session() as session:
        with pytest.raises(ValidationError):
            roles_service.update_role(
                session,
                security.ROLE_ADMIN,
                permissions=[security.P_DASHBOARD],
                operator_id=admin_id,
            )
        with pytest.raises(ValidationError):
            roles_service.delete_role(session, security.ROLE_ADMIN, operator_id=admin_id)


def test_custom_role_in_use_cannot_be_deleted_until_reassigned(db):
    admin_id = _admin(db)
    with db.session() as session:
        role = roles_service.create_role(
            session,
            name="Temporary",
            permissions=[security.P_INVENTORY_VIEW],
            operator_id=admin_id,
        )
        user = auth_service.create_user(
            session,
            username="temporary",
            name="Temporary User",
            role=role.key,
            password="temporary-pass",
        )
        user_id = user.id
        with pytest.raises(ValidationError):
            roles_service.delete_role(session, role.key, operator_id=admin_id)
        auth_service.update_user(
            session,
            user_id,
            username=user.username,
            name=user.name,
            role=security.ROLE_STAFF,
            is_active=True,
            operator_id=admin_id,
        )
        roles_service.delete_role(session, role.key, operator_id=admin_id)
        assert session.get(Role, role.key) is None
        assert not security.is_known_role(role.key)


def test_owner_cannot_create_roles(db):
    _admin(db)
    security.set_actor(
        security.Actor(id=2, username="owner", name="Owner", role=security.ROLE_OWNER)
    )
    with db.session() as session:
        with pytest.raises(PermissionDenied):
            roles_service.create_role(
                session,
                name="Rogue",
                permissions=[security.P_SETTINGS_MANAGE],
                operator_id=2,
            )


def test_permission_implications_and_unknown_permissions_are_dropped():
    permissions = security.normalize_permissions(
        [
            security.P_SALES_REFUND,
            security.P_USERS_MANAGE,
            "unknown.permission",
        ]
    )
    assert security.P_SALES_VIEW in permissions
    assert security.P_USERS_VIEW in permissions
    assert "unknown.permission" not in permissions
