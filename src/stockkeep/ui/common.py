"""Shared helpers used by the individual pages and dialogs."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QWidget,
)

from ..errors import StockKeepError
from .models import TableColumn


def qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


def pydate(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def error_text(exc: Exception) -> str:
    message = getattr(exc, "message", None)
    if message:
        return str(message)
    text = str(exc).strip()
    return text or exc.__class__.__name__


def show_error(parent, exc: Exception, title: str = "Could not complete the action") -> None:
    QMessageBox.warning(parent, title, error_text(exc))


def show_info(parent, message: str, title: str = "StockKeep") -> None:
    QMessageBox.information(parent, title, message)


def confirm(
    parent,
    title: str,
    message: str,
    *,
    confirm_text: str = "Continue",
    cancel_text: str = "Cancel",
    danger: bool = False,
) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    box.setText(message)
    accept = box.addButton(confirm_text, QMessageBox.AcceptRole)
    box.addButton(cancel_text, QMessageBox.RejectRole)
    if danger:
        accept.setObjectName("DangerButton")
    box.exec()
    return box.clickedButton() is accept


def confirm_typed(
    parent,
    title: str,
    message: str,
    expected: str,
    *,
    danger: bool = True,
) -> bool:
    """Two-step confirmation for privileged actions (inventory replacement)."""
    if not confirm(parent, title, message, confirm_text="Continue", danger=danger):
        return False
    from PySide6.QtWidgets import QInputDialog

    text, ok = QInputDialog.getText(
        parent,
        title,
        f"Type {expected} to confirm this action:",
    )
    return bool(ok and text.strip() == expected)


def money_column(
    page, key: str, label: str, width: int = 120, *, bold: bool = False
) -> TableColumn:
    return TableColumn(
        key,
        label,
        width,
        align=int(Qt.AlignRight | Qt.AlignVCenter),
        formatter=lambda row: page.state.money(row.get(key)),
        bold=bold,
    )


def qty_column(page, key: str, label: str, width: int = 100) -> TableColumn:
    return TableColumn(
        key,
        label,
        width,
        align=int(Qt.AlignRight | Qt.AlignVCenter),
        formatter=lambda row: page.state.quantity(row.get(key)),
    )


def text_column(
    key: str, label: str, width: int = 130, *, bold: bool = False, align=None
) -> TableColumn:
    column = TableColumn(key, label, width, bold=bold)
    if align is not None:
        column.align = align
    return column


def export_path(
    parent,
    state,
    name: str,
    *,
    formats: str = "Excel workbook (*.xlsx);;CSV file (*.csv)",
) -> Path | None:
    base = state.paths.exports_dir / f"{name}_{date.today():%Y%m%d}.xlsx"
    selected, _filter = QFileDialog.getSaveFileName(
        parent, "Export", str(base), formats
    )
    if not selected:
        return None
    target = Path(selected)
    return target


class DateRangeBar(QWidget):
    """Two date pickers plus a preset selector."""

    changed = Signal()

    PRESETS = (
        ("today", "Today"),
        ("yesterday", "Yesterday"),
        ("7", "Last 7 days"),
        ("30", "Last 30 days"),
        ("month", "This month"),
        ("last_month", "Last month"),
        ("year", "Year to date"),
        ("all", "All time"),
        ("custom", "Custom range"),
    )

    def __init__(self, default_preset: str = "30", parent=None):
        super().__init__(parent)
        self._updating = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.preset = QComboBox()
        for key, label in self.PRESETS:
            self.preset.addItem(label, key)
        self.preset.setMinimumWidth(132)
        layout.addWidget(self.preset)

        self.start_edit = QDateEdit()
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("dd MMM yyyy")
        self.start_edit.setMinimumWidth(122)
        layout.addWidget(self.start_edit)

        dash = QLabel("to")
        dash.setObjectName("Muted")
        layout.addWidget(dash)

        self.end_edit = QDateEdit()
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("dd MMM yyyy")
        self.end_edit.setMinimumWidth(122)
        layout.addWidget(self.end_edit)

        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.start_edit.dateChanged.connect(self._dates_edited)
        self.end_edit.dateChanged.connect(self._dates_edited)
        self.set_preset(default_preset)

    # ------------------------------------------------------------------
    def _bounds(self, key: str) -> tuple[date, date] | None:
        current = date.today()
        if key == "today":
            return current, current
        if key == "yesterday":
            day = current - timedelta(days=1)
            return day, day
        if key == "7":
            return current - timedelta(days=6), current
        if key == "30":
            return current - timedelta(days=29), current
        if key == "month":
            return current.replace(day=1), current
        if key == "last_month":
            first_this = current.replace(day=1)
            end = first_this - timedelta(days=1)
            return end.replace(day=1), end
        if key == "year":
            return current.replace(month=1, day=1), current
        if key == "all":
            return date(2000, 1, 1), current
        return None

    def set_preset(self, key: str) -> None:
        index = self.preset.findData(key)
        if index < 0:
            return
        self._updating = True
        try:
            self.preset.setCurrentIndex(index)
            bounds = self._bounds(key)
            if bounds:
                self.start_edit.setDate(qdate(bounds[0]))
                self.end_edit.setDate(qdate(bounds[1]))
        finally:
            self._updating = False
        self.changed.emit()

    def set_range(self, start: date, end: date) -> None:
        self._updating = True
        try:
            self.start_edit.setDate(qdate(start))
            self.end_edit.setDate(qdate(end))
            self.preset.setCurrentIndex(self.preset.findData("custom"))
        finally:
            self._updating = False
        self.changed.emit()

    def range(self) -> tuple[date, date]:
        start = pydate(self.start_edit.date())
        end = pydate(self.end_edit.date())
        if end < start:
            start, end = end, start
        return start, end

    def _preset_changed(self, _index: int) -> None:
        if self._updating:
            return
        key = self.preset.currentData()
        bounds = self._bounds(str(key))
        if bounds is None:
            return
        self._updating = True
        try:
            self.start_edit.setDate(qdate(bounds[0]))
            self.end_edit.setDate(qdate(bounds[1]))
        finally:
            self._updating = False
        self.changed.emit()

    def _dates_edited(self, _value) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            self.preset.setCurrentIndex(self.preset.findData("custom"))
        finally:
            self._updating = False
        self.changed.emit()
