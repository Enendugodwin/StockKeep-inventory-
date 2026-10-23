"""Main window: persistent sidebar, stacked pages, shortcuts, background jobs."""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..services.backup import auto_backup_if_due
from ..services.scheduler import (
    config_from_settings,
    generate_missing,
    scheduled_task_status,
)
from ..services.settings_service import load_settings, update_settings
from ..timeutil import today
from .. import security
from . import icons
from .common import confirm
from .pages.adjustments import AdjustmentsPage
from .pages.audit import AuditPage
from .pages.dashboard import DashboardPage
from .pages.import_stock import ImportStockPage
from .pages.inventory import InventoryPage
from .pages.monthly import MonthlyPage
from .pages.receiving import ReceivingPage
from .pages.record_sale import RecordSalePage
from .pages.reports_page import ReportsPage
from .pages.roles import RolesPage
from .pages.settings import SettingsPage
from .pages.transactions import TransactionsPage
from .pages.users import UsersPage
from .theme import apply_theme
from .workers import run_task

log = logging.getLogger(__name__)

NAV_ITEMS = [
    ("dashboard", "Dashboard", "dashboard", security.P_DASHBOARD),
    ("inventory", "Inventory", "inventory", security.P_INVENTORY_VIEW),
    ("import", "Import Stock", "import", security.P_INVENTORY_IMPORT),
    ("sale", "Record Sale", "sale", security.P_SALES_CREATE),
    ("transactions", "Transactions", "transactions", security.P_SALES_VIEW),
    ("receiving", "Stock Receiving", "receiving", security.P_STOCK_RECEIVE),
    ("adjustments", "Stock Adjustments", "adjustments", security.P_STOCK_ADJUST),
    ("reports", "Reports & Exports", "reports", security.P_REPORTS_VIEW),
    ("monthly", "Monthly Summary", "monthly", security.P_MONTHLY_VIEW),
    ("audit", "Audit Log", "audit", security.P_AUDIT_VIEW),
    ("users", "Users", "user", security.P_USERS_VIEW),
    ("roles", "Roles", "roles", security.P_ROLES_VIEW),
    ("settings", "Settings", "settings", security.P_SETTINGS_MANAGE),
]

PAGE_CLASSES = {
    "dashboard": DashboardPage,
    "inventory": InventoryPage,
    "import": ImportStockPage,
    "sale": RecordSalePage,
    "transactions": TransactionsPage,
    "receiving": ReceivingPage,
    "adjustments": AdjustmentsPage,
    "reports": ReportsPage,
    "monthly": MonthlyPage,
    "audit": AuditPage,
    "users": UsersPage,
    "roles": RolesPage,
    "settings": SettingsPage,
}


def _nav_meta(key: str) -> tuple[str, str, str, str] | None:
    return next((item for item in NAV_ITEMS if item[0] == key), None)


class MainWindow(QMainWindow):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.pages: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self._report_task_running = False
        self._active_workers = []
        self.setMinimumSize(1180, 740)
        self.resize(1400, 880)
        self._build_ui()
        self._build_shortcuts()
        self.state.theme_changed.connect(self._apply_theme)
        self.state.settings_changed.connect(self._settings_updated)
        self.state.notification.connect(self.show_status)
        self.go_to(self._first_available_key())
        QTimer.singleShot(900, self._startup_tasks)
        self.maintenance_timer = QTimer(self)
        self.maintenance_timer.setInterval(5 * 60 * 1000)
        self.maintenance_timer.timeout.connect(self._periodic_tasks)
        self.maintenance_timer.start()
        self._update_context_label()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("AppRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        # Pages are created lazily on first visit.  This keeps startup fast and
        # avoids constructing inventory/report pages a cashier can never open.

        self.status = QStatusBar()
        self.status.setSizeGripEnabled(False)
        self.setStatusBar(self.status)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("Muted")
        self.status.addWidget(self.status_label, 1)
        self.context_label = QLabel("")
        self.context_label.setObjectName("Muted")
        self.status.addPermanentWidget(self.context_label)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(242)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 20, 14, 16)
        layout.setSpacing(6)

        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(8, 0, 6, 8)
        brand_layout.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(icons.pixmap("package", "#2DC6B8", 30))
        brand_layout.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("StockKeep")
        title.setObjectName("BrandTitle")
        titles.addWidget(title)
        subtitle = QLabel("INVENTORY CONTROL")
        subtitle.setObjectName("BrandSub")
        titles.addWidget(subtitle)
        brand_layout.addLayout(titles, 1)
        layout.addWidget(brand)

        layout.addSpacing(14)
        section = QLabel("WORKSPACE")
        section.setObjectName("SidebarSection")
        section.setContentsMargins(10, 0, 0, 4)
        layout.addWidget(section)

        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, label, icon_name, permission in NAV_ITEMS:
            if not self.state.can(permission):
                continue
            button = QPushButton(label.replace("&", "&&"))
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setIcon(icons.icon(icon_name, "#A8BAC5", 19))
            button.setIconSize(QSize(19, 19))
            button.setMinimumHeight(41)
            button.clicked.connect(lambda _checked=False, k=key: self.go_to(k))
            group.addButton(button)
            self.nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        footer = QFrame()
        footer.setObjectName("SidebarFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(12, 12, 12, 12)
        footer_layout.setSpacing(7)
        user_row = QHBoxLayout()
        user_row.setSpacing(8)
        user_icon = QLabel()
        user_icon.setPixmap(icons.pixmap("user", "#7DE3D8", 18))
        user_row.addWidget(user_icon)
        self.user_label = QLabel(self.state.operator_name)
        self.user_label.setObjectName("SidebarUser")
        user_row.addWidget(self.user_label, 1)
        footer_layout.addLayout(user_row)
        self.role_label = QLabel(self.state.role_label)
        self.role_label.setObjectName("SidebarMuted")
        footer_layout.addWidget(self.role_label)
        self.business_label = QLabel(self.state.settings.business_name)
        self.business_label.setObjectName("SidebarMuted")
        self.business_label.setWordWrap(True)
        footer_layout.addWidget(self.business_label)
        self.report_label = QLabel("Daily reports: checking…")
        self.report_label.setObjectName("SidebarMuted")
        self.report_label.setWordWrap(True)
        footer_layout.addWidget(self.report_label)
        self.theme_button = QPushButton("Light mode")
        self.theme_button.setObjectName("NavButton")
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.setIcon(icons.icon("sun", "#A8BAC5", 17))
        self.theme_button.clicked.connect(self._toggle_theme)
        footer_layout.addWidget(self.theme_button)
        self.password_button = QPushButton("Change password")
        self.password_button.setObjectName("NavButton")
        self.password_button.setCursor(Qt.PointingHandCursor)
        self.password_button.setIcon(icons.icon("settings", "#A8BAC5", 17))
        self.password_button.clicked.connect(self._change_password)
        self.password_button.setVisible(self.state.current_user is not None)
        footer_layout.addWidget(self.password_button)
        self.signout_button = QPushButton("Sign out")
        self.signout_button.setObjectName("NavButton")
        self.signout_button.setCursor(Qt.PointingHandCursor)
        self.signout_button.setIcon(icons.icon("left", "#A8BAC5", 17))
        self.signout_button.clicked.connect(self._sign_out)
        self.signout_button.setVisible(self.state.current_user is not None)
        footer_layout.addWidget(self.signout_button)
        layout.addWidget(footer)
        return sidebar

    def _build_shortcuts(self) -> None:
        bindings = {
            "Ctrl+N": lambda: self._invoke("new_action"),
            "Ctrl+F": lambda: self._invoke("focus_search"),
            "Ctrl+S": lambda: self._invoke("save_action"),
            "Ctrl+E": lambda: self._invoke("export_action"),
            "F5": lambda: self.current_page().refresh() if self.current_page() else None,
        }
        self._shortcuts = []
        for sequence, handler in bindings.items():
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def current_page(self):
        widget = self.stack.currentWidget()
        return widget

    def go_to(self, key: str) -> None:
        meta = _nav_meta(key)
        if meta is None:
            return
        if not self.state.can(meta[3]):
            self.show_status("Your role does not have access to that section.")
            return
        page = self.pages.get(key)
        if page is None:
            page = PAGE_CLASSES[key](self.state, self)
            page.key = key
            self.pages[key] = page
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        for nav_key, button in self.nav_buttons.items():
            active = nav_key == key
            button.setChecked(active)
            color = "#7DE3D8" if active else "#A8BAC5"
            icon_name = next(item[2] for item in NAV_ITEMS if item[0] == nav_key)
            button.setIcon(icons.icon(icon_name, color, 19))
        self.user_label.setText(self.state.operator_name)
        self.role_label.setText(self.state.role_label)
        self.business_label.setText(self.state.settings.business_name)
        self.setWindowTitle(f"StockKeep — {self.state.settings.business_name}")
        self._update_context_label()
        page.refresh()

    def _first_available_key(self) -> str:
        for key, _label, _icon, permission in NAV_ITEMS:
            if self.state.can(permission):
                return key
        return "sale"

    def _invoke(self, method: str) -> None:
        page = self.current_page()
        if page is not None and hasattr(page, method):
            getattr(page, method)()

    # ------------------------------------------------------------------
    # Theme / settings
    # ------------------------------------------------------------------
    def _apply_theme(self, theme: str) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        for key, button in self.nav_buttons.items():
            active = key == self.current_page().key if self.current_page() else key == "dashboard"
            color = "#7DE3D8" if active else "#A8BAC5"
            icon_name = next(item[2] for item in NAV_ITEMS if item[0] == key)
            button.setIcon(icons.icon(icon_name, color, 19))
        self.theme_button.setText("Dark mode" if self.state.theme == "light" else "Light mode")
        self.theme_button.setIcon(
            icons.icon("moon" if self.state.theme == "light" else "sun", "#A8BAC5", 17)
        )

    def _toggle_theme(self) -> None:
        new_theme = "dark" if self.state.theme == "light" else "light"
        with self.state.database.session() as session:
            update_settings(session, {"theme": new_theme}, self.state.paths)
        self.state.reload_settings()
        self.state.theme_changed.emit(new_theme)
        self.state.notification.emit(f"Switched to {new_theme} theme.")

    def _settings_updated(self) -> None:
        self.user_label.setText(self.state.operator_name)
        self.role_label.setText(self.state.role_label)
        self.business_label.setText(self.state.settings.business_name)
        self.setWindowTitle(f"StockKeep — {self.state.settings.business_name}")
        self.theme_button.setText("Dark mode" if self.state.theme == "light" else "Light mode")
        self._update_context_label()
        self._apply_theme(self.state.theme)
        if self.current_page():
            self.current_page().refresh()

    def _update_context_label(self) -> None:
        day = today(self.state.settings.timezone).strftime("%d %b %Y")
        self.context_label.setText(
            f"{self.state.operator_name} ({self.state.role_label})   ·   "
            f"{self.state.settings.business_name}   ·   {day}"
        )

    def _change_password(self) -> None:
        from .auth_dialogs import ChangePasswordDialog

        dialog = ChangePasswordDialog(self.state, self)
        if dialog.exec():
            self.show_status("Your password was changed.")

    def _sign_out(self) -> None:
        if not confirm(
            self,
            "Sign out",
            "Sign out of StockKeep? The application will return to the sign-in screen.",
            confirm_text="Sign out",
        ):
            return
        self.state.sign_out_requested = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ------------------------------------------------------------------
    # Background maintenance
    # ------------------------------------------------------------------
    def _maintenance_job(self):
        with self.state.database.session() as session:
            settings = load_settings(session, self.state.paths)
        if settings.backup_enabled:
            try:
                auto_backup_if_due(
                    self.state.database,
                    settings,
                    settings.backup_root(self.state.paths),
                    operator_id=settings.operator_id,
                )
            except Exception:
                log.exception("Automatic backup failed")
        config = config_from_settings(settings, self.state.paths)
        return generate_missing(self.state.database, config)

    def _startup_tasks(self) -> None:
        self.show_status("Checking daily reports and backups…")
        self._run_maintenance(startup=True)

    def _periodic_tasks(self) -> None:
        self._run_maintenance(startup=False)

    def _run_maintenance(self, *, startup: bool) -> None:
        if self._report_task_running:
            return
        self._report_task_running = True
        self.report_label.setText("Daily reports: checking…")

        def done(summary):
            self._report_task_running = False
            if summary.locked:
                self.report_label.setText("Daily reports: run in progress")
                return
            if summary.failed:
                self.report_label.setText(f"Daily reports: {summary.failed} failed")
                self.show_status(
                    f"Report generation finished with {summary.failed} failure(s). See Reports & Exports."
                )
            elif summary.generated:
                self.report_label.setText(f"Daily reports: {summary.generated} generated")
                self.show_status(f"Generated {summary.generated} daily report bundle(s).")
                self.state.notify_data_changed()
            else:
                self.report_label.setText("Daily reports: up to date")
                if not startup:
                    self.show_status("Daily reports are up to date.")
            reports_page = self.pages.get("reports")
            if reports_page is not None and (reports_page.isVisible() or summary.generated):
                reports_page.refresh()
            dashboard = self.pages.get("dashboard")
            if dashboard is not None and dashboard.isVisible():
                dashboard.refresh()

        def failed(message):
            self._report_task_running = False
            self.report_label.setText("Daily reports: check failed")
            log.warning("Report maintenance failed: %s", message)
            self.show_status("Could not check report status. Open Reports & Exports for details.")

        run_task(self, self._maintenance_job, on_success=done, on_error=failed)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def show_status(self, message: str, timeout: int = 6000) -> None:
        self.status_label.setText(message)
        if timeout:
            QTimer.singleShot(timeout, lambda: self.status_label.setText("Ready"))

    def apply_task_status(self) -> None:
        installed, _detail = scheduled_task_status()
        page = self.pages.get("settings")
        if page is not None and hasattr(page, "set_task_status"):
            page.set_task_status(installed)

    def request_report_refresh(self) -> None:
        """Re-run the background report catch-up after data changes."""
        self._periodic_tasks()

    def refresh_all(self) -> None:
        for page in self.pages.values():
            try:
                page.refresh()
            except Exception:
                log.exception("Page refresh failed for %s", getattr(page, "key", "?"))
        self._update_context_label()

    def closeEvent(self, event):  # noqa: N802
        try:
            self.maintenance_timer.stop()
        except Exception:
            pass
        # Let short maintenance jobs finish so they cannot write to a database
        # that is being disposed during shutdown.
        QThreadPool.globalInstance().waitForDone(5000)
        super().closeEvent(event)
