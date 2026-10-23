"""Generate the StockKeep application icon (PNG preview + multi-size ICO).

Run:  .venv\\Scripts\\python.exe tools\\make_icon.py
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)

    margin = size * 0.055
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    background = QPainterPath()
    background.addRoundedRect(rect, size * 0.22, size * 0.22)
    painter.fillPath(background, QColor("#0E7C86"))

    # Simple "stacked boxes" mark.
    stroke = max(1.6, size * 0.055)
    pen = QPen(QColor("#FFFFFF"))
    pen.setWidthF(stroke)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    left = size * 0.26
    right = size * 0.74
    mid = size * 0.5
    top = size * 0.30
    bottom = size * 0.72

    box = QPainterPath()
    box.moveTo(mid, top)
    box.lineTo(right, top + size * 0.11)
    box.lineTo(mid, top + size * 0.22)
    box.lineTo(left, top + size * 0.11)
    box.closeSubpath()
    painter.drawPath(box)

    painter.drawLine(mid, top + size * 0.22, mid, top + size * 0.46)
    painter.drawLine(left, top + size * 0.11, left, bottom - size * 0.13)
    painter.drawLine(right, top + size * 0.11, right, bottom - size * 0.13)
    painter.drawLine(left, bottom - size * 0.13, mid, bottom)
    painter.drawLine(right, bottom - size * 0.13, mid, bottom)
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data


def write_ico(path: Path, images: list[QImage]) -> None:
    payloads = [(image.width(), png_bytes(image)) for image in images]
    header = struct.pack("<HHH", 0, 1, len(payloads))
    offset = 6 + 16 * len(payloads)
    entries = b""
    body = b""
    for size, data in payloads:
        dimension = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        body += data
    path.write_bytes(header + entries + body)


def main() -> None:
    QApplication.instance() or QApplication([])
    ASSETS.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw(size) for size in sizes]
    preview = draw(512)
    preview.save(str(ASSETS / "stockkeep.png"), "PNG")
    write_ico(ASSETS / "stockkeep.ico", images)
    print(f"Wrote {ASSETS / 'stockkeep.ico'} and {ASSETS / 'stockkeep.png'}")


if __name__ == "__main__":
    main()
