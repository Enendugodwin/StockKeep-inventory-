"""Tests for the Task Scheduler helper process flags."""

from __future__ import annotations

import os
import subprocess

from stockkeep.services import scheduler


def test_helper_processes_hide_their_console_on_windows():
    flags = scheduler._hidden_console()
    if os.name == "nt":
        assert flags["creationflags"] & subprocess.CREATE_NO_WINDOW
    else:
        assert flags == {}


def test_scheduled_command_uses_a_windowless_python_in_source_checkouts():
    command = scheduler.scheduled_command()
    assert "--generate-reports" in command
    if not getattr(__import__("sys"), "frozen", False):
        assert "pythonw.exe" in command.lower()
