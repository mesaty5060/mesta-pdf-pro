"""Mesta PDF Pro — professional desktop PDF reader & editor."""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from pdfstudio.i18n import is_rtl
from pdfstudio.mainwindow import MainWindow


def main():
    import multiprocessing
    multiprocessing.freeze_support()  # background OCR process (needed in the .exe)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Mesta PDF Pro")
    app.setOrganizationName("Mesta")
    app.setLayoutDirection(Qt.RightToLeft if is_rtl() else Qt.LeftToRight)
    app.setFont(QFont("Segoe UI Variable Text", 10))
    win = MainWindow()
    win.show()
    args = [a for a in sys.argv[1:] if os.path.exists(a)]
    if args:
        win.open_file(args[0], ask=False)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
