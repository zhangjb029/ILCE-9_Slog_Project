"""Locate and load the firmware-derived JSON tables.

Inside a PyInstaller onefile build the tables live under ``sys._MEIPASS/data``;
running from source they sit next to the package in ``src/data``.
"""
import json
import sys
from pathlib import Path


def data_root() -> Path:
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return Path(meipass) / 'data'
    return Path(__file__).resolve().parent.parent / 'data'


def resource_json(name: str) -> dict:
    return json.loads((data_root() / name).read_text(encoding='utf-8'))
