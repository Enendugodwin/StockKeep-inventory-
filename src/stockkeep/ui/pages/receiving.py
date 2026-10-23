"""Stock receiving page."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
)

from ...money import from_minor
from ...services import catalog, stock
from ..common import pydate, qdate, show_error
from ..models import TableColumn
from ..widgets import DataTable, PageHeader, ProductCombo, SectionCard
from .base import BasePage


class ReceivingPage(BasePage):
    def build(self) -> None:
        self.header = PageHeader(
            "Stock Receiving", "Record supplier deliveries. Every receipt becomes a stock movement."
        )
        self.header.add_action("Receive stock", "primary", "receiving", self._receive)
        self.layout.addWidget(self.header)

        card = SectionCard("New receipt", "Supplier and reference details are optional but recommended.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        self.product_combo = ProductCombo()
        self.product_combo.product_changed.connect(self._product_changed)
        grid.addWidget(self._label("Stock item *"), 0, 0)
        grid.addWidget(self.product_combo, 0, 1, 1, 3)

        self.quantity_edit = QLineEdit()
        self.quantity_edit.setPlaceholderText("e.g. 12")
        grid.addWidget(self._label("Quantity received *"), 1, 0)
        grid.addWidget(self.quantity_edit, 1, 1)

        self.cost_edit = QLineEdit()
        self.cost_edit.setPlaceholderText("Unit cost")
        grid.addWidget(self._label("Unit cost"), 1, 2)
        grid.addWidget(self.cost_edit, 1, 3)

        self.supplier_edit = QLineEdit()
        self.supplier_edit.setPlaceholderText("Supplier name")
        grid.addWidget(self._label("Supplier"), 2, 0)
        grid.addWidget(self.supplier_edit, 2, 1)

        self.reference_edit = QLineEdit()
        self.reference_edit.setPlaceholderText("Invoice / delivery note")
        grid.addWidget(self._label("Reference"), 2, 2)
        grid.addWidget(self.reference_edit, 2, 3)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd MMM yyyy")
        self.date_edit.setDate(qdate(self.state.business_date))
        grid.addWidget(self._label("Business date"), 3, 0)
        grid.addWidget(self.date_edit, 3, 1)

        self.update_cost_check = QCheckBox("Update the product cost price")
        self.update_cost_check.setChecked(True)
        grid.addWidget(self.update_cost_check, 3, 2, 1, 2)

        self.note_edit = QPlainTextEdit()
        self.note_edit.setFixedHeight(58)
        self.note_edit.setPlaceholderText("Optional note")
        grid.addWidget(self._label("Note"), 4, 0)
        grid.addWidget(self.note_edit, 4, 1, 1, 3)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        card.content.addLayout(grid)
        self.layout.addWidget(card)

        recent = SectionCard("Recent receipts", "Latest stock received")
        self.table = DataTable()
        self.table.setMinimumHeight(230)
        recent.content.addWidget(self.table, 1)
        self.layout.addWidget(recent, 1)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        with self.state.database.session() as session:
            products = catalog.all_active_products(session)
        current = self.product_combo.current_product_id()
        self.product_combo.load(products)
        if current is not None:
            self.product_combo.select_product(current)
        self._load_recent()

    def _load_recent(self) -> None:
        with self.state.database.session() as session:
            rows = [
                {
                    "created_at": receipt.created_at,
                    "business_date": receipt.business_date,
                    "product": receipt.product.name if receipt.product else "",
                    "quantity_milli": receipt.quantity_milli,
                    "unit_cost_minor": receipt.unit_cost_minor,
                    "value_minor": int((receipt.quantity_milli * receipt.unit_cost_minor) // 1000),
                    "supplier": receipt.supplier.name if receipt.supplier else "",
                    "reference": receipt.reference or "",
                    "operator": receipt.operator.name if receipt.operator else "",
                }
                for receipt in stock.recent_receipts(session, 80)
            ]
        self.table.set_data(
            rows,
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
                    120,
                    formatter=lambda row: self.state.date(row.get("business_date")),
                ),
                TableColumn("product", "Stock item", 200, bold=True),
                TableColumn(
                    "quantity_milli",
                    "Qty",
                    80,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("quantity_milli")),
                ),
                TableColumn(
                    "unit_cost_minor",
                    "Unit cost",
                    100,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("unit_cost_minor")),
                ),
                TableColumn(
                    "value_minor",
                    "Value",
                    110,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("value_minor")),
                ),
                TableColumn("supplier", "Supplier", 140),
                TableColumn("reference", "Reference", 140),
                TableColumn("operator", "Operator", 120),
            ],
        )

    def _product_changed(self, _product_id) -> None:
        product_id = self.product_combo.current_product_id()
        if product_id is None:
            return
        with self.state.database.session() as session:
            product = session.get(catalog.Product, product_id)
            if product is None:
                return
            self.cost_edit.setText(str(from_minor(product.cost_price_minor)))
            self.reference_edit.setPlaceholderText(
                f"Invoice / delivery note  ·  current stock {self.state.quantity(product.quantity_milli)}"
            )
        self.quantity_edit.setFocus()

    def _receive(self) -> None:
        product_id = self.product_combo.current_product_id()
        if product_id is None:
            show_error(self, ValueError("Choose a stock item first."), "No stock item")
            return
        business_day: date = pydate(self.date_edit.date())
        try:
            with self.state.database.session() as session:
                stock.receive_stock(
                    session,
                    product_id=product_id,
                    quantity=self.quantity_edit.text(),
                    unit_cost=self.cost_edit.text() or None,
                    supplier_name=self.supplier_edit.text(),
                    reference=self.reference_edit.text(),
                    note=self.note_edit.toPlainText(),
                    operator_id=self.state.operator_id,
                    business_date=business_day,
                    update_cost_price=self.update_cost_check.isChecked(),
                )
        except Exception as exc:
            show_error(self, exc, "Could not record the receipt")
            return
        self.quantity_edit.clear()
        self.reference_edit.clear()
        self.note_edit.clear()
        self.state.notify_data_changed()
        self.main.request_report_refresh()
        self.main.show_status("Stock receipt recorded.")
        self.refresh()

    # ------------------------------------------------------------------
    def save_action(self) -> None:
        self._receive()

    def new_action(self) -> None:
        self.product_combo.setFocus()
        self.product_combo.lineEdit().selectAll()
