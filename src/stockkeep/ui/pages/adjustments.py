"""Stock adjustments: damage, loss, expiry and count corrections."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
)

from ...services import catalog, stock
from ..common import pydate, qdate, show_error
from ..models import TableColumn
from ..widgets import DataTable, PageHeader, ProductCombo, SectionCard
from .base import BasePage


ADJUSTMENT_OPTIONS = [
    ("Damaged stock", "damage"),
    ("Missing / lost stock", "loss"),
    ("Expired stock", "expiry"),
    ("Stock-count correction", "count"),
    ("Other authorised adjustment", "adjustment"),
]


class AdjustmentsPage(BasePage):
    def build(self) -> None:
        self.header = PageHeader(
            "Stock Adjustments",
            "Every adjustment writes an immutable movement and is attributed to you.",
        )
        self.header.add_action("Record adjustment", "primary", "adjustments", self._submit)
        self.layout.addWidget(self.header)

        card = SectionCard(
            "New adjustment",
            "Use a count correction to set the physically counted quantity; other types remove stock.",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        self.product_combo = ProductCombo()
        self.product_combo.product_changed.connect(self._product_changed)
        grid.addWidget(self._label("Stock item *"), 0, 0)
        grid.addWidget(self.product_combo, 0, 1, 1, 3)

        self.type_combo = QComboBox()
        for label, value in ADJUSTMENT_OPTIONS:
            self.type_combo.addItem(label, value)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        grid.addWidget(self._label("Adjustment type *"), 1, 0)
        grid.addWidget(self.type_combo, 1, 1)

        self.quantity_label = self._label("Quantity to remove *")
        grid.addWidget(self.quantity_label, 1, 2)
        self.quantity_edit = QLineEdit()
        self.quantity_edit.setPlaceholderText("e.g. 2")
        grid.addWidget(self.quantity_edit, 1, 3)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd MMM yyyy")
        self.date_edit.setDate(qdate(self.state.business_date))
        grid.addWidget(self._label("Business date"), 2, 0)
        grid.addWidget(self.date_edit, 2, 1)

        self.stock_hint = QLabel("Select a stock item to see its current quantity.")
        self.stock_hint.setObjectName("Muted")
        grid.addWidget(self.stock_hint, 2, 2, 1, 2)

        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("Why is this adjustment needed? (required)")
        grid.addWidget(self._label("Reason *"), 3, 0)
        grid.addWidget(self.reason_edit, 3, 1, 1, 3)

        self.note_edit = QPlainTextEdit()
        self.note_edit.setFixedHeight(58)
        self.note_edit.setPlaceholderText("Optional note")
        grid.addWidget(self._label("Note"), 4, 0)
        grid.addWidget(self.note_edit, 4, 1, 1, 3)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        card.content.addLayout(grid)

        warning = QLabel(
            "Adjustments cannot be edited or deleted. If a correction is wrong, record a new "
            "adjustment with the correct quantity."
        )
        warning.setObjectName("Muted")
        warning.setWordWrap(True)
        card.content.addWidget(warning)
        self.layout.addWidget(card)

        recent = SectionCard("Recent adjustments", "Damage, loss, expiry and count corrections")
        self.table = DataTable()
        self.table.setMinimumHeight(220)
        recent.content.addWidget(self.table, 1)
        self.layout.addWidget(recent, 1)
        self._type_changed()

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        with self.state.database.session() as session:
            products = catalog.all_active_products(session)
            self._form_rows = [
                {
                    "created_at": movement.created_at,
                    "business_date": movement.business_date,
                    "product": movement.product.name if movement.product else "",
                    "type": stock.TYPE_LABELS.get(movement.movement_type, movement.movement_type.title()),
                    "change": movement.quantity_change_milli,
                    "before": movement.quantity_before_milli,
                    "after": movement.quantity_after_milli,
                    "reason": movement.reason or "",
                    "operator": movement.operator.name if movement.operator else "",
                }
                for movement in stock.recent_adjustments(session, 80)
            ]
        current = self.product_combo.current_product_id()
        self.product_combo.load(products)
        if current is not None:
            self.product_combo.select_product(current)
        self.table.set_data(
            self._form_rows,
            [
                TableColumn(
                    "created_at",
                    "Recorded",
                    140,
                    formatter=lambda row: self.state.datetime(row.get("created_at")),
                ),
                TableColumn(
                    "business_date",
                    "Business date",
                    118,
                    formatter=lambda row: self.state.date(row.get("business_date")),
                ),
                TableColumn("product", "Stock item", 190, bold=True),
                TableColumn("type", "Type", 150),
                TableColumn(
                    "change",
                    "Change",
                    86,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("change")),
                ),
                TableColumn(
                    "before",
                    "Before",
                    82,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("before")),
                ),
                TableColumn(
                    "after",
                    "After",
                    82,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("after")),
                ),
                TableColumn("reason", "Reason", 240),
                TableColumn("operator", "Operator", 120),
            ],
        )

    def _type_changed(self, _index: int = 0) -> None:
        counted = self.type_combo.currentData() == "count"
        self.quantity_label.setText("Counted quantity *" if counted else "Quantity to remove *")
        self.quantity_edit.setPlaceholderText(
            "Physical quantity on hand" if counted else "e.g. 2"
        )

    def _product_changed(self, _product_id) -> None:
        stock_milli = self.product_combo.current_stock_milli()
        if stock_milli is None:
            self.stock_hint.setText("Select a stock item to see its current quantity.")
            return
        self.stock_hint.setText(
            f"Current quantity: {self.state.quantity(stock_milli)}  ·  "
            f"Price: {self.state.money(self.product_combo.current_price_minor())}"
        )

    def _submit(self) -> None:
        product_id = self.product_combo.current_product_id()
        if product_id is None:
            show_error(self, ValueError("Choose a stock item first."), "No stock item")
            return
        reason = self.reason_edit.text().strip()
        if not reason:
            show_error(self, ValueError("A reason is required."), "Reason required")
            return
        adjustment_type = self.type_combo.currentData()
        business_day: date = pydate(self.date_edit.date())
        try:
            with self.state.database.session() as session:
                if adjustment_type == "count":
                    stock.adjust_stock(
                        session,
                        product_id=product_id,
                        adjustment_type=adjustment_type,
                        new_quantity=self.quantity_edit.text(),
                        reason=reason,
                        note=self.note_edit.toPlainText(),
                        operator_id=self.state.operator_id,
                        business_date=business_day,
                    )
                else:
                    stock.adjust_stock(
                        session,
                        product_id=product_id,
                        adjustment_type=adjustment_type,
                        quantity=self.quantity_edit.text(),
                        reason=reason,
                        note=self.note_edit.toPlainText(),
                        operator_id=self.state.operator_id,
                        business_date=business_day,
                    )
        except Exception as exc:
            show_error(self, exc, "Could not record the adjustment")
            return
        self.quantity_edit.clear()
        self.reason_edit.clear()
        self.note_edit.clear()
        self.state.notify_data_changed()
        self.main.request_report_refresh()
        self.main.show_status("Stock adjustment recorded.")
        self.refresh()

    def save_action(self) -> None:
        self._submit()

    def new_action(self) -> None:
        self.product_combo.setFocus()
        self.product_combo.lineEdit().selectAll()
