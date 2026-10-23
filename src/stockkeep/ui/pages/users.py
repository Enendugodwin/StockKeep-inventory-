"""User accounts and role-based access administration (Admin only)."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel

from ... import security
from ...services import auth_service
from ..auth_dialogs import ResetPasswordDialog, UserEditorDialog
from ..common import confirm, show_error
from ...models import User
from ..models import TableColumn
from ..theme import palette
from ..widgets import DataTable, PageHeader, SectionCard
from .base import BasePage


class UsersPage(BasePage):
    def build(self) -> None:
        self.header = PageHeader(
            "Users & roles",
            "Control who can sell, manage inventory or administer StockKeep.",
        )
        if self.state.can(security.P_ROLES_MANAGE):
            self.header.add_action(
                "Manage roles", "secondary", "roles", lambda: self.main.go_to("roles")
            )
        self.new_button = self.header.add_action("New user", "primary", "plus", self.new_action)
        self.edit_button = self.header.add_action("Edit", "secondary", "edit", self._edit)
        self.password_button = self.header.add_action(
            "Reset password", "secondary", "settings", self._reset_password
        )
        self.toggle_button = self.header.add_action(
            "Deactivate", "secondary", "x", self._toggle_active
        )
        for button in (
            self.new_button,
            self.edit_button,
            self.password_button,
            self.toggle_button,
        ):
            button.setVisible(self.state.can(security.P_USERS_MANAGE))
        self.layout.addWidget(self.header)

        self.roles_card = SectionCard(
            "Role permissions",
            "Roles are defined once and enforced in the interface and in the services.",
        )
        self.roles_grid = QGridLayout()
        self.roles_grid.setHorizontalSpacing(18)
        self.roles_grid.setVerticalSpacing(6)
        self.roles_card.content.addLayout(self.roles_grid)
        self.layout.addWidget(self.roles_card)

        card = SectionCard("Accounts", "Passwords are stored as salted PBKDF2 hashes.")
        self.table = DataTable()
        self.table.doubleClicked.connect(self._edit)
        card.content.addWidget(self.table, 1)
        self.layout.addWidget(card, 1)
        self.empty_hint = QLabel("")
        self.empty_hint.setObjectName("Muted")
        self.layout.addWidget(self.empty_hint)

    # ------------------------------------------------------------------
    def _render_roles(self, counts: dict[str, int]) -> None:
        while self.roles_grid.count():
            item = self.roles_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, role in enumerate(security.role_definitions()):
            row = (index // 3) * 2
            column = index % 3
            title = QLabel(f"{role.name}  ·  {counts.get(role.key, 0)} user(s)")
            title.setObjectName("SectionTitle")
            self.roles_grid.addWidget(title, row, column)
            body = QLabel(role.description)
            body.setObjectName("Muted")
            body.setWordWrap(True)
            self.roles_grid.addWidget(body, row + 1, column)

    def refresh(self) -> None:
        try:
            with self.state.database.session() as session:
                users = auth_service.list_users(session)
                counts = {
                    role.key: session.query(User)
                    .filter(User.role == role.key)
                    .count()
                    for role in security.role_definitions()
                }
                rows = [
                    {
                        "id": user.id,
                        "name": user.name,
                        "username": user.username,
                        "role": user.role,
                        "role_label": security.role_label(user.role),
                        "is_active": user.is_active,
                        "status": "Active" if user.is_active else "Inactive",
                        "last_login_at": user.last_login_at,
                    }
                    for user in users
                ]
        except Exception as exc:
            show_error(self, exc, "Could not load users")
            return

        self._render_roles(counts)
        self.table.set_data(
            rows,
            [
                TableColumn("name", "Full name", 220, bold=True),
                TableColumn("username", "Username", 180),
                TableColumn("role_label", "Role", 130),
                TableColumn(
                    "status",
                    "Status",
                    110,
                    color=lambda row: (
                        palette(self.state.theme)["success"]
                        if row.get("is_active")
                        else palette(self.state.theme)["muted"]
                    ),
                ),
                TableColumn(
                    "last_login_at",
                    "Last sign-in",
                    180,
                    formatter=lambda row: self.state.datetime(row.get("last_login_at"))
                    or "Never",
                ),
            ],
        )
        self.table.connect_selection(self._selection_changed)
        read_only = "" if self.state.can(security.P_USERS_MANAGE) else "  ·  read-only"
        self.header.subtitle_label.setText(
            f"{len(rows):,} account(s)  ·  signed in as {self.state.operator_name} "
            f"({self.state.role_label}){read_only}"
        )
        self.empty_hint.setText("" if rows else "No user accounts found.")
        self._selection_changed()

    def _selection_changed(self, *_args) -> None:
        record = self.table.selected_record()
        manage = self.state.can(security.P_USERS_MANAGE)
        self.edit_button.setEnabled(manage and record is not None)
        self.password_button.setEnabled(manage and record is not None)
        if record is None:
            self.toggle_button.setEnabled(False)
            self.toggle_button.setText("Deactivate")
            return
        is_self = record.get("id") == self.state.operator_id
        self.toggle_button.setEnabled(manage and not is_self)
        self.toggle_button.setText("Deactivate" if record.get("is_active") else "Activate")

    def _selected(self) -> dict | None:
        return self.table.selected_record()

    def new_action(self) -> None:
        if not self.state.can(security.P_USERS_MANAGE):
            return
        dialog = UserEditorDialog(self.state, parent=self)
        if dialog.exec() and dialog.saved_id:
            self.state.notify_data_changed()
            self.main.show_status("User account created.")
            self.refresh()

    def _edit(self, *_args) -> None:
        if not self.state.can(security.P_USERS_MANAGE):
            return
        record = self._selected()
        if record is None:
            return
        dialog = UserEditorDialog(self.state, user_id=int(record["id"]), parent=self)
        if dialog.exec() and dialog.saved_id:
            if dialog.saved_id == self.state.operator_id:
                self.state.set_current_user(dialog.user)
                self.state.settings_changed.emit()
            self.state.notify_data_changed()
            self.main.show_status("User account updated.")
            self.refresh()

    def _reset_password(self) -> None:
        if not self.state.can(security.P_USERS_MANAGE):
            return
        record = self._selected()
        if record is None:
            return
        dialog = ResetPasswordDialog(
            self.state,
            int(record["id"]),
            parent=self,
            username=str(record.get("username", "")),
        )
        if dialog.exec():
            self.main.show_status(f"Password reset for {record.get('username')}.")

    def _toggle_active(self) -> None:
        if not self.state.can(security.P_USERS_MANAGE):
            return
        record = self._selected()
        if record is None or record.get("id") == self.state.operator_id:
            return
        active = bool(record.get("is_active"))
        action = "Deactivate" if active else "Activate"
        if active and not confirm(
            self,
            f"{action} account",
            f"{action} {record.get('username')}? They will no longer be able to sign in.",
            confirm_text=action,
            danger=True,
        ):
            return
        try:
            with self.state.database.session() as session:
                auth_service.update_user(
                    session,
                    int(record["id"]),
                    username=str(record["username"]),
                    name=str(record["name"]),
                    role=str(record["role"]),
                    is_active=not active,
                    operator_id=self.state.operator_id,
                )
        except Exception as exc:
            show_error(self, exc)
            return
        self.state.notify_data_changed()
        self.main.show_status(f"Account {action.lower()}d.")
        self.refresh()
