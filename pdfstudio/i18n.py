"""Tiny translation layer. Source strings are Arabic; other languages map Arabic -> translation.

By default the app follows the Windows display language ("system"); the user can pick another one
in Settings ▸ Language (stored in HKCU\\Software\\Mesta\\Mesta PDF Pro\\language). Changing it needs a restart.
"""
from __future__ import annotations

import importlib

LANGUAGES = {"ar": "العربية", "en": "English", "fr": "Français"}
RTL_LANGS = {"ar"}

_table: dict[str, str] = {}
_lang = "ar"


def current_language() -> str:
    return _lang


def is_rtl() -> bool:
    return _lang in RTL_LANGS


def system_language() -> str:
    """Windows display language if we have it, otherwise English."""
    try:
        from PySide6.QtCore import QLocale
        for tag in QLocale.system().uiLanguages():
            code = tag.lower()[:2]
            if code in LANGUAGES:
                return code
    except Exception:
        pass
    return "en"


def chosen_language() -> str:
    """"system" (default: follow Windows) or a fixed code the user picked."""
    try:
        from .brand import settings
        return str(settings().value("language", "system") or "system")
    except Exception:
        return "system"


def load_language(lang: str | None = None):
    global _table, _lang
    if lang is None:
        lang = chosen_language()
    if lang == "system":
        lang = system_language()
    lang = lang.lower()[:2]
    if lang not in LANGUAGES:
        lang = "ar"
    _lang = lang
    _table = {}
    if lang != "ar":
        try:
            _table = importlib.import_module(f".lang_{lang}", __package__).T
        except Exception:
            _table = {}


def tr(s: str) -> str:
    return _table.get(s, s) if _table else s


load_language()
