"""Role administration: create roles and choose what each role can do and see."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from ... import security
from ...services import roles_service
from ..auth_dialogs import RoleEditorDialog
from ..common import confirm, show_error
from ..models import TableColumn
from ..widgets import DataTable, PageHeader, SectionCard
from .base import BasePage


class RolesPage(BasePage):
    def build(self) -> None:
        self.header = PageHeader(
            "Roles & permissions",
            "Create custom roles and choose exactly which sections and actions they can use.",
        )
        self.new_button = self.header.add_action("New role", "primary", "plus", self.new_action)
        self.edit_button = self.header.add_action("Edit", "secondary", "edit", self._edit)
        self.delete_button = self.header.add_action(
            "Delete", "secondary", "trash", self._delete
        )
        for button in (self.new_button, self.edit_button, self.delete_button):
            button.setVisible(self.state.can(security.P_ROLES_MANAGE))
        self.layout.addWidget(self.header)

        card = SectionCard(
            "Roles",
            "Built-in roles can be adjusted; the Admin role always keeps full access. "
            "Permission changes apply to users at their next sign-in.",
        )
        self.table = DataTable()
        self.table.doubleClicked.connect(self._edit)
        card.content.addWidget(self.table, 1)
        self.layout.addWidget(card, 1)

        self.empty_hint = QLabel("")
        self.empty_hint.setObjectName("Muted")
        self.layout.addWidget(self.empty_hint)

    def refresh(self) -> None:
        try:
            with self.state.database.session() as session:
                roles = roles_service.list_roles(session)
                rows = []
                for role in roles:
                    permissions = roles_service.role_permissions(session, role.key)
                    rows.append(
                        {
                            "key": role.key,
                            "name": role.name,
                            "type": "Built-in" if role.is_system else "Custom",
                            "is_system": bool(role.is_system),
                            "users": roles_service.user_count(session, role.key),
                            "permissions": len(permissions),
                            "description": role.description,
                        }
                    )
        except Exception as exc:
            show_error(self, exc, "Could not load roles")
            return

        self.table.set_data(
            rows,
            [
                TableColumn("name", "Role", 180, bold=True),
                TableColumn("type", "Type", 100),
                TableColumn(
                    "users",
                    "Users",
                    80,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                ),
                TableColumn(
                    "permissions",
                    "Permissions",
                    110,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                ),
                TableColumn("description", "What it can do", 520),
            ],
        )
        self.table.connect_selection(self._selection_changed)
        if self.state.can(security.P_ROLES_MANAGE):
            subtitle = (
                f"{len(rows):,} role(s)  ·  managed by {self.state.operator_name}"
            )
        else:
            subtitle = f"{len(rows):,} role(s)  ·  read-only"
        self.header.subtitle_label.setText(subtitle)
        self.empty_hint.setText("" if rows else "No roles found.")
        self._selection_changed()

    def _selection_changed(self, *_args) -> None:
        record = self.table.selected_record()
        manage = self.state.can(security.P_ROLES_MANAGE)
        admin = bool(record and record.get("key") == security.ROLE_ADMIN)
        self.edit_button.setEnabled(manage and record is not None and not admin)
        self.delete_button.setEnabled(
            manage and record is not None and not admin and not record.get("is_system")
        )

    def _selected(self) -> dict | None:
        return self.table.selected_record()

    def new_action(self) -> None:
        if not self.state.can(security.P_ROLES_MANAGE):
            return
        dialog = RoleEditorDialog(self.state, parent=self)
        if dialog.exec() and dialog.saved_key:
            self.state.notify_data_changed()
            self.main.show_status(f"Role '{dialog.saved_key}' created.")
            self.refresh()

    def _edit(self, *_args) -> None:
        if not self.state.can(security.P_ROLES_MANAGE):
            return
        record = self._selected()
        if record is None or record.get("key") == security.ROLE_ADMIN:
            return
        dialog = RoleEditorDialog(
            self.state, role_key=str(record["key"]), parent=self
        )
        if dialog.exec() and dialog.saved_key:
            self.state.notify_data_changed()
            self.main.show_status(f"Role '{record['name']}' updated.")
            self.refresh()

    def _delete(self) -> None:
        if not self.state.can(security.P_ROLES_MANAGE):
            return
        record = self._selected()
        if record is None or record.get("is_system"):
            return
        if not confirm(
            self,
            "Delete role",
            f"Delete the role '{record['name']}'? This cannot be undone.",
            confirm_text="Delete",
            danger=True,
        ):
            return
        try:
            with self.state.database.session() as session:
                roles_service.delete_role(
                    session,
                    str(record["key"]),
                    operator_id=self.state.operator_id,
                )
        except Exception as exc:
            show_error(self, exc)
            return
        self.state.notify_data_changed()
        self.main.show_status(f"Role '{record['name']}' deleted.")
        self.refresh()
