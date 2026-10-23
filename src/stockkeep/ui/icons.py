"""Small inline SVG icon set rendered natively with QtSvg."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "dashboard": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "inventory": '<path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/>',
    "import": '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 18v2h16v-2"/>',
    "sale": '<circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/><path d="M3 4h2l2.5 11h10.5l2-7H6"/>',
    "transactions": '<path d="M6 3h9l3 3v15H6z"/><path d="M9 9h6M9 13h6M9 17h4"/>',
    "receiving": '<path d="M3 6h11v10H3z"/><path d="M14 10h4l3 3v3h-7z"/><circle cx="7" cy="18" r="1.6"/><circle cx="17" cy="18" r="1.6"/>',
    "adjustments": '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
    "reports": '<path d="M4 20V4"/><path d="M4 20h16"/><path d="M7 17v-5M12 17V8M17 17V5"/>',
    "monthly": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "audit": '<path d="M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M16 16l5 5"/>',
    "download": '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 19h16"/>',
    "upload": '<path d="M12 21V9"/><path d="M7 14l5-5 5 5"/><path d="M4 4h16"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v5h-5"/>',
    "print": '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M6 14h12v7H6z"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14"/><path d="M10 11v6M14 11v6"/>',
    "edit": '<path d="M4 20h4l11-11-4-4L4 16z"/><path d="M13 6l5 5"/>',
    "folder": '<path d="M3 6h6l2 2h10v11H3z"/>',
    "backup": '<path d="M4 15v4h16v-4"/><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/>',
    "restore": '<path d="M4 15v4h16v-4"/><path d="M12 21V9"/><path d="M7 14l5-5 5 5"/>',
    "check": '<path d="M4 12l5 5L20 6"/>',
    "alert": '<path d="M12 3l9 17H3z"/><path d="M12 9v5M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "left": '<path d="M15 5l-7 7 7 7"/>',
    "right": '<path d="M9 5l7 7-7 7"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z"/>',
    "save": '<path d="M5 3h12l4 4v14H5z"/><path d="M8 3v6h8V3M8 21v-7h8v7"/>',
    "filter": '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
    "package": '<path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/>',
    "receipt": '<path d="M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.5-6 8-6s8 2 8 6"/>',
    "roles": '<circle cx="9" cy="8" r="3"/><path d="M3 21c0-3.2 2.7-5 6-5s6 1.8 6 5"/><circle cx="17" cy="9" r="2.2"/><path d="M15.5 21c0-2.5 1.8-4 3.5-4s3.5 1.5 3.5 4"/>',
    "warning": '<path d="M12 3l9 17H3z"/><path d="M12 10v4M12 17h.01"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "arrow-up": '<path d="M12 20V5"/><path d="M6 11l6-6 6 6"/>',
    "arrow-down": '<path d="M12 4v15"/><path d="M6 13l6 6 6-6"/>',
}


@lru_cache(maxsize=512)
def pixmap(name: str, color: str = "#0E7C86", size: int = 20) -> QPixmap:
    body = PATHS.get(name)
    if body is None:
        body = PATHS["info"]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.9" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    ratio = 2
    canvas = QPixmap(size * ratio, size * ratio)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    canvas.setDevicePixelRatio(ratio)
    return canvas


@lru_cache(maxsize=512)
def icon(name: str, color: str = "#0E7C86", size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))
