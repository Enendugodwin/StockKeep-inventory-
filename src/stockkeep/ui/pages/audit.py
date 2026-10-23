"""Append-only audit log."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QWidget

from ...exporting import write_csv
from ...services import audit
from ..common import DateRangeBar, export_path, show_error
from ..dialogs import AuditDetailDialog
from ..models import TableColumn
from ..widgets import DataTable, PageHeader, PaginationBar, SearchBox, SectionCard, open_path
from ..workers import run_task
from .base import BasePage


class AuditPage(BasePage):
    def build(self) -> None:
        self.page = 1
        self.page_size = 200
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._reload)

        self.header = PageHeader(
            "Audit Log", "Every sale, receipt, adjustment, import, report and backup is recorded."
        )
        self.detail_button = self.header.add_action("View details", "secondary", "receipt", self._view)
        self.header.add_action("Export", "secondary", "download", self.export_action)
        self.layout.addWidget(self.header)

        filters = QWidget()
        row = QHBoxLayout(filters)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.range = DateRangeBar("30")
        self.range.changed.connect(self._filters_changed)
        row.addWidget(self.range)
        self.search = SearchBox("Search action, entity, reason or details…")
        self.search.textChanged.connect(self._search_changed)
        row.addWidget(self.search, 1)
        self.layout.addWidget(filters)

        card = SectionCard("Events", "Newest first")
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
                events, total = audit.list_events(
                    session,
                    start=start,
                    end=end,
                    search=self.search.text(),
                    limit=self.page_size,
                    offset=(self.page - 1) * self.page_size,
                )
                rows = [
                    {
                        "id": event.id,
                        "created_at": event.created_at,
                        "operator": event.operator.name if event.operator else "System",
                        "action": event.action,
                        "entity_type": event.entity_type,
                        "entity_id": event.entity_id or "",
                        "reason": event.reason or "",
                        "details_json": event.details_json or "",
                    }
                    for event in events
                ]
        except Exception as exc:
            show_error(self, exc, "Could not load the audit log")
            return

        self.table.set_data(
            rows,
            [
                TableColumn(
                    "created_at",
                    "Recorded",
                    150,
                    formatter=lambda row: self.state.datetime(row.get("created_at")),
                ),
                TableColumn("operator", "Operator", 140),
                TableColumn("action", "Action", 170, bold=True),
                TableColumn("entity_type", "Entity", 130),
                TableColumn("entity_id", "Entity ID", 100),
                TableColumn("reason", "Reason", 300),
            ],
        )
        self.table.connect_selection(self._selection_changed)
        self.pager.set_state(self.page, total, self.page_size)
        self.header.subtitle_label.setText(
            f"{total:,} event(s)  ·  {self.state.date(start)} to {self.state.date(end)}"
        )
        self._selection_changed()

    def _selection_changed(self, *_args) -> None:
        self.detail_button.setEnabled(self.table.selected_record() is not None)

    def _view(self, *_args) -> None:
        record = self.table.selected_record()
        if record is not None:
            AuditDetailDialog(self.state, record, self).exec()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def export_action(self) -> None:
        target = export_path(self, self.state, "audit_log", formats="CSV file (*.csv)")
        if target is None:
            return
        if target.suffix.lower() != ".csv":
            target = target.with_suffix(".csv")
        start, end = self.range.range()
        search = self.search.text()

        def job():
            with self.state.database.session() as session:
                events, _total = audit.list_events(
                    session, start=start, end=end, search=search, limit=10000, offset=0
                )
                rows = [
                    [
                        self.state.datetime(event.created_at),
                        event.operator.name if event.operator else "System",
                        event.action,
                        event.entity_type,
                        event.entity_id or "",
                        event.reason or "",
                        event.details_json or "",
                    ]
                    for event in events
                ]
            return write_csv(
                target,
                ["Recorded", "Operator", "Action", "Entity", "Entity ID", "Reason", "Details"],
                rows,
            )

        run_task(
            self,
            job,
            on_success=lambda path: (
                self.main.show_status(f"Audit log exported to {path}."),
                open_path(path),
            ),
            message="Exporting the audit log…",
            title="Export",
        )

    def export_action_shortcut(self) -> None:
        self.export_action()
