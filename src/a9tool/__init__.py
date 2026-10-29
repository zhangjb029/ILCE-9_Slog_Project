"""ILCE-9 功能槽位工具。"""
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / 'vendor'
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

__version__ = '1.0.0'
