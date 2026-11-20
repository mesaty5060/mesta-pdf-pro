"""Stamps (أختام), signatures and image import with background removal."""
from __future__ import annotations

import math
import os
import random
import time

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QDate, QIODevice, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QIcon, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QTransform)
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDateEdit, QDialog, QFileDialog,
                               QFontComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget, QListView)
from .i18n import tr

from .brand import DATA_DIR as APPDIR, data_dir as _data_dir
LIB_DIRS = {"stamp": _data_dir("stamps"), "signature": _data_dir("signatures")}

INK_COLORS = [(tr("أزرق"), "#1d3fbf"), (tr("أحمر"), "#c8102e"), (tr("أخضر"), "#0f7b3b"), (tr("بنفسجي"), "#6b21a8"),
              (tr("أسود"), "#111111")]


# =========================================================================== image utils
def qimage_to_png(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def _to_array(img: QImage):
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl // 4, 4)[:, :w].copy()
    return arr  # B, G, R, A


def _from_array(arr) -> QImage:
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    img = QImage(arr.data, w, h, w * 4, QImage.Format_ARGB32)
    return img.copy()


def trim(img: QImage, pad=6) -> QImage:
    arr = _to_array(img)
    ys, xs = np.nonzero(arr[:, :, 3] > 8)
    if len(xs) == 0:
        return img
    x0, x1 = max(0, xs.min() - pad), min(arr.shape[1], xs.max() + pad + 1)
    y0, y1 = max(0, ys.min() - pad), min(arr.shape[0], ys.max() + pad + 1)
    return img.copy(int(x0), int(y0), int(x1 - x0), int(y1 - y0))


def remove_background(img: QImage, threshold=200, recolor: QColor | None = None) -> QImage:
    """Make paper (light) pixels transparent with soft edges. Perfect for scanned stamps/signatures."""
    arr = _to_array(img).astype(np.float32)
    b, g, r, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    chroma = np.max(arr[..., :3], axis=2) - np.min(arr[..., :3], axis=2)
    lo = max(0.0, threshold - 90.0)
    alpha = np.clip((threshold - lum) / max(1.0, threshold - lo), 0, 1)
    alpha = np.maximum(alpha, np.clip((chroma - 25) / 60.0, 0, 1) * (lum < 235))  # keep coloured ink
    out = arr.copy()
    out[..., 3] = np.minimum(a, alpha * 255)
    if recolor is not None:
        out[..., 0] = recolor.blue()
        out[..., 1] = recolor.green()
        out[..., 2] = recolor.red()
    else:  # deepen remaining ink a little so it doesn't look washed out
        out[..., :3] = np.clip(out[..., :3] * 0.85, 0, 255)
    return trim(_from_array(out.astype(np.uint8)))


def apply_opacity_rotation(img: QImage, opacity=1.0, angle=0.0) -> QImage:
    if abs(angle) > 0.01:
        img = img.transformed(QTransform().rotate(angle), Qt.SmoothTransformation)
    if opacity < 0.999:
        arr = _to_array(img)
        arr[..., 3] = (arr[..., 3].astype(np.float32) * opacity).astype(np.uint8)
        img = _from_array(arr)
    return img


def ink_effect(img: QImage, strength: float, seed=None) -> QImage:
    """Simulate real rubber-stamp ink: uneven pressure + speckles."""
    if strength <= 0:
        return img
    rng = np.random.default_rng(seed)
    arr = _to_array(img)
    h, w = arr.shape[:2]
    cs = max(4, int(min(w, h) / 10))
    coarse = rng.random((h // cs + 2, w // cs + 2)).astype(np.float32)
    big = np.kron(coarse, np.ones((cs, cs), np.float32))[:h, :w]
    k = max(1, cs // 2)
    pad = np.pad(big, k, mode="edge")
    cum = pad.cumsum(0).cumsum(1)
    sm = (cum[2 * k:, 2 * k:] - cum[:-2 * k, 2 * k:] - cum[2 * k:, :-2 * k] + cum[:-2 * k, :-2 * k]) / (4 * k * k)
    sm = sm[:h, :w]
    fine = rng.random((h, w)).astype(np.float32)
    keep = 1.0 - strength * (0.55 * np.clip(sm * 1.6 - 0.45, 0, 1) + 0.6 * (fine > 1 - 0.18 * strength))
    arr[..., 3] = (arr[..., 3].astype(np.float32) * np.clip(keep, 0.15, 1)).astype(np.uint8)
    return _from_array(arr)


def checker_pixmap(img: QImage, size: QSize) -> QPixmap:
    pm = QPixmap(size)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    c = QColor("#e9ebf0")
    s = 10
    for y in range(0, size.height(), s):
        for x in range(0, size.width(), s):
            if (x // s + y // s) % 2:
                p.fillRect(x, y, s, s, c)
    if img is not None and not img.isNull():
        scaled = img.scaled(size * 0.92, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawImage((size.width() - scaled.width()) // 2, (size.height() - scaled.height()) // 2, scaled)
    p.end()
    return pm


# =========================================================================== stamp rendering
def _fit_font(family, text, max_w, start_px, bold=True, min_px=8):
    px = start_px
    while px > min_px:
        f = QFont(family)
        f.setPixelSize(int(px))
        f.setBold(bold)
        if QFontMetricsF(f).horizontalAdvance(text) <= max_w:
            return f
        px -= 1
    f = QFont(family)
    f.setPixelSize(min_px)
    f.setBold(bold)
    return f


def _arc_text_path(text, font, cx, cy, radius, span_deg, top=True) -> QPainterPath:
    path = QPainterPath()
    path.addText(0, 0, font, text)
    br = path.boundingRect()
    if br.width() <= 0:
        return QPainterPath()
    span = math.radians(span_deg)
    # centre the glyph band on `radius`
    mid = (br.top() + br.bottom()) / 2  # negative: middle of glyphs above baseline
    rb = radius + mid if top else radius - mid
    for i in range(path.elementCount()):
        el = path.elementAt(i)
        t = (el.x - br.left()) / br.width()
        if top:
            th = -math.pi / 2 - span / 2 + t * span
            R = rb - el.y
        else:
            th = math.pi / 2 + span / 2 - t * span
            R = rb + el.y
        path.setElementPositionAt(i, cx + R * math.cos(th), cy + R * math.sin(th))
    return path


def _star(cx, cy, r, points=5) -> QPainterPath:
    p = QPainterPath()
    for i in range(points * 2):
        rr = r if i % 2 == 0 else r * 0.45
        a = -math.pi / 2 + i * math.pi / points
        pt = QPointF(cx + rr * math.cos(a), cy + rr * math.sin(a))
        p.moveTo(pt) if i == 0 else p.lineTo(pt)
    p.closeSubpath()
    return p


def render_round_stamp(top="", center="", bottom="", color="#1d3fbf", family="Arial", double=True,
                       stars=True, size=700, oval=False) -> QImage:
    W = size
    H = int(size * (0.68 if oval else 1.0))
    img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    col = QColor(color)
    lw = size * 0.022
    cx, cy = W / 2, H / 2
    # draw everything on a circle, then squash vertically for oval stamps
    if oval:
        p.translate(cx, cy)
        p.scale(1.0, H / W)
        p.translate(-cx, -cx)
        cy = cx
    R = size / 2 - lw
    p.setPen(QPen(col, lw))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy), R, R)
    if double:
        p.setPen(QPen(col, lw * 0.45))
        p.drawEllipse(QPointF(cx, cy), R - lw * 1.6, R - lw * 1.6)
    inner = R * 0.60
    p.setPen(QPen(col, lw * 0.6))
    p.drawEllipse(QPointF(cx, cy), inner, inner)
    band_mid = (R - lw * 2 + inner) / 2
    band = (R - lw * 2) - inner
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    text_px = band * 0.62
    has_bottom = bool(bottom.strip())
    span_top = 230 if not has_bottom else 150
    if top.strip():
        f = _fit_font(family, top, math.radians(span_top) * band_mid, text_px)
        p.drawPath(_arc_text_path(top, f, cx, cy, band_mid, span_top, True))
    if has_bottom:
        f = _fit_font(family, bottom, math.radians(110) * band_mid, text_px * 0.9)
        p.drawPath(_arc_text_path(bottom, f, cx, cy, band_mid, 110, False))
    if stars:
        sr = band * 0.16
        if has_bottom:
            p.drawPath(_star(cx - band_mid, cy, sr))
            p.drawPath(_star(cx + band_mid, cy, sr))
        else:
            p.drawPath(_star(cx, cy + band_mid, sr))
    lines = [ln for ln in center.split("\n") if ln.strip()]
    if lines:
        avail_h = inner * 1.45
        lh = min(avail_h / len(lines), inner * 0.55)
        y = cy - lh * len(lines) / 2
        for ln in lines:
            # width available at this height in the inner circle
            dy = abs(y + lh / 2 - cy)
            half = math.sqrt(max(0.0, inner * inner - dy * dy)) * 0.86
            f = _fit_font(family, ln, half * 2, lh * 0.78)
            path = QPainterPath()
            path.addText(0, 0, f, ln)
            br = path.boundingRect()
            fm = QFontMetricsF(f)
            path.translate(cx - br.center().x(), y + lh / 2 + (fm.ascent() - fm.descent()) / 2)
            p.drawPath(path)
            y += lh
    p.end()
    return img


def render_rect_stamp(text="", color="#c8102e", family="Arial", double=True, rounded=True, size=700) -> QImage:
    lines = [ln for ln in text.split("\n") if ln.strip()] or [" "]
    px = size * 0.11
    fonts = []
    widths = []
    for i, ln in enumerate(lines):
        f = QFont(family)
        f.setPixelSize(int(px * (1.0 if i == 0 else 0.72)))
        f.setBold(True)
        fonts.append(f)
        widths.append(QFontMetricsF(f).horizontalAdvance(ln))
    lw = size * 0.018
    padx, pady = px * 0.8, px * 0.55
    heights = [QFontMetricsF(f).height() * 1.05 for f in fonts]
    W = int(max(widths) + padx * 2 + lw * 4)
    H = int(sum(heights) + pady * 2 + lw * 4)
    img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    col = QColor(color)
    rad = px * 0.35 if rounded else 0
    p.setPen(QPen(col, lw))
    p.drawRoundedRect(QRectF(lw, lw, W - 2 * lw, H - 2 * lw), rad, rad)
    if double:
        p.setPen(QPen(col, lw * 0.45))
        o = lw * 2.3
        p.drawRoundedRect(QRectF(o, o, W - 2 * o, H - 2 * o), rad * 0.7, rad * 0.7)
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    y = lw * 2 + pady
    for ln, f, h in zip(lines, fonts, heights):
        path = QPainterPath()
        path.addText(0, 0, f, ln)
        br = path.boundingRect()
        fm = QFontMetricsF(f)
        path.translate(W / 2 - br.center().x(), y + (h + fm.ascent() - fm.descent()) / 2)
        p.drawPath(path)
        y += h
    p.end()
    return img


# =========================================================================== library
def library_items(kind="stamp"):
    d = LIB_DIRS[kind]
    files = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".png")]
    return sorted(files, key=os.path.getmtime, reverse=True)


def save_to_library(img: QImage, kind="stamp") -> str:
    path = os.path.join(LIB_DIRS[kind], f"{kind}_{int(time.time() * 1000)}.png")
    img.save(path, "PNG")
    return path


class LibraryList(QListWidget):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.setViewMode(QListView.IconMode)
        self.setIconSize(QSize(130, 110))
        self.setGridSize(QSize(150, 135))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSpacing(6)
        self.refresh()

    def refresh(self):
        self.clear()
        for path in library_items(self.kind):
            img = QImage(path)
            it = QListWidgetItem(QIcon(checker_pixmap(img, QSize(130, 110))), "")
            it.setData(Qt.UserRole, path)
            it.setToolTip(os.path.basename(path))
            self.addItem(it)

    def current_image(self):
        it = self.currentItem()
        return QImage(it.data(Qt.UserRole)) if it else None

    def delete_current(self):
        it = self.currentItem()
        if it:
            try:
                os.remove(it.data(Qt.UserRole))
            except OSError:
                pass
            self.refresh()


# =========================================================================== dialogs
class ColorButton(QPushButton):
    changed = Signal(QColor)

    def __init__(self, color="#1d3fbf"):
        super().__init__()
        self.color = QColor(color)
        self.setFixedWidth(46)
        self.clicked.connect(self._pick)
        self._paint()

    def _paint(self):
        self.setStyleSheet(f"background:{self.color.name()}; border-radius:6px; min-height:22px;")

    def set_color(self, c):
        self.color = QColor(c)
        self._paint()
        self.changed.emit(self.color)

    def _pick(self):
        c = QColorDialog.getColor(self.color, self, tr("اختر اللون"))
        if c.isValid():
            self.set_color(c)


def color_row(btn: ColorButton) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    h.addWidget(btn)
    for name, hexc in INK_COLORS:
        b = QPushButton()
        b.setToolTip(name)
        b.setFixedSize(22, 22)
        b.setStyleSheet(f"background:{hexc}; border-radius:11px; padding:0; border:2px solid rgba(255,255,255,.4);")
        b.clicked.connect(lambda _=False, c=hexc: btn.set_color(c))
        h.addWidget(b)
    h.addStretch(1)
    from PySide6.QtWidgets import QSizePolicy
    w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return w


class ImageImportDialog(QDialog):
    """Load an image, optionally remove the paper background and recolour it."""

    def __init__(self, parent, path, kind="stamp", remove_bg=True):
        super().__init__(parent)
        self.setWindowTitle(tr("استيراد صورة"))
        self.kind = kind
        self.src = QImage(path)
        if self.src.width() > 1600 or self.src.height() > 1600:
            self.src = self.src.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.result_image = None
        lay = QVBoxLayout(self)
        self.preview = QLabel()
        self.preview.setFixedSize(460, 320)
        self.preview.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.preview, 0, Qt.AlignCenter)
        form = QFormLayout()
        self.chk_bg = QCheckBox(tr("إزالة خلفية الورقة (جعلها شفافة)"))
        self.chk_bg.setChecked(remove_bg)
        self.sl = QSlider(Qt.Horizontal)
        self.sl.setRange(120, 250)
        self.sl.setValue(205)
        self.chk_color = QCheckBox(tr("توحيد لون الحبر"))
        self.btn_color = ColorButton("#1d3fbf" if kind == "stamp" else "#111111")
        form.addRow(self.chk_bg)
        form.addRow(tr("درجة الإزالة"), self.sl)
        form.addRow(self.chk_color, color_row(self.btn_color))
        lay.addLayout(form)
        btns = QHBoxLayout()
        self.b_save = QPushButton(tr("حفظ في المكتبة + استخدام"))
        self.b_save.setObjectName("Primary")
        b_use = QPushButton(tr("استخدام فقط"))
        b_cancel = QPushButton(tr("إلغاء"))
        btns.addWidget(self.b_save)
        btns.addWidget(b_use)
        btns.addStretch(1)
        btns.addWidget(b_cancel)
        lay.addLayout(btns)
        if kind == "image":
            self.b_save.hide()
        for w in (self.chk_bg, self.chk_color):
            w.toggled.connect(self.update_preview)
        self.sl.valueChanged.connect(self.update_preview)
        self.btn_color.changed.connect(self.update_preview)
        self.b_save.clicked.connect(lambda: self._finish(True))
        b_use.clicked.connect(lambda: self._finish(False))
        b_cancel.clicked.connect(self.reject)
        self.update_preview()

    def processed(self) -> QImage:
        if self.chk_bg.isChecked():
            return remove_background(self.src, self.sl.value(),
                                     self.btn_color.color if self.chk_color.isChecked() else None)
        img = self.src.convertToFormat(QImage.Format_ARGB32)
        if self.chk_color.isChecked():
            arr = _to_array(img)
            c = self.btn_color.color
            arr[..., 0], arr[..., 1], arr[..., 2] = c.blue(), c.green(), c.red()
            img = _from_array(arr)
        return img

    def update_preview(self):
        self.preview.setPixmap(checker_pixmap(self.processed(), self.preview.size()))

    def _finish(self, save):
        self.result_image = self.processed()
        if save:
            save_to_library(self.result_image, self.kind)
        self.accept()


class StampDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("الأختام"))
        self.resize(860, 600)
        self.result_image: QImage | None = None
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        # ---- library tab
        lib = QWidget()
        ll = QVBoxLayout(lib)
        self.lib = LibraryList("stamp")
        self.lib.itemDoubleClicked.connect(lambda _: self._use_library())
        ll.addWidget(self.lib)
        row = QHBoxLayout()
        b_use = QPushButton(tr("استخدام الختم المحدد"))
        b_use.setObjectName("Primary")
        b_imp = QPushButton(tr("استيراد ختم من صورة / سكانر…"))
        b_del = QPushButton(tr("حذف من المكتبة"))
        b_del.setObjectName("Danger")
        row.addWidget(b_use)
        row.addWidget(b_imp)
        row.addStretch(1)
        row.addWidget(b_del)
        ll.addLayout(row)
        hint = QLabel(tr("نصيحة: صوّر الختم الحقيقي على ورقة بيضاء ثم استورده — البرنامج يزيل الخلفية تلقائياً."))
        hint.setObjectName("Hint")
        ll.addWidget(hint)
        b_use.clicked.connect(self._use_library)
        b_imp.clicked.connect(self._import)
        b_del.clicked.connect(self.lib.delete_current)
        self.tabs.addTab(lib, tr("مكتبة الأختام"))

        # ---- designer tab
        des = QWidget()
        dl = QHBoxLayout(des)
        form = QFormLayout()
        self.cb_type = QComboBox()
        self.cb_type.addItems([tr("ختم دائري"), tr("ختم بيضاوي"), tr("ختم مستطيل")])
        self.ed_top = QLineEdit(tr("شركة النيل للتجارة والمقاولات"))
        self.ed_center = QPlainTextEdit(tr("معتمد\nAPPROVED"))
        self.ed_center.setFixedHeight(70)
        self.ed_bottom = QLineEdit(tr("القاهرة - ج.م.ع"))
        self.chk_date = QCheckBox(tr("إضافة التاريخ"))
        self.date = QDateEdit(QDate.currentDate())
        self.date.setDisplayFormat("yyyy/MM/dd")
        self.date.setCalendarPopup(True)
        self.btn_color = ColorButton("#1d3fbf")
        self.font_cb = QFontComboBox()
        self.font_cb.setCurrentFont(QFont("Arial"))
        self.chk_double = QCheckBox(tr("إطار مزدوج"))
        self.chk_double.setChecked(True)
        self.chk_stars = QCheckBox(tr("نجوم زخرفية"))
        self.chk_stars.setChecked(True)
        self.sl_ink = QSlider(Qt.Horizontal)
        self.sl_ink.setRange(0, 100)
        self.sl_ink.setValue(25)
        self.sl_rot = QSlider(Qt.Horizontal)
        self.sl_rot.setRange(-30, 30)
        self.sl_rot.setValue(-8)
        form.addRow(tr("النوع"), self.cb_type)
        form.addRow(tr("النص العلوي"), self.ed_top)
        form.addRow(tr("نص المنتصف"), self.ed_center)
        form.addRow(tr("النص السفلي"), self.ed_bottom)
        dr = QHBoxLayout()
        dr.addWidget(self.chk_date)
        dr.addWidget(self.date)
        form.addRow(dr)
        form.addRow(tr("اللون"), color_row(self.btn_color))
        form.addRow(tr("الخط"), self.font_cb)
        opts = QHBoxLayout()
        opts.addWidget(self.chk_double)
        opts.addWidget(self.chk_stars)
        form.addRow(opts)
        form.addRow(tr("تأثير الحبر الحقيقي"), self.sl_ink)
        form.addRow(tr("ميل الختم"), self.sl_rot)
        fw = QWidget()
        fw.setLayout(form)
        fw.setMaximumWidth(420)
        dl.addWidget(fw)
        right = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(380, 380)
        self.preview.setAlignment(Qt.AlignCenter)
        right.addWidget(self.preview, 0, Qt.AlignCenter)
        rb = QHBoxLayout()
        b_now = QPushButton(tr("استخدام الآن"))
        b_now.setObjectName("Primary")
        b_save = QPushButton(tr("حفظ في المكتبة"))
        rb.addWidget(b_now)
        rb.addWidget(b_save)
        right.addLayout(rb)
        right.addStretch(1)
        dl.addLayout(right)
        self.tabs.addTab(des, tr("تصميم ختم جديد"))
        b_now.clicked.connect(self._use_design)
        b_save.clicked.connect(self._save_design)
        for w in (self.ed_top, self.ed_bottom):
            w.textChanged.connect(self.update_preview)
        self.ed_center.textChanged.connect(self.update_preview)
        for w in (self.chk_date, self.chk_double, self.chk_stars):
            w.toggled.connect(self.update_preview)
        self.date.dateChanged.connect(self.update_preview)
        self.cb_type.currentIndexChanged.connect(self.update_preview)
        self.font_cb.currentFontChanged.connect(self.update_preview)
        self.btn_color.changed.connect(self.update_preview)
        self.sl_ink.valueChanged.connect(self.update_preview)
        self.sl_rot.valueChanged.connect(self.update_preview)
        self._seed = random.randint(0, 10 ** 6)
        if self.lib.count() == 0:
            self.tabs.setCurrentIndex(1)
        self.update_preview()

    def design_image(self, size=700) -> QImage:
        center = self.ed_center.toPlainText()
        if self.chk_date.isChecked():
            center = (center + "\n" + self.date.date().toString("yyyy/MM/dd")).strip()
        fam = self.font_cb.currentFont().family()
        col = self.btn_color.color.name()
        t = self.cb_type.currentIndex()
        if t == 2:
            txt = "\n".join(x for x in [self.ed_top.text(), center, self.ed_bottom.text()] if x.strip())
            img = render_rect_stamp(txt, col, fam, self.chk_double.isChecked(), True, size)
        else:
            img = render_round_stamp(self.ed_top.text(), center, self.ed_bottom.text(), col, fam,
                                     self.chk_double.isChecked(), self.chk_stars.isChecked(), size, oval=(t == 1))
        img = ink_effect(img, self.sl_ink.value() / 100.0, self._seed)
        img = apply_opacity_rotation(img, 1.0, self.sl_rot.value())
        return trim(img, 2)

    def update_preview(self):
        self.preview.setPixmap(checker_pixmap(self.design_image(420), self.preview.size()))

    def _use_design(self):
        self.result_image = self.design_image()
        self.accept()

    def _save_design(self):
        save_to_library(self.design_image(), "stamp")
        self.lib.refresh()
        QMessageBox.information(self, tr("تم"), tr("تم حفظ الختم في المكتبة."))

    def _use_library(self):
        img = self.lib.current_image()
        if img is None:
            QMessageBox.information(self, tr("الأختام"), tr("اختر ختماً من المكتبة أولاً."))
            return
        self.result_image = img
        self.accept()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("اختر صورة الختم"), "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)")
        if not path:
            return
        d = ImageImportDialog(self, path, "stamp")
        if d.exec():
            self.lib.refresh()
            self.result_image = d.result_image
            self.accept()


class SignaturePad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 220)
        self.strokes: list[list[QPointF]] = []
        self.color = QColor("#0b1f66")
        self.width_ = 3.2
        self.setCursor(Qt.CrossCursor)

    def clear(self):
        self.strokes = []
        self.update()

    def mousePressEvent(self, e):
        self.strokes.append([e.position()])
        self.update()

    def mouseMoveEvent(self, e):
        if self.strokes and e.buttons() & Qt.LeftButton:
            self.strokes[-1].append(e.position())
            self.update()

    def _paint(self, p: QPainter, scale=1.0):
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self.color, self.width_ * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for s in self.strokes:
            pts = [QPointF(pt.x() * scale, pt.y() * scale) for pt in s]
            if len(pts) == 1:
                p.drawPoint(pts[0])
                continue
            path = QPainterPath(pts[0])
            for i in range(1, len(pts) - 1):
                mid = (pts[i] + pts[i + 1]) / 2
                path.quadTo(pts[i], mid)
            path.lineTo(pts[-1])
            p.drawPath(path)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ffffff"))
        p.setPen(QPen(QColor("#c9ced8"), 1, Qt.DashLine))
        y = int(self.height() * 0.75)
        p.drawLine(30, y, self.width() - 30, y)
        self._paint(p)
        p.end()

    def image(self) -> QImage | None:
        if not self.strokes:
            return None
        s = 3.0
        img = QImage(int(self.width() * s), int(self.height() * s), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        self._paint(p, s)
        p.end()
        return trim(img, 8)


class SignatureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("التوقيع"))
        self.resize(720, 470)
        self.result_image = None
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        # draw
        dw = QWidget()
        dl = QVBoxLayout(dw)
        self.pad = SignaturePad()
        dl.addWidget(self.pad)
        row = QHBoxLayout()
        self.btn_color = ColorButton("#0b1f66")
        self.btn_color.changed.connect(lambda c: (setattr(self.pad, "color", c), self.pad.update()))
        row.addWidget(QLabel(tr("اللون")))
        row.addWidget(color_row(self.btn_color))
        self.sp_w = QSlider(Qt.Horizontal)
        self.sp_w.setRange(10, 80)
        self.sp_w.setValue(32)
        self.sp_w.valueChanged.connect(lambda v: (setattr(self.pad, "width_", v / 10), self.pad.update()))
        row.addWidget(QLabel(tr("السُمك")))
        row.addWidget(self.sp_w)
        b_clear = QPushButton(tr("مسح"))
        b_clear.clicked.connect(self.pad.clear)
        row.addWidget(b_clear)
        dl.addLayout(row)
        self.tabs.addTab(dw, tr("ارسم توقيعك"))
        # type
        tw = QWidget()
        tl = QFormLayout(tw)
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText(tr("اكتب اسمك"))
        self.cb_font = QComboBox()
        for f in ["Segoe Script", "Lucida Handwriting", "Ink Free", "Brush Script MT", "Mistral", "Freestyle Script",
                  "Monotype Corsiva", "Arial"]:
            self.cb_font.addItem(f)
        self.typed_prev = QLabel()
        self.typed_prev.setFixedSize(560, 160)
        self.typed_prev.setAlignment(Qt.AlignCenter)
        tl.addRow(tr("الاسم"), self.ed_name)
        tl.addRow(tr("الخط"), self.cb_font)
        tl.addRow(self.typed_prev)
        self.ed_name.textChanged.connect(self._typed_preview)
        self.cb_font.currentIndexChanged.connect(self._typed_preview)
        self.tabs.addTab(tw, tr("اكتب"))
        # library
        lw = QWidget()
        ll = QVBoxLayout(lw)
        self.lib = LibraryList("signature")
        self.lib.itemDoubleClicked.connect(lambda _: self._use())
        ll.addWidget(self.lib)
        lr = QHBoxLayout()
        b_imp = QPushButton(tr("استيراد توقيع من صورة…"))
        b_del = QPushButton(tr("حذف"))
        b_del.setObjectName("Danger")
        lr.addWidget(b_imp)
        lr.addStretch(1)
        lr.addWidget(b_del)
        ll.addLayout(lr)
        b_imp.clicked.connect(self._import)
        b_del.clicked.connect(self.lib.delete_current)
        self.tabs.addTab(lw, tr("توقيعاتي المحفوظة"))
        # buttons
        br = QHBoxLayout()
        b_use = QPushButton(tr("استخدام"))
        b_use.setObjectName("Primary")
        b_save = QPushButton(tr("حفظ + استخدام"))
        b_cancel = QPushButton(tr("إلغاء"))
        br.addWidget(b_use)
        br.addWidget(b_save)
        br.addStretch(1)
        br.addWidget(b_cancel)
        lay.addLayout(br)
        b_use.clicked.connect(self._use)
        b_save.clicked.connect(lambda: self._use(save=True))
        b_cancel.clicked.connect(self.reject)
        if self.lib.count():
            self.tabs.setCurrentIndex(2)
        self._typed_preview()

    def _typed_image(self):
        name = self.ed_name.text().strip()
        if not name:
            return None
        f = QFont(self.cb_font.currentText())
        f.setPixelSize(140)
        fm = QFontMetricsF(f)
        w, h = int(fm.horizontalAdvance(name) + 60), int(fm.height() + 40)
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(f)
        p.setPen(self.btn_color.color)
        p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, name)
        p.end()
        return trim(img)

    def _typed_preview(self):
        self.typed_prev.setPixmap(checker_pixmap(self._typed_image(), self.typed_prev.size()))

    def _current(self):
        i = self.tabs.currentIndex()
        if i == 0:
            return self.pad.image()
        if i == 1:
            return self._typed_image()
        return self.lib.current_image()

    def _use(self, save=False):
        img = self._current()
        if img is None or img.isNull():
            QMessageBox.information(self, tr("التوقيع"), tr("ارسم أو اكتب أو اختر توقيعاً أولاً."))
            return
        if save and self.tabs.currentIndex() != 2:
            save_to_library(img, "signature")
        self.result_image = img
        self.accept()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("اختر صورة التوقيع"), "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)")
        if not path:
            return
        d = ImageImportDialog(self, path, "signature")
        if d.exec():
            self.lib.refresh()
            self.result_image = d.result_image
            self.accept()
