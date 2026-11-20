"""Windows integration: register Mesta PDF Pro as a PDF reader (per-user, no admin rights)."""
from __future__ import annotations

import os
import sys

from .brand import APP_NAME, PROGID


def launch_command() -> tuple[str, str]:
    """Return (command line with %1, icon path)."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return f'"{exe}" "%1"', exe
    main = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    return f'"{pyw}" "{main}" "%1"', pyw


def register_pdf_reader() -> None:
    import ctypes
    import winreg

    cmd, icon = launch_command()
    base = r"Software\Classes"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{PROGID}") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"PDF Document ({APP_NAME})")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{PROGID}\DefaultIcon") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{icon}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{PROGID}\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\.pdf\OpenWithProgids") as k:
        winreg.SetValueEx(k, PROGID, 0, winreg.REG_NONE, b"")
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED


LAUNCHER_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{5C1D9E27-8A4B-4F36-B0E2-7D93A1C6F548}_is1"


def find_mesta_launcher() -> str | None:
    """Path of MestaLauncher.exe when Mesta Launcher is installed (optional — PDF Pro never needs it)."""
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, LAUNCHER_KEY) as k:
                folder = winreg.QueryValueEx(k, "InstallLocation")[0]
        except OSError:
            continue
        exe = os.path.join(folder, "MestaLauncher.exe")
        if os.path.isfile(exe):
            return exe
    return None


def open_default_apps_settings() -> None:
    try:
        os.startfile("ms-settings:defaultapps")
    except OSError:
        pass
