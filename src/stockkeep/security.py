"""Role-based access control and password hashing.

StockKeep is a local desktop application, but different people share the same
PC.  This module defines the three roles and the permissions they grant, keeps
the signed-in actor (the single source of truth for permission checks), and
provides salted PBKDF2 password hashing.

Permissions are enforced twice: navigation/actions in the UI and the primary
mutating service functions.  When no actor is set (unit tests, CLI report jobs,
and the headless tooling) the system context is allowed to proceed.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from .errors import PermissionDenied

# Roles ---------------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"
ROLE_STAFF = "staff"

# Permissions ---------------------------------------------------------------
P_DASHBOARD = "dashboard.view"
P_INVENTORY_VIEW = "inventory.view"
P_INVENTORY_EDIT = "inventory.edit"
P_INVENTORY_IMPORT = "inventory.import"
P_STOCK_RECEIVE = "stock.receive"
P_STOCK_ADJUST = "stock.adjust"
P_SALES_CREATE = "sales.create"
P_SALES_VIEW = "sales.view"
P_SALES_REFUND = "sales.refund"
P_REPORTS_VIEW = "reports.view"
P_REPORTS_MANAGE = "reports.manage"
P_MONTHLY_VIEW = "monthly.view"
P_AUDIT_VIEW = "audit.view"
P_USERS_VIEW = "users.view"
P_USERS_MANAGE = "users.manage"
P_ROLES_VIEW = "roles.view"
P_ROLES_MANAGE = "roles.manage"
P_SETTINGS_MANAGE = "settings.manage"
P_BACKUP_MANAGE = "backup.manage"

ALL_PERMISSIONS = frozenset(
    {
        P_DASHBOARD,
        P_INVENTORY_VIEW,
        P_INVENTORY_EDIT,
        P_INVENTORY_IMPORT,
        P_STOCK_RECEIVE,
        P_STOCK_ADJUST,
        P_SALES_CREATE,
        P_SALES_VIEW,
        P_SALES_REFUND,
        P_REPORTS_VIEW,
        P_REPORTS_MANAGE,
        P_MONTHLY_VIEW,
        P_AUDIT_VIEW,
        P_USERS_VIEW,
        P_USERS_MANAGE,
        P_ROLES_VIEW,
        P_ROLES_MANAGE,
        P_SETTINGS_MANAGE,
        P_BACKUP_MANAGE,
    }
)

# Human-readable labels used by the role editor.
PERMISSION_LABELS: dict[str, tuple[str, str]] = {
    P_DASHBOARD: ("Dashboard", "See sales KPIs, stock alerts, recent activity and quick actions."),
    P_INVENTORY_VIEW: ("View inventory", "Open the inventory list and product history."),
    P_INVENTORY_EDIT: ("Add / edit items", "Create, edit, archive and restore products."),
    P_INVENTORY_IMPORT: ("Import stock files", "Preview and apply CSV/XLSX imports."),
    P_STOCK_RECEIVE: ("Receive stock", "Record supplier receipts against products."),
    P_STOCK_ADJUST: ("Adjust stock", "Record damage, loss, expiry and count corrections."),
    P_SALES_CREATE: ("Record sales", "Open the sale counter and complete transactions."),
    P_SALES_VIEW: ("View transactions", "See permanent sales history and receipts (read-only)."),
    P_SALES_REFUND: ("Refund / reverse", "Issue partial refunds, full refunds and reversals."),
    P_REPORTS_VIEW: ("View reports", "Open daily reports, exports and transaction exports."),
    P_REPORTS_MANAGE: ("Manage reports", "Regenerate report bundles and run report jobs."),
    P_MONTHLY_VIEW: ("Monthly summary", "See monthly performance and stock movement summaries."),
    P_AUDIT_VIEW: ("Audit log", "See the security and business audit trail."),
    P_USERS_VIEW: ("View users", "See accounts and their assigned roles (read-only)."),
    P_USERS_MANAGE: ("Manage users", "Create, edit, deactivate and reset user accounts."),
    P_ROLES_VIEW: ("View roles", "See role names, descriptions and permission counts (read-only)."),
    P_ROLES_MANAGE: ("Manage roles", "Create custom roles and choose what each role can do and see."),
    P_SETTINGS_MANAGE: ("Settings", "Change business settings, storage, backups and automation."),
    P_BACKUP_MANAGE: ("Backups", "Create, verify and restore database backups."),
}

PERMISSION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Overview", (P_DASHBOARD,)),
    (
        "Inventory",
        (
            P_INVENTORY_VIEW,
            P_INVENTORY_EDIT,
            P_INVENTORY_IMPORT,
            P_STOCK_RECEIVE,
            P_STOCK_ADJUST,
        ),
    ),
    ("Sales", (P_SALES_CREATE, P_SALES_VIEW, P_SALES_REFUND)),
    ("Reports", (P_REPORTS_VIEW, P_REPORTS_MANAGE, P_MONTHLY_VIEW)),
    (
        "Administration",
        (
            P_AUDIT_VIEW,
            P_USERS_VIEW,
            P_USERS_MANAGE,
            P_ROLES_VIEW,
            P_ROLES_MANAGE,
            P_SETTINGS_MANAGE,
            P_BACKUP_MANAGE,
        ),
    ),
)


@dataclass(frozen=True)
class RoleDefinition:
    """A role and the exact permissions it grants.

    Built-in roles are kept in code as sensible defaults.  The database copies
    them on first run and may add custom roles; the in-memory registry is what
    the signed-in actor checks on every action.
    """

    key: str
    name: str
    description: str
    permissions: frozenset[str]
    is_system: bool = False
    editable: bool = True


# Owner: operational oversight and inventory management, but not settings or
# the audit log.  User accounts are visible read-only; role administration is
# admin-only so an owner cannot grant themselves settings access.
OWNER_PERMISSIONS = frozenset(
    ALL_PERMISSIONS
    - {
        P_SETTINGS_MANAGE,
        P_AUDIT_VIEW,
        P_BACKUP_MANAGE,
        P_USERS_MANAGE,
        P_ROLES_MANAGE,
    }
)

# Base user: dashboard, the sale counter and read-only transaction history.
STAFF_PERMISSIONS = frozenset({P_DASHBOARD, P_SALES_CREATE, P_SALES_VIEW})

BUILTIN_ROLES: dict[str, RoleDefinition] = {
    ROLE_ADMIN: RoleDefinition(
        ROLE_ADMIN,
        "Admin",
        "Full access: sales, inventory, reports, users, roles, audit, settings and backups.",
        ALL_PERMISSIONS,
        is_system=True,
        editable=False,
    ),
    ROLE_OWNER: RoleDefinition(
        ROLE_OWNER,
        "Owner",
        "Operational oversight and inventory management; everything except settings, audit and role administration.",
        OWNER_PERMISSIONS,
        is_system=True,
        editable=True,
    ),
    ROLE_STAFF: RoleDefinition(
        ROLE_STAFF,
        "Base user",
        "Dashboard, record sales and read-only transaction history.",
        STAFF_PERMISSIONS,
        is_system=True,
        editable=True,
    ),
}

# Backwards-compatible names for the built-in roles.
ROLE_LABELS = {key: value.name for key, value in BUILTIN_ROLES.items()}
ROLE_DESCRIPTIONS = {key: value.description for key, value in BUILTIN_ROLES.items()}
ROLE_ORDER = (ROLE_ADMIN, ROLE_OWNER, ROLE_STAFF)
ROLE_PERMISSIONS = {key: value.permissions for key, value in BUILTIN_ROLES.items()}

_roles: dict[str, RoleDefinition] = dict(BUILTIN_ROLES)


def normalize_permissions(values) -> frozenset[str]:
    """Keep known permissions and add the views implied by management rights."""
    permissions = {value for value in values if value in ALL_PERMISSIONS}
    if P_INVENTORY_EDIT in permissions:
        permissions.add(P_INVENTORY_VIEW)
    if P_USERS_MANAGE in permissions or P_ROLES_MANAGE in permissions:
        permissions.add(P_USERS_VIEW)
    if P_ROLES_MANAGE in permissions:
        permissions.add(P_ROLES_VIEW)
    if P_SALES_REFUND in permissions:
        permissions.add(P_SALES_VIEW)
    if P_REPORTS_MANAGE in permissions:
        permissions.add(P_REPORTS_VIEW)
    return frozenset(permissions)


def set_role_definitions(definitions) -> None:
    """Replace the custom-role registry after loading roles from the database."""
    global _roles
    merged = dict(BUILTIN_ROLES)
    for definition in definitions:
        if definition.key == ROLE_ADMIN:
            continue
        merged[definition.key] = definition
    _roles = merged


def reset_role_definitions() -> None:
    global _roles
    _roles = dict(BUILTIN_ROLES)


def role_definitions() -> tuple[RoleDefinition, ...]:
    builtins = tuple(_roles[key] for key in ROLE_ORDER if key in _roles)
    custom = sorted(
        (role for key, role in _roles.items() if key not in ROLE_ORDER),
        key=lambda role: role.name.lower(),
    )
    return builtins + tuple(custom)


def role_definition(role: str) -> RoleDefinition | None:
    return _roles.get(role)


def role_label(role: str) -> str:
    definition = _roles.get(role)
    return definition.name if definition else str(role).replace("_", " ").title()


def role_description(role: str) -> str:
    definition = _roles.get(role)
    return definition.description if definition else ""


def is_known_role(role: str) -> bool:
    return role in _roles


def permissions_for(role: str) -> frozenset[str]:
    if role == ROLE_ADMIN:
        return ALL_PERMISSIONS
    definition = _roles.get(role)
    return definition.permissions if definition else frozenset()


MIN_PASSWORD_LENGTH = 8
PBKDF2_ITERATIONS = 260_000
_HASH_SCHEME = "pbkdf2_sha256"


@dataclass(frozen=True)
class Actor:
    """The signed-in user, copied out of the ORM session."""

    id: int | None
    username: str
    name: str
    role: str

    @property
    def role_label(self) -> str:
        return role_label(self.role)

    def can(self, permission: str) -> bool:
        return permission in permissions_for(self.role)


_current_actor: Actor | None = None


def set_actor(actor: Actor | None) -> None:
    global _current_actor
    _current_actor = actor


def current_actor() -> Actor | None:
    return _current_actor


def has_permission(permission: str) -> bool:
    actor = _current_actor
    if actor is None:
        return True  # system context: tests, CLI jobs and headless tools
    return actor.can(permission)


def require(permission: str) -> None:
    actor = _current_actor
    if actor is not None and not actor.can(permission):
        raise PermissionDenied(
            f"Your role ({actor.role_label}) is not allowed to perform this action."
        )


def requires(permission: str):
    """Decorator that enforces a permission on a service function."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            require(permission)
            return func(*args, **kwargs)

        return wrapper

    return decorator


# Password hashing ----------------------------------------------------------
def hash_password(password: str) -> str:
    password = str(password or "")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"{_HASH_SCHEME}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        scheme, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != _HASH_SCHEME:
            return False
        rounds = int(iterations)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False
    computed = hashlib.pbkdf2_hmac(
        "sha256", str(password or "").encode("utf-8"), salt, rounds
    )
    return hmac.compare_digest(computed, expected)


# Constant-time dummy verification for unknown usernames, so a failed login
# does not reveal whether the account exists through timing.
_DUMMY_HASH = hash_password(secrets.token_hex(12))


def verify_dummy(password: str) -> None:
    verify_password(password, _DUMMY_HASH)
