"""Record a multi-item sale."""

from __future__ import annotations

import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...models import PAYMENT_METHODS
from ...money import from_milli, line_total_minor, to_milli, to_minor
from ...services import catalog, sales
from ..common import show_error
from ..dialogs import ReceiptDialog
from ..models import TableColumn
from ..widgets import (
    DataTable,
    Divider,
    PageHeader,
    ProductCombo,
    SectionCard,
    make_button,
)
from ..workers import run_task
from .base import BasePage


class RecordSalePage(BasePage):
    def build(self) -> None:
        self.cart: list[dict] = []
        self.idempotency_key = uuid.uuid4().hex
        self._busy = False

        self.header = PageHeader(
            "Record Sale", "Build the basket, choose a payment method and complete the sale."
        )
        self.header.add_action("Clear", "secondary", "trash", self._clear)
        self.complete_header = self.header.add_action(
            "Complete sale", "primary", "check", self._complete
        )
        self.layout.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(12)

        basket_card = SectionCard("Basket", "Add products, quantities and optional line discounts.")
        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.product_combo = ProductCombo()
        self.product_combo.product_changed.connect(self._product_changed)
        add_row.addWidget(self.product_combo, 1)
        self.quantity_edit = QLineEdit("1")
        self.quantity_edit.setFixedWidth(86)
        self.quantity_edit.setAlignment(Qt.AlignRight)
        self.quantity_edit.setPlaceholderText("Qty")
        add_row.addWidget(self.quantity_edit)
        self.discount_edit = QLineEdit("0.00")
        self.discount_edit.setFixedWidth(96)
        self.discount_edit.setAlignment(Qt.AlignRight)
        self.discount_edit.setPlaceholderText("Discount")
        add_row.addWidget(self.discount_edit)
        add_button = make_button("Add to basket", "primary", "plus", self._add_item)
        add_row.addWidget(add_button)
        basket_card.content.addLayout(add_row)

        self.stock_hint = QLabel("Select a product to see availability.")
        self.stock_hint.setObjectName("Muted")
        basket_card.content.addWidget(self.stock_hint)

        self.table = DataTable()
        self.table.setMinimumHeight(260)
        basket_card.content.addWidget(self.table, 1)

        cart_actions = QHBoxLayout()
        remove = make_button("Remove selected", "secondary", "trash", self._remove_selected)
        cart_actions.addWidget(remove)
        cart_actions.addStretch(1)
        self.footer_hint = QLabel("Ctrl+N focuses the product search  ·  Ctrl+S completes the sale")
        self.footer_hint.setObjectName("Muted")
        cart_actions.addWidget(self.footer_hint)
        basket_card.content.addLayout(cart_actions)
        body.addWidget(basket_card, 3)

        payment_card = SectionCard("Payment", "Summary and payment details")
        self.subtotal_label = QLabel(self.state.money(0))
        self.discount_label = QLabel(self.state.money(0))
        self.total_label = QLabel(self.state.money(0))
        self.total_label.setObjectName("KpiValue")
        for label, value in (
            ("Subtotal", self.subtotal_label),
            ("Discounts", self.discount_label),
        ):
            row = QHBoxLayout()
            text = QLabel(label)
            text.setObjectName("Muted")
            row.addWidget(text, 1)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(value)
            payment_card.content.addLayout(row)
        payment_card.content.addWidget(Divider())
        total_row = QHBoxLayout()
        total_text = QLabel("Total")
        total_text.setObjectName("SectionTitle")
        total_row.addWidget(total_text, 1)
        self.total_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        total_row.addWidget(self.total_label)
        payment_card.content.addLayout(total_row)

        method_label = QLabel("Payment method")
        method_label.setObjectName("FieldLabel")
        payment_card.content.addWidget(method_label)
        self.payment_combo = QComboBox()
        for method in PAYMENT_METHODS:
            self.payment_combo.addItem(method)
        payment_card.content.addWidget(self.payment_combo)

        notes_label = QLabel("Notes")
        notes_label.setObjectName("FieldLabel")
        payment_card.content.addWidget(notes_label)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(76)
        self.notes_edit.setPlaceholderText("Optional note shown on the transaction")
        payment_card.content.addWidget(self.notes_edit)

        payment_card.content.addStretch(1)
        self.complete_button = make_button(
            "Complete sale", "primary", "check", self._complete
        )
        self.complete_button.setMinimumHeight(44)
        payment_card.content.addWidget(self.complete_button)
        body.addWidget(payment_card, 2)
        self.layout.addLayout(body, 1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        with self.state.database.session() as session:
            products = catalog.all_active_products(session)
        self.product_combo.load(products)
        self._render_cart()

    def _product_changed(self, _product_id) -> None:
        stock = self.product_combo.current_stock_milli()
        price = self.product_combo.current_price_minor()
        if stock is None:
            self.stock_hint.setText("Select a product to see availability.")
            return
        self.stock_hint.setText(
            f"Available: {self.state.quantity(stock)} {self._unit()}  ·  "
            f"Price: {self.state.money(price)}"
        )

    def _unit(self) -> str:
        product_id = self.product_combo.current_product_id()
        if product_id is None:
            return ""
        with self.state.database.session() as session:
            product = session.get(catalog.Product, product_id)
            return product.unit if product else ""

    def _add_item(self) -> None:
        product_id = self.product_combo.current_product_id()
        if product_id is None:
            show_error(self, ValueError("Choose a product first."), "No product selected")
            return
        try:
            qty_milli = to_milli(self.quantity_edit.text() or 0, field="Quantity")
            if qty_milli <= 0:
                raise ValueError("Quantity must be greater than zero.")
            discount_minor = to_minor(self.discount_edit.text() or 0, field="Discount")
            if discount_minor < 0:
                raise ValueError("Discount cannot be negative.")
        except Exception as exc:
            show_error(self, exc, "Check the quantity and discount")
            return

        price_minor = int(self.product_combo.current_price_minor() or 0)
        name = self.product_combo.current_name()
        stock = int(self.product_combo.current_stock_milli() or 0)
        existing = next((row for row in self.cart if row["product_id"] == product_id), None)
        existing_qty = existing["quantity_milli"] if existing else 0
        if existing_qty + qty_milli > stock:
            show_error(
                self,
                ValueError(
                    f"Only {self.state.quantity(stock)} available for {name}; "
                    f"{self.state.quantity(existing_qty)} already in the basket."
                ),
                "Not enough stock",
            )
            return
        try:
            if existing:
                new_qty = existing_qty + qty_milli
                new_discount = existing["discount_minor"] + discount_minor
                gross = line_total_minor(new_qty, price_minor)
                if new_discount > gross:
                    raise ValueError("Discount cannot exceed the line value.")
                existing["quantity_milli"] = new_qty
                existing["discount_minor"] = new_discount
                existing["line_total_minor"] = gross - new_discount
                if existing["unit_price_minor"] != price_minor:
                    existing["unit_price_minor"] = price_minor
            else:
                gross = line_total_minor(qty_milli, price_minor)
                if discount_minor > gross:
                    raise ValueError("Discount cannot exceed the line value.")
                self.cart.append(
                    {
                        "product_id": product_id,
                        "name": name,
                        "quantity_milli": qty_milli,
                        "unit_price_minor": price_minor,
                        "discount_minor": discount_minor,
                        "line_total_minor": gross - discount_minor,
                    }
                )
        except Exception as exc:
            show_error(self, exc, "Check the discount")
            return
        self.quantity_edit.setText("1")
        self.discount_edit.setText("0.00")
        self.product_combo.setCurrentIndex(-1)
        self.product_combo.lineEdit().clear()
        self._render_cart()

    def _remove_selected(self) -> None:
        record = self.table.selected_record()
        if record is None:
            return
        product_id = record.get("product_id")
        self.cart = [row for row in self.cart if row["product_id"] != product_id]
        self._render_cart()

    def _clear(self) -> None:
        self.cart.clear()
        self.notes_edit.clear()
        self.idempotency_key = uuid.uuid4().hex
        self._render_cart()

    def _render_cart(self) -> None:
        subtotal = sum(row["line_total_minor"] + row["discount_minor"] for row in self.cart)
        discount = sum(row["discount_minor"] for row in self.cart)
        net = sum(row["line_total_minor"] for row in self.cart)
        self.subtotal_label.setText(self.state.money(subtotal))
        self.discount_label.setText(self.state.money(discount))
        self.total_label.setText(self.state.money(net))
        self.complete_button.setEnabled(bool(self.cart) and not self._busy)
        self.table.set_data(
            self.cart,
            [
                TableColumn("name", "Product", 220, bold=True),
                TableColumn(
                    "quantity_milli",
                    "Qty",
                    74,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("quantity_milli")),
                ),
                TableColumn(
                    "unit_price_minor",
                    "Unit price",
                    108,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("unit_price_minor")),
                ),
                TableColumn(
                    "discount_minor",
                    "Discount",
                    98,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("discount_minor")),
                ),
                TableColumn(
                    "line_total_minor",
                    "Line total",
                    116,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("line_total_minor")),
                    bold=True,
                ),
            ],
        )

    # ------------------------------------------------------------------
    def _complete(self) -> None:
        if self._busy:
            return
        if not self.cart:
            show_error(self, ValueError("The basket is empty."), "Nothing to sell")
            return
        items = [
            {
                "product_id": row["product_id"],
                "quantity": from_milli(row["quantity_milli"]),
                "discount_minor": row["discount_minor"],
            }
            for row in self.cart
        ]
        payment = self.payment_combo.currentText()
        notes = self.notes_edit.toPlainText().strip()
        key = self.idempotency_key

        def job():
            with self.state.database.session() as session:
                sale = sales.create_sale(
                    session,
                    items=items,
                    payment_method=payment,
                    operator_id=self.state.operator_id,
                    business_date=self.state.business_date,
                    idempotency_key=key,
                    notes=notes,
                )
                return {
                    "transaction_number": sale.transaction_number,
                    "payment_method": sale.payment_method,
                    "subtotal_minor": sale.subtotal_minor,
                    "discount_total_minor": sale.discount_total_minor,
                    "net_total_minor": sale.net_total_minor,
                    "business_date": sale.business_date,
                    "items": [
                        {
                            "name": item.product_name_snapshot,
                            "quantity_milli": item.quantity_milli,
                            "unit_price_minor": item.unit_price_minor,
                            "line_total_minor": item.line_total_minor,
                        }
                        for item in sale.items
                    ],
                }

        self._busy = True
        self.complete_button.setEnabled(False)
        self.complete_header.setEnabled(False)
        run_task(
            self,
            job,
            on_success=self._sold,
            on_error=self._sale_failed,
            message="Completing the sale…",
            title="Record sale",
        )

    def _sold(self, receipt: dict) -> None:
        self._busy = False
        self.complete_button.setEnabled(True)
        self.complete_header.setEnabled(True)
        self.cart.clear()
        self.notes_edit.clear()
        self.idempotency_key = uuid.uuid4().hex
        self.refresh()
        self.state.notify_data_changed()
        self.main.request_report_refresh()
        self.main.show_status(
            f"Sale {receipt['transaction_number']} completed — {self.state.money(receipt['net_total_minor'])}."
        )
        ReceiptDialog(receipt, self.state, self).exec()

    def _sale_failed(self, message: str) -> None:
        self._busy = False
        self.complete_button.setEnabled(bool(self.cart))
        self.complete_header.setEnabled(True)
        show_error(self, Exception(message), "Sale could not be completed")
        self.refresh()

    # ------------------------------------------------------------------
    def new_action(self) -> None:
        self.product_combo.setFocus()
        self.product_combo.lineEdit().selectAll()

    def focus_search(self) -> None:
        self.new_action()

    def save_action(self) -> None:
        self._complete()
