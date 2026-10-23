"""Settings, backups and scheduled reports."""

from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import available_timezones

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ... import security
from ...money import CURRENCY_SYMBOLS
from ...services import backup as backup_service
from ...services import settings_service
from ...services import scheduler
from ..common import confirm, confirm_typed, show_error, show_info
from ..models import TableColumn
from ..widgets import DataTable, PageHeader, SectionCard, make_button, open_path
from ..workers import run_task
from .base import BasePage


COMMON_TIMEZONES = [
    "Africa/Lagos",
    "Africa/Accra",
    "Africa/Nairobi",
    "Africa/Johannesburg",
    "Europe/London",
    "Europe/Paris",
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Singapore",
    "Australia/Sydney",
    "UTC",
]


class SettingsPage(BasePage):
    def build(self) -> None:
        self.header = PageHeader("Settings", "Business identity, storage, backups and scheduling.")
        self.header.add_action("Save settings", "primary", "save", self.save_action)
        self.header.add_action("Reload", "secondary", "refresh", self.refresh)
        self.layout.addWidget(self.header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.body = QVBoxLayout(container)
        self.body.setContentsMargins(0, 0, 6, 0)
        self.body.setSpacing(12)
        scroll.setWidget(container)
        self.layout.addWidget(scroll, 1)

        self._build_business_card()
        self._build_storage_card()
        self.backup_card = self._build_backup_card()
        self.backup_card.setVisible(self.state.can(security.P_BACKUP_MANAGE))
        self._build_schedule_card()
        self._build_diagnostics_card()

    # ------------------------------------------------------------------
    def _grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(9)
        return grid

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _build_business_card(self) -> None:
        card = SectionCard("Business & preferences", "Used across receipts, reports and the interface.")
        grid = self._grid()
        self.business_name = QLineEdit()
        self.currency_code = QComboBox()
        self.currency_code.setEditable(True)
        for code in sorted(set(CURRENCY_SYMBOLS) | {"NGN", "USD", "EUR", "GBP", "GHS", "KES", "ZAR"}):
            self.currency_code.addItem(code)
        self.currency_symbol = QLineEdit()
        self.currency_symbol.setMaxLength(6)
        self.currency_symbol.setFixedWidth(90)
        self.timezone = QComboBox()
        self.timezone.setEditable(True)
        zones = sorted(available_timezones()) or COMMON_TIMEZONES
        for zone in zones:
            self.timezone.addItem(zone)
        for zone in COMMON_TIMEZONES:
            if self.timezone.findText(zone) < 0:
                self.timezone.addItem(zone)
        self.close_time = QTimeEdit()
        self.close_time.setDisplayFormat("HH:mm")
        self.close_time.setFixedWidth(100)
        self.page_size = QSpinBox()
        self.page_size.setRange(10, 500)
        self.page_size.setSingleStep(10)
        self.theme = QComboBox()
        self.theme.addItem("Light", "light")
        self.theme.addItem("Dark", "dark")

        grid.addWidget(self._label("Business name"), 0, 0)
        grid.addWidget(self.business_name, 0, 1)
        grid.addWidget(self._label("Currency code"), 0, 2)
        grid.addWidget(self.currency_code, 0, 3)
        grid.addWidget(self._label("Currency symbol"), 1, 0)
        grid.addWidget(self.currency_symbol, 1, 1)
        grid.addWidget(self._label("Timezone"), 1, 2)
        grid.addWidget(self.timezone, 1, 3)
        grid.addWidget(self._label("Daily closing time"), 2, 0)
        grid.addWidget(self.close_time, 2, 1)
        grid.addWidget(self._label("Rows per table page"), 2, 2)
        grid.addWidget(self.page_size, 2, 3)
        grid.addWidget(self._label("Theme"), 3, 0)
        grid.addWidget(self.theme, 3, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        card.content.addLayout(grid)
        self.body.addWidget(card)

    def _build_storage_card(self) -> None:
        card = SectionCard(
            "Storage",
            "Reports and backups live in the application folder; you can point them at another drive.",
        )
        grid = self._grid()
        self.report_dir = QLineEdit()
        report_browse = make_button("Browse…", "secondary", "folder", lambda: self._browse_dir(self.report_dir))
        report_row = QHBoxLayout()
        report_row.setSpacing(6)
        report_row.addWidget(self.report_dir, 1)
        report_row.addWidget(report_browse)
        self.backup_dir = QLineEdit()
        backup_browse = make_button("Browse…", "secondary", "folder", lambda: self._browse_dir(self.backup_dir))
        backup_row = QHBoxLayout()
        backup_row.setSpacing(6)
        backup_row.addWidget(self.backup_dir, 1)
        backup_row.addWidget(backup_browse)
        grid.addWidget(self._label("Reports folder"), 0, 0)
        grid.addLayout(report_row, 0, 1, 1, 3)
        grid.addWidget(self._label("Backups folder"), 1, 0)
        grid.addLayout(backup_row, 1, 1, 1, 3)
        self.backup_enabled = QCheckBox("Create an automatic backup on the first start of each day")
        grid.addWidget(self.backup_enabled, 2, 0, 1, 3)
        self.backup_retention = QSpinBox()
        self.backup_retention.setRange(1, 365)
        grid.addWidget(self._label("Keep recent backups"), 3, 0)
        grid.addWidget(self.backup_retention, 3, 1)
        grid.addWidget(make_button("Open data folder", "ghost", "folder", lambda: open_path(self.state.paths.home)), 3, 2, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        card.content.addLayout(grid)
        self.body.addWidget(card)

    def _build_backup_card(self) -> SectionCard:
        card = SectionCard(
            "Backups & restore",
            "Backups use SQLite's online backup API and are integrity-checked before restore.",
        )
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(make_button("Create backup", "primary", "backup", self._create_backup))
        self.verify_button = make_button("Verify selected", "secondary", "check", self._verify_backup)
        self.restore_button = make_button("Restore selected", "danger", "restore", self._restore_backup)
        self.prune_button = make_button("Prune old", "ghost", "trash", self._prune_backups)
        for button in (self.verify_button, self.restore_button, self.prune_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(make_button("Refresh list", "ghost", "refresh", self._load_backups))
        card.content.addLayout(actions)

        self.backups_table = DataTable()
        self.backups_table.setMinimumHeight(190)
        self.backups_table.connect_selection(self._backup_selection_changed)
        card.content.addWidget(self.backups_table, 1)
        self.backup_hint = QLabel("")
        self.backup_hint.setObjectName("Muted")
        self.backup_hint.setWordWrap(True)
        card.content.addWidget(self.backup_hint)
        self.body.addWidget(card)
        return card

    def _build_schedule_card(self) -> None:
        card = SectionCard(
            "Automatic daily reports",
            "A Windows Task Scheduler job allows report generation without leaving StockKeep open.",
        )
        row = QHBoxLayout()
        row.setSpacing(10)
        self.task_status = QLabel("Checking scheduled task…")
        self.task_status.setObjectName("Muted")
        row.addWidget(self.task_status, 1)
        row.addWidget(make_button("Install task", "secondary", "clock", self._install_task))
        row.addWidget(make_button("Remove task", "ghost", "trash", self._remove_task))
        row.addWidget(make_button("Re-check", "ghost", "refresh", self._check_task))
        card.content.addLayout(row)
        self.body.addWidget(card)

    def _build_diagnostics_card(self) -> None:
        card = SectionCard("About & diagnostics", f"StockKeep {__version__}")
        self.diagnostics = QLabel("")
        self.diagnostics.setObjectName("Muted")
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.content.addWidget(self.diagnostics)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(make_button("Check database integrity", "secondary", "check", self._integrity_check))
        row.addWidget(make_button("Open log", "ghost", "receipt", lambda: open_path(self.state.paths.log_path)))
        row.addWidget(make_button("Open reports", "ghost", "reports", lambda: open_path(self.state.report_config.report_root)))
        row.addWidget(make_button("Open backups", "ghost", "backup", lambda: open_path(self.state.settings.backup_root(self.state.paths))))
        row.addStretch(1)
        card.content.addLayout(row)
        self.body.addWidget(card)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        settings = self.state.reload_settings()
        self.business_name.setText(settings.business_name)
        code_index = self.currency_code.findText(settings.currency_code)
        if code_index >= 0:
            self.currency_code.setCurrentIndex(code_index)
        else:
            self.currency_code.setEditText(settings.currency_code)
        self.currency_symbol.setText(settings.currency_symbol)
        tz_index = self.timezone.findText(settings.timezone)
        if tz_index >= 0:
            self.timezone.setCurrentIndex(tz_index)
        else:
            self.timezone.setEditText(settings.timezone)
        try:
            hour, minute = (int(part) for part in settings.close_time.split(":"))
        except (ValueError, TypeError):
            hour, minute = 23, 59
        self.close_time.setTime(QTime(hour, minute))
        self.page_size.setValue(settings.page_size)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        self.report_dir.setText(str(settings.report_root(self.state.paths)))
        self.backup_dir.setText(str(settings.backup_root(self.state.paths)))
        self.backup_enabled.setChecked(settings.backup_enabled)
        self.backup_retention.setValue(settings.backup_retention)

        self.diagnostics.setText(
            f"Data folder: {self.state.paths.home}\n"
            f"Database: {self.state.database.db_path}  ·  schema version {self.state.database.schema_version()}\n"
            f"Reports: {settings.report_root(self.state.paths)}\n"
            f"Backups: {settings.backup_root(self.state.paths)}\n"
            f"Log file: {self.state.paths.log_path}"
        )
        self._load_backups()
        self._check_task(async_run=True)

    # ------------------------------------------------------------------
    def save_action(self) -> None:
        values = {
            "business_name": self.business_name.text().strip() or "My Business",
            "currency_code": self.currency_code.currentText().strip().upper(),
            "currency_symbol": self.currency_symbol.text().strip(),
            "timezone": self.timezone.currentText().strip(),
            "daily_close_time": self.close_time.time().toString("HH:mm"),
            "page_size": str(self.page_size.value()),
            "theme": self.theme.currentData(),
            "report_dir": self.report_dir.text().strip(),
            "backup_dir": self.backup_dir.text().strip(),
            "backup_enabled": "1" if self.backup_enabled.isChecked() else "0",
            "backup_retention": str(self.backup_retention.value()),
        }
        previous_theme = self.state.theme
        try:
            with self.state.database.session() as session:
                settings_service.update_settings(session, values, self.state.paths)
        except Exception as exc:
            show_error(self, exc, "Settings could not be saved")
            return
        self.state.reload_settings()
        self.state.settings_changed.emit()
        if self.state.theme != previous_theme:
            self.state.theme_changed.emit(self.state.theme)
        self.state.notification.emit("Settings saved.")
        self.refresh()

    def _browse_dir(self, target: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose a folder", target.text() or str(self.state.paths.home))
        if selected:
            target.setText(selected)

    # ------------------------------------------------------------------
    def _load_backups(self) -> None:
        directory = self.state.settings.backup_root(self.state.paths)
        rows = []
        for path in backup_service.list_backups(directory):
            manifest = {}
            manifest_path = path.with_suffix(path.suffix + ".json")
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    manifest = {}
            rows.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "created": path.stat().st_mtime,
                    "size": path.stat().st_size,
                    "schema": manifest.get("schema_version", ""),
                    "label": manifest.get("label", ""),
                }
            )
        import datetime as _dt

        self.backups_table.set_data(
            rows,
            [
                TableColumn("name", "Backup file", 260, bold=True),
                TableColumn(
                    "created",
                    "Created",
                    150,
                    formatter=lambda row: _dt.datetime.fromtimestamp(row.get("created")).strftime(
                        "%d %b %Y, %H:%M"
                    ),
                ),
                TableColumn(
                    "size",
                    "Size",
                    90,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: f"{row.get('size', 0) / 1048576:.2f} MB",
                ),
                TableColumn(
                    "schema", "Schema", 70, align=int(Qt.AlignRight | Qt.AlignVCenter)
                ),
                TableColumn("label", "Label", 120),
            ],
        )
        self.backup_hint.setText(
            f"{len(rows)} backup(s) in {directory}  ·  retention keeps the newest "
            f"{self.state.settings.backup_retention}."
        )
        self._backup_selection_changed()

    def _backup_selection_changed(self, *_args) -> None:
        selected = self.backups_table.selected_record() is not None
        self.verify_button.setEnabled(selected)
        self.restore_button.setEnabled(selected)
        self.prune_button.setEnabled(bool(self.backups_table.model_ref and self.backups_table.model_ref.rows))

    def _selected_backup(self) -> dict | None:
        return self.backups_table.selected_record()

    def _create_backup(self) -> None:
        directory = self.state.settings.backup_root(self.state.paths)
        target = directory / backup_service.backup_filename("manual")
        label = "manual"

        def job():
            return backup_service.create_backup(
                self.state.database, target, label=label, operator_id=self.state.operator_id
            )

        def done(info):
            backup_service.prune_backups(directory, self.state.settings.backup_retention)
            self.main.show_status(f"Backup created: {info.path.name}")
            self._load_backups()
            show_info(self, f"Backup created at:\n{info.path}", "Backup complete")

        run_task(
            self,
            job,
            on_success=done,
            message="Creating a consistent database backup…",
            title="Backup",
        )

    def _verify_backup(self) -> None:
        record = self._selected_backup()
        if record is None:
            return
        ok, detail = backup_service.verify_backup(record["path"])
        if ok:
            show_info(self, "This backup is intact and matches its manifest.", "Backup verified")
        else:
            show_error(self, Exception(detail), "Backup verification failed")

    def _restore_backup(self) -> None:
        record = self._selected_backup()
        if record is None:
            return
        if not confirm_typed(
            self,
            "Restore backup",
            "Restoring replaces the live database with the selected backup. A safety backup is "
            "created first, but all changes made after this backup will be lost from the live data. "
            "StockKeep will reload afterwards.",
            "RESTORE",
        ):
            return
        path = Path(record["path"])
        directory = self.state.settings.backup_root(self.state.paths)

        def job():
            return backup_service.restore_backup(
                self.state.database,
                path,
                backup_dir=directory,
                operator_id=self.state.operator_id,
            )

        def done(pre_restore):
            self.state.reload_settings()
            self.state.settings_changed.emit()
            self.state.theme_changed.emit(self.state.theme)
            self.state.notify_data_changed()
            self.main.refresh_all()
            self._load_backups()
            show_info(
                self,
                f"The backup was restored.\n\nA pre-restore safety copy was saved as:\n{pre_restore.path}",
                "Restore complete",
            )

        run_task(
            self,
            job,
            on_success=done,
            message="Restoring the database…",
            title="Restore backup",
        )

    def _prune_backups(self) -> None:
        directory = self.state.settings.backup_root(self.state.paths)
        keep = self.state.settings.backup_retention
        if not confirm(
            self,
            "Prune backups",
            f"Delete all but the newest {keep} backup(s) in {directory}?",
            confirm_text="Prune",
            danger=True,
        ):
            return
        removed = backup_service.prune_backups(directory, keep)
        self._load_backups()
        self.main.show_status(f"Pruned {len(removed)} old backup(s).")

    # ------------------------------------------------------------------
    def _check_task(self, async_run: bool = False) -> None:
        if async_run:
            run_task(
                self,
                scheduler.scheduled_task_status,
                on_success=lambda result: self.set_task_status(result[0], result[1]),
                message=None,
            )
            return
        installed, detail = scheduler.scheduled_task_status()
        self.set_task_status(installed, detail)

    def set_task_status(self, installed: bool, detail: str = "") -> None:
        if installed:
            self.task_status.setText(f"Scheduled task installed  ·  runs daily at {self.state.settings.close_time}")
        else:
            self.task_status.setText(
                detail or "No scheduled task. Reports are generated while the app is open."
            )

    def _install_task(self) -> None:
        close_time = self.state.settings.close_time

        def job():
            ok, message = scheduler.install_scheduled_task(close_time)
            if ok:
                with self.state.database.session() as session:
                    settings_service.set_setting(session, "scheduled_task_installed", "1")
            return ok, message

        def done(result):
            ok, message = result
            if not ok:
                show_error(self, Exception(message), "Task Scheduler")
            else:
                self.main.show_status(message)
            self._check_task()

        run_task(self, job, on_success=done, message="Installing the scheduled task…", title="Scheduling")

    def _remove_task(self) -> None:
        if not confirm(
            self,
            "Remove scheduled task",
            "Remove the Windows Task Scheduler job for daily reports?",
            confirm_text="Remove",
            danger=True,
        ):
            return

        def job():
            ok, message = scheduler.remove_scheduled_task()
            if ok:
                with self.state.database.session() as session:
                    settings_service.set_setting(session, "scheduled_task_installed", "0")
            return ok, message

        def done(result):
            ok, message = result
            if not ok:
                show_error(self, Exception(message), "Task Scheduler")
            else:
                self.main.show_status(message)
            self._check_task()

        run_task(self, job, on_success=done, message="Removing the scheduled task…", title="Scheduling")

    # ------------------------------------------------------------------
    def _integrity_check(self) -> None:
        try:
            ok, detail = self.state.database.integrity_check()
        except Exception as exc:
            show_error(self, exc, "Integrity check failed")
            return
        if ok:
            show_info(self, "The database passed its integrity check.", "Database integrity")
        else:
            show_error(self, Exception(detail), "Database integrity")
