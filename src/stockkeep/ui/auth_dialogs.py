"""Authentication dialogs: first-run setup, sign-in and account management."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import security
from ..services import auth_service, roles_service
from . import icons
from .common import error_text


def _buttons(dialog: QDialog, text: str, *, cancel: bool = True) -> tuple[QDialogButtonBox, QPushButton]:
    box = QDialogButtonBox()
    if cancel:
        box.addButton(QDialogButtonBox.Cancel)
    accept = QPushButton(text)
    accept.setObjectName("PrimaryButton")
    accept.setDefault(True)
    box.addButton(accept, QDialogButtonBox.AcceptRole)
    box.rejected.connect(dialog.reject)
    return box, accept


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


def _brand_header(subtitle: str) -> QWidget:
    header = QWidget()
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    logo = QLabel()
    logo.setPixmap(icons.pixmap("package", "#0E7C86", 40))
    logo.setFixedSize(44, 44)
    layout.addWidget(logo)
    titles = QVBoxLayout()
    titles.setSpacing(1)
    title = QLabel("StockKeep")
    title.setObjectName("LoginTitle")
    titles.addWidget(title)
    hint = QLabel(subtitle)
    hint.setObjectName("LoginSubtitle")
    hint.setWordWrap(True)
    titles.addWidget(hint)
    layout.addLayout(titles, 1)
    return header


class LoginDialog(QDialog):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.user = None
        self.setWindowTitle("Sign in - StockKeep")
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)
        layout.addWidget(_brand_header("Inventory control"))
        business = QLabel(state.settings.business_name)
        business.setObjectName("Muted")
        layout.addWidget(business)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.username = QLineEdit()
        self.username.setPlaceholderText("Username")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow(_field_label("Username"), self.username)
        form.addRow(_field_label("Password"), self.password)
        layout.addLayout(form)

        self.show_password = QCheckBox("Show password")
        self.show_password.toggled.connect(self._toggle_password)
        layout.addWidget(self.show_password)

        self.error = QLabel("")
        self.error.setObjectName("ErrorLabel")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)

        box, self.submit = _buttons(self, "Sign in")
        box.accepted.connect(self._submit)
        layout.addWidget(box)

        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._submit)
        self.username.setFocus()

    def _toggle_password(self, checked: bool) -> None:
        self.password.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def _fail(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(True)
        self.password.selectAll()
        self.password.setFocus()

    def _submit(self) -> None:
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            self._fail("Enter your username and password.")
            return
        try:
            with self.state.database.session() as session:
                user = auth_service.authenticate(session, username, password)
        except Exception as exc:
            self._fail(error_text(exc))
            return
        if user is None:
            self._fail("Incorrect username or password, or the account is inactive.")
            return
        self.user = user
        self.accept()


class SetupAdminDialog(QDialog):
    """First-run administrator creation."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.user = None
        self.setWindowTitle("Create administrator - StockKeep")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)
        layout.addWidget(
            _brand_header("First run - create the administrator account for this PC.")
        )

        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit("Administrator")
        self.username = QLineEdit("admin")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.Password)
        form.addRow(_field_label("Full name"), self.name)
        form.addRow(_field_label("Username"), self.username)
        form.addRow(_field_label("Password"), self.password)
        form.addRow(_field_label("Confirm password"), self.confirm)
        layout.addLayout(form)

        hint = QLabel(
            f"Use at least {security.MIN_PASSWORD_LENGTH} characters. "
            "This account has full access and can create the Owner and Base user accounts."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.error = QLabel("")
        self.error.setObjectName("ErrorLabel")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)

        box, self.submit = _buttons(self, "Create administrator", cancel=False)
        box.accepted.connect(self._submit)
        layout.addWidget(box)

        self.name.setFocus()
        self.confirm.returnPressed.connect(self._submit)

    def _fail(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(True)

    def _submit(self) -> None:
        if self.password.text() != self.confirm.text():
            self._fail("The passwords do not match.")
            self.confirm.selectAll()
            self.confirm.setFocus()
            return
        try:
            with self.state.database.session() as session:
                user = auth_service.create_initial_admin(
                    session,
                    username=self.username.text(),
                    name=self.name.text(),
                    password=self.password.text(),
                )
        except Exception as exc:
            self._fail(error_text(exc))
            return
        self.user = user
        self.accept()


class UserEditorDialog(QDialog):
    def __init__(self, state, *, user_id: int | None = None, parent=None):
        super().__init__(parent)
        self.state = state
        self.user_id = user_id
        self.saved_id: int | None = None
        self.user = None
        if user_id is not None:
            with state.database.session() as session:
                self.user = auth_service.get_user(session, user_id)

        self.setWindowTitle("Edit user" if user_id else "New user")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)
        title = QLabel("User account details")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit(self.user.name if self.user else "")
        self.name.setPlaceholderText("e.g. Ada Okafor")
        self.username = QLineEdit(self.user.username if self.user else "")
        self.role = QComboBox()
        for definition in security.role_definitions():
            self.role.addItem(definition.name, definition.key)
            index = self.role.count() - 1
            self.role.setItemData(index, definition.description, Qt.ToolTipRole)
        if self.user:
            index = self.role.findData(self.user.role)
            self.role.setCurrentIndex(index if index >= 0 else 0)
        self.active = QCheckBox("Account is active")
        self.active.setChecked(bool(self.user.is_active) if self.user else True)
        form.addRow(_field_label("Full name"), self.name)
        form.addRow(_field_label("Username"), self.username)
        form.addRow(_field_label("Role"), self.role)
        form.addRow(_field_label("Status"), self.active)

        self.password = None
        self.confirm = None
        if user_id is None:
            self.password = QLineEdit()
            self.password.setEchoMode(QLineEdit.Password)
            self.confirm = QLineEdit()
            self.confirm.setEchoMode(QLineEdit.Password)
            form.addRow(_field_label("Password"), self.password)
            form.addRow(_field_label("Confirm password"), self.confirm)
        layout.addLayout(form)

        self.role_hint = QLabel("")
        self.role_hint.setObjectName("Muted")
        self.role_hint.setWordWrap(True)
        layout.addWidget(self.role_hint)
        self.role.currentIndexChanged.connect(self._role_changed)
        self._role_changed()

        self.error = QLabel("")
        self.error.setObjectName("ErrorLabel")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)

        box, self.submit = _buttons(self, "Save user")
        box.accepted.connect(self._submit)
        layout.addWidget(box)
        self.name.setFocus()

    def _role_changed(self, *_args) -> None:
        role = self.role.currentData()
        self.role_hint.setText(security.role_description(str(role)))

    def _fail(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(True)

    def _submit(self) -> None:
        try:
            if self.user_id is None:
                if self.password.text() != self.confirm.text():
                    self._fail("The passwords do not match.")
                    return
                with self.state.database.session() as session:
                    user = auth_service.create_user(
                        session,
                        username=self.username.text(),
                        name=self.name.text(),
                        role=str(self.role.currentData()),
                        password=self.password.text(),
                        is_active=self.active.isChecked(),
                        operator_id=self.state.operator_id,
                    )
            else:
                with self.state.database.session() as session:
                    user = auth_service.update_user(
                        session,
                        self.user_id,
                        username=self.username.text(),
                        name=self.name.text(),
                        role=str(self.role.currentData()),
                        is_active=self.active.isChecked(),
                        operator_id=self.state.operator_id,
                    )
        except Exception as exc:
            self._fail(error_text(exc))
            return
        self.saved_id = user.id
        self.user = user
        self.accept()


class RoleEditorDialog(QDialog):
    """Create a custom role or edit an existing role's permissions."""

    def __init__(self, state, *, role_key: str | None = None, parent=None):
        super().__init__(parent)
        self.state = state
        self.role_key = role_key
        self.saved_key: str | None = None
        self._role = None
        self._permissions: frozenset[str] = frozenset()
        if role_key is not None:
            with state.database.session() as session:
                role = roles_service.get_role(session, role_key)
                self._permissions = roles_service.role_permissions(session, role_key)
                self._role = {
                    "key": role.key,
                    "name": role.name,
                    "description": role.description,
                    "is_system": bool(role.is_system),
                }

        is_admin = role_key == security.ROLE_ADMIN
        is_system = bool(self._role and self._role["is_system"])
        self.setWindowTitle("Edit role" if role_key else "New role")
        self.setModal(True)
        self.setMinimumSize(640, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)
        title = QLabel(
            f"Edit {self._role['name']}" if role_key else "Create a custom role"
        )
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        hint = QLabel(
            "Choose exactly what this role can do and see.  Service functions "
            "enforce the same permissions as the navigation."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit(self._role["name"] if self._role else "")
        self.name.setPlaceholderText("e.g. Floor supervisor")
        self.description = QLineEdit(self._role["description"] if self._role else "")
        self.description.setPlaceholderText("Short summary shown to administrators")
        if is_system:
            self.name.setReadOnly(True)
            self.description.setReadOnly(True)
        form.addRow(_field_label("Role name"), self.name)
        form.addRow(_field_label("Description"), self.description)
        layout.addLayout(form)

        permissions_title = QLabel("Permissions")
        permissions_title.setObjectName("SectionTitle")
        layout.addWidget(permissions_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(2, 2, 12, 2)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        self.permission_checks: dict[str, QCheckBox] = {}
        row = 0
        selected = self._permissions or frozenset({security.P_DASHBOARD})
        for group, permissions in security.PERMISSION_GROUPS:
            group_label = QLabel(group.upper())
            group_label.setObjectName("KpiLabel")
            grid.addWidget(group_label, row, 0, 1, 2)
            row += 1
            for index, permission in enumerate(permissions):
                label, help_text = security.PERMISSION_LABELS[permission]
                check = QCheckBox(label)
                check.setToolTip(help_text)
                check.setChecked(permission in selected)
                check.setEnabled(not is_admin)
                self.permission_checks[permission] = check
                grid.addWidget(check, row + index // 2, index % 2)
            row += (len(permissions) + 1) // 2
        grid.setRowStretch(row, 1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        if is_admin:
            note = QLabel("The Admin role always has every permission.")
        elif is_system:
            note = QLabel(
                "This is a built-in role. Its name is fixed, but an administrator "
                "can change its permissions."
            )
        else:
            note = QLabel(
                "Existing users keep this role after edits; permission changes "
                "apply the next time they sign in."
            )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.error = QLabel("")
        self.error.setObjectName("ErrorLabel")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)

        box, self.submit = _buttons(self, "Save role", cancel=not is_admin)
        if is_admin:
            close = QPushButton("Close")
            close.clicked.connect(self.reject)
            box.addButton(close, QDialogButtonBox.RejectRole)
            self.submit.setVisible(False)
        box.accepted.connect(self._submit)
        layout.addWidget(box)
        if not is_admin:
            self.name.setFocus()

    def _submit(self) -> None:
        if self.role_key == security.ROLE_ADMIN:
            self.reject()
            return
        permissions = [
            permission
            for permission, check in self.permission_checks.items()
            if check.isChecked()
        ]
        if not permissions:
            self.error.setText("Select at least one permission.")
            self.error.setVisible(True)
            return
        try:
            with self.state.database.session() as session:
                if self.role_key:
                    role = roles_service.update_role(
                        session,
                        self.role_key,
                        name=self.name.text(),
                        description=self.description.text(),
                        permissions=permissions,
                        operator_id=self.state.operator_id,
                    )
                else:
                    role = roles_service.create_role(
                        session,
                        name=self.name.text(),
                        description=self.description.text(),
                        permissions=permissions,
                        operator_id=self.state.operator_id,
                    )
        except Exception as exc:
            self.error.setText(error_text(exc))
            self.error.setVisible(True)
            return
        self.saved_key = role.key
        self.accept()


class ResetPasswordDialog(QDialog):
    def __init__(self, state, user_id: int, *, parent=None, username: str = ""):
        super().__init__(parent)
        self.state = state
        self.user_id = user_id
        self.setWindowTitle("Reset password")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)
        title = QLabel(f"Set a new password{' for ' + username if username else ''}")
        title.setObjectName("SectionTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.Password)
        form.addRow(_field_label("New password"), self.password)
        form.addRow(_field_label("Confirm password"), self.confirm)
        layout.addLayout(form)

        hint = QLabel(f"At least {security.MIN_PASSWORD_LENGTH} characters.")
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        self.error = QLabel("")
        self.error.setObjectName("ErrorLabel")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)

        box, self.submit = _buttons(self, "Reset password")
        box.accepted.connect(self._submit)
        layout.addWidget(box)
        self.password.setFocus()

    def _submit(self) -> None:
        if self.password.text() != self.confirm.text():
            self.error.setText("The passwords do not match.")
            self.error.setVisible(True)
            return
        try:
            with self.state.database.session() as session:
                auth_service.reset_password(
                    session,
                    self.user_id,
                    self.password.text(),
                    operator_id=self.state.operator_id,
                )
        except Exception as exc:
            self.error.setText(error_text(exc))
            self.error.setVisible(True)
            return
        self.accept()


class ChangePasswordDialog(QDialog):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Change password")
        self.setModal(True)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)
        title = QLabel("Change your password")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        self.current = QLineEdit()
        self.current.setEchoMode(QLineEdit.Password)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.Password)
        form.addRow(_field_label("Current password"), self.current)
        form.addRow(_field_label("New password"), self.password)
        form.addRow(_field_label("Confirm password"), self.confirm)
        layout.addLayout(form)

        hint = QLabel(f"At least {security.MIN_PASSWORD_LENGTH} characters.")
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        self.error = QLabel("")
        self.error.setObjectName("ErrorLabel")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)

        box, self.submit = _buttons(self, "Change password")
        box.accepted.connect(self._submit)
        layout.addWidget(box)
        self.current.setFocus()

    def _submit(self) -> None:
        if self.password.text() != self.confirm.text():
            self.error.setText("The new passwords do not match.")
            self.error.setVisible(True)
            return
        actor = self.state.current_user
        if actor is None or actor.id is None:
            self.error.setText("No signed-in user.")
            self.error.setVisible(True)
            return
        try:
            with self.state.database.session() as session:
                auth_service.change_own_password(
                    session,
                    actor.id,
                    self.current.text(),
                    self.password.text(),
                )
        except Exception as exc:
            self.error.setText(error_text(exc))
            self.error.setVisible(True)
            return
        self.accept()
