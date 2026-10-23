"""Inventory catalogue page."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from ... import security
from ...services import catalog, reports
from ..common import confirm, export_path, show_error
from ..dialogs import ProductDetailDialog, ProductEditorDialog
from ..models import TableColumn
from ..theme import status_color
from ..widgets import (
    DataTable,
    PageHeader,
    PaginationBar,
    SearchBox,
    SectionCard,
    open_path,
)
from ..workers import run_task
from .base import BasePage


STATUS_OPTIONS = [
    ("All stock", "all"),
    ("In stock", "in"),
    ("Low stock", "low"),
    ("Out of stock", "out"),
    ("Archived", "archived"),
]


class InventoryPage(BasePage):
    def build(self) -> None:
        self.page = 1
        self.page_size = self.state.settings.page_size
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._reload)

        self.header = PageHeader("Inventory", "Your stock catalogue and current quantities.")
        self.add_button = self.header.add_action("Add item", "primary", "plus", self.new_action)
        self.edit_button = self.header.add_action("Edit", "secondary", "edit", self._edit)
        self.archive_button = self.header.add_action(
            "Archive", "secondary", "trash", self._archive_toggle
        )
        self.header.add_action("Export", "secondary", "download", self.export_action)
        for button in (self.add_button, self.edit_button, self.archive_button):
            button.setVisible(self.state.can(security.P_INVENTORY_EDIT))
        self.layout.addWidget(self.header)

        filters = QWidget()
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)
        self.search = SearchBox("Search name, product ID or SKU…")
        self.search.textChanged.connect(self._search_changed)
        filter_layout.addWidget(self.search, 1)

        self.category = QComboBox()
        self.category.setMinimumWidth(170)
        self.category.currentIndexChanged.connect(self._filters_changed)
        filter_layout.addWidget(self.category)

        self.status = QComboBox()
        for label, value in STATUS_OPTIONS:
            self.status.addItem(label, value)
        self.status.currentIndexChanged.connect(self._filters_changed)
        filter_layout.addWidget(self.status)
        self.layout.addWidget(filters)

        card = SectionCard("Stock items", "Quantities change only through receiving, sales and adjustments.")
        self.table = DataTable()
        self.table.doubleClicked.connect(self._open_details)
        card.content.addWidget(self.table, 1)
        self.pager = PaginationBar()
        self.pager.page_changed.connect(self._page_changed)
        card.content.addWidget(self.pager)
        self.layout.addWidget(card, 1)
        self.empty_hint = QLabel("")
        self.empty_hint.setObjectName("Muted")
        self.layout.addWidget(self.empty_hint)

        self._load_categories()

    # ------------------------------------------------------------------
    def _load_categories(self) -> None:
        current = self.category.currentData()
        with self.state.database.session() as session:
            categories = catalog.list_categories(session)
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("All categories", None)
        for item in categories:
            self.category.addItem(item.name, item.id)
        index = self.category.findData(current)
        self.category.setCurrentIndex(index if index >= 0 else 0)
        self.category.blockSignals(False)

    def refresh(self) -> None:
        self._load_categories()
        self._reload()

    def _reload(self) -> None:
        try:
            with self.state.database.session() as session:
                products, total = catalog.inventory_page(
                    session,
                    search=self.search.text(),
                    category_id=self.category.currentData(),
                    status=self.status.currentData() or "all",
                    page=self.page,
                    page_size=self.page_size,
                )
                rows = [
                    {
                        "id": product.id,
                        "product_code": product.product_code,
                        "name": product.name,
                        "sku": product.sku or "",
                        "category": product.category_name,
                        "unit": product.unit,
                        "cost_price_minor": product.cost_price_minor,
                        "selling_price_minor": product.selling_price_minor,
                        "quantity_milli": product.quantity_milli,
                        "reorder_level_milli": product.reorder_level_milli,
                        "status": product.status() if product.is_active else "Archived",
                        "is_active": product.is_active,
                        "updated_at": product.updated_at,
                    }
                    for product in products
                ]
        except Exception as exc:
            show_error(self, exc, "Could not load inventory")
            return

        self.table.set_data(
            rows,
            [
                TableColumn("product_code", "Product ID", 105),
                TableColumn("name", "Stock item", 230, bold=True),
                TableColumn("sku", "SKU / barcode", 120),
                TableColumn("category", "Category", 120),
                TableColumn("unit", "Unit", 62),
                TableColumn(
                    "cost_price_minor",
                    "Cost",
                    100,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("cost_price_minor")),
                ),
                TableColumn(
                    "selling_price_minor",
                    "Price",
                    100,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("selling_price_minor")),
                ),
                TableColumn(
                    "quantity_milli",
                    "Quantity",
                    90,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("quantity_milli")),
                    bold=True,
                ),
                TableColumn(
                    "reorder_level_milli",
                    "Reorder",
                    80,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("reorder_level_milli")),
                ),
                TableColumn(
                    "status",
                    "Status",
                    100,
                    formatter=lambda row: row.get("status", ""),
                    color=lambda row: status_color(row.get("status"), self.state.theme),
                ),
                TableColumn(
                    "updated_at",
                    "Updated",
                    140,
                    formatter=lambda row: self.state.datetime(row.get("updated_at")),
                ),
            ],
        )
        self.table.connect_selection(self._selection_changed)
        self.pager.set_state(self.page, total, self.page_size)
        shown = len(rows)
        self.empty_hint.setText(
            "" if total else "No stock items match the current filters. Add an item or clear the search."
        )
        self.header.subtitle_label.setText(
            f"{total:,} matching item(s)  ·  showing {shown:,}  ·  page {self.pager.page} of {self.pager.pages}"
        )
        self._selection_changed()

    # ------------------------------------------------------------------
    def _search_changed(self) -> None:
        self.page = 1
        self._timer.start(260)

    def _filters_changed(self) -> None:
        self.page = 1
        self._reload()

    def _page_changed(self, page: int) -> None:
        self.page = page
        self._reload()

    def _selected(self) -> dict | None:
        return self.table.selected_record()

    def _selection_changed(self, *_args) -> None:
        record = self._selected()
        self.edit_button.setEnabled(record is not None)
        self.archive_button.setEnabled(record is not None)
        if record is not None:
            self.archive_button.setText("Restore" if not record.get("is_active") else "Archive")

    def _open_details(self, *_args) -> None:
        record = self._selected()
        if record is None:
            return
        dialog = ProductDetailDialog(self.state, int(record["id"]), self)
        dialog.edit_requested.connect(self._edit_product)
        dialog.exec()
        self._reload()

    def _edit_product(self, product_id: int) -> None:
        if not self.state.can(security.P_INVENTORY_EDIT):
            return
        dialog = ProductEditorDialog(self.state, product_id=product_id, parent=self)
        if dialog.exec() and dialog.saved_id:
            self.state.notify_data_changed()
            self.main.request_report_refresh()
            self.main.show_status("Stock item updated.")
            self._reload()

    def new_action(self) -> None:
        if not self.state.can(security.P_INVENTORY_EDIT):
            return
        dialog = ProductEditorDialog(self.state, parent=self)
        if dialog.exec() and dialog.saved_id:
            self.state.notify_data_changed()
            self.main.request_report_refresh()
            self.main.show_status("Stock item created.")
            self._reload()

    def _edit(self) -> None:
        record = self._selected()
        if record is not None:
            self._edit_product(int(record["id"]))

    def _archive_toggle(self) -> None:
        if not self.state.can(security.P_INVENTORY_EDIT):
            return
        record = self._selected()
        if record is None:
            return
        active = bool(record.get("is_active"))
        if active:
            if not confirm(
                self,
                "Archive stock item",
                f"Archive {record['name']}? It will no longer be available for sale, "
                "but its history is preserved.",
                confirm_text="Archive",
                danger=True,
            ):
                return
        try:
            with self.state.database.session() as session:
                if active:
                    catalog.archive_product(
                        session,
                        int(record["id"]),
                        operator_id=self.state.operator_id,
                        reason="Archived from inventory",
                    )
                else:
                    catalog.restore_product(
                        session, int(record["id"]), operator_id=self.state.operator_id
                    )
        except Exception as exc:
            show_error(self, exc)
            return
        self.state.notify_data_changed()
        self.main.show_status("Stock item archived." if active else "Stock item restored.")
        self._reload()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def export_action(self) -> None:
        target = export_path(self, self.state, "inventory_snapshot")
        if target is None:
            return
        fmt = "xlsx" if target.suffix.lower() == ".xlsx" else "csv"
        today = date.today()

        def job():
            with self.state.database.session() as session:
                return reports.export_report(
                    session,
                    "inventory",
                    today,
                    today,
                    target,
                    fmt=fmt,
                    tz=self.state.settings.timezone,
                    currency_symbol=self.state.settings.currency_symbol,
                    business_name=self.state.settings.business_name,
                )

        def done(path):
            self.main.show_status(f"Inventory exported to {path}.")
            open_path(path)

        run_task(self, job, on_success=done, message="Exporting inventory…", title="Export")
