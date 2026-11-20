"""Dialogs and small widgets."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFontComboBox,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QRadioButton, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget, QButtonGroup)

from .engine import FONTS, ORIGINAL_FONT
from .icons import svg_icon
from .stamps import ColorButton, apply_opacity_rotation, color_row, trim
from .i18n import tr


def parse_pages(text: str, count: int, current: int) -> list[int]:
    t = (text or "").strip()
    if not t or t in ("all", tr("الكل")):
        return list(range(count))
    out = []
    for part in t.replace(tr("،"), ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a) if a.strip() else 1
            b = int(b) if b.strip() else count
            out.extend(range(a - 1, b))
        else:
            out.append(int(part) - 1)
    return sorted({p for p in out if 0 <= p < count})


def place_near_cursor(dlg: QDialog):
    dlg.adjustSize()
    pos = QCursor.pos() + QPoint(18, 18)
    scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    g = scr.availableGeometry()
    x = min(max(g.left(), pos.x()), g.right() - dlg.width())
    y = min(max(g.top(), pos.y()), g.bottom() - dlg.height())
    dlg.move(x, y)


class PagesSelector(QWidget):
    def __init__(self, allow_current=True):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.r_all = QRadioButton(tr("كل الصفحات"))
        self.r_cur = QRadioButton(tr("الصفحة الحالية"))
        self.r_rng = QRadioButton(tr("نطاق:"))
        self.ed = QLineEdit()
        self.ed.setPlaceholderText(tr("مثال: 1-3, 7"))
        self.r_all.setChecked(True)
        for w in (self.r_all, self.r_cur, self.r_rng, self.ed):
            h.addWidget(w)
        if not allow_current:
            self.r_cur.hide()

    def pages(self, count, current):
        if self.r_cur.isChecked():
            return [current]
        if self.r_rng.isChecked():
            return parse_pages(self.ed.text(), count, current)
        return list(range(count))


# =========================================================================== text editor
class TextEditDialog(QDialog):
    def __init__(self, parent, title, text="", style=None, multiline=False, show_align=False,
                 allow_original=True, allow_delete=True, allow_expand=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        style = dict(style or {})
        self.deleted = False
        self.expand = False
        lay = QVBoxLayout(self)
        if multiline:
            self.ed = QPlainTextEdit(text)
            self.ed.setMinimumHeight(120)
        else:
            self.ed = QLineEdit(text)
            self.ed.returnPressed.connect(self.accept)
        f = self.ed.font()
        f.setPointSize(12)
        self.ed.setFont(f)
        lay.addWidget(self.ed)
        form = QFormLayout()
        self.cb_font = QComboBox()
        if allow_original:
            self.cb_font.addItem(tr("الخط الأصلي (مطابقة تلقائية)"), ORIGINAL_FONT)
        for fam in FONTS:
            self.cb_font.addItem(fam, fam)
        idx = self.cb_font.findData(style.get("family", ORIGINAL_FONT if allow_original else "Arial"))
        self.cb_font.setCurrentIndex(max(0, idx))
        self.sp_size = QDoubleSpinBox()
        self.sp_size.setRange(3, 300)
        self.sp_size.setDecimals(1)
        self.sp_size.setValue(float(style.get("size", 12)))
        c = style.get("color", (0, 0, 0))
        self.btn_color = ColorButton(QColor.fromRgbF(*c[:3]).name())
        self.chk_b = QCheckBox(tr("عريض"))
        self.chk_i = QCheckBox(tr("مائل"))
        self.chk_b.setChecked(bool(style.get("bold", False)))
        self.chk_i.setChecked(bool(style.get("italic", False)))
        row = QHBoxLayout()
        row.addWidget(self.cb_font, 1)
        row.addWidget(QLabel(tr("الحجم")))
        row.addWidget(self.sp_size)
        form.addRow(tr("الخط"), row)
        bi = QHBoxLayout()
        bi.addWidget(self.chk_b)
        bi.addWidget(self.chk_i)
        bi.addStretch(1)
        form.addRow(tr("النمط"), bi)
        form.addRow(tr("اللون"), color_row(self.btn_color))
        self.cb_align = QComboBox()
        for lbl, v in ((tr("يمين"), "right"), (tr("وسط"), "center"), (tr("يسار"), "left"), (tr("ضبط"), "justify")):
            self.cb_align.addItem(lbl, v)
        self.cb_align.setCurrentIndex(max(0, self.cb_align.findData(style.get("align", "left"))))
        if show_align:
            form.addRow(tr("المحاذاة"), self.cb_align)
        lay.addLayout(form)
        self._bold_touched = False
        self.chk_b.toggled.connect(lambda _: setattr(self, "_bold_touched", True))
        self.chk_i.toggled.connect(lambda _: setattr(self, "_bold_touched", True))
        hint = QLabel(tr("التعديل يحذف النص القديم فعلياً من الملف ويكتب الجديد مكانه بنفس الحجم واللون."))
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        btns = QHBoxLayout()
        ok = QPushButton(tr("تطبيق"))
        ok.setObjectName("Primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)
        if allow_expand:
            ex = QPushButton(tr("تعديل الفقرة كاملة"))
            ex.clicked.connect(self._expand)
            btns.addWidget(ex)
        if allow_delete:
            d = QPushButton(tr("حذف النص"))
            d.setObjectName("Danger")
            d.clicked.connect(self._delete)
            btns.addWidget(d)
        btns.addStretch(1)
        cancel = QPushButton(tr("إلغاء"))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        lay.addLayout(btns)
        self.ed.setFocus()
        if isinstance(self.ed, QLineEdit):
            self.ed.selectAll()

    def _expand(self):
        self.expand = True
        self.reject()

    def _delete(self):
        self.deleted = True
        self.accept()

    def text(self):
        return self.ed.toPlainText() if isinstance(self.ed, QPlainTextEdit) else self.ed.text()

    def style(self):
        c = self.btn_color.color
        st = {"family": self.cb_font.currentData(), "size": self.sp_size.value(),
              "color": (c.redF(), c.greenF(), c.blueF()), "align": self.cb_align.currentData()}
        if self._bold_touched or self.cb_font.currentData() != ORIGINAL_FONT:
            st["bold"] = self.chk_b.isChecked()
            st["italic"] = self.chk_i.isChecked()
        return st

    def align(self):
        return self.cb_align.currentData()


# =========================================================================== find bar
class FindBar(QWidget):
    search = Signal(str)
    nav = Signal(int)
    replaceAll = Signal(str, str)
    closed = Signal()

    def __init__(self, icon_color="#ddd"):
        super().__init__()
        self.setObjectName("FindBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 6, 10, 6)
        self.ed = QLineEdit()
        self.ed.setPlaceholderText(tr("ابحث في المستند…"))
        self.ed.setMinimumWidth(220)
        self.ed.returnPressed.connect(lambda: self.search.emit(self.ed.text()))
        self.lbl = QLabel("")
        self.lbl.setObjectName("Hint")
        b_prev = QToolButton()
        b_prev.setIcon(svg_icon("up", icon_color))
        b_next = QToolButton()
        b_next.setIcon(svg_icon("down", icon_color))
        b_prev.clicked.connect(lambda: self.nav.emit(-1))
        b_next.clicked.connect(lambda: self.nav.emit(1))
        self.ed_rep = QLineEdit()
        self.ed_rep.setPlaceholderText(tr("استبدال بـ…"))
        self.ed_rep.setMinimumWidth(200)
        self.b_rep = QPushButton(tr("استبدال الكل"))
        self.b_rep.setObjectName("Primary")
        self.b_rep.clicked.connect(lambda: self.replaceAll.emit(self.ed.text(), self.ed_rep.text()))
        b_close = QToolButton()
        b_close.setIcon(svg_icon("close", icon_color))
        b_close.clicked.connect(self._close)
        for w in (self.ed, b_prev, b_next, self.lbl):
            h.addWidget(w)
        h.addSpacing(16)
        h.addWidget(self.ed_rep)
        h.addWidget(self.b_rep)
        h.addStretch(1)
        h.addWidget(b_close)
        self.hide()

    def open(self, replace=False):
        self.ed_rep.setVisible(replace)
        self.b_rep.setVisible(replace)
        self.show()
        self.ed.setFocus()
        self.ed.selectAll()

    def _close(self):
        self.hide()
        self.closed.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._close()
        else:
            super().keyPressEvent(e)


# =========================================================================== tools dialogs
def _buttons(dlg, ok_text=tr("تطبيق")):
    h = QHBoxLayout()
    ok = QPushButton(ok_text)
    ok.setObjectName("Primary")
    ok.clicked.connect(dlg.accept)
    c = QPushButton(tr("إلغاء"))
    c.clicked.connect(dlg.reject)
    h.addWidget(ok)
    h.addStretch(1)
    h.addWidget(c)
    return h


class WatermarkDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("علامة مائية"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.r_text = QRadioButton(tr("نص"))
        self.r_img = QRadioButton(tr("صورة / شعار"))
        self.r_text.setChecked(True)
        tr = QHBoxLayout()
        tr.addWidget(self.r_text)
        tr.addWidget(self.r_img)
        tr.addStretch(1)
        form.addRow(tr("النوع"), tr)
        self.ed = QLineEdit(tr("سري - CONFIDENTIAL"))
        form.addRow(tr("النص"), self.ed)
        self.font_cb = QFontComboBox()
        self.font_cb.setCurrentFont(QFont("Arial"))
        form.addRow(tr("الخط"), self.font_cb)
        self.img_path = QLineEdit()
        b = QPushButton(tr("اختيار…"))
        b.clicked.connect(self._pick)
        ir = QHBoxLayout()
        ir.addWidget(self.img_path)
        ir.addWidget(b)
        form.addRow(tr("الصورة"), ir)
        self.btn_color = ColorButton("#c8102e")
        form.addRow(tr("اللون"), color_row(self.btn_color))
        self.sl_op = QSlider(Qt.Horizontal)
        self.sl_op.setRange(5, 100)
        self.sl_op.setValue(22)
        form.addRow(tr("الشفافية"), self.sl_op)
        self.sp_angle = QSpinBox()
        self.sp_angle.setRange(-90, 90)
        self.sp_angle.setValue(45)
        form.addRow(tr("الزاوية"), self.sp_angle)
        self.sp_scale = QSpinBox()
        self.sp_scale.setRange(10, 100)
        self.sp_scale.setValue(70)
        self.sp_scale.setSuffix(tr(" % من عرض الصفحة"))
        form.addRow(tr("الحجم"), self.sp_scale)
        self.cb_place = QComboBox()
        for lbl, v in ((tr("المنتصف"), "center"), (tr("تكرار على الصفحة"), "tile"), (tr("أعلى اليمين"), "top-right"),
                       (tr("أعلى اليسار"), "top-left"), (tr("أسفل اليمين"), "bottom-right"), (tr("أسفل اليسار"), "bottom-left")):
            self.cb_place.addItem(lbl, v)
        form.addRow(tr("الموضع"), self.cb_place)
        self.pages = PagesSelector()
        form.addRow(tr("الصفحات"), self.pages)
        lay.addLayout(form)
        lay.addLayout(_buttons(self))

    def _pick(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("صورة"), "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if p:
            self.img_path.setText(p)
            self.r_img.setChecked(True)

    def image(self) -> QImage | None:
        op = self.sl_op.value() / 100.0
        if self.r_img.isChecked():
            img = QImage(self.img_path.text())
            if img.isNull():
                return None
            img = img.convertToFormat(QImage.Format_ARGB32)
        else:
            text = self.ed.text().strip()
            if not text:
                return None
            f = QFont(self.font_cb.currentFont().family())
            f.setPixelSize(160)
            f.setBold(True)
            fm = QFontMetricsF(f)
            w, h = int(fm.horizontalAdvance(text) + 40), int(fm.height() + 20)
            img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.setFont(f)
            p.setPen(self.btn_color.color)
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, text)
            p.end()
        return trim(apply_opacity_rotation(img, op, -self.sp_angle.value()), 2)


class PageNumbersDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("ترقيم الصفحات"))
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.cb_fmt = QComboBox()
        self.cb_fmt.setEditable(True)
        self.cb_fmt.addItems(["{n}", tr("صفحة {n} من {total}"), "Page {n} of {total}", "- {n} -", "{n} / {total}"])
        form.addRow(tr("الصيغة"), self.cb_fmt)
        self.cb_pos = QComboBox()
        for lbl, v in ((tr("أسفل - وسط"), "bottom-center"), (tr("أسفل - يمين"), "bottom-right"), (tr("أسفل - يسار"), "bottom-left"),
                       (tr("أعلى - وسط"), "top-center"), (tr("أعلى - يمين"), "top-right"), (tr("أعلى - يسار"), "top-left")):
            self.cb_pos.addItem(lbl, v)
        form.addRow(tr("الموضع"), self.cb_pos)
        self.sp_size = QSpinBox()
        self.sp_size.setRange(6, 48)
        self.sp_size.setValue(11)
        form.addRow(tr("الحجم"), self.sp_size)
        self.btn_color = ColorButton("#111111")
        form.addRow(tr("اللون"), color_row(self.btn_color))
        self.sp_start = QSpinBox()
        self.sp_start.setRange(0, 100000)
        self.sp_start.setValue(1)
        form.addRow(tr("يبدأ من"), self.sp_start)
        self.chk_skip = QCheckBox(tr("بدون ترقيم للصفحة الأولى (الغلاف)"))
        form.addRow(self.chk_skip)
        lay.addLayout(form)
        lay.addLayout(_buttons(self))


class ProtectDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("حماية بكلمة مرور"))
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.user = QLineEdit()
        self.user.setEchoMode(QLineEdit.Password)
        self.owner = QLineEdit()
        self.owner.setEchoMode(QLineEdit.Password)
        form.addRow(tr("كلمة مرور الفتح"), self.user)
        form.addRow(tr("كلمة مرور المالك (اختياري)"), self.owner)
        self.c_print = QCheckBox(tr("السماح بالطباعة"))
        self.c_print.setChecked(True)
        self.c_copy = QCheckBox(tr("السماح بنسخ النص"))
        self.c_edit = QCheckBox(tr("السماح بالتعديل"))
        for c in (self.c_print, self.c_copy, self.c_edit):
            form.addRow(c)
        lay.addLayout(form)
        lay.addLayout(_buttons(self, tr("حفظ نسخة محمية…")))


class MetadataDialog(QDialog):
    KEYS = (("title", tr("العنوان")), ("author", tr("المؤلف")), ("subject", tr("الموضوع")), ("keywords", tr("الكلمات المفتاحية")),
            ("creator", tr("أنشئ بواسطة")))

    def __init__(self, parent, meta: dict):
        super().__init__(parent)
        self.setWindowTitle(tr("خصائص المستند"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.eds = {}
        for k, lbl in self.KEYS:
            e = QLineEdit(meta.get(k, "") or "")
            self.eds[k] = e
            form.addRow(lbl, e)
        lay.addLayout(form)
        lay.addLayout(_buttons(self, tr("حفظ")))

    def values(self):
        return {k: e.text() for k, e in self.eds.items()}


class CompressDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("ضغط الملف"))
        lay = QVBoxLayout(self)
        self.grp = QButtonGroup(self)
        self.opts = [(tr("جودة عالية (ضغط خفيف)"), 200, 85), (tr("متوازن (مُوصى به)"), 130, 72), (tr("أقصى ضغط"), 85, 55)]
        for i, (lbl, _, _) in enumerate(self.opts):
            r = QRadioButton(lbl)
            if i == 1:
                r.setChecked(True)
            self.grp.addButton(r, i)
            lay.addWidget(r)
        lay.addLayout(_buttons(self, tr("ضغط وحفظ…")))

    def params(self):
        _, dpi, q = self.opts[self.grp.checkedId()]
        return dpi, q


class ExportImagesDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("تصدير الصفحات كصور"))
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.sp_dpi = QSpinBox()
        self.sp_dpi.setRange(36, 600)
        self.sp_dpi.setValue(150)
        form.addRow(tr("الدقة (DPI)"), self.sp_dpi)
        self.cb_fmt = QComboBox()
        self.cb_fmt.addItems(["png", "jpg"])
        form.addRow(tr("الصيغة"), self.cb_fmt)
        self.pages = PagesSelector()
        form.addRow(tr("الصفحات"), self.pages)
        lay.addLayout(form)
        lay.addLayout(_buttons(self, tr("تصدير…")))


class SplitDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("تقسيم الملف"))
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.r_every = QRadioButton(tr("كل"))
        self.sp_n = QSpinBox()
        self.sp_n.setRange(1, 10000)
        self.sp_n.setValue(1)
        self.r_every.setChecked(True)
        row = QHBoxLayout()
        row.addWidget(self.r_every)
        row.addWidget(self.sp_n)
        row.addWidget(QLabel(tr("صفحة في ملف منفصل")))
        row.addStretch(1)
        form.addRow(row)
        self.r_range = QRadioButton(tr("استخراج صفحات محددة:"))
        self.ed = QLineEdit()
        self.ed.setPlaceholderText(tr("مثال: 1-3, 7"))
        r2 = QHBoxLayout()
        r2.addWidget(self.r_range)
        r2.addWidget(self.ed)
        form.addRow(r2)
        lay.addLayout(form)
        lay.addLayout(_buttons(self, tr("تنفيذ…")))


LANG_NAMES = {"ara": tr("العربية"), "eng": "English", "fra": "Français", "deu": "Deutsch", "tur": "Türkçe",
              "urd": tr("اردو"), "fas": tr("فارسی"), "spa": "Español"}


class OcrDialog(QDialog):
    def __init__(self, parent, langs):
        super().__init__(parent)
        self.setWindowTitle(tr("التعرف على النص (OCR)"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        info = QLabel(tr("يحوّل الصفحات المصوّرة (سكانر) إلى نص يمكن البحث فيه ونسخه وتعديله.\n"
                      "شكل الصفحة لا يتغير — يُضاف النص المتعرَّف عليه بشكل غير مرئي فوق الصورة."))
        info.setObjectName("Hint")
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()
        self.cb_lang = QComboBox()
        combos = [("auto", tr("تلقائي — يكتشف لغة الصفحة"))]
        if "ara" in langs and "eng" in langs:
            combos.append(("ara+eng", tr("العربية + English (مُوصى به)")))
        for l in langs:
            combos.append((l, LANG_NAMES.get(l, l)))
        for code, name in combos:
            self.cb_lang.addItem(name, code)
        form.addRow(tr("لغة المستند"), self.cb_lang)
        self.cb_dpi = QComboBox()
        self.cb_dpi.addItem(tr("عادية (300 DPI) — أسرع"), 300)
        self.cb_dpi.addItem(tr("عالية (400 DPI) — للخط الصغير"), 400)
        form.addRow(tr("الدقة"), self.cb_dpi)
        self.pages = PagesSelector()
        form.addRow(tr("الصفحات"), self.pages)
        self.chk_skip = QCheckBox(tr("تخطي الصفحات التي بها نص بالفعل"))
        self.chk_skip.setChecked(True)
        form.addRow(self.chk_skip)
        lay.addLayout(form)
        lay.addLayout(_buttons(self, tr("ابدأ التعرف")))

    def language(self):
        return self.cb_lang.currentData()

    def dpi(self):
        return self.cb_dpi.currentData()


SCAN_KINDS = (("stamp", "ختم"), ("logo", "شعار"), ("signature", "توقيع"), ("image", "صورة"))


def _rgba_qimage(res):
    if not res:
        return None
    w, h, data, _ = res
    return QImage(data, w, h, w * 4, QImage.Format_RGBA8888).copy()


class ExtractDialog(QDialog):
    """Preview + options for cutting a stamp / logo out of a scanned page."""

    def __init__(self, parent, engine, pno, rect):
        super().__init__(parent)
        from PySide6.QtCore import QSize
        from .stamps import checker_pixmap
        self._checker = checker_pixmap
        self.engine, self.pno, self.rect = engine, pno, rect
        self.setWindowTitle(tr("فصل عنصر من السكان"))
        lay = QVBoxLayout(self)
        self.preview = QLabel()
        self.preview.setFixedSize(QSize(380, 280))
        self.preview.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.preview, 0, Qt.AlignCenter)
        form = QFormLayout()
        self.r_color = QRadioButton(tr("الحبر الملون فقط (أختام وتوقيعات) — الكتابة السوداء تبقى في مكانها"))
        self.r_all = QRadioButton(tr("كل ما في المنطقة (شعار أسود أو متعدد الألوان)"))
        thr = engine.suggest_threshold(pno, rect)
        colored = engine.scan_object_image(pno, rect, "color", thr, dpi=72)
        (self.r_color if colored else self.r_all).setChecked(True)
        form.addRow(self.r_color)
        form.addRow(self.r_all)
        self.sl = QSlider(Qt.Horizontal)
        self.sl.setRange(10, 80)
        self.sl.setValue(thr)
        form.addRow(tr("حساسية اللون"), self.sl)
        self.cb_kind = QComboBox()
        for k, lbl in SCAN_KINDS:
            self.cb_kind.addItem(tr(lbl), k)
        form.addRow(tr("نوع الطبقة"), self.cb_kind)
        lay.addLayout(form)
        lay.addLayout(_buttons(self, tr("فصل كطبقة")))
        for w in (self.r_color, self.r_all):
            w.toggled.connect(self.update_preview)
        self.sl.valueChanged.connect(self.update_preview)
        self.update_preview()

    def mode(self):
        return "color" if self.r_color.isChecked() else "all"

    def update_preview(self):
        self.sl.setEnabled(self.r_color.isChecked())
        img = _rgba_qimage(self.engine.scan_object_image(self.pno, self.rect, self.mode(), self.sl.value(), dpi=150))
        self.preview.setPixmap(self._checker(img, self.preview.size()))


class DetectDialog(QDialog):
    """List of stamps / logos / signatures found inside a scanned page."""

    def __init__(self, parent, engine, pno, found):
        super().__init__(parent)
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QListView, QListWidget, QListWidgetItem
        from .stamps import checker_pixmap
        self.setWindowTitle(tr("الأختام والشعارات المكتشفة"))
        self.resize(640, 460)
        lay = QVBoxLayout(self)
        hint = QLabel(tr("علّم العناصر التي تريد فصلها. كل عنصر سيُقص من السكان ويصبح طبقة مستقلة."))
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.lst = QListWidget()
        self.lst.setViewMode(QListView.IconMode)
        self.lst.setIconSize(QSize(150, 130))
        self.lst.setGridSize(QSize(175, 175))
        self.lst.setResizeMode(QListView.Adjust)
        self.lst.setMovement(QListView.Static)
        for i, (r, col) in enumerate(found):
            thr = engine.suggest_threshold(pno, r)
            img = _rgba_qimage(engine.scan_object_image(pno, r, "color", thr, dpi=110))
            it = QListWidgetItem(QIcon(checker_pixmap(img, QSize(150, 130))), tr("عنصر {n}").format(n=i + 1))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, (r, thr))
            self.lst.addItem(it)
        lay.addWidget(self.lst)
        form = QFormLayout()
        self.cb_kind = QComboBox()
        for k, lbl in SCAN_KINDS:
            self.cb_kind.addItem(tr(lbl), k)
        form.addRow(tr("نوع الطبقة"), self.cb_kind)
        lay.addLayout(form)
        lay.addLayout(_buttons(self, tr("فصل المحدد كطبقات")))

    def selected(self):
        out = []
        for i in range(self.lst.count()):
            it = self.lst.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out


class EraseOptions(QWidget):
    """Radio list used in the properties panel for the erase tool."""
    MODES = [("all_white", tr("مسح كل شيء + تبييض المنطقة")),
             ("all", tr("مسح كل شيء (بدون تبييض)")),
             ("text", tr("مسح النص فقط")),
             ("images", tr("مسح الصور فقط (بكسلات المنطقة)")),
             ("graphics", tr("مسح الرسومات والخطوط فقط")),
             ("whiteout", tr("تغطية بمستطيل أبيض فقط"))]

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.grp = QButtonGroup(self)
        for i, (k, lbl) in enumerate(self.MODES):
            r = QRadioButton(lbl)
            r.setProperty("mode", k)
            if i == 0:
                r.setChecked(True)
            self.grp.addButton(r, i)
            v.addWidget(r)

    def mode(self):
        return self.MODES[self.grp.checkedId()][0]
