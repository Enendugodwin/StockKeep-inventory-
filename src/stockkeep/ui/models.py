"""Qt table models for inventory, sales and report tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont


@dataclass
class TableColumn:
    key: str
    label: str
    width: int = 130
    align: int = int(Qt.AlignLeft | Qt.AlignVCenter)
    formatter: Callable[[dict], str] | None = None
    color: Callable[[dict], str | None] | None = None
    bold: bool = False


class RecordTableModel(QAbstractTableModel):
    """A lightweight model over a list of dicts (fast; no per-cell widgets)."""

    def __init__(self, columns: list[TableColumn], rows: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows: list[dict] = list(rows or [])
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = list(rows or [])
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(self.columns):
                return self.columns[section].label
        if orientation == Qt.Vertical and role == Qt.DisplayRole:
            return str(section + 1)
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        column = self.columns[index.column()]
        if role == Qt.DisplayRole:
            if column.formatter:
                try:
                    return column.formatter(row)
                except Exception:
                    return ""
            value = row.get(column.key, "")
            return "" if value is None else str(value)
        if role == Qt.UserRole:
            return row.get(column.key)
        if role == Qt.TextAlignmentRole:
            return column.align
        if role == Qt.ForegroundRole and column.color:
            color = column.color(row)
            return QBrush(QColor(color)) if color else None
        if role == Qt.FontRole and column.bold:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ToolTipRole:
            if column.formatter:
                try:
                    return column.formatter(row)
                except Exception:
                    return None
            return str(row.get(column.key, ""))
        return None

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        if not (0 <= column < len(self.columns)):
            return
        col = self.columns[column]
        reverse = order == Qt.DescendingOrder

        def key(row):
            value = row.get(col.key)
            if value is None:
                return (1, "")
            if isinstance(value, (int, float)):
                return (0, value)
            return (0, str(value).lower())

        self.layoutAboutToBeChanged.emit()
        self.rows.sort(key=key, reverse=reverse)
        self._sort_column = column
        self._sort_order = order
        self.layoutChanged.emit()

    def row_at(self, row_index: int) -> dict | None:
        if 0 <= row_index < len(self.rows):
            return self.rows[row_index]
        return None
