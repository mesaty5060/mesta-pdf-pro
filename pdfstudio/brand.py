"""Mesta product identity — one place for names, settings and Windows integration ids.

Every Mesta app (Mesta PDF Pro, the Mesta downloader, …) follows the same pattern:
  publisher / settings organisation : "Mesta"
  settings key                      : HKCU\\Software\\Mesta\\<APP_NAME>
  per-user data folder              : %APPDATA%\\Mesta\\<SHORT>
"""
from __future__ import annotations

import os
import shutil

PUBLISHER = "Mesta"
APP_NAME = "Mesta PDF Pro"
SHORT = "PDF Pro"
EXE_NAME = "MestaPDFPro"
PROGID = "Mesta.PDFPro.Document"
VERSION = "2.2.3"

DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), PUBLISHER, SHORT)
_OLD_DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PDFStudio")


def settings():
    """QSettings for the app; settings from the old "PDF Studio" name are carried over once."""
    from PySide6.QtCore import QSettings
    s = QSettings(PUBLISHER, APP_NAME)
    if not s.value("_migrated", False):
        old = QSettings("PDFStudio", "PDFStudio")
        for k in old.allKeys():
            if not s.contains(k):
                s.setValue(k, old.value(k))
        s.setValue("_migrated", True)
    return s


def data_dir(*parts) -> str:
    """Per-user data folder (stamps, signatures…); the old PDF Studio folder is copied over once."""
    if not os.path.isdir(DATA_DIR) and os.path.isdir(_OLD_DATA_DIR):
        try:
            shutil.copytree(_OLD_DATA_DIR, DATA_DIR)
        except OSError:
            pass
    path = os.path.join(DATA_DIR, *parts)
    os.makedirs(path, exist_ok=True)
    return path
