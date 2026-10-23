"""Daily report generation, date-range exports and monthly workbooks."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from ..errors import StockKeepError, ValidationError
from ..exporting import atomic_path, replace_atomically, safe_text, write_csv
from ..models import (
    REPORT_COMPLETED,
    REPORT_FAILED,
    REPORT_RUNNING,
    REPORT_STALE,
    ReportJob,
    Setting,
)
from ..money import as_decimal_str, format_qty, from_milli, from_minor
from ..timeutil import as_local, month_bounds, utc_now
from . import analytics, audit
from .report_state import ensure_daily_job

log = logging.getLogger(__name__)

DAILY_FILENAMES = {
    "transactions_csv": "transactions_{day}.csv",
    "transactions_xlsx": "transactions_{day}.xlsx",
    "movements_csv": "stock_movements_{day}.csv",
    "summary_xlsx": "daily_summary_{day}.xlsx",
}

HEADER_FILL = PatternFill("solid", fgColor="0E7C86")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color="0B2B33")
MUTED_FONT = Font(color="5B6B77")
TOTAL_FILL = PatternFill("solid", fgColor="E6F2F3")
THIN = Side(style="thin", color="D5DEE5")
BOTTOM_BORDER = Border(top=THIN)


@dataclass
class Column:
    header: str
    key: str
    kind: str = "text"  # text | date | datetime | money | qty | int
    width: float = 16


@dataclass
class SheetSpec:
    title: str
    columns: list[Column]
    rows: list[dict]
    totals: dict[str, object] | None = None
    total_label: str = "TOTAL"
    note: str | None = None


@dataclass
class ReportOutcome:
    day: date
    status: str  # generated | skipped | failed
    files: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"generated", "skipped"}


TRANSACTION_COLUMNS = [
    Column("Transaction ID", "transaction_number", "text", 24),
    Column("Business Date", "business_date", "date", 13),
    Column("Transaction Timestamp", "created_at", "datetime", 20),
    Column("Product ID", "product_id", "int", 10),
    Column("Product Name", "product_name", "text", 30),
    Column("Quantity Sold", "quantity_milli", "qty", 13),
    Column("Unit Selling Price", "unit_price_minor", "money", 16),
    Column("Discount", "discount_minor", "money", 12),
    Column("Line Total", "line_total_minor", "money", 14),
    Column("Payment Method", "payment_method", "text", 16),
    Column("Operator", "operator", "text", 16),
    Column("Transaction Status", "status", "text", 18),
]

MOVEMENT_COLUMNS = [
    Column("Business Date", "business_date", "date", 13),
    Column("Recorded At", "created_at", "datetime", 20),
    Column("Product ID", "product_id", "int", 10),
    Column("Product", "product_name", "text", 30),
    Column("Movement Type", "movement_type", "text", 16),
    Column("Change", "quantity_change_milli", "qty", 12),
    Column("Before", "quantity_before_milli", "qty", 12),
    Column("After", "quantity_after_milli", "qty", 12),
    Column("Unit Cost", "unit_cost_minor", "money", 14),
    Column("Reference", "reference", "text", 18),
    Column("Reason", "reason", "text", 34),
    Column("Operator", "operator", "text", 16),
]

DAILY_SUMMARY_COLUMNS = [
    Column("Metric", "metric", "text", 32),
    Column("Value", "value", "text", 28),
]

STOCK_SUMMARY_COLUMNS = [
    Column("Movement", "label", "text", 26),
    Column("Quantity", "quantity_milli", "qty", 16),
]

DAILY_SALES_COLUMNS = [
    Column("Business Date", "business_date", "date", 14),
    Column("Sales", "sales_count", "int", 10),
    Column("Units Sold", "units_milli", "qty", 12),
    Column("Gross Sales", "gross_minor", "money", 10),
    Column("Discounts", "discount_minor", "money", 8),
    Column("Refunds", "refund_minor", "money", 8),
    Column("Net Sales", "net_minor", "money", 8),
    Column("Est. COGS", "cogs_minor", "money", 8),
]

PRODUCT_PERFORMANCE_COLUMNS = [
    Column("Product ID", "product_code", "text", 13),
    Column("Product", "name", "text", 30),
    Column("Unit", "unit", "text", 8),
    Column("Opening Qty", "opening_milli", "qty", 12),
    Column("Received", "received_milli", "qty", 10),
    Column("Sold", "sold_milli", "qty", 10),
    Column("Returns", "returned_milli", "qty", 10),
    Column("Damaged", "damaged_milli", "qty", 10),
    Column("Lost", "lost_milli", "qty", 8),
    Column("Expired", "expired_milli", "qty", 8),
    Column("Adjustments", "adjusted_milli", "qty", 12),
    Column("Closing Qty", "closing_milli", "qty", 12),
    Column("Revenue", "revenue_minor", "money", 10),
    Column("Est. COGS", "cogs_minor", "money", 10),
    Column("Est. Gross Profit", "gross_profit_minor", "money", 10),
]

PAYMENT_COLUMNS = [
    Column("Payment Method", "payment_method", "text", 20),
    Column("Gross Sales", "gross_minor", "money", 10),
    Column("Discounts", "discount_minor", "money", 10),
    Column("Refunds", "refund_minor", "money", 10),
    Column("Net", "net_minor", "money", 10),
]

INVENTORY_COLUMNS = [
    Column("Product ID", "product_code", "text", 13),
    Column("Product", "name", "text", 30),
    Column("SKU / Barcode", "sku", "text", 16),
    Column("Category", "category", "text", 14),
    Column("Unit", "unit", "text", 8),
    Column("Cost Price", "cost_price_minor", "money", 12),
    Column("Selling Price", "selling_price_minor", "money", 12),
    Column("Quantity", "quantity_milli", "qty", 12),
    Column("Reorder Level", "reorder_level_milli", "qty", 12),
    Column("Status", "status", "text", 14),
    Column("Cost Value", "cost_value_minor", "money", 14),
    Column("Selling Value", "selling_value_minor", "money", 14),
    Column("Last Updated", "updated_at", "datetime", 20),
]

REFUND_COLUMNS = [
    Column("Refund / Reversal No.", "refund_number", "text", 22),
    Column("Business Date", "business_date", "date", 13),
    Column("Recorded At", "created_at", "datetime", 20),
    Column("Original Sale", "transaction_number", "text", 22),
    Column("Kind", "kind", "text", 10),
    Column("Amount", "amount_minor", "money", 12),
    Column("Payment Method", "payment_method", "text", 16),
    Column("Restocked", "restocked", "text", 10),
    Column("Reason", "reason", "text", 34),
]

SUMMARY_ITEMS = [
    ("Completed sales count", "sales_count"),
    ("Units sold", "units_milli"),
    ("Gross sales", "gross_minor"),
    ("Discounts", "discount_minor"),
    ("Refunds", "refund_minor"),
    ("Net sales", "net_minor"),
    ("Estimated COGS", "cogs_minor"),
    ("Estimated gross profit", "gross_profit_minor"),
]


# ---------------------------------------------------------------------------
# Cell conversion / workbook writing
# ---------------------------------------------------------------------------
def _escape_excel(value):
    if isinstance(value, str):
        return safe_text(value)
    return value


def _convert_cell(column: Column, value, *, tz: str, for_csv: bool):
    if value is None:
        return "" if for_csv else None
    if column.kind == "money":
        return as_decimal_str(int(value)) if for_csv else float(from_minor(value))
    if column.kind == "qty":
        if for_csv:
            text = f"{from_milli(value):.3f}".rstrip("0").rstrip(".")
            return text or "0"
        return float(from_milli(value))
    if column.kind == "int":
        return int(value or 0)
    if column.kind == "date":
        return value.isoformat() if for_csv else value
    if column.kind == "datetime":
        local = as_local(value, tz) if isinstance(value, datetime) else value
        if isinstance(local, datetime):
            if for_csv:
                return local.strftime("%Y-%m-%d %H:%M:%S")
            return local.replace(tzinfo=None)
        return "" if for_csv else None
    text = "" if value is None else str(value)
    if text.startswith("="):
        text = "'" + text
    return text


def _currency_format(symbol: str) -> str:
    clean = (symbol or "").replace('"', "")
    return f'"{clean}"#,##0.00'


def write_workbook(
    path: Path | str,
    sheets: list[SheetSpec],
    *,
    title: str | None = None,
    tz: str = "Africa/Lagos",
    currency_symbol: str = "\u20a6",
    metadata: dict[str, str] | None = None,
) -> Path:
    target = Path(path)
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    workbook = Workbook()
    workbook.remove(workbook.active)
    title_fill = PatternFill("solid", fgColor="F3F8F9")
    # Keep the machine-readable header row at row 1: branding goes into the
    # workbook properties and the print header instead of title rows.
    if title:
        workbook.properties.title = title
    if metadata:
        workbook.properties.subject = " | ".join(f"{k}: {v}" for k, v in metadata.items())

    for spec in sheets:
        worksheet = workbook.create_sheet(spec.title[:31])
        if title:
            worksheet.oddHeader.center.text = title
        row_index = 1
        if spec.note:
            worksheet.cell(row=row_index, column=1, value=spec.note).font = MUTED_FONT
            row_index += 1

        header_row = row_index
        for col_index, column in enumerate(spec.columns, start=1):
            cell = worksheet.cell(row=header_row, column=col_index, value=column.header)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            worksheet.column_dimensions[get_column_letter(col_index)].width = column.width
        worksheet.row_dimensions[header_row].height = 22

        data_start = header_row + 1
        for offset, row in enumerate(spec.rows):
            excel_row = data_start + offset
            for col_index, column in enumerate(spec.columns, start=1):
                value = _convert_cell(column, row.get(column.key), tz=tz, for_csv=False)
                cell = worksheet.cell(row=excel_row, column=col_index, value=_escape_excel(value))
                if column.kind == "money":
                    cell.number_format = _currency_format(currency_symbol)
                    cell.alignment = Alignment(horizontal="right")
                elif column.kind == "qty":
                    cell.number_format = "#,##0.###"
                    cell.alignment = Alignment(horizontal="right")
                elif column.kind == "int":
                    cell.alignment = Alignment(horizontal="right")
                elif column.kind == "date":
                    cell.number_format = "yyyy-mm-dd"
                elif column.kind == "datetime":
                    cell.number_format = "yyyy-mm-dd hh:mm:ss"
                if offset % 2 == 1:
                    cell.fill = title_fill

        last_data_row = data_start + len(spec.rows) - 1
        if spec.rows:
            worksheet.auto_filter.ref = (
                f"A{header_row}:{get_column_letter(len(spec.columns))}{last_data_row}"
            )
        worksheet.freeze_panes = f"A{data_start}"

        if spec.totals:
            total_row = last_data_row + 1 if spec.rows else data_start
            for col_index, column in enumerate(spec.columns, start=1):
                if col_index == 1:
                    value = spec.total_label
                elif column.key in spec.totals:
                    value = _convert_cell(
                        column, spec.totals.get(column.key), tz=tz, for_csv=False
                    )
                else:
                    value = None
                cell = worksheet.cell(row=total_row, column=col_index, value=value)
                cell.font = Font(bold=True)
                cell.fill = TOTAL_FILL
                cell.border = BOTTOM_BORDER
                if column.kind == "money":
                    cell.number_format = _currency_format(currency_symbol)
                elif column.kind == "qty":
                    cell.number_format = "#,##0.###"

    temp = atomic_path(target)
    try:
        workbook.save(temp)
        replace_atomically(temp, target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    finally:
        workbook.close()
    return target


def write_sheet_csv(path: Path | str, spec: SheetSpec, *, tz: str = "Africa/Lagos") -> Path:
    headers = [column.header for column in spec.columns]
    rows = [
        [_convert_cell(column, row.get(column.key), tz=tz, for_csv=True) for column in spec.columns]
        for row in spec.rows
    ]
    return write_csv(path, headers, rows)


# ---------------------------------------------------------------------------
# Daily reports
# ---------------------------------------------------------------------------
def daily_directory(root: Path, day: date) -> Path:
    return Path(root) / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"


def daily_paths(root: Path, day: date) -> dict[str, Path]:
    directory = daily_directory(root, day)
    day_text = day.isoformat()
    return {
        "directory": directory,
        "transactions_csv": directory / f"transactions_{day_text}.csv",
        "transactions_xlsx": directory / f"transactions_{day_text}.xlsx",
        "movements_csv": directory / f"stock_movements_{day_text}.csv",
        "summary_xlsx": directory / f"daily_summary_{day_text}.xlsx",
    }


def daily_files_exist(root: Path, day: date) -> bool:
    paths = daily_paths(root, day)
    return all(paths[key].is_file() for key in DAILY_FILENAMES)


def _daily_summary_values(session: Session, day: date) -> dict:
    sales = analytics.sales_summary(session, day, day)
    movements = analytics.movement_summary(session, day, day)
    cogs = analytics.cost_of_goods_sold(session, day, day)
    units = analytics.units_sold(session, day, day)
    return {
        "sales_count": sales["sales_count"],
        "units_milli": units,
        "gross_minor": sales["gross_minor"],
        "discount_minor": sales["discount_minor"],
        "refund_minor": sales["refund_minor"],
        "net_minor": sales["net_minor"],
        "cogs_minor": cogs,
        "gross_profit_minor": sales["net_minor"] - cogs,
        "movements": movements,
    }


def _write_daily_files(
    session: Session,
    day: date,
    root: Path,
    *,
    tz: str,
    currency_symbol: str,
    business_name: str = "StockKeep",
) -> list[str]:
    paths = daily_paths(root, day)
    paths["directory"].mkdir(parents=True, exist_ok=True)
    transactions = analytics.transaction_rows(session, day, day)
    movements = analytics.stock_movement_rows(session, day, day)
    summary = _daily_summary_values(session, day)
    payment = analytics.payment_totals(session, day, day)

    transaction_totals = {
        "quantity_milli": sum(row["quantity_milli"] for row in transactions),
        "discount_minor": sum(row["discount_minor"] for row in transactions),
        "line_total_minor": sum(row["line_total_minor"] for row in transactions),
    }
    transaction_sheet = SheetSpec(
        "Transactions", TRANSACTION_COLUMNS, transactions, transaction_totals
    )
    write_sheet_csv(paths["transactions_csv"], transaction_sheet, tz=tz)

    summary_rows = []
    for label, key in SUMMARY_ITEMS:
        value = summary[key]
        if key in {"gross_minor", "discount_minor", "refund_minor", "net_minor", "cogs_minor", "gross_profit_minor"}:
            text = f"{currency_symbol}{from_minor(value):,.2f}"
        elif key == "units_milli":
            text = format_qty(value)
        else:
            text = str(value)
        summary_rows.append({"metric": label, "value": text})

    stock_rows = [
        {"label": "Opening stock", "quantity_milli": summary["movements"]["opening_milli"]},
        {"label": "Stock received", "quantity_milli": summary["movements"]["received_milli"]},
        {"label": "Units sold", "quantity_milli": summary["movements"]["sold_milli"]},
        {"label": "Customer returns", "quantity_milli": summary["movements"]["returned_milli"]},
        {"label": "Damaged", "quantity_milli": summary["movements"]["damaged_milli"]},
        {"label": "Lost", "quantity_milli": summary["movements"]["lost_milli"]},
        {"label": "Expired", "quantity_milli": summary["movements"]["expired_milli"]},
        {"label": "Other adjustments", "quantity_milli": summary["movements"]["adjusted_milli"]},
        {"label": "Closing stock", "quantity_milli": summary["movements"]["closing_milli"]},
    ]
    payment_rows = [
        {
            "metric": f"{row['payment_method']} net",
            "value": f"{currency_symbol}{from_minor(row['net_minor']):,.2f}",
        }
        for row in payment
    ]
    summary_sheet = SheetSpec("Daily Summary", DAILY_SUMMARY_COLUMNS, summary_rows + payment_rows)
    movement_sheet = SheetSpec(
        "Stock Movements",
        MOVEMENT_COLUMNS,
        movements,
        {
            "quantity_change_milli": sum(row["quantity_change_milli"] for row in movements),
        },
    )
    write_workbook(
        paths["summary_xlsx"],
        [summary_sheet, movement_sheet],
        tz=tz,
        currency_symbol=currency_symbol,
        title=f"Daily summary - {day.isoformat()}",
        metadata={"Business": business_name},
    )
    write_workbook(
        paths["transactions_xlsx"],
        [transaction_sheet, summary_sheet, movement_sheet],
        tz=tz,
        currency_symbol=currency_symbol,
        title=f"Daily transactions - {day.isoformat()}",
        metadata={"Business": business_name},
    )
    movement_csv = SheetSpec("Stock Movements", MOVEMENT_COLUMNS, movements)
    write_sheet_csv(paths["movements_csv"], movement_csv, tz=tz)
    return [str(paths[key]) for key in DAILY_FILENAMES]


def generate_daily(
    database,
    day: date,
    root: Path,
    *,
    tz: str = "Africa/Lagos",
    currency_symbol: str = "\u20a6",
    business_name: str = "StockKeep",
    force: bool = False,
    operator_id: int | None = None,
) -> ReportOutcome:
    """Generate (or reuse) the four-file daily bundle for a business date."""
    day = day if isinstance(day, date) else date.fromisoformat(str(day))
    root = Path(root)
    job_id = None
    with database.session() as session:
        job = ensure_daily_job(session, day)
        job_id = job.id
        if (
            job.status == REPORT_COMPLETED
            and not force
            and daily_files_exist(root, day)
        ):
            return ReportOutcome(day, "skipped", [str(p) for p in daily_paths(root, day).values()])
        job.status = REPORT_RUNNING
        job.attempts = int(job.attempts or 0) + 1
        job.last_error = None
    try:
        with database.session() as session:
            files = _write_daily_files(
                session,
                day,
                root,
                tz=tz,
                currency_symbol=currency_symbol,
                business_name=business_name,
            )
            job = session.get(ReportJob, job_id)
            job.status = REPORT_COMPLETED
            job.file_path = str(daily_directory(root, day))
            job.generated_at = utc_now()
            job.last_error = None
            audit.record(
                session,
                "report.generated",
                "report_job",
                job.id,
                operator_id=operator_id,
                details={"date": day.isoformat(), "files": files, "attempt": job.attempts},
            )
        return ReportOutcome(day, "generated", files)
    except Exception as exc:  # keep the job actionable for retry
        log.exception("Daily report generation failed for %s", day)
        error = f"{type(exc).__name__}: {exc}"
        try:
            with database.session() as session:
                job = session.get(ReportJob, job_id)
                if job is not None:
                    job.status = REPORT_FAILED
                    job.last_error = error[:2000]
                    session.add(
                        audit.AuditEvent(
                            action="report.failed",
                            entity_type="report_job",
                            entity_id=str(job.id),
                            reason=error[:2000],
                            operator_id=operator_id,
                        )
                    )
        except Exception:  # pragma: no cover
            log.exception("Could not record report failure")
        return ReportOutcome(day, "failed", error=error)


def mark_daily_stale(database, day: date) -> None:
    from .report_state import mark_daily_dirty

    with database.session() as session:
        mark_daily_dirty(session, day)


def report_status_rows(session: Session, limit: int = 60) -> list[ReportJob]:
    return (
        session.query(ReportJob)
        .filter(ReportJob.report_type == "daily")
        .order_by(ReportJob.period_start.desc())
        .limit(limit)
        .all()
    )


def recover_running_jobs(session: Session) -> int:
    rows = session.query(ReportJob).filter(ReportJob.status == REPORT_RUNNING).all()
    for row in rows:
        row.status = "pending"
    return len(rows)


# ---------------------------------------------------------------------------
# Date-range exports
# ---------------------------------------------------------------------------
EXPORT_TYPES = {
    "sales": "Sales transactions",
    "daily_summary": "Daily summary",
    "stock_movements": "Stock movements",
    "inventory": "Inventory snapshot",
    "refunds": "Returns and refunds",
    "product_performance": "Product performance",
    "payment_summary": "Payment summary",
}


def _transport_columns() -> list[Column]:
    return [
        Column("Transaction ID", "transaction_number", "text", 24),
        Column("Business Date", "business_date", "date", 13),
        Column("Transaction Timestamp", "created_at", "datetime", 20),
        Column("Product ID", "product_id", "int", 10),
        Column("Product Name", "product_name", "text", 30),
        Column("Quantity Sold", "quantity_milli", "qty", 13),
        Column("Unit Selling Price", "unit_price_minor", "money", 16),
        Column("Discount", "discount_minor", "money", 12),
        Column("Line Total", "line_total_minor", "money", 14),
        Column("Payment Method", "payment_method", "text", 16),
        Column("Operator", "operator", "text", 16),
        Column("Transaction Status", "status", "text", 18),
    ]


def build_export_sheet(
    session: Session,
    kind: str,
    start: date,
    end: date,
    *,
    product_id: int | None = None,
    payment_method: str | None = None,
) -> SheetSpec:
    if kind not in EXPORT_TYPES:
        raise ValidationError(f"Unknown report type: {kind}", "report_type")
    if kind == "sales":
        rows = analytics.transaction_rows(
            session,
            start,
            end,
            product_id=product_id,
            payment_method=payment_method,
        )
        return SheetSpec(
            "Sales Transactions",
            _transport_columns(),
            rows,
            {
                "quantity_milli": sum(r["quantity_milli"] for r in rows),
                "discount_minor": sum(r["discount_minor"] for r in rows),
                "line_total_minor": sum(r["line_total_minor"] for r in rows),
            },
        )
    if kind == "daily_summary":
        rows = analytics.daily_summary_rows(session, start, end)
        return SheetSpec(
            "Daily Summary",
            DAILY_SALES_COLUMNS,
            rows,
            {
                "sales_count": sum(r["sales_count"] for r in rows),
                "units_milli": sum(r["units_milli"] for r in rows),
                "gross_minor": sum(r["gross_minor"] for r in rows),
                "discount_minor": sum(r["discount_minor"] for r in rows),
                "refund_minor": sum(r["refund_minor"] for r in rows),
                "net_minor": sum(r["net_minor"] for r in rows),
                "cogs_minor": sum(r["cogs_minor"] for r in rows),
            },
        )
    if kind == "stock_movements":
        rows = analytics.stock_movement_rows(session, start, end, product_id=product_id)
        return SheetSpec(
            "Stock Movements",
            MOVEMENT_COLUMNS,
            rows,
            {"quantity_change_milli": sum(r["quantity_change_milli"] for r in rows)},
        )
    if kind == "inventory":
        rows = analytics.inventory_rows(session, product_id=product_id)
        return SheetSpec(
            "Inventory Snapshot",
            INVENTORY_COLUMNS,
            rows,
            {
                "quantity_milli": sum(r["quantity_milli"] for r in rows),
                "cost_value_minor": sum(r["cost_value_minor"] for r in rows),
                "selling_value_minor": sum(r["selling_value_minor"] for r in rows),
            },
        )
    if kind == "refunds":
        rows = analytics.refund_rows(session, start, end, product_id=product_id)
        return SheetSpec(
            "Returns and Refunds",
            REFUND_COLUMNS,
            rows,
            {"amount_minor": sum(r["amount_minor"] for r in rows)},
        )
    if kind == "product_performance":
        rows = analytics.product_performance(session, start, end)
        if product_id:
            rows = [r for r in rows if r["product_id"] == product_id]
        return SheetSpec(
            "Product Performance",
            PRODUCT_PERFORMANCE_COLUMNS,
            rows,
            {
                "opening_milli": sum(r["opening_milli"] for r in rows),
                "received_milli": sum(r["received_milli"] for r in rows),
                "sold_milli": sum(r["sold_milli"] for r in rows),
                "returned_milli": sum(r["returned_milli"] for r in rows),
                "closing_milli": sum(r["closing_milli"] for r in rows),
                "revenue_minor": sum(r["revenue_minor"] for r in rows),
                "gross_profit_minor": sum(r["gross_profit_minor"] for r in rows),
            },
        )
    rows = analytics.payment_totals(session, start, end)
    if payment_method:
        rows = [r for r in rows if r["payment_method"] == payment_method]
    return SheetSpec(
        "Payment Summary",
        PAYMENT_COLUMNS,
        rows,
        {
            "gross_minor": sum(r["gross_minor"] for r in rows),
            "discount_minor": sum(r["discount_minor"] for r in rows),
            "refund_minor": sum(r["refund_minor"] for r in rows),
            "net_minor": sum(r["net_minor"] for r in rows),
        },
    )


def export_report(
    session: Session,
    kind: str,
    start: date,
    end: date,
    destination: Path | str,
    *,
    fmt: str | None = None,
    product_id: int | None = None,
    payment_method: str | None = None,
    tz: str = "Africa/Lagos",
    currency_symbol: str = "\u20a6",
    business_name: str = "StockKeep",
) -> Path:
    if end < start:
        raise ValidationError("End date cannot be before the start date.", "end_date")
    target = Path(destination)
    resolved = (fmt or target.suffix.lstrip(".") or "csv").lower()
    if resolved not in {"csv", "xlsx"}:
        raise ValidationError("Export format must be CSV or Excel.", "format")
    if target.suffix.lower() != "." + resolved:
        target = target.with_suffix("." + resolved)
    spec = build_export_sheet(
        session, kind, start, end, product_id=product_id, payment_method=payment_method
    )
    if resolved == "csv":
        return write_sheet_csv(target, spec, tz=tz)
    return write_workbook(
        target,
        [spec],
        tz=tz,
        currency_symbol=currency_symbol,
        title=f"{EXPORT_TYPES[kind]} - {start.isoformat()} to {end.isoformat()}",
        metadata={"Business": business_name},
    )


# ---------------------------------------------------------------------------
# Monthly exports
# ---------------------------------------------------------------------------
def _executive_rows(summary: dict, currency_symbol: str, business_name: str) -> list[dict]:
    def money(value):
        return f"{currency_symbol}{from_minor(value):,.2f}"

    valuation = summary["valuation"]
    return [
        {"metric": "Business", "value": business_name},
        {"metric": "Period", "value": f"{summary['start']} to {summary['end']}"},
        {"metric": "Completed sales", "value": str(summary["sales_count"])},
        {"metric": "Opening stock", "value": format_qty(summary["opening_milli"])},
        {"metric": "Stock received", "value": format_qty(summary["received_milli"])},
        {"metric": "Units sold", "value": format_qty(summary["sold_milli"])},
        {"metric": "Customer returns", "value": format_qty(summary["returned_milli"])},
        {"metric": "Damaged stock", "value": format_qty(summary["damaged_milli"])},
        {"metric": "Lost stock", "value": format_qty(summary["lost_milli"])},
        {"metric": "Expired stock", "value": format_qty(summary["expired_milli"])},
        {"metric": "Other adjustments", "value": format_qty(summary["adjusted_milli"])},
        {"metric": "Closing stock", "value": format_qty(summary["closing_milli"])},
        {"metric": "Gross sales", "value": money(summary["gross_minor"])},
        {"metric": "Discounts", "value": money(summary["discount_minor"])},
        {"metric": "Refunds", "value": money(summary["refund_minor"])},
        {"metric": "Net sales", "value": money(summary["net_minor"])},
        {"metric": "Estimated COGS", "value": money(summary["cogs_minor"])},
        {"metric": "Estimated gross profit", "value": money(summary["gross_profit_minor"])},
        {
            "metric": "Current inventory valuation (cost)",
            "value": money(valuation["cost_minor"]),
        },
        {
            "metric": "Current inventory valuation (selling)",
            "value": money(valuation["selling_minor"]),
        },
        {"metric": "Products missing cost price", "value": str(valuation["missing_cost_products"])},
    ]


def monthly_sheets(
    session: Session,
    year: int,
    month: int,
    *,
    currency_symbol: str = "\u20a6",
    business_name: str = "StockKeep",
) -> list[SheetSpec]:
    summary = analytics.monthly_summary(session, year, month)
    daily = summary["daily"]
    products = summary["products"]
    payments = summary["payment_totals"]
    movements = summary["movement_by_type"]

    movement_rows = []
    labels = {
        "opening": "Opening stock",
        "receipt": "Stock received",
        "sale": "Sales deductions",
        "return": "Customer returns",
        "damage": "Damaged",
        "loss": "Lost",
        "expiry": "Expired",
        "adjustment": "Adjustments",
        "import": "Imports",
        "reversal": "Reversals",
    }
    for key, label in labels.items():
        movement_rows.append({"label": label, "quantity_milli": int(movements.get(key, 0))})
    movement_rows.append({"label": "Net movement", "quantity_milli": summary["closing_milli"] - summary["opening_milli"]})
    movement_rows.append({"label": "Closing stock", "quantity_milli": summary["closing_milli"]})

    executive = SheetSpec(
        "Executive Summary",
        DAILY_SUMMARY_COLUMNS,
        _executive_rows(summary, currency_symbol, business_name),
    )
    daily_sheet = SheetSpec(
        "Daily Sales",
        DAILY_SALES_COLUMNS,
        daily,
        {
            "sales_count": sum(r["sales_count"] for r in daily),
            "units_milli": sum(r["units_milli"] for r in daily),
            "gross_minor": sum(r["gross_minor"] for r in daily),
            "discount_minor": sum(r["discount_minor"] for r in daily),
            "refund_minor": sum(r["refund_minor"] for r in daily),
            "net_minor": sum(r["net_minor"] for r in daily),
            "cogs_minor": sum(r["cogs_minor"] for r in daily),
        },
    )
    product_sheet = SheetSpec(
        "Product Performance",
        PRODUCT_PERFORMANCE_COLUMNS,
        products,
        {
            "opening_milli": sum(r["opening_milli"] for r in products),
            "received_milli": sum(r["received_milli"] for r in products),
            "sold_milli": sum(r["sold_milli"] for r in products),
            "returned_milli": sum(r["returned_milli"] for r in products),
            "closing_milli": sum(r["closing_milli"] for r in products),
            "revenue_minor": sum(r["revenue_minor"] for r in products),
            "cogs_minor": sum(r["cogs_minor"] for r in products),
            "gross_profit_minor": sum(r["gross_profit_minor"] for r in products),
        },
    )
    stock_sheet = SheetSpec("Stock Movements", STOCK_SUMMARY_COLUMNS, movement_rows)
    payment_sheet = SheetSpec(
        "Payment Summary",
        PAYMENT_COLUMNS,
        payments,
        {
            "gross_minor": sum(r["gross_minor"] for r in payments),
            "discount_minor": sum(r["discount_minor"] for r in payments),
            "refund_minor": sum(r["refund_minor"] for r in payments),
            "net_minor": sum(r["net_minor"] for r in payments),
        },
    )
    return [executive, daily_sheet, product_sheet, stock_sheet, payment_sheet]


def export_monthly(
    session: Session,
    year: int,
    month: int,
    destination: Path | str,
    *,
    fmt: str = "xlsx",
    tz: str = "Africa/Lagos",
    currency_symbol: str = "\u20a6",
    business_name: str = "StockKeep",
) -> Path:
    start, _ = month_bounds(year, month)
    target = Path(destination)
    sheets = monthly_sheets(
        session, year, month, currency_symbol=currency_symbol, business_name=business_name
    )
    if fmt == "xlsx":
        if target.suffix.lower() != ".xlsx":
            target = target.with_suffix(".xlsx")
        return write_workbook(
            target,
            sheets,
            tz=tz,
            currency_symbol=currency_symbol,
            title=f"Monthly report - {start:%B %Y}",
            metadata={"Business": business_name},
        )
    if fmt == "csv":
        folder = target.with_suffix("") if target.suffix else target
        folder = Path(str(folder) + "_csv")
        folder.mkdir(parents=True, exist_ok=True)
        names = {
            "Executive Summary": "executive_summary.csv",
            "Daily Sales": "daily_sales.csv",
            "Product Performance": "product_performance.csv",
            "Stock Movements": "stock_movements.csv",
            "Payment Summary": "payment_summary.csv",
        }
        for spec in sheets:
            write_sheet_csv(folder / names[spec.title], spec, tz=tz)
        return folder
    raise ValidationError("Monthly export format must be csv or xlsx.", "fmt")


# ---------------------------------------------------------------------------
# Scheduler support
# ---------------------------------------------------------------------------
def activity_dates(session: Session) -> list[date]:
    from ..models import Refund, Sale, StockMovement

    dates: set[date] = set()
    for column in (Sale.business_date, StockMovement.business_date, Refund.business_date):
        for (value,) in session.query(column).distinct().all():
            if value is not None:
                dates.add(value)
    return sorted(dates)


def last_successful_report(session: Session) -> ReportJob | None:
    return (
        session.query(ReportJob)
        .filter(ReportJob.report_type == "daily", ReportJob.status == REPORT_COMPLETED)
        .order_by(ReportJob.period_start.desc())
        .first()
    )
