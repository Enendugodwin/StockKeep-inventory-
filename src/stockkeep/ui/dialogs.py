"""Native dialogs shared by StockKeep pages."""

from __future__ import annotations

import json
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import security
from ..models import PAYMENT_METHODS
from ..money import from_milli
from ..services import catalog, sales, stock
from ..timeutil import today
from . import icons
from .common import confirm, error_text, money_column, show_error
from .models import TableColumn
from .widgets import DataTable, Divider, make_button


def _label(text: str, object_name: str = "FieldLabel") -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    return label


def _dialog_buttons(dialog: QDialog, save_text: str) -> tuple[QDialogButtonBox, QPushButton]:
    box = QDialogButtonBox(QDialogButtonBox.Cancel)
    save = QPushButton(save_text)
    save.setObjectName("PrimaryButton")
    box.addButton(save, QDialogButtonBox.AcceptRole)
    box.rejected.connect(dialog.reject)
    return box, save


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
class ProductEditorDialog(QDialog):
    def __init__(self, state, *, product_id: int | None = None, parent=None):
        super().__init__(parent)
        self.state = state
        self.product_id = product_id
        self.saved_id: int | None = None
        self.setWindowTitle("Edit stock item" if product_id else "Add stock item")
        self.setModal(True)
        self.setMinimumWidth(600)

        product = None
        categories: list[str] = []
        with state.database.session() as session:
            categories = [item.name for item in catalog.list_categories(session)]
            if product_id is not None:
                product = session.get(catalog.Product, product_id)
                if product is None:
                    raise ValueError("Product not found.")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        title = QLabel("Stock item details")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        layout.addLayout(grid)

        self.code_edit = QLineEdit(product.product_code if product else "")
        self.code_edit.setPlaceholderText("Leave blank to generate automatically")
        self.code_edit.setReadOnly(bool(product))
        self.name_edit = QLineEdit(product.name if product else "")
        self.name_edit.setPlaceholderText("e.g. Coca-Cola 50cl")
        self.sku_edit = QLineEdit(product.sku or "" if product else "")
        self.sku_edit.setPlaceholderText("Optional barcode / SKU")

        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItem("")
        for name in categories:
            self.category_combo.addItem(name)
        if product and product.category_name:
            index = self.category_combo.findText(product.category_name)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
            else:
                self.category_combo.setEditText(product.category_name)

        self.unit_combo = QComboBox()
        self.unit_combo.setEditable(True)
        for unit in catalog.UNITS:
            self.unit_combo.addItem(unit)
        self.unit_combo.setCurrentText(product.unit if product else "pcs")

        self.cost_edit = QLineEdit(str(product.cost_price) if product else "0.00")
        self.price_edit = QLineEdit(str(product.selling_price) if product else "0.00")
        self.quantity_edit = QLineEdit("0")
        self.reorder_edit = QLineEdit(str(product.reorder_level) if product else "0")

        grid.addWidget(_label("Product ID"), 0, 0)
        grid.addWidget(self.code_edit, 0, 1)
        grid.addWidget(_label("Stock name *"), 0, 2)
        grid.addWidget(self.name_edit, 0, 3)
        grid.addWidget(_label("SKU / barcode"), 1, 0)
        grid.addWidget(self.sku_edit, 1, 1)
        grid.addWidget(_label("Category"), 1, 2)
        grid.addWidget(self.category_combo, 1, 3)
        grid.addWidget(_label("Unit"), 2, 0)
        grid.addWidget(self.unit_combo, 2, 1)
        grid.addWidget(_label("Cost price"), 2, 2)
        grid.addWidget(self.cost_edit, 2, 3)
        grid.addWidget(_label("Selling price *"), 3, 0)
        grid.addWidget(self.price_edit, 3, 1)
        grid.addWidget(_label("Reorder level"), 3, 2)
        grid.addWidget(self.reorder_edit, 3, 3)

        if product:
            current = QLineEdit(state.quantity(product.quantity_milli))
            current.setReadOnly(True)
            current.setToolTip("Use Stock Receiving or Stock Adjustments to change quantity.")
            grid.addWidget(_label("Quantity on hand"), 4, 0)
            grid.addWidget(current, 4, 1)
            self.is_active_check = QCheckBox("Active (available for sale)")
            self.is_active_check.setChecked(product.is_active)
            grid.addWidget(self.is_active_check, 4, 2, 1, 2)
        else:
            grid.addWidget(_label("Opening quantity"), 4, 0)
            grid.addWidget(self.quantity_edit, 4, 1)
            self.is_active_check = QCheckBox("Active (available for sale)")
            self.is_active_check.setChecked(True)
            grid.addWidget(self.is_active_check, 4, 2, 1, 2)

        self.description_edit = QPlainTextEdit(product.description or "" if product else "")
        self.description_edit.setFixedHeight(64)
        grid.addWidget(_label("Description"), 5, 0)
        grid.addWidget(self.description_edit, 5, 1, 1, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        hint = QLabel(
            "Prices use your configured currency. Quantities may be decimal (for example 1.5 kg)."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        _box, save_button = _dialog_buttons(self, "Save changes" if product else "Create product")
        layout.addWidget(_box)
        save_button.clicked.connect(self._save)
        self.name_edit.setFocus()

    def _save(self) -> None:
        try:
            with self.state.database.session() as session:
                if self.product_id is None:
                    product = catalog.create_product(
                        session,
                        name=self.name_edit.text(),
                        selling_price=self.price_edit.text(),
                        cost_price=self.cost_edit.text() or 0,
                        quantity=self.quantity_edit.text() or 0,
                        reorder_level=self.reorder_edit.text() or 0,
                        unit=self.unit_combo.currentText(),
                        sku=self.sku_edit.text(),
                        category=self.category_combo.currentText(),
                        description=self.description_edit.toPlainText(),
                        product_code=self.code_edit.text() or None,
                        is_active=self.is_active_check.isChecked(),
                        operator_id=self.state.operator_id,
                        business_date=self.state.business_date,
                    )
                    self.saved_id = product.id
                else:
                    catalog.update_product(
                        session,
                        self.product_id,
                        name=self.name_edit.text(),
                        selling_price=self.price_edit.text(),
                        cost_price=self.cost_edit.text() or 0,
                        reorder_level=self.reorder_edit.text() or 0,
                        unit=self.unit_combo.currentText(),
                        sku=self.sku_edit.text(),
                        category=self.category_combo.currentText(),
                        description=self.description_edit.toPlainText(),
                        is_active=self.is_active_check.isChecked(),
                        operator_id=self.state.operator_id,
                        business_date=self.state.business_date,
                    )
                    self.saved_id = self.product_id
        except Exception as exc:
            show_error(self, exc)
            return
        self.accept()


class ProductDetailDialog(QDialog):
    edit_requested = Signal(int)

    def __init__(self, state, product_id: int, parent=None):
        super().__init__(parent)
        self.state = state
        self.product_id = product_id
        self.setWindowTitle("Stock item")
        self.setModal(True)
        self.setMinimumSize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self.title = QLabel("")
        self.title.setObjectName("PageTitle")
        header.addWidget(self.title, 1)
        self.code_label = QLabel("")
        self.code_label.setObjectName("Muted")
        header.addWidget(self.code_label)
        layout.addLayout(header)

        self.info = QLabel("")
        self.info.setObjectName("Muted")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        layout.addWidget(Divider())

        subtitles = QHBoxLayout()
        movement_title = QLabel("Stock movement history")
        movement_title.setObjectName("SectionTitle")
        subtitles.addWidget(movement_title, 1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        subtitles.addWidget(self.count_label)
        layout.addLayout(subtitles)

        self.table = DataTable()
        self.table.setMinimumHeight(280)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        edit = make_button("Edit details", "secondary", "edit")
        edit.clicked.connect(lambda: self.edit_requested.emit(self.product_id))
        edit.setVisible(self.state.can(security.P_INVENTORY_EDIT))
        buttons.addWidget(edit)
        close = make_button("Close", "primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.load()

    def load(self) -> None:
        with self.state.database.session() as session:
            product = session.get(catalog.Product, self.product_id)
            if product is None:
                self.reject()
                return
            history = catalog.product_history(session, product.id, limit=200)
            rows = [
                {
                    "created_at": movement.created_at,
                    "type": movement.movement_type.title(),
                    "change": movement.quantity_change_milli,
                    "before": movement.quantity_before_milli,
                    "after": movement.quantity_after_milli,
                    "reason": movement.reason or "",
                    "operator": movement.operator.name if movement.operator else "",
                }
                for movement in history
            ]
            self.title.setText(product.name)
            self.code_label.setText(product.product_code)
            self.info.setText(
                f"SKU: {product.sku or '—'}    ·    Category: {product.category_name or '—'}    ·    "
                f"Unit: {product.unit}    ·    Cost: {self.state.money(product.cost_price_minor)}    ·    "
                f"Price: {self.state.money(product.selling_price_minor)}    ·    "
                f"Stock: {self.state.quantity(product.quantity_milli)}    ·    "
                f"Reorder: {self.state.quantity(product.reorder_level_milli)}    ·    "
                f"Status: {product.status() if product.is_active else 'Archived'}"
            )
            if product.description:
                self.info.setText(self.info.text() + f"\n{product.description}")
        self.count_label.setText(f"{len(rows)} movement(s)")
        self.table.set_data(
            rows,
            [
                TableColumn(
                    "created_at",
                    "Recorded",
                    150,
                    formatter=lambda row: self.state.datetime(row.get("created_at")),
                ),
                TableColumn("type", "Type", 110),
                TableColumn(
                    "change",
                    "Change",
                    90,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("change")),
                ),
                TableColumn(
                    "before",
                    "Before",
                    90,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("before")),
                ),
                TableColumn(
                    "after",
                    "After",
                    90,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("after")),
                ),
                TableColumn("reason", "Reason", 250),
                TableColumn("operator", "Operator", 130),
            ],
        )


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------
class SaleDetailDialog(QDialog):
    def __init__(self, state, sale_id: int, parent=None):
        super().__init__(parent)
        self.state = state
        self.sale_id = sale_id
        self.changed = False
        self.setWindowTitle("Transaction")
        self.setModal(True)
        self.setMinimumSize(800, 580)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.title = QLabel("")
        self.title.setObjectName("PageTitle")
        header.addWidget(self.title, 1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        header.addWidget(self.status)
        layout.addLayout(header)

        self.meta = QLabel("")
        self.meta.setObjectName("Muted")
        self.meta.setWordWrap(True)
        layout.addWidget(self.meta)
        layout.addWidget(Divider())

        items_title = QLabel("Items")
        items_title.setObjectName("SectionTitle")
        layout.addWidget(items_title)
        self.items_table = DataTable()
        self.items_table.setMinimumHeight(170)
        layout.addWidget(self.items_table)

        totals = QHBoxLayout()
        totals.addStretch(1)
        self.totals = QLabel("")
        self.totals.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        totals.addWidget(self.totals)
        layout.addLayout(totals)

        refund_title = QLabel("Refunds and reversals")
        refund_title.setObjectName("SectionTitle")
        layout.addWidget(refund_title)
        self.refunds_table = DataTable()
        self.refunds_table.setMinimumHeight(110)
        layout.addWidget(self.refunds_table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.refund_button = make_button("Refund / Reverse", "danger", "restore")
        self.refund_button.clicked.connect(self._refund)
        self.refund_button.setVisible(self.state.can(security.P_SALES_REFUND))
        buttons.addWidget(self.refund_button)
        close = make_button("Close", "primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.load()

    def load(self) -> None:
        with self.state.database.session() as session:
            sale = sales.get_sale(session, self.sale_id)
            summary = sales.sale_refund_summary(session, sale)
            items = [
                {
                    "name": item.product_name_snapshot,
                    "quantity": item.quantity_milli,
                    "unit_price": item.unit_price_minor,
                    "discount": item.discount_minor,
                    "line_total": item.line_total_minor,
                }
                for item in sale.items
            ]
            refunds = [
                {
                    "number": refund.refund_number,
                    "date": refund.business_date,
                    "kind": refund.kind.title(),
                    "amount": refund.amount_minor,
                    "restocked": "Yes" if refund.restocked else "No",
                    "reason": refund.reason,
                }
                for refund in sale.refunds
            ]
            active = sale.status in ("completed", "partially_refunded")
            self.title.setText(sale.transaction_number)
            self.status.setText(sale.status.replace("_", " ").title())
            self.meta.setText(
                f"Business date: {self.state.date(sale.business_date)}    ·    "
                f"Recorded: {self.state.datetime(sale.created_at)}    ·    "
                f"Payment: {sale.payment_method}    ·    "
                f"Operator: {sale.operator.name if sale.operator else '—'}    ·    "
                f"Refunded: {self.state.money(sale.refund_total_minor)}"
            )
            self.totals.setText(
                f"Subtotal {self.state.money(sale.subtotal_minor)}    ·    "
                f"Discounts {self.state.money(sale.discount_total_minor)}    ·    "
                f"<b>Net {self.state.money(sale.net_total_minor)}</b>"
            )
            self.refund_button.setEnabled(active and summary["refunded_qty_milli"] < summary["sold_qty_milli"])
            if sale.notes:
                self.meta.setText(self.meta.text() + f"    ·    Notes: {sale.notes}")
        self.items_table.set_data(
            items,
            [
                TableColumn("name", "Product", 280),
                TableColumn(
                    "quantity",
                    "Qty",
                    90,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("quantity")),
                ),
                money_column(self, "unit_price", "Unit price", 120),
                money_column(self, "discount", "Discount", 100),
                money_column(self, "line_total", "Line total", 130, bold=True),
            ],
        )
        self.refunds_table.set_data(
            refunds,
            [
                TableColumn("number", "Refund / reversal", 170),
                TableColumn("date", "Date", 120, formatter=lambda row: self.state.date(row.get("date"))),
                TableColumn("kind", "Kind", 90),
                money_column(self, "amount", "Amount", 110),
                TableColumn("restocked", "Restocked", 90),
                TableColumn("reason", "Reason", 240),
            ],
        )

    def _refund(self) -> None:
        dialog = RefundDialog(self.state, self.sale_id, self)
        if dialog.exec() == QDialog.Accepted:
            self.changed = True
            self.load()


class RefundDialog(QDialog):
    def __init__(self, state, sale_id: int, parent=None):
        super().__init__(parent)
        self.state = state
        self.sale_id = sale_id
        self.setWindowTitle("Refund or reverse a sale")
        self.setModal(True)
        self.setMinimumWidth(700)

        with state.database.session() as session:
            sale = sales.get_sale(session, sale_id)
            remaining = sales.refundable_quantities(session, sale)
            self.items = [
                {
                    "sale_item_id": item.id,
                    "name": item.product_name_snapshot,
                    "quantity_milli": item.quantity_milli,
                    "remaining_milli": remaining.get(item.id, 0),
                }
                for item in sale.items
            ]
            self.transaction_number = sale.transaction_number

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel(f"Refund {self.transaction_number}")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        hint = QLabel(
            "Sales history is permanent. A refund returns money and, by default, stock; "
            "a reversal nullifies the whole transaction."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(len(self.items), 4)
        self.table.setHorizontalHeaderLabels(["Product", "Sold", "Refundable", "Refund now"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(170)
        self.spins: list[QDoubleSpinBox] = []
        for row, item in enumerate(self.items):
            name = QTableWidgetItem(item["name"])
            name.setData(Qt.UserRole, item["sale_item_id"])
            sold = QTableWidgetItem(self.state.quantity(item["quantity_milli"]))
            sold.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            remaining = QTableWidgetItem(self.state.quantity(item["remaining_milli"]))
            remaining.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setMinimum(0)
            spin.setMaximum(float(from_milli(item["remaining_milli"])))
            spin.setSingleStep(1)
            spin.setValue(float(from_milli(item["remaining_milli"])))
            spin.setEnabled(item["remaining_milli"] > 0)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, sold)
            self.table.setItem(row, 2, remaining)
            self.table.setCellWidget(row, 3, spin)
            self.spins.append(spin)
        layout.addWidget(self.table)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Refund (partial or full)", "refund")
        self.kind_combo.addItem("Reverse transaction (full)", "reversal")
        form.addRow(_label("Action"), self.kind_combo)
        self.restock_check = QCheckBox("Return the refunded quantity to stock")
        self.restock_check.setChecked(True)
        form.addRow(_label("Restock"), self.restock_check)
        self.reason_edit = QPlainTextEdit()
        self.reason_edit.setFixedHeight(64)
        self.reason_edit.setPlaceholderText("Reason (required)")
        form.addRow(_label("Reason *"), self.reason_edit)
        layout.addLayout(form)

        self.kind_combo.currentIndexChanged.connect(self._kind_changed)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = make_button("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        submit = make_button("Process refund", "danger", "restore")
        submit.clicked.connect(self._submit)
        buttons.addWidget(submit)
        layout.addLayout(buttons)

    def _kind_changed(self, _index: int) -> None:
        reversal = self.kind_combo.currentData() == "reversal"
        for item, spin in zip(self.items, self.spins):
            if reversal:
                spin.setValue(float(from_milli(item["remaining_milli"])))
            spin.setEnabled(not reversal and item["remaining_milli"] > 0)
        self.restock_check.setEnabled(True)

    def _submit(self) -> None:
        reason = self.reason_edit.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Reason required", "Enter a reason for the refund or reversal.")
            return
        items = []
        for item, spin in zip(self.items, self.spins):
            quantity = from_milli(int(round(spin.value() * 1000)))
            if quantity > 0:
                items.append({"sale_item_id": item["sale_item_id"], "quantity": quantity})
        if not items:
            QMessageBox.warning(self, "Nothing selected", "Enter at least one quantity to refund.")
            return
        kind = self.kind_combo.currentData()
        if kind == "reversal":
            if not confirm(
                self,
                "Reverse transaction",
                "This will reverse the entire transaction and mark it as reversed. "
                "The original record is kept for audit. Continue?",
                confirm_text="Reverse",
                danger=True,
            ):
                return
        try:
            with self.state.database.session() as session:
                sales.refund_sale(
                    session,
                    sale_id=self.sale_id,
                    reason=reason,
                    items=items,
                    kind=kind,
                    restock=self.restock_check.isChecked(),
                    operator_id=self.state.operator_id,
                    business_date=self.state.business_date,
                )
        except Exception as exc:
            show_error(self, exc)
            return
        self.accept()


class ReceiptDialog(QDialog):
    def __init__(self, receipt: dict, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Sale completed")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)

        icon_row = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap("check", "#16803C", 28))
        icon_row.addWidget(icon_label)
        title = QLabel("Sale completed")
        title.setObjectName("PageTitle")
        icon_row.addWidget(title, 1)
        layout.addLayout(icon_row)

        meta = QLabel(
            f"{receipt['transaction_number']}    ·    {state.money(receipt['net_total_minor'])}    ·    "
            f"{receipt['payment_method']}"
        )
        meta.setObjectName("Muted")
        layout.addWidget(meta)
        layout.addWidget(Divider())

        table = DataTable()
        table.set_data(
            receipt["items"],
            [
                TableColumn("name", "Product", 240),
                TableColumn(
                    "quantity_milli",
                    "Qty",
                    80,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: state.quantity(row.get("quantity_milli")),
                ),
                money_column(self, "unit_price_minor", "Price", 100),
                money_column(self, "line_total_minor", "Line total", 110),
            ],
        )
        table.setMinimumHeight(180)
        layout.addWidget(table, 1)

        totals = QLabel(
            f"Subtotal {state.money(receipt['subtotal_minor'])}    ·    "
            f"Discount {state.money(receipt['discount_total_minor'])}    ·    "
            f"<b>Total {state.money(receipt['net_total_minor'])}</b>"
        )
        totals.setAlignment(Qt.AlignRight)
        layout.addWidget(totals)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = make_button("Done", "primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
class AuditDetailDialog(QDialog):
    def __init__(self, state, event: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Audit event")
        self.setModal(True)
        self.setMinimumSize(620, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)

        title = QLabel(event.get("action", ""))
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        meta = QLabel(
            f"{state.datetime(event.get('created_at'))}    ·    "
            f"{event.get('operator') or 'System'}    ·    "
            f"{event.get('entity_type')} #{event.get('entity_id') or '—'}"
        )
        meta.setObjectName("Muted")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        if event.get("reason"):
            reason = QLabel(f"Reason: {event['reason']}")
            reason.setWordWrap(True)
            layout.addWidget(reason)

        details = QPlainTextEdit()
        details.setReadOnly(True)
        try:
            payload = json.loads(event.get("details_json") or "{}")
            details.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))
        except (TypeError, ValueError):
            details.setPlainText(event.get("details_json") or "")
        details.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(details, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = make_button("Close", "primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
