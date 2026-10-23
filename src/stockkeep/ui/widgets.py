"""Reusable native widgets used across StockKeep pages."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .models import RecordTableModel, TableColumn


# ---------------------------------------------------------------------------
# Layout primitives
# ---------------------------------------------------------------------------
class Card(QFrame):
    def __init__(self, parent=None, *, padding: int = 16, spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)


class SectionCard(Card):
    def __init__(
        self,
        title: str,
        subtitle: str = "",
        parent=None,
        *,
        padding: int = 16,
    ):
        super().__init__(parent, padding=padding, spacing=10)
        self.header = QWidget(self)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("SectionTitle")
        titles.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("SectionSubtitle")
        self.subtitle_label.setVisible(bool(subtitle))
        titles.addWidget(self.subtitle_label)
        header_layout.addLayout(titles, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        header_layout.addLayout(self.actions)
        self.body.addWidget(self.header)
        self.content = QVBoxLayout()
        self.content.setContentsMargins(0, 2, 0, 0)
        self.content.setSpacing(8)
        self.body.addLayout(self.content, 1)

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        return widget


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        titles.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("PageSubtitle")
        titles.addWidget(self.subtitle_label)
        layout.addLayout(titles, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def add_action(
        self,
        text: str,
        variant: str = "secondary",
        icon: str | None = None,
        slot=None,
    ) -> QPushButton:
        button = QPushButton(display_text(text))
        if variant == "primary":
            button.setObjectName("PrimaryButton")
        elif variant == "danger":
            button.setObjectName("DangerButton")
        if icon:
            button.setIcon(icons.icon(icon, "#FFFFFF" if variant == "primary" else "#667C8A", 18))
            button.setIconSize(QSize(18, 18))
        if slot is not None:
            button.clicked.connect(slot)
        self.actions.addWidget(button)
        return button


class KpiCard(QFrame):
    def __init__(self, label: str, icon: str = "package", tone: str = "#0E7C86", parent=None):
        super().__init__(parent)
        self.setObjectName("KpiCard")
        self.setMinimumHeight(106)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 13)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap(icon, tone, 17))
        top.addWidget(icon_label)
        self.label = QLabel(label.upper())
        self.label.setObjectName("KpiLabel")
        top.addWidget(self.label, 1)
        layout.addLayout(top)
        self.value = QLabel("—")
        self.value.setObjectName("KpiValue")
        layout.addWidget(self.value)
        self.hint = QLabel("")
        self.hint.setObjectName("KpiHint")
        self.hint.setVisible(False)
        layout.addWidget(self.hint)

    def set_value(self, value: str, hint: str | None = None) -> None:
        self.value.setText(value)
        if hint:
            self.hint.setText(hint)
            self.hint.setVisible(True)
        else:
            self.hint.setVisible(False)


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)


class Field(QWidget):
    def __init__(self, label: str, widget: QWidget, hint: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        text = QLabel(label)
        text.setObjectName("FieldLabel")
        layout.addWidget(text)
        layout.addWidget(widget)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("Muted")
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)


class EmptyState(QWidget):
    def __init__(self, title: str, text: str = "", icon_name: str = "package", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 26, 18, 26)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)
        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap(icon_name, "#8AA0AC", 30))
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)
        title_label = QLabel(title)
        title_label.setObjectName("EmptyTitle")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        if text:
            text_label = QLabel(text)
            text_label.setObjectName("EmptyText")
            text_label.setAlignment(Qt.AlignCenter)
            text_label.setWordWrap(True)
            layout.addWidget(text_label)


# ---------------------------------------------------------------------------
# Buttons / inputs
# ---------------------------------------------------------------------------
def display_text(value: str) -> str:
    """Escape ampersands so Qt does not treat them as button mnemonics."""
    return str(value).replace("&", "&&")


def make_button(
    text: str,
    variant: str = "secondary",
    icon_name: str | None = None,
    slot=None,
    parent=None,
) -> QPushButton:
    button = QPushButton(display_text(text), parent)
    if variant == "primary":
        button.setObjectName("PrimaryButton")
        color = "#FFFFFF"
    elif variant == "danger":
        button.setObjectName("DangerButton")
        color = "#C0362C"
    elif variant == "ghost":
        button.setObjectName("GhostButton")
        color = "#667C8A"
    elif variant == "link":
        button.setObjectName("LinkButton")
        color = "#0E7C86"
    elif variant == "quick":
        button.setObjectName("QuickAction")
        color = "#0E7C86"
    else:
        color = "#667C8A"
    if icon_name:
        button.setIcon(icons.icon(icon_name, color, 17))
        button.setIconSize(QSize(17, 17))
    if slot is not None:
        button.clicked.connect(slot)
    return button


class SearchBox(QLineEdit):
    def __init__(self, placeholder: str = "Search…", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.addAction(icons.icon("search", "#8AA0AC", 16), QLineEdit.LeadingPosition)
        self.setMinimumWidth(220)


class PaginationBar(QWidget):
    page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.page = 1
        self.page_size = 50
        self.total = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.info = QLabel("0 records")
        self.info.setObjectName("Muted")
        layout.addWidget(self.info, 1)
        self.prev = QPushButton()
        self.prev.setObjectName("SecondaryButton")
        self.prev.setIcon(icons.icon("left", "#667C8A", 16))
        self.prev.setFixedWidth(34)
        self.prev.clicked.connect(lambda: self._go(self.page - 1))
        layout.addWidget(self.prev)
        self.page_label = QLabel("Page 1 of 1")
        self.page_label.setObjectName("Muted")
        self.page_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.page_label)
        self.next = QPushButton()
        self.next.setObjectName("SecondaryButton")
        self.next.setIcon(icons.icon("right", "#667C8A", 16))
        self.next.setFixedWidth(34)
        self.next.clicked.connect(lambda: self._go(self.page + 1))
        layout.addWidget(self.next)

    @property
    def pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    def set_state(self, page: int, total: int, page_size: int) -> None:
        self.page = max(1, page)
        self.total = max(0, total)
        self.page_size = max(1, page_size)
        self.info.setText(f"{self.total:,} record{'s' if self.total != 1 else ''}")
        self.page_label.setText(f"Page {min(self.page, self.pages)} of {self.pages}")
        self.prev.setEnabled(self.page > 1)
        self.next.setEnabled(self.page < self.pages)

    def _go(self, page: int) -> None:
        if 1 <= page <= self.pages and page != self.page:
            self.page = page
            self.page_changed.emit(page)


class ProductCombo(QComboBox):
    """Searchable product picker with ids and stock levels."""

    product_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(14)
        self.setMinimumWidth(280)
        self.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.completer().setFilterMode(Qt.MatchContains)
        self.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self._stock: dict[int, int] = {}
        self._price: dict[int, int] = {}
        self._names: dict[int, str] = {}
        self.currentIndexChanged.connect(self._changed)

    def load(self, products) -> None:
        current = self.current_product_id()
        self.blockSignals(True)
        self.clear()
        self._stock.clear()
        self._price.clear()
        self._names.clear()
        for product in products:
            label = f"{product.name}  ·  {product.product_code}"
            self.addItem(label, product.id)
            self._stock[product.id] = int(product.quantity_milli)
            self._price[product.id] = int(product.selling_price_minor)
            self._names[product.id] = product.name
        self.setCurrentIndex(-1)
        self.lineEdit().clear()
        self.blockSignals(False)
        if current in self._stock:
            self.select_product(current)

    def select_product(self, product_id: int) -> None:
        index = self.findData(product_id)
        if index >= 0:
            self.setCurrentIndex(index)

    def current_product_id(self) -> int | None:
        data = self.currentData()
        return int(data) if data is not None else None

    def current_stock_milli(self) -> int | None:
        product_id = self.current_product_id()
        return self._stock.get(product_id) if product_id is not None else None

    def current_price_minor(self) -> int | None:
        product_id = self.current_product_id()
        return self._price.get(product_id) if product_id is not None else None

    def current_name(self) -> str:
        product_id = self.current_product_id()
        return self._names.get(product_id, "") if product_id is not None else ""

    def _changed(self, _index: int) -> None:
        self.product_changed.emit(self.current_product_id())


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
class DataTable(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSortingEnabled(True)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(38)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.model_ref: RecordTableModel | None = None
        self._selection_callbacks = []

    def connect_selection(self, callback) -> None:
        """Register a selection handler that survives `set_data()` model swaps."""
        if callback in self._selection_callbacks:
            return
        self._selection_callbacks.append(callback)
        if self.selectionModel() is not None:
            self.selectionModel().selectionChanged.connect(callback)

    def set_data(self, rows: list[dict], columns: list[TableColumn]) -> None:
        self.setSortingEnabled(False)
        self.model_ref = RecordTableModel(columns, rows, self)
        self.setModel(self.model_ref)
        header = self.horizontalHeader()
        for index, column in enumerate(columns):
            self.setColumnWidth(index, column.width)
        self.setSortingEnabled(True)
        model = self.selectionModel()
        if model is not None:
            for callback in self._selection_callbacks:
                model.selectionChanged.connect(callback)

    def selected_record(self) -> dict | None:
        indexes = self.selectionModel().selectedRows() if self.selectionModel() else []
        if not indexes or self.model_ref is None:
            return None
        return self.model_ref.row_at(indexes[0].row())

    def record_at(self, index) -> dict | None:
        if self.model_ref is None or not index.isValid():
            return None
        return self.model_ref.row_at(index.row())


class BarChart(QWidget):
    """Small native bar chart (no charting dependency)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values: list[tuple[str, int]] = []
        self.minimum_height = 160
        self.setMinimumHeight(self.minimum_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_values(self, values: list[tuple[str, int]]) -> None:
        self.values = list(values or [])
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        palette = self.palette()
        text_color = palette.color(QPalette.Text)
        muted = palette.color(QPalette.Mid)
        accent = palette.color(QPalette.Highlight)
        rect = self.rect().adjusted(4, 8, -4, -24)
        if not self.values:
            painter.setPen(muted)
            painter.drawText(rect, Qt.AlignCenter, "No data for this period")
            painter.end()
            return

        maximum = max(value for _label, value in self.values)
        maximum = max(1, maximum)
        count = len(self.values)
        slot = rect.width() / max(1, count)
        bar_width = max(3.0, slot * 0.58)
        baseline = rect.bottom()

        painter.setPen(Qt.NoPen)
        for index, (label, value) in enumerate(self.values):
            height = 0 if value <= 0 else max(3.0, (value / maximum) * rect.height())
            left = rect.left() + index * slot + (slot - bar_width) / 2
            painter.setBrush(accent)
            painter.drawRoundedRect(
                int(left), int(baseline - height), int(bar_width), int(height), 3, 3
            )

        painter.setPen(muted)
        font = QFont(painter.font())
        font.setPointSizeF(7.5)
        painter.setFont(font)
        step = max(1, count // 7)
        for index, (label, _value) in enumerate(self.values):
            if index % step and index != count - 1:
                continue
            left = rect.left() + index * slot
            painter.drawText(
                int(left - 6), baseline + 4, int(slot + 12), 16, Qt.AlignHCenter | Qt.AlignTop, label
            )
        painter.setPen(text_color)
        painter.end()


def open_path(path: Path | str) -> None:
    target = Path(path)
    if target.is_file():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))
    elif target.is_dir():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
    elif target.parent.is_dir():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))
