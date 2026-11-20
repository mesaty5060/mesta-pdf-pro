"""Continuous-scroll PDF canvas with object picking and editing tools."""
from __future__ import annotations

import bisect

import pymupdf
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QTransform)
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsLineItem, QGraphicsPathItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView, QHBoxLayout, QPushButton, QWidget)

from .engine import PageObject, PdfDocument
from .i18n import tr


class Tool:
    HAND = "hand"
    SELECT = "select"
    EDIT_TEXT = "edit_text"
    ADD_TEXT = "add_text"
    ERASE = "erase"
    INK = "ink_remove"
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKE = "strike"
    RECT = "rect"
    ELLIPSE = "ellipse"
    LINE = "line"
    ARROW = "arrow"
    PEN = "pen"
    NOTE = "note"
    TEXT = "text_select"
    EXTRACT = "extract"


AREA_TOOLS = {Tool.ERASE, Tool.INK, Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKE, Tool.RECT, Tool.ELLIPSE, Tool.TEXT,
              Tool.EXTRACT, Tool.EDIT_TEXT}
KIND_COLORS = {"line": "#5b8cff", "block": "#5b8cff", "image": "#22c55e", "annot": "#f59e0b", "drawing": "#c084fc",
               "layer": "#06b6d4", "scan": "#ec4899"}
MOVABLE = ("image", "layer", "drawing")
GAP = 18.0
HANDLE_PX = 9


def _qrect(r) -> QRectF:
    r = pymupdf.Rect(r)
    return QRectF(r.x0, r.y0, r.width, r.height)


def _corners(r: QRectF):
    return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]


def _handle_cursor(h: int):
    return {0: Qt.SizeFDiagCursor, 2: Qt.SizeFDiagCursor, 1: Qt.SizeBDiagCursor, 3: Qt.SizeBDiagCursor,
            4: Qt.SizeVerCursor, 6: Qt.SizeVerCursor, 5: Qt.SizeHorCursor, 7: Qt.SizeHorCursor}.get(h, Qt.ArrowCursor)


def _handles(r: QRectF):
    """0-3 corners (keep proportions), 4-7 edges top/right/bottom/left (stretch one side)."""
    c = r.center()
    return _corners(r) + [QPointF(c.x(), r.top()), QPointF(r.right(), c.y()), QPointF(c.x(), r.bottom()),
                          QPointF(r.left(), c.y())]


# ============================================================================ items
class PageItem(QGraphicsItem):
    def __init__(self, pno: int, w: float, h: float):
        super().__init__()
        self.pno, self.w, self.h = pno, w, h
        self.pix: QPixmap | None = None
        self.pix_scale = 0.0
        self.setZValue(0)

    def boundingRect(self):
        return QRectF(-3, -3, self.w + 10, self.h + 10)

    def paint(self, p: QPainter, opt, widget=None):
        p.setPen(Qt.NoPen)
        for i, a in ((6, 18), (4, 28), (2, 40)):
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRect(QRectF(i * 0.5, i, self.w, self.h))
        p.fillRect(QRectF(0, 0, self.w, self.h), Qt.white)
        if self.pix:
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(QRectF(0, 0, self.w, self.h), self.pix, QRectF(self.pix.rect()))


class FrameItem(QGraphicsItem):
    """Selection / placement frame with corner handles (handles stay constant size on screen)."""

    def __init__(self, color="#5b8cff", handles=True, fill_alpha=28):
        super().__init__()
        self.rect = QRectF()
        self.color = QColor(color)
        self.handles = handles
        self.fill_alpha = fill_alpha
        self.pix: QPixmap | None = None
        self.setZValue(60)

    def set_rect(self, r: QRectF):
        self.prepareGeometryChange()
        self.rect = QRectF(r)
        self.update()

    def boundingRect(self):
        return self.rect.adjusted(-20, -20, 20, 20)

    def paint(self, p: QPainter, opt, widget=None):
        scale = p.worldTransform().m11() or 1.0
        if self.pix:
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(self.rect, self.pix, QRectF(self.pix.rect()))
        fill = QColor(self.color)
        fill.setAlpha(self.fill_alpha)
        pen = QPen(self.color, 1.6)
        pen.setCosmetic(True)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(fill if not self.pix else Qt.NoBrush)
        p.drawRect(self.rect)
        if self.handles:
            hs = HANDLE_PX / scale
            pen = QPen(self.color, 1.4)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.white)
            for i, c in enumerate(_handles(self.rect)):
                if i < 4:
                    p.drawRect(QRectF(c.x() - hs / 2, c.y() - hs / 2, hs, hs))
                else:
                    p.drawEllipse(QRectF(c.x() - hs / 2, c.y() - hs / 2, hs, hs))

    def handle_at(self, scene_pt: QPointF, scale: float) -> int:
        if not self.handles:
            return -1
        hs = (HANDLE_PX + 6) / scale
        for i, c in enumerate(_handles(self.rect)):
            if QRectF(c.x() - hs / 2, c.y() - hs / 2, hs, hs).contains(scene_pt):
                return i
        return -1


class FloatBar(QWidget):
    """Small floating action bar shown next to the selection / placed stamp."""
    triggered = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("FloatBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(6, 5, 6, 5)
        self.lay.setSpacing(5)
        self.lay.setSizeConstraint(QHBoxLayout.SetFixedSize)
        self.hide()

    def set_actions(self, actions):
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        for key, text, style in actions:
            b = QPushButton(text)
            if style:
                b.setObjectName(style)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("padding:5px 11px;")
            b.clicked.connect(lambda _=False, k=key: self.triggered.emit(k))
            self.lay.addWidget(b)
        self.adjustSize()


# ============================================================================ view
class PdfView(QGraphicsView):
    pageChanged = Signal(int)
    zoomChanged = Signal(float)
    selectionChanged = Signal(object)
    editTextRequested = Signal(object)
    addTextRequested = Signal(int, QPointF)
    areaSelected = Signal(str, int, QRectF)
    lineDrawn = Signal(str, int, QPointF, QPointF)
    inkDrawn = Signal(int, list)
    noteRequested = Signal(int, QPointF)
    placeCommitted = Signal(int, QRectF, object, bool)
    placeCancelled = Signal()
    moveRequested = Signal(object, QRectF)
    contextRequested = Signal(object, QPoint)
    floatAction = Signal(str, object)
    hoverInfo = Signal(str)
    filesDropped = Signal(list)
    scanPicked = Signal(int, QRectF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PdfView")
        self.setLayoutDirection(Qt.LeftToRight)
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.engine: PdfDocument | None = None
        self.items_: list[PageItem] = []
        self.tops: list[float] = []
        self.zoom = 1.0
        self.tool = Tool.SELECT
        self.block_mode = False
        self._cur_page = -1
        self._objs: dict[int, list] = {}
        self._hover = QGraphicsRectItem()
        self._hover.setZValue(50)
        self._hover.hide()
        self._hover_obj = None
        self.sel_obj: PageObject | None = None
        self._sel = FrameItem()
        self._sel.hide()
        self._drag = None
        self._band = None
        self._band_start = None
        self._band_page = -1
        self._line = None
        self._path_item = None
        self._path_pts = []
        self._search_items = []
        # placing a stamp / image / signature
        self.place_img: QImage | None = None
        self._place = FrameItem("#8b5cf6", True, 0)
        self._place.hide()
        self._place_aspect = 1.0
        self.bar = FloatBar(self.viewport())
        self.bar.triggered.connect(self._on_bar)
        self._render_timer = QTimer(self, singleShot=True, interval=40, timeout=self._render_visible)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.horizontalScrollBar().valueChanged.connect(lambda _: self._position_bar())
        self.ann_color = QColor("#e11d48")
        self.night = False
        self.read_only = True
        self.band_shift = False
        self.last_click = None
        self.last_mouse = None
        self._textsel_items = []

    # ------------------------------------------------------------------ reading helpers
    def set_night(self, on: bool):
        self.night = on
        for it in self.items_:
            it.pix_scale = 0
        self._render_visible()

    def set_text_boxes(self, boxes: dict):
        """Light highlight on every piece of text (when the user turns on "show text")."""
        for it in getattr(self, "_textbox_items", []):
            if it.scene() is not None:
                self.scene_.removeItem(it)
        self._textbox_items = []
        for pno, rects in boxes.items():
            if pno >= len(self.items_):
                continue
            for r in rects:
                it = QGraphicsRectItem(self.to_scene(pno, r))
                it.setBrush(QColor(16, 185, 129, 45))
                pen = QPen(QColor(16, 185, 129, 150), 0.8)
                pen.setCosmetic(True)
                it.setPen(pen)
                it.setZValue(42)
                self.scene_.addItem(it)
                self._textbox_items.append(it)

    def set_text_selection(self, pno, rects):
        for it in self._textsel_items:
            self.scene_.removeItem(it)
        self._textsel_items.clear()
        for r in rects:
            it = QGraphicsRectItem(self.to_scene(pno, r))
            c = QColor("#3b82f6")
            c.setAlpha(80)
            it.setBrush(c)
            it.setPen(Qt.NoPen)
            it.setZValue(45)
            self.scene_.addItem(it)
            self._textsel_items.append(it)

    # ------------------------------------------------------------------ document
    def set_engine(self, engine: PdfDocument | None):
        self.engine = engine
        self.reload(keep_pos=False)

    def reload(self, keep_pos=True):
        frac = 0.0
        if keep_pos and self.items_:
            sb = self.verticalScrollBar()
            frac = sb.value() / max(1, sb.maximum())
        self._clear_overlays()
        for it in self.items_:
            self.scene_.removeItem(it)
        self.items_.clear()
        self.tops.clear()
        self._objs.clear()
        if not self.engine or not self.engine.is_open:
            self.scene_.setSceneRect(QRectF(0, 0, 10, 10))
            return
        y = GAP
        maxw = 0
        for pno in range(self.engine.page_count):
            w, h = self.engine.page_display_size(pno)
            it = PageItem(pno, w, h)
            it.setPos(-w / 2, y)
            self.scene_.addItem(it)
            self.items_.append(it)
            self.tops.append(y)
            y += h + GAP
            maxw = max(maxw, w)
        self.scene_.setSceneRect(QRectF(-maxw / 2 - 40, 0, maxw + 80, y + GAP))
        for it in (self._hover, self._sel, self._place):
            if it.scene() is None:
                self.scene_.addItem(it)
        if keep_pos:
            sb = self.verticalScrollBar()
            sb.setValue(int(frac * sb.maximum()))
        self._render_timer.start()

    def refresh_pages(self, pnos=None):
        """Re-render after the document changed. If page geometry changed, rebuild."""
        if not self.engine:
            return
        if len(self.items_) != self.engine.page_count or any(
                (it.w, it.h) != self.engine.page_display_size(i) for i, it in enumerate(self.items_)):
            self.reload(keep_pos=True)
            return
        targets = range(len(self.items_)) if pnos is None else pnos
        for p in targets:
            if 0 <= p < len(self.items_):
                self.items_[p].pix_scale = 0
                self._objs.pop(p, None)
        self._hover.hide()
        self._hover_obj = None
        self.clear_selection()
        self._render_visible()

    def _clear_overlays(self):
        self.set_text_selection(0, [])
        self.set_text_boxes({})
        self._hover.hide()
        self.clear_selection()
        self.cancel_place(emit=False)
        self.set_search_hits({})

    # ------------------------------------------------------------------ rendering
    def _render_visible(self):
        if not self.items_:
            return
        vis = self.mapToScene(self.viewport().rect()).boundingRect()
        margin = vis.height() * 0.6
        want = vis.adjusted(0, -margin, 0, margin)
        scale = self.zoom * self.devicePixelRatioF()
        for it in self.items_:
            r = it.sceneBoundingRect()
            if r.intersects(want):
                s = min(scale, 7000.0 / max(it.w, it.h))
                if abs(it.pix_scale - s) > 1e-3:
                    try:
                        pix = self.engine.render(it.pno, s)
                        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
                        if self.night:
                            img.invertPixels()
                        it.pix = QPixmap.fromImage(img)
                        it.pix_scale = s
                        it.update()
                    except Exception:
                        pass
            elif it.pix is not None and not r.intersects(want.adjusted(0, -3 * margin, 0, 3 * margin)):
                it.pix = None
                it.pix_scale = 0

    def _on_scroll(self, _=None):
        self._render_timer.start()
        self._position_bar()
        p = self.page_at_view_center()
        if p != self._cur_page and p >= 0:
            self._cur_page = p
            self.pageChanged.emit(p)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._render_timer.start()
        self._position_bar()

    # ------------------------------------------------------------------ zoom / navigation
    def set_zoom(self, z: float, mouse_anchor=False):
        z = max(0.1, min(8.0, z))
        if not mouse_anchor:
            self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.setTransform(QTransform.fromScale(z, z))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.zoom = z
        self.zoomChanged.emit(z)
        self._render_timer.start()
        self._position_bar()

    def zoom_in(self):
        self.set_zoom(self.zoom * 1.2)

    def zoom_out(self):
        self.set_zoom(self.zoom / 1.2)

    def fit_width(self):
        if self.items_:
            w = max(it.w for it in self.items_)
            self.set_zoom((self.viewport().width() - 40) / w)

    def fit_page(self):
        if self.items_:
            p = max(0, self._cur_page)
            it = self.items_[p]
            z = min((self.viewport().width() - 40) / it.w, (self.viewport().height() - 30) / it.h)
            self.set_zoom(z)
            self.go_to_page(p)

    def go_to_page(self, pno: int, focus: QRectF | None = None):
        if not (0 <= pno < len(self.items_)):
            return
        it = self.items_[pno]
        if focus is not None:
            self.centerOn(it.pos() + focus.center())
        else:
            vh = self.viewport().height() / self.zoom
            self.centerOn(QPointF(0, it.pos().y() + vh / 2 - GAP * 0.6))
        self._on_scroll()

    def page_at_view_center(self) -> int:
        if not self.items_:
            return -1
        c = self.mapToScene(self.viewport().rect().center())
        i = bisect.bisect_right(self.tops, c.y()) - 1
        return max(0, min(i, len(self.items_) - 1))

    def current_page(self) -> int:
        return max(0, self._cur_page)

    def page_at(self, sp: QPointF, strict=True):
        if not self.items_:
            return -1, QPointF()
        i = bisect.bisect_right(self.tops, sp.y()) - 1
        i = max(0, min(i, len(self.items_) - 1))
        it = self.items_[i]
        lp = sp - it.pos()
        if strict and not QRectF(0, 0, it.w, it.h).contains(lp):
            return -1, lp
        return i, lp

    def to_scene(self, pno: int, r: QRectF) -> QRectF:
        return r.translated(self.items_[pno].pos())

    # ------------------------------------------------------------------ tools
    def set_tool(self, tool: str):
        self.tool = tool
        self._hover.hide()
        self._hover_obj = None
        if tool not in (Tool.SELECT,):
            self.clear_selection()
        self.setDragMode(QGraphicsView.ScrollHandDrag if tool == Tool.HAND else QGraphicsView.NoDrag)
        cur = {
            Tool.HAND: Qt.OpenHandCursor, Tool.SELECT: Qt.ArrowCursor, Tool.EDIT_TEXT: Qt.IBeamCursor,
            Tool.ADD_TEXT: Qt.IBeamCursor, Tool.NOTE: Qt.PointingHandCursor, Tool.TEXT: Qt.IBeamCursor,
        }.get(tool, Qt.CrossCursor)
        self.viewport().setCursor(cur)

    # ------------------------------------------------------------------ objects
    def objects(self, pno: int):
        if pno not in self._objs:
            res = self.engine.get_objects(pno)
            conv = lambda o: (o, _qrect(self.engine.to_display(pno, o.rect)))
            self._objs[pno] = {k: [conv(o) for o in v] for k, v in res.items()}
        return self._objs[pno]

    def pick(self, pno: int, lp: QPointF, mode: str):
        objs = self.objects(pno)
        if mode == "text":
            pool = objs["blocks"] if self.block_mode else objs["lines"]
        else:
            pool = ([(o, r) for o, r in objs.get("layers", []) if o.data.get("visible", True)]
                    + objs["annots"] + [(o, r) for o, r in objs["images"] if not o.data.get("full_page")]
                    + objs["drawings"] + objs.get("scan", []))
        cands = [(o, r) for o, r in pool if r.adjusted(-1.5, -1.5, 1.5, 1.5).contains(lp)]
        if not cands:
            return None, None
        pri = {"layer": 0, "annot": 1, "image": 2, "drawing": 3, "scan": 4}
        if mode == "text":  # the field whose centre is nearest to the click (OCR boxes can overlap)
            def dist(t):
                c = t[1].center()
                return abs(c.x() - lp.x()) / max(t[1].width(), 1) + abs(c.y() - lp.y()) / max(t[1].height(), 1)
            cands.sort(key=dist)
        else:
            cands.sort(key=lambda t: (pri.get(t[0].kind, 3), t[1].width() * t[1].height()))
        return cands[0]

    def _show_hover(self, pno, obj, r):
        if obj is None:
            self._hover.hide()
            self._hover_obj = None
            self.hoverInfo.emit("")
            return
        if obj is self._hover_obj:
            return
        self._hover_obj = obj
        c = QColor(KIND_COLORS.get(obj.kind, "#5b8cff"))
        pen = QPen(c, 1.5)
        pen.setCosmetic(True)
        fill = QColor(c)
        fill.setAlpha(35)
        self._hover.setPen(pen)
        self._hover.setBrush(fill)
        self._hover.setRect(self.to_scene(pno, r).adjusted(-1, -1, 1, 1))
        self._hover.show()
        self.hoverInfo.emit(obj.label)

    def select(self, obj: PageObject | None, r: QRectF | None = None):
        self.sel_obj = obj
        if obj is None:
            self._sel.hide()
            self.bar.hide()
            self.selectionChanged.emit(None)
            return
        if r is None:
            r = _qrect(self.engine.to_display(obj.pno, obj.rect))
        self._sel.color = QColor(KIND_COLORS.get(obj.kind, "#5b8cff"))
        self._sel.handles = obj.kind in MOVABLE
        self._sel.set_rect(self.to_scene(obj.pno, r))
        self._sel.show()
        acts = []
        if obj.kind == "layer":
            if obj.data["meta"].get("kind") == "text":
                acts.append(("edit_layer", tr("تعديل النص"), "Primary"))
            acts += [("hide_layer", tr("إخفاء"), None), ("flatten_layer", tr("دمج في الصفحة"), None),
                     ("delete", tr("حذف"), "Danger")]
        elif obj.kind == "image":
            acts = [("delete", tr("حذف"), "Danger"), ("delete_all", tr("حذف من كل الصفحات"), None),
                    ("replace", tr("استبدال"), None), ("save", tr("حفظ الصورة"), None)]
        elif obj.kind in ("annot", "drawing"):
            acts = [("delete", tr("حذف"), "Danger")]
        elif obj.kind in ("line", "block"):
            acts = [("edit", tr("تعديل النص"), "Primary"), ("delete", tr("حذف"), "Danger")]
        self.bar.set_actions(acts)
        self.bar.show()
        self._position_bar()
        self.selectionChanged.emit(obj)

    def clear_selection(self):
        if self.sel_obj is not None or self._sel.isVisible():
            self.select(None)

    def _on_bar(self, key):
        if self._place.isVisible():
            if key == "apply":
                self.commit_place(False)
            elif key == "apply_all":
                self.commit_place(True)
            elif key == "cancel":
                self.cancel_place()
            return
        if self.sel_obj is not None:
            self.floatAction.emit(key, self.sel_obj)

    def _position_bar(self):
        if not self.bar.isVisible():
            return
        frame = self._place if self._place.isVisible() else self._sel
        if not frame.isVisible():
            self.bar.hide()
            return
        r = self.mapFromScene(frame.rect).boundingRect()
        self.bar.adjustSize()
        x = r.center().x() - self.bar.width() // 2
        y = r.bottom() + 10
        if y + self.bar.height() > self.viewport().height() - 4:
            y = r.top() - self.bar.height() - 10
        x = max(4, min(x, self.viewport().width() - self.bar.width() - 4))
        y = max(4, min(y, self.viewport().height() - self.bar.height() - 4))
        self.bar.move(int(x), int(y))
        self.bar.raise_()

    # ------------------------------------------------------------------ search hits
    def set_search_hits(self, hits: dict, current=None):
        for it in self._search_items:
            self.scene_.removeItem(it)
        self._search_items.clear()
        for pno, rects in hits.items():
            if pno >= len(self.items_):
                continue
            for r in rects:
                it = QGraphicsRectItem(self.to_scene(pno, r))
                cur = current is not None and current[0] == pno and current[1] == r
                c = QColor("#f97316" if cur else "#facc15")
                c.setAlpha(110 if cur else 80)
                it.setBrush(c)
                it.setPen(Qt.NoPen)
                it.setZValue(40)
                self.scene_.addItem(it)
                self._search_items.append(it)

    # ------------------------------------------------------------------ placing images / stamps
    def start_place(self, img: QImage, width_pt: float | None = None):
        self.cancel_place(emit=False)
        self.clear_selection()
        if not self.items_:
            return
        self.place_img = img
        pno = self.current_page()
        it = self.items_[pno]
        w = width_pt or min(it.w * 0.3, img.width() * 0.75)
        h = w * img.height() / max(1, img.width())
        self._place_aspect = img.width() / max(1, img.height())
        vis = self.mapToScene(self.viewport().rect()).boundingRect() & it.sceneBoundingRect()
        c = vis.center() if not vis.isEmpty() else it.sceneBoundingRect().center()
        self._place.pix = QPixmap.fromImage(img)
        self._place.set_rect(QRectF(c.x() - w / 2, c.y() - h / 2, w, h))
        self._place.show()
        self.bar.set_actions([("apply", tr("تطبيق"), "Primary"), ("apply_all", tr("تطبيق على كل الصفحات"), None),
                              ("cancel", tr("إلغاء"), None)])
        self.bar.show()
        self._position_bar()
        self.viewport().setCursor(Qt.SizeAllCursor)

    def update_place_image(self, img: QImage):
        if not self._place.isVisible():
            return
        r = self._place.rect
        self.place_img = img
        self._place.pix = QPixmap.fromImage(img)
        self._place_aspect = img.width() / max(1, img.height())
        h = r.width() / self._place_aspect
        self._place.set_rect(QRectF(r.center().x() - r.width() / 2, r.center().y() - h / 2, r.width(), h))
        self._position_bar()

    def placing(self) -> bool:
        return self._place.isVisible()

    def commit_place(self, all_pages=False):
        if not self._place.isVisible():
            return
        r = self._place.rect
        pno, _ = self.page_at(r.center(), strict=False)
        local = r.translated(-self.items_[pno].pos())
        img = self.place_img
        self.cancel_place(emit=False)
        self.placeCommitted.emit(pno, local, img, all_pages)

    def cancel_place(self, emit=True):
        was = self._place.isVisible()
        self._place.hide()
        self._place.pix = None
        self.place_img = None
        if self.bar.isVisible() and not self._sel.isVisible():
            self.bar.hide()
        self.set_tool(self.tool)
        if emit and was:
            self.placeCancelled.emit()

    # ------------------------------------------------------------------ mouse
    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self.zoom * f, mouse_anchor=True)
            e.accept()
            return
        super().wheelEvent(e)

    def mousePressEvent(self, e):
        if not self.items_:
            return super().mousePressEvent(e)
        sp = self.mapToScene(e.position().toPoint())
        scale = self.zoom
        # --- placing stamp/image has priority
        if self._place.isVisible() and e.button() == Qt.LeftButton:
            h = self._place.handle_at(sp, scale)
            if h >= 0:
                self._drag = ("place_resize", h, QRectF(self._place.rect), sp)
            elif self._place.rect.contains(sp):
                self._drag = ("place_move", -1, QRectF(self._place.rect), sp)
            else:  # click elsewhere: move stamp there
                r = self._place.rect
                self._place.set_rect(r.translated(sp - r.center()))
                self._position_bar()
                self._drag = ("place_move", -1, QRectF(self._place.rect), sp)
            return
        if self.tool == Tool.HAND or e.button() == Qt.MiddleButton:
            return super().mousePressEvent(e)
        pno, lp = self.page_at(sp)
        if e.button() == Qt.RightButton and self.read_only:
            self.contextRequested.emit(None, e.globalPosition().toPoint())
            return
        if e.button() == Qt.RightButton:
            obj = self.sel_obj
            if pno >= 0:
                o, r = self.pick(pno, lp, "select")
                if o is None:
                    o, r = self.pick(pno, lp, "text")
                if o is not None:
                    self.select(o, r)
                    obj = o
            self.contextRequested.emit(obj, e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        t = self.tool
        if t == Tool.SELECT:
            if self.sel_obj is not None and self._sel.isVisible():
                h = self._sel.handle_at(sp, scale)
                if h >= 0:
                    self._drag = ("resize", h, QRectF(self._sel.rect), sp)
                    return
                if self.sel_obj.kind in MOVABLE and self._sel.rect.contains(sp):
                    self._drag = ("move", -1, QRectF(self._sel.rect), sp)
                    return
            if pno < 0:
                self.clear_selection()
                return
            o, r = self.pick(pno, lp, "select")
            if o is not None and o.kind == "scan":
                self.clear_selection()
                self._hover.hide()
                self._hover_obj = None
                self.scanPicked.emit(pno, r)
                return
            if o is None:  # empty spot: drag a box to cut anything out of a scan
                self.clear_selection()
                self._band_page, self._band_start = pno, lp
                self._band = QGraphicsRectItem()
                pen = QPen(QColor("#ec4899"), 1.5)
                pen.setCosmetic(True)
                pen.setStyle(Qt.DashLine)
                self._band.setPen(pen)
                self._band.setBrush(QColor(236, 72, 153, 35))
                self._band.setZValue(70)
                self.scene_.addItem(self._band)
                self._band.setRect(self.to_scene(pno, QRectF(lp, lp)))
                return
            self.select(o, r)
            if o.kind in MOVABLE:
                self._drag = ("move", -1, QRectF(self._sel.rect), sp)
            return
        if pno < 0:
            return
        if t == Tool.ADD_TEXT:
            self.addTextRequested.emit(pno, lp)
        elif t == Tool.NOTE:
            self.noteRequested.emit(pno, lp)
        elif t in AREA_TOOLS:
            self._band_page, self._band_start = pno, lp
            self._band = QGraphicsRectItem()
            if t == Tool.TEXT:
                self.set_text_selection(0, [])
            c = QColor({Tool.ERASE: "#ef4444", Tool.INK: "#0ea5e9", Tool.TEXT: "#3b82f6", Tool.EXTRACT: "#8b5cf6",
                     Tool.EDIT_TEXT: "#5b8cff"}.get(t, self.ann_color.name()))
            pen = QPen(c, 1.5)
            pen.setCosmetic(True)
            pen.setStyle(Qt.DashLine)
            fill = QColor(c)
            fill.setAlpha(40)
            self._band.setPen(pen)
            self._band.setBrush(fill)
            self._band.setZValue(70)
            self.scene_.addItem(self._band)
            self._band.setRect(self.to_scene(pno, QRectF(lp, lp)))
        elif t in (Tool.LINE, Tool.ARROW):
            self._band_page, self._band_start = pno, lp
            self._line = QGraphicsLineItem()
            pen = QPen(self.ann_color, 2)
            pen.setCosmetic(True)
            self._line.setPen(pen)
            self._line.setZValue(70)
            self.scene_.addItem(self._line)
        elif t == Tool.PEN:
            self._band_page = pno
            self._path_pts = [lp]
            self._path_item = QGraphicsPathItem()
            pen = QPen(self.ann_color, 2)
            pen.setCosmetic(True)
            pen.setCapStyle(Qt.RoundCap)
            self._path_item.setPen(pen)
            self._path_item.setZValue(70)
            self.scene_.addItem(self._path_item)

    def _clamp_to_page(self, pno, lp: QPointF) -> QPointF:
        it = self.items_[pno]
        return QPointF(max(0, min(it.w, lp.x())), max(0, min(it.h, lp.y())))

    def paste_target(self):
        """Where Ctrl+V puts things: under the mouse if it is over a page, else the middle of the view."""
        if self.last_mouse is not None and self.viewport().rect().contains(self.viewport().mapFromGlobal(QCursor.pos())):
            return self.last_mouse
        c = self.mapToScene(self.viewport().rect().center())
        pno, lp = self.page_at(c, strict=False)
        it = self.items_[pno]
        return pno, QPointF(max(20, min(it.w - 20, lp.x())), max(20, min(it.h - 20, lp.y())))

    def mouseMoveEvent(self, e):
        if not self.items_:
            return super().mouseMoveEvent(e)
        sp = self.mapToScene(e.position().toPoint())
        _p, _lp = self.page_at(sp)
        if _p >= 0:
            self.last_mouse = (_p, _lp)
        if self._drag:
            kind, h, orig, start = self._drag
            d = sp - start
            frame = self._place if kind.startswith("place") else self._sel
            if kind.endswith("move"):
                frame.set_rect(orig.translated(d))
            elif h >= 4:  # side handle: stretch width or height only
                r = QRectF(orig)
                if h == 4:
                    r.setTop(min(sp.y(), orig.bottom() - 6))
                elif h == 5:
                    r.setRight(max(sp.x(), orig.left() + 6))
                elif h == 6:
                    r.setBottom(max(sp.y(), orig.top() + 6))
                else:
                    r.setLeft(min(sp.x(), orig.right() - 6))
                frame.set_rect(r)
                if kind.startswith("place"):
                    self._place_aspect = r.width() / max(1e-6, r.height())
            else:  # corner: keep proportions (Shift = free)
                aspect = self._place_aspect if kind.startswith("place") else orig.width() / max(1e-6, orig.height())
                anchor = _corners(orig)[(h + 2) % 4]
                cx = sp.x()
                w = max(8.0, abs(cx - anchor.x()))
                hh = w / aspect
                if e.modifiers() & Qt.ShiftModifier:
                    hh = max(8.0, abs(sp.y() - anchor.y()))
                x0 = anchor.x() - w if cx < anchor.x() else anchor.x()
                y0 = anchor.y() - hh if sp.y() < anchor.y() else anchor.y()
                frame.set_rect(QRectF(x0, y0, w, hh))
            self._position_bar()
            return
        if self._band is not None:
            lp = self._clamp_to_page(self._band_page, sp - self.items_[self._band_page].pos())
            self._band.setRect(self.to_scene(self._band_page, QRectF(self._band_start, lp).normalized()))
            return
        if self._line is not None:
            a = self.items_[self._band_page].pos() + self._band_start
            self._line.setLine(a.x(), a.y(), sp.x(), sp.y())
            return
        if self._path_item is not None:
            lp = self._clamp_to_page(self._band_page, sp - self.items_[self._band_page].pos())
            self._path_pts.append(lp)
            path = QPainterPath(self.items_[self._band_page].pos() + self._path_pts[0])
            for p in self._path_pts[1:]:
                path.lineTo(self.items_[self._band_page].pos() + p)
            self._path_item.setPath(path)
            return
        if self._place.isVisible():
            h = self._place.handle_at(sp, self.zoom)
            self.viewport().setCursor(_handle_cursor(h) if h >= 0
                                      else Qt.SizeAllCursor)
            return
        if self.tool in (Tool.SELECT, Tool.EDIT_TEXT):
            pno, lp = self.page_at(sp)
            if pno < 0:
                self._show_hover(-1, None, None)
            else:
                if self.tool == Tool.SELECT:
                    if self.sel_obj is not None and self._sel.isVisible():
                        h = self._sel.handle_at(sp, self.zoom)
                        if h >= 0:
                            self.viewport().setCursor(_handle_cursor(h))
                            return
                    o, r = self.pick(pno, lp, "select")
                    if o is None:
                        o, r = self.pick(pno, lp, "text")
                    self.viewport().setCursor(Qt.SizeAllCursor if o is not None and o.kind in MOVABLE
                                              else Qt.PointingHandCursor if o is not None else Qt.ArrowCursor)
                else:
                    o, r = self.pick(pno, lp, "text")
                self._show_hover(pno, o, r)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag:
            kind, h, orig, start = self._drag
            self._drag = None
            if kind.startswith("place"):
                return
            new = QRectF(self._sel.rect)
            if self.sel_obj is not None and (abs(new.x() - orig.x()) > 0.5 or abs(new.y() - orig.y()) > 0.5
                                             or abs(new.width() - orig.width()) > 0.5):
                pno = self.sel_obj.pno
                self.moveRequested.emit(self.sel_obj, new.translated(-self.items_[pno].pos()))
            return
        if self._band is not None:
            self.band_shift = bool(e.modifiers() & Qt.ShiftModifier)
            r = self._band.rect().translated(-self.items_[self._band_page].pos())
            self.scene_.removeItem(self._band)
            self._band = None
            if self.tool == Tool.EDIT_TEXT and r.width() * r.height() < 60:  # a click: edit that line
                self.last_click = (self._band_page, QPointF(self._band_start))
                o, rr = self.pick(self._band_page, self._band_start, "text")
                if o is not None:
                    self.select(o, rr)
                    self.editTextRequested.emit(o)
                else:  # no recognised text here: let the window look at the ink under the click
                    p = self._band_start
                    self.areaSelected.emit(self.tool, self._band_page, QRectF(p.x() - 1, p.y() - 1, 2, 2))
                return
            if (r.width() > 3 and r.height() > 3) and not (self.tool == Tool.SELECT and r.width() * r.height() < 120):
                self.areaSelected.emit(self.tool, self._band_page, r)
            return
        if self._line is not None:
            ln = self._line.line()
            self.scene_.removeItem(self._line)
            self._line = None
            off = self.items_[self._band_page].pos()
            a, b = QPointF(ln.x1(), ln.y1()) - off, QPointF(ln.x2(), ln.y2()) - off
            if (a - b).manhattanLength() > 4:
                self.lineDrawn.emit(self.tool, self._band_page, a, b)
            return
        if self._path_item is not None:
            self.scene_.removeItem(self._path_item)
            self._path_item = None
            if len(self._path_pts) > 2:
                self.inkDrawn.emit(self._band_page, list(self._path_pts))
            self._path_pts = []
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self._place.isVisible():
            self.commit_place(False)
            return
        if self.tool in (Tool.SELECT, Tool.EDIT_TEXT) and self.items_ and not self.read_only:
            sp = self.mapToScene(e.position().toPoint())
            pno, lp = self.page_at(sp)
            if pno >= 0:
                o, r = self.pick(pno, lp, "text")
                if o is not None:
                    self.select(o, r)
                    self.editTextRequested.emit(o)
                    return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        if self._place.isVisible():
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.commit_place(False)
                return
            if k == Qt.Key_Escape:
                self.cancel_place()
                return
        if k == Qt.Key_Delete and self.sel_obj is not None:
            self.floatAction.emit("delete", self.sel_obj)
            return
        if k == Qt.Key_Escape:
            if self.sel_obj is not None or self._textsel_items:
                self.clear_selection()
                self.set_text_selection(0, [])
                return
            e.ignore()  # let the window handle it (e.g. leave full screen)
            return
        if self.items_ and not e.modifiers() & Qt.ControlModifier:
            cur = self.current_page()
            target = {Qt.Key_PageDown: cur + 1, Qt.Key_PageUp: cur - 1, Qt.Key_Home: 0,
                      Qt.Key_End: len(self.items_) - 1}.get(k)
            if target is not None:
                self.go_to_page(max(0, min(target, len(self.items_) - 1)))
                return
        super().keyPressEvent(e)

    def leaveEvent(self, e):
        self._show_hover(-1, None, None)
        super().leaveEvent(e)

    # ------------------------------------------------------------------ drag & drop files
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if files:
            self.filesDropped.emit(files)
