"""Silent background work for scanned files: text recognition (OCR) and element detection.

Nothing is shown to the user. Pages are processed one by one, starting with the page being read.
OCR runs in a separate process; results are written into the document without marking it as modified.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

from PySide6.QtCore import QObject, QTimer

from . import ocr_worker
from .engine import TESSDATA, ocr_languages


class BackgroundRecognizer(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.pool: ProcessPoolExecutor | None = None
        self.job = None
        self.queue: list[int] = []
        self.token = 0
        self.timer = QTimer(self, interval=350, timeout=self._tick)
        self.langs = ocr_languages()

    # ------------------------------------------------------------------ control
    def restart(self):
        """New document (or big change): queue every page again, current page first."""
        self.token += 1
        self.job = None
        eng = self.win.engine
        if not (eng.is_open and TESSDATA and self.langs and self.enabled()):
            self.timer.stop()
            return
        self.queue = list(range(eng.page_count))
        self.focus(self.win.view.current_page())
        self.timer.start()

    def refresh(self):
        """After edits / undo: re-queue pages that lost their recognised text."""
        eng = self.win.engine
        if not eng.is_open or not self.enabled():
            return
        for p in range(eng.page_count):
            if p not in self.queue:
                self.queue.append(p)
        self.timer.start()

    def enabled(self) -> bool:
        return self.win.settings.value("auto_ocr", "true") in (True, "true", "1", 1)

    def focus(self, pno: int):
        """Do the page the user is looking at (and the next ones) first."""
        front = [p for p in (pno, pno + 1, pno + 2, pno - 1) if p in self.queue]
        self.queue = front + [p for p in self.queue if p not in front]

    def busy_with(self, pno: int) -> bool:
        return (self.job is not None and self.job[1] == pno) or pno in self.queue

    def shutdown(self):
        self.timer.stop()
        if self.pool is not None:
            try:
                self.pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self.pool = None

    # ------------------------------------------------------------------ work loop
    def _tick(self):
        eng = self.win.engine
        if not eng.is_open:
            return
        if self.job is not None:
            fut, pno, token, epoch = self.job
            if not fut.done():
                return
            self.job = None
            if token == self.token and pno < eng.page_count:
                if epoch != eng.epoch:
                    self.queue.insert(0, pno)  # page changed meanwhile: do it again
                elif not eng.has_text(pno):
                    try:
                        data, _lang = fut.result()
                        eng.ocr_apply(pno, data)
                        self.win.on_background_page_ready(pno)
                    except Exception:
                        pass
        if self.job is None:
            while self.queue:
                pno = self.queue.pop(0)
                if pno >= eng.page_count:
                    continue
                try:
                    if not eng.is_scanned(pno):
                        continue
                    eng.get_objects(pno)  # element detection, cached for the Edit tab
                    pix = eng.ocr_prepare(pno, 300)
                    data = pix.tobytes("pnm")
                except Exception:
                    continue
                if self.pool is None:
                    self.pool = ProcessPoolExecutor(max_workers=1)
                fut = self.pool.submit(ocr_worker.run_auto, data, TESSDATA, self.langs)
                self.job = (fut, pno, self.token, eng.epoch)
                return
            self.timer.stop()
