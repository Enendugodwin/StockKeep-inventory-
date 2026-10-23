"""Application logging configuration (rotating file + console)."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def configure_logging(paths, *, verbose: bool = False) -> None:
    root = logging.getLogger()
    if getattr(root, "_stockkeep_configured", False):
        return
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    try:
        handler = logging.handlers.RotatingFileHandler(
            Path(paths.log_path), maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError:
        pass
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING if not verbose else logging.DEBUG)
    console.setFormatter(formatter)
    root.addHandler(console)
    root._stockkeep_configured = True
