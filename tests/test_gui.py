"""Headless GUI smoke tests (offscreen Qt)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("pytestqt")

from stockkeep.ui.main_window import NAV_ITEMS, MainWindow
from stockkeep.ui.state import AppState
from stockkeep.ui.theme import apply_theme
from stockkeep import security
from stockkeep.security import Actor
from stockkeep.services import roles_service


@pytest.fixture()
def window(db, paths, qapp):
    apply_theme(qapp, "light")
    state = AppState(db, paths)
    win = MainWindow(state)
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_window_builds_every_page(window):
    for key, _label, _icon, _permission in NAV_ITEMS:
        window.go_to(key)
        assert key in window.pages
        assert window.current_page().key == key


def test_theme_toggle_updates_state(window, qapp):
    initial = window.state.theme
    window._toggle_theme()
    qapp.processEvents()
    assert window.state.theme != initial
    assert window.state.theme in {"light", "dark"}


def test_page_refresh_is_safe_without_data(window, qapp):
    for key, _label, _icon, _permission in NAV_ITEMS:
        window.go_to(key)
        qapp.processEvents()
        window.current_page().refresh()
        qapp.processEvents()


def _role_window(db, paths, qapp, role: str):
    state = AppState(db, paths)
    state.set_current_user(Actor(id=None, username="tester", name="Tester", role=role))
    win = MainWindow(state)
    return state, win


def test_staff_navigation_has_dashboard_sales_and_transactions(db, paths, qapp):
    state, win = _role_window(db, paths, qapp, security.ROLE_STAFF)
    try:
        assert set(win.nav_buttons) == {"dashboard", "sale", "transactions"}
        assert set(win.pages) == {"dashboard"}
        assert win.current_page().key == "dashboard"
        win.go_to("transactions")
        assert win.current_page().key == "transactions"
        win.go_to("inventory")
        assert win.current_page().key == "transactions"
        assert "inventory" not in win.pages
    finally:
        win.close()
        state.clear_current_user()


def test_owner_navigation_has_all_but_settings_audit_and_roles(db, paths, qapp):
    state, win = _role_window(db, paths, qapp, security.ROLE_OWNER)
    try:
        assert set(win.nav_buttons) == {
            "dashboard",
            "inventory",
            "import",
            "sale",
            "transactions",
            "receiving",
            "adjustments",
            "reports",
            "monthly",
            "users",
            "roles",
        }
        assert "settings" not in win.nav_buttons
        assert "audit" not in win.nav_buttons
    finally:
        win.close()
        state.clear_current_user()


def test_admin_sees_every_section(db, paths, qapp):
    state, win = _role_window(db, paths, qapp, security.ROLE_ADMIN)
    try:
        assert set(win.nav_buttons) == {key for key, *_rest in NAV_ITEMS}
        win.go_to("users")
        assert win.current_page().key == "users"
    finally:
        win.close()
        state.clear_current_user()


def test_base_transactions_are_read_only(db, paths, qapp):
    state, win = _role_window(db, paths, qapp, security.ROLE_STAFF)
    try:
        win.go_to("transactions")
        page = win.current_page()
        assert page.refund_button.isHidden()
    finally:
        win.close()
        state.clear_current_user()


def test_owner_users_page_is_read_only(db, paths, qapp):
    state, win = _role_window(db, paths, qapp, security.ROLE_OWNER)
    try:
        win.go_to("users")
        page = win.current_page()
        assert page.new_button.isHidden()
        assert page.edit_button.isHidden()
        assert page.password_button.isHidden()
        assert page.toggle_button.isHidden()
        win.go_to("roles")
        roles_page = win.current_page()
        assert roles_page.key == "roles"
        assert roles_page.new_button.isHidden()
        assert roles_page.edit_button.isHidden()
        assert roles_page.delete_button.isHidden()
    finally:
        win.close()
        state.clear_current_user()


def test_custom_role_navigation_uses_its_permissions(db, paths, qapp):
    security.set_actor(
        Actor(id=1, username="admin", name="Admin", role=security.ROLE_ADMIN)
    )
    try:
        with db.session() as session:
            role = roles_service.create_role(
                session,
                name="Read only floor",
                permissions=[security.P_DASHBOARD, security.P_SALES_VIEW],
                operator_id=1,
            )
            role_key = role.key
        state, win = _role_window(db, paths, qapp, role_key)
        try:
            assert set(win.nav_buttons) == {"dashboard", "transactions"}
            win.go_to("transactions")
            assert win.current_page().refund_button.isHidden()
            win.go_to("inventory")
            assert win.current_page().key == "transactions"
        finally:
            win.close()
            state.clear_current_user()
    finally:
        security.set_actor(None)
