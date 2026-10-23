"""Application theme: palettes, Qt palette and stylesheet."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#F2F5F7",
    "surface": "#FFFFFF",
    "surface_alt": "#F7FAFB",
    "sidebar": "#0B1E26",
    "sidebar_hover": "#14313D",
    "nav_text": "#A8BAC5",
    "nav_active_text": "#7DE3D8",
    "text": "#14242E",
    "muted": "#667C8A",
    "border": "#DCE6EB",
    "border_soft": "#EDF2F5",
    "accent": "#0E7C86",
    "accent_hover": "#0A626B",
    "accent_soft": "#E2F4F5",
    "accent_text": "#0B5B62",
    "success": "#16803C",
    "warning": "#B45309",
    "danger": "#C0362C",
    "selection": "#D9F0F2",
    "input": "#FFFFFF",
    "shadow": "#DCE6EB",
    "dark": False,
}

DARK = {
    "bg": "#081117",
    "surface": "#0F1C24",
    "surface_alt": "#13232D",
    "sidebar": "#061016",
    "sidebar_hover": "#10242E",
    "nav_text": "#90A7B3",
    "nav_active_text": "#7DEFE2",
    "text": "#E7F0F4",
    "muted": "#8AA0AC",
    "border": "#223640",
    "border_soft": "#182B35",
    "accent": "#2DC6B8",
    "accent_hover": "#46DACB",
    "accent_soft": "#103A3C",
    "accent_text": "#7DEFE2",
    "success": "#4ADE80",
    "warning": "#FBBF24",
    "danger": "#F87171",
    "selection": "#12464A",
    "input": "#0C1820",
    "shadow": "#041014",
    "dark": True,
}


def palette(name: str) -> dict:
    return DARK if str(name).lower() == "dark" else LIGHT


def status_color(status: str, theme: str = "light") -> str:
    p = palette(theme)
    text = str(status or "").lower()
    if text in {"out of stock"} or "reversed" in text:
        return p["danger"]
    if "low stock" in text or "unconfirmed" in text or "partial" in text:
        return p["warning"]
    if text in {"in stock", "completed"} or "refunded" == text:
        return p["success"] if text == "in stock" or text == "completed" else p["muted"]
    if text in {"archived", "refunded", "skipped", "stale"}:
        return p["muted"]
    if text in {"failed", "error", "invalid", "duplicate"}:
        return p["danger"]
    if text in {"generated", "completed", "new", "update"}:
        return p["success"]
    return p["text"]


def build_stylesheet(theme_name: str = "light") -> str:
    p = palette(theme_name)
    return f"""
    * {{
        font-family: "Segoe UI", "Segoe UI Variable", "Inter", Arial;
        font-size: 13px;
        outline: none;
    }}
    QWidget {{ color: {p['text']}; }}
    QMainWindow, QWidget#AppRoot, QWidget#PageRoot {{ background: {p['bg']}; }}
    QDialog {{ background: {p['surface']}; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    QWidget#Sidebar {{ background: {p['sidebar']}; }}
    QLabel#BrandTitle {{ color: #FFFFFF; font-size: 20px; font-weight: 700; }}
    QLabel#BrandSub {{ color: {p['nav_text']}; font-size: 10.5px; font-weight: 600; }}
    QLabel#SidebarSection {{ color: {p['nav_text']}; font-size: 10px; font-weight: 700; }}
    QLabel#SidebarUser {{ color: #E9F3F6; font-size: 12px; font-weight: 600; }}
    QLabel#SidebarMuted {{ color: {p['nav_text']}; font-size: 11px; }}
    QFrame#SidebarFooter {{ background: {p['sidebar_hover']}; border-radius: 10px; }}

    QPushButton#NavButton {{
        background: transparent; color: {p['nav_text']}; text-align: left;
        padding: 9px 14px; border: none; border-radius: 8px; font-size: 13px;
        font-weight: 500;
    }}
    QPushButton#NavButton:hover {{ background: {p['sidebar_hover']}; color: #FFFFFF; }}
    QPushButton#NavButton:checked {{
        background: {p['sidebar_hover']}; color: {p['nav_active_text']}; font-weight: 700;
    }}

    QLabel#PageTitle {{ font-size: 25px; font-weight: 700; color: {p['text']}; }}
    QLabel#PageSubtitle {{ color: {p['muted']}; font-size: 12.5px; }}
    QLabel#SectionTitle {{ font-size: 15px; font-weight: 700; color: {p['text']}; }}
    QLabel#SectionSubtitle {{ color: {p['muted']}; font-size: 11.5px; }}
    QLabel#Muted {{ color: {p['muted']}; }}
    QLabel#FieldLabel {{ color: {p['muted']}; font-size: 11.5px; font-weight: 600; }}
    QLabel#KpiLabel {{ color: {p['muted']}; font-size: 11px; font-weight: 700; }}
    QLabel#KpiValue {{ color: {p['text']}; font-size: 24px; font-weight: 700; }}
    QLabel#KpiHint {{ color: {p['muted']}; font-size: 10.5px; }}
    QLabel#EmptyTitle {{ color: {p['text']}; font-size: 14px; font-weight: 600; }}
    QLabel#EmptyText {{ color: {p['muted']}; font-size: 12px; }}
    QLabel#BadgeText {{ color: {p['accent_text']}; font-size: 10.5px; font-weight: 700; }}
    QLabel#StatGood {{ color: {p['success']}; font-weight: 600; }}
    QLabel#StatWarn {{ color: {p['warning']}; font-weight: 600; }}
    QLabel#StatBad {{ color: {p['danger']}; font-weight: 600; }}
    QLabel#ErrorLabel {{ color: {p['danger']}; font-size: 11.5px; }}
    QLabel#LoginTitle {{ font-size: 22px; font-weight: 700; color: {p['text']}; }}
    QLabel#LoginSubtitle {{ color: {p['muted']}; font-size: 12px; }}

    QFrame#Card, QFrame#KpiCard, QFrame#TableCard {{
        background: {p['surface']}; border: 1px solid {p['border']};
        border-radius: 12px;
    }}
    QFrame#KpiCard {{ border-radius: 12px; }}
    QFrame#KpiAccent {{ border-radius: 3px; }}
    QFrame#Divider {{ background: {p['border_soft']}; max-height: 1px; border: none; }}

    QPushButton {{
        background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']};
        border-radius: 7px; padding: 7px 14px; min-height: 20px; font-weight: 500;
    }}
    QPushButton:hover {{ border-color: {p['accent']}; color: {p['accent_text']}; }}
    QPushButton:pressed {{ background: {p['accent_soft']}; }}
    QPushButton:disabled {{ color: {p['muted']}; background: {p['surface_alt']}; border-color: {p['border_soft']}; }}
    QPushButton#PrimaryButton {{
        background: {p['accent']}; color: #FFFFFF; border: 1px solid {p['accent']};
        font-weight: 600; padding: 8px 16px;
    }}
    QPushButton#PrimaryButton:hover {{ background: {p['accent_hover']}; border-color: {p['accent_hover']}; color: #FFFFFF; }}
    QPushButton#PrimaryButton:disabled {{ background: {p['muted']}; border-color: {p['muted']}; color: {p['surface']}; }}
    QPushButton#DangerButton {{
        background: transparent; color: {p['danger']}; border: 1px solid {p['danger']};
    }}
    QPushButton#DangerButton:hover {{ background: {p['danger']}; color: #FFFFFF; }}
    QPushButton#GhostButton {{ background: transparent; border: 1px solid transparent; color: {p['muted']}; }}
    QPushButton#GhostButton:hover {{ background: {p['surface_alt']}; color: {p['text']}; }}
    QPushButton#LinkButton {{ background: transparent; border: none; color: {p['accent']}; padding: 2px 4px; }}
    QPushButton#LinkButton:hover {{ color: {p['accent_hover']}; text-decoration: underline; }}
    QPushButton#QuickAction {{
        background: {p['surface_alt']}; border: 1px solid {p['border']};
        border-radius: 10px; padding: 12px; text-align: left; font-weight: 600;
    }}
    QPushButton#QuickAction:hover {{ border-color: {p['accent']}; background: {p['accent_soft']}; }}

    QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
        background: {p['input']}; border: 1px solid {p['border']}; border-radius: 7px;
        padding: 6px 9px; min-height: 21px; selection-background-color: {p['accent']};
        selection-color: #FFFFFF;
    }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus,
    QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border: 1px solid {p['accent']};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        background: {p['surface_alt']}; color: {p['muted']};
    }}
    QLineEdit[readOnly="true"] {{ background: {p['surface_alt']}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
        border-top: 5px solid {p['muted']}; margin-right: 8px; }}
    QComboBox QAbstractItemView {{
        background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 6px;
        selection-background-color: {p['accent_soft']}; selection-color: {p['text']}; padding: 4px;
        outline: 0;
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
        width: 18px; border: none; background: transparent;
    }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 17px; height: 17px; border: 1px solid {p['border']};
        border-radius: 4px; background: {p['input']}; }}
    QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}

    QTableView, QTableWidget {{
        background: {p['surface']}; alternate-background-color: {p['surface_alt']};
        border: 1px solid {p['border']}; border-radius: 9px; gridline-color: transparent;
        selection-background-color: {p['selection']}; selection-color: {p['text']};
        outline: 0;
    }}
    QTableView::item, QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {p['border_soft']}; }}
    QTableView::item:selected, QTableWidget::item:selected {{
        background: {p['selection']}; color: {p['text']};
    }}
    QHeaderView::section {{
        background: {p['surface_alt']}; color: {p['muted']}; border: none;
        border-bottom: 1px solid {p['border']}; padding: 8px; font-weight: 700;
        font-size: 10.5px;
    }}
    QHeaderView::section:hover {{ color: {p['text']}; }}
    QTableCornerButton::section {{ background: {p['surface_alt']}; border: none; }}

    QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 10px; background: {p['surface']}; top: -1px; }}
    QTabBar::tab {{
        background: transparent; color: {p['muted']}; padding: 9px 16px; margin-right: 4px;
        border: none; border-bottom: 2px solid transparent; font-weight: 600;
    }}
    QTabBar::tab:selected {{ color: {p['accent_text']}; border-bottom: 2px solid {p['accent']}; }}
    QTabBar::tab:hover {{ color: {p['text']}; }}

    QGroupBox {{
        border: 1px solid {p['border']}; border-radius: 10px; margin-top: 14px;
        padding: 16px 12px 12px 12px; font-weight: 700;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {p['text']}; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p['border']}; min-height: 24px; border-radius: 5px; }}
    QScrollBar::handle:vertical:hover {{ background: {p['muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p['border']}; min-width: 24px; border-radius: 5px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    QProgressBar {{
        background: {p['surface_alt']}; border: 1px solid {p['border']}; border-radius: 6px;
        height: 10px; text-align: center; color: {p['muted']}; font-size: 10px;
    }}
    QProgressBar::chunk {{ background: {p['accent']}; border-radius: 5px; }}

    QStatusBar {{ background: {p['surface']}; color: {p['muted']}; border-top: 1px solid {p['border']}; }}
    QStatusBar::item {{ border: none; }}
    QToolTip {{ background: {p['sidebar']}; color: #FFFFFF; border: none; padding: 5px 8px; border-radius: 4px; }}
    QMenu {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 5px; }}
    QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {p['accent_soft']}; color: {p['text']}; }}
    QListWidget {{ background: {p['input']}; border: 1px solid {p['border']}; border-radius: 8px; }}
    QSplitter::handle {{ background: transparent; width: 10px; }}
    QDialogButtonBox QPushButton {{ min-width: 82px; }}
    """


def apply_theme(app: QApplication, theme_name: str = "light") -> None:
    p = palette(theme_name)
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet(theme_name))

    qt_palette = QPalette()
    qt_palette.setColor(QPalette.Window, QColor(p["bg"]))
    qt_palette.setColor(QPalette.WindowText, QColor(p["text"]))
    qt_palette.setColor(QPalette.Base, QColor(p["input"]))
    qt_palette.setColor(QPalette.AlternateBase, QColor(p["surface_alt"]))
    qt_palette.setColor(QPalette.ToolTipBase, QColor(p["sidebar"]))
    qt_palette.setColor(QPalette.ToolTipText, QColor("#FFFFFF"))
    qt_palette.setColor(QPalette.Text, QColor(p["text"]))
    qt_palette.setColor(QPalette.Button, QColor(p["surface"]))
    qt_palette.setColor(QPalette.ButtonText, QColor(p["text"]))
    qt_palette.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    qt_palette.setColor(QPalette.Highlight, QColor(p["accent"]))
    qt_palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    qt_palette.setColor(QPalette.Link, QColor(p["accent"]))
    app.setPalette(qt_palette)

    font = QFont("Segoe UI")
    font.setPointSizeF(9.5)
    app.setFont(font)
