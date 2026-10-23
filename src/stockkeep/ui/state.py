"""Shared application state for pages (settings, formatting, signals)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..db import Database
from ..money import format_money, format_qty
from ..paths import AppPaths
from .. import security
from ..security import Actor
from ..services.scheduler import config_from_settings
from ..services.settings_service import AppSettings, load_settings
from ..timeutil import as_local, today


class AppState(QObject):
    data_changed = Signal()
    settings_changed = Signal()
    notification = Signal(str)
    theme_changed = Signal(str)

    def __init__(self, database: Database, paths: AppPaths, parent=None):
        super().__init__(parent)
        self.database = database
        self.paths = paths
        self.settings = AppSettings()
        self.current_user: Actor | None = None
        self.sign_out_requested = False
        self.reload_settings()
        self.session = database.session

    def set_current_user(self, user) -> Actor:
        """Adopt an ORM user (or Actor) as the signed-in actor."""
        actor = Actor(
            id=getattr(user, "id", None),
            username=str(getattr(user, "username", "") or ""),
            name=str(getattr(user, "name", "") or ""),
            role=str(getattr(user, "role", security.ROLE_STAFF)),
        )
        self.current_user = actor
        security.set_actor(actor)
        return actor

    def clear_current_user(self) -> None:
        self.current_user = None
        security.set_actor(None)

    def can(self, permission: str) -> bool:
        """Permission check for navigation and actions.

        A missing actor means system context (tests and headless tooling) and
        is allowed; the desktop application always signs a user in first.
        """
        if self.current_user is None:
            return True
        return self.current_user.can(permission)

    @property
    def role(self) -> str:
        return self.current_user.role if self.current_user else security.ROLE_ADMIN

    @property
    def role_label(self) -> str:
        return security.role_label(self.role)


    def reload_settings(self) -> AppSettings:
        with self.database.session() as session:
            self.settings = load_settings(session, self.paths)
        self.report_config = config_from_settings(self.settings, self.paths)
        return self.settings

    # ---- formatting ------------------------------------------------------
    def money(self, minor: int | None) -> str:
        return format_money(minor, self.settings.currency_symbol)

    def plain_money(self, minor: int | None) -> str:
        return format_money(minor, self.settings.currency_symbol)

    def quantity(self, milli: int | None) -> str:
        return format_qty(milli)

    def datetime(self, value) -> str:
        local = as_local(value, self.settings.timezone)
        return local.strftime("%d %b %Y, %H:%M") if local else ""

    def datetime_short(self, value) -> str:
        local = as_local(value, self.settings.timezone)
        return local.strftime("%d %b, %H:%M") if local else ""

    def date(self, value) -> str:
        return value.strftime("%d %b %Y") if value else ""

    @property
    def operator_id(self) -> int | None:
        if self.current_user is not None:
            return self.current_user.id
        return self.settings.operator_id

    @property
    def operator_name(self) -> str:
        if self.current_user is not None:
            return self.current_user.name
        return self.settings.operator_name

    @property
    def theme(self) -> str:
        return self.settings.theme

    @property
    def business_date(self):
        return today(self.settings.timezone)

    def notify_data_changed(self) -> None:
        self.data_changed.emit()
