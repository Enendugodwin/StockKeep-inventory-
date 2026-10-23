"""Transaction history with refunds and reversals."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QWidget

from ... import security
from ...models import PAYMENT_METHODS
from ...services import reports, sales
from ..common import DateRangeBar, export_path, show_error
from ..dialogs import RefundDialog, SaleDetailDialog
from ..models import TableColumn
from ..theme import status_color
from ..widgets import DataTable, PageHeader, PaginationBar, SearchBox, SectionCard, open_path
from ..workers import run_task
from .base import BasePage


STATUSES = [
    ("All statuses", "all"),
    ("Completed", "completed"),
    ("Partially refunded", "partially_refunded"),
    ("Refunded", "refunded"),
    ("Reversed", "reversed"),
]


class TransactionsPage(BasePage):
    def build(self) -> None:
        self.page = 1
        self.page_size = 100
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._reload)

        self.header = PageHeader(
            "Transactions", "Permanent sales history. Refunds and reversals append records."
        )
        self.view_button = self.header.add_action("View", "secondary", "receipt", self._view)
        self.refund_button = self.header.add_action(
            "Refund / Reverse", "secondary", "restore", self._refund
        )
        self.refund_button.setVisible(self.state.can(security.P_SALES_REFUND))
        self.header.add_action("Export", "secondary", "download", self.export_action)
        self.layout.addWidget(self.header)

        filters = QWidget()
        row = QHBoxLayout(filters)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.range = DateRangeBar("30")
        self.range.changed.connect(self._filters_changed)
        row.addWidget(self.range)
        self.status = QComboBox()
        for label, value in STATUSES:
            self.status.addItem(label, value)
        self.status.currentIndexChanged.connect(self._filters_changed)
        row.addWidget(self.status)
        self.payment = QComboBox()
        self.payment.addItem("All payments", None)
        for method in PAYMENT_METHODS:
            self.payment.addItem(method, method)
        self.payment.currentIndexChanged.connect(self._filters_changed)
        row.addWidget(self.payment)
        self.search = SearchBox("Search transaction or product…")
        self.search.textChanged.connect(self._search_changed)
        row.addWidget(self.search, 1)
        self.layout.addWidget(filters)

        card = SectionCard("Sales", "Completed, refunded and reversed transactions")
        self.table = DataTable()
        self.table.doubleClicked.connect(self._view)
        card.content.addWidget(self.table, 1)
        self.pager = PaginationBar()
        self.pager.page_size = self.page_size
        self.pager.page_changed.connect(self._page_changed)
        card.content.addWidget(self.pager)
        self.layout.addWidget(card, 1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self._reload()

    def _filters_changed(self) -> None:
        self.page = 1
        self._reload()

    def _search_changed(self) -> None:
        self.page = 1
        self._timer.start(260)

    def _page_changed(self, page: int) -> None:
        self.page = page
        self._reload()

    def _reload(self) -> None:
        start, end = self.range.range()
        try:
            with self.state.database.session() as session:
                rows, total = sales.list_sales(
                    session,
                    start=start,
                    end=end,
                    status=self.status.currentData(),
                    payment_method=self.payment.currentData(),
                    search=self.search.text(),
                    page=self.page,
                    page_size=self.page_size,
                )
                records = [
                    {
                        "id": sale.id,
                        "number": sale.transaction_number,
                        "business_date": sale.business_date,
                        "created_at": sale.created_at,
                        "items": len(sale.items),
                        "quantity_milli": sum(item.quantity_milli for item in sale.items),
                        "subtotal_minor": sale.subtotal_minor,
                        "discount_minor": sale.discount_total_minor,
                        "refund_minor": sale.refund_total_minor,
                        "net_minor": sale.net_total_minor,
                        "payment": sale.payment_method,
                        "status": sale.status,
                        "operator": sale.operator.name if sale.operator else "",
                    }
                    for sale in rows
                ]
        except Exception as exc:
            show_error(self, exc, "Could not load transactions")
            return

        self.table.set_data(
            records,
            [
                TableColumn("number", "Transaction", 160, bold=True),
                TableColumn(
                    "created_at",
                    "Recorded",
                    140,
                    formatter=lambda row: self.state.datetime(row.get("created_at")),
                ),
                TableColumn(
                    "items",
                    "Items",
                    58,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                ),
                TableColumn(
                    "quantity_milli",
                    "Qty",
                    74,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("quantity_milli")),
                ),
                TableColumn(
                    "subtotal_minor",
                    "Subtotal",
                    100,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("subtotal_minor")),
                ),
                TableColumn(
                    "discount_minor",
                    "Discount",
                    94,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("discount_minor")),
                ),
                TableColumn(
                    "refund_minor",
                    "Refunded",
                    94,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("refund_minor")),
                ),
                TableColumn(
                    "net_minor",
                    "Net",
                    108,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("net_minor")),
                    bold=True,
                ),
                TableColumn("payment", "Payment", 104),
                TableColumn(
                    "status",
                    "Status",
                    122,
                    formatter=lambda row: str(row.get("status", "")).replace("_", " ").title(),
                    color=lambda row: status_color(row.get("status"), self.state.theme),
                ),
                TableColumn("operator", "Operator", 120),
            ],
        )
        self.table.connect_selection(self._selection_changed)
        self.pager.set_state(self.page, total, self.page_size)
        self.header.subtitle_label.setText(
            f"{total:,} transaction(s)  ·  {self.state.date(start)} to {self.state.date(end)}"
        )
        self._selection_changed()

    # ------------------------------------------------------------------
    def _selected(self) -> dict | None:
        return self.table.selected_record()

    def _selection_changed(self, *_args) -> None:
        record = self._selected()
        self.view_button.setEnabled(record is not None)
        active = bool(record) and record.get("status") in {"completed", "partially_refunded"}
        self.refund_button.setEnabled(
            active and self.state.can(security.P_SALES_REFUND)
        )

    def _view(self, *_args) -> None:
        record = self._selected()
        if record is None:
            return
        dialog = SaleDetailDialog(self.state, int(record["id"]), self)
        dialog.exec()
        if dialog.changed:
            self.state.notify_data_changed()
            self.main.request_report_refresh()
            self._reload()

    def _refund(self) -> None:
        record = self._selected()
        if record is None:
            return
        dialog = RefundDialog(self.state, int(record["id"]), self)
        if dialog.exec():
            self.state.notify_data_changed()
            self.main.request_report_refresh()
            self.main.show_status("Refund recorded.")
            self._reload()

    def export_action(self) -> None:
        start, end = self.range.range()
        target = export_path(self, self.state, f"sales_{start}_{end}")
        if target is None:
            return
        fmt = "xlsx" if target.suffix.lower() == ".xlsx" else "csv"
        payment = self.payment.currentData()

        def job():
            with self.state.database.session() as session:
                return reports.export_report(
                    session,
                    "sales",
                    start,
                    end,
                    target,
                    fmt=fmt,
                    payment_method=payment,
                    tz=self.state.settings.timezone,
                    currency_symbol=self.state.settings.currency_symbol,
                    business_name=self.state.settings.business_name,
                )

        run_task(
            self,
            job,
            on_success=lambda path: (self.main.show_status(f"Export saved to {path}."), open_path(path)),
            message="Exporting transactions…",
            title="Export",
        )

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()
