"""Main application window."""
from __future__ import annotations

import os
import traceback

import pymupdf
from PySide6.QtCore import QPoint, QPointF, QRectF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QSizePolicy, QCheckBox, QComboBox, QDockWidget, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSlider, QSpinBox,
                               QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget, QDoubleSpinBox)

from . import theme as th
from .dialogs import (CompressDialog, DetectDialog, EraseOptions, ExportImagesDialog, ExtractDialog, FindBar,
                      MetadataDialog, OcrDialog,
                      PageNumbersDialog, ProtectDialog, SplitDialog, TextEditDialog, WatermarkDialog,
                      parse_pages, place_near_cursor)
from .engine import ORIGINAL_FONT, PasswordRequired, PdfDocument, has_rtl
from .icons import logo_pixmap, svg_icon
from .stamps import (ColorButton, ImageImportDialog, SignatureDialog, StampDialog, apply_opacity_rotation,
                     color_row, qimage_to_png)
from .viewer import PdfView, Tool
from .i18n import tr

from .brand import APP_NAME, settings as _brand_settings
OPEN_FILTER = tr("PDF والصور (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.xps *.epub);;PDF (*.pdf);;كل الملفات (*.*)")

TOOL_INFO = {
    Tool.TEXT: (tr("تحديد النص ونسخه"), tr("اسحب على النص لتحديده، ويُنسخ تلقائياً. Ctrl+C للنسخ مرة أخرى.")),
    Tool.SELECT: (tr("تحديد عنصر"),
                  tr("اضغط على أي صورة أو ختم أو شعار أو توقيع لتحديده — وإن كان داخل سكان يُفصل كعنصر مستقل. "
                     "اسحب مربعاً لفصل أي جزء. ثم اسحبه لنقله أو Delete لحذفه.")),
    Tool.HAND: (tr("أداة اليد"), tr("اسحب لتحريك الصفحة. Ctrl + عجلة الماوس للتكبير.")),
    Tool.EDIT_TEXT: (tr("تعديل النصوص"),
                     tr("مرّر الماوس فوق أي سطر ثم اضغط عليه لتعديله.\n"
                     "النص القديم يُحذف فعلياً من الملف ويُكتب الجديد في نفس المكان بنفس الحجم واللون،"
                     " ويحاول البرنامج استخدام نفس الخط الأصلي.\nيدعم العربية والإنجليزية.")),
    Tool.ADD_TEXT: (tr("إضافة نص"), tr("اضغط في أي مكان بالصفحة لكتابة نص جديد.\nالنص العربي يبدأ من نقطة الضغط ناحية اليسار.")),
    Tool.ERASE: (tr("مسح منطقة"), tr("ارسم مستطيلاً حول ما تريد مسحه (ختم، توقيع، نص، صورة).\nاختر نوع المسح:")),
    Tool.INK: (tr("إزالة ختم من صفحة ممسوحة ضوئياً"),
               tr("للملفات المصوّرة (سكانر): ارسم مستطيلاً حول الختم الأزرق/الأحمر.\n"
               "سيتم حذف الحبر الملون فقط مع الإبقاء على الكتابة السوداء تحته.")),
    Tool.EXTRACT: (tr("فصل عنصر من السكان"),
                   tr("ارسم مستطيلاً حول ختم أو شعار أو توقيع موجود داخل الصفحة المصوّرة.\nسيتم قصّه بخلفية شفافة ومسحه من السكان ووضعه كطبقة مستقلة يمكنك نقلها أو إخفاؤها أو حذفها.")),
    Tool.HIGHLIGHT: (tr("تظليل"), tr("ارسم مستطيلاً فوق الكلمات لتظليلها.")),
    Tool.UNDERLINE: (tr("تسطير"), tr("ارسم مستطيلاً فوق الكلمات لوضع خط تحتها.")),
    Tool.STRIKE: (tr("شطب"), tr("ارسم مستطيلاً فوق الكلمات لشطبها.")),
    Tool.RECT: (tr("مستطيل"), tr("اسحب لرسم مستطيل.")),
    Tool.ELLIPSE: (tr("دائرة"), tr("اسحب لرسم دائرة / شكل بيضاوي.")),
    Tool.LINE: (tr("خط"), tr("اسحب لرسم خط.")),
    Tool.ARROW: (tr("سهم"), tr("اسحب لرسم سهم.")),
    Tool.PEN: (tr("قلم حر"), tr("ارسم بحرية على الصفحة.")),
    Tool.NOTE: (tr("ملاحظة"), tr("اضغط على الصفحة لإضافة ملاحظة لاصقة.")),
}
ANNOT_TOOLS = {Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKE, Tool.RECT, Tool.ELLIPSE, Tool.LINE, Tool.ARROW,
               Tool.PEN, Tool.NOTE}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = _brand_settings()
        self.theme_name = self.settings.value("theme", "dark")
        if self.theme_name not in th.THEMES:
            self.theme_name = "dark"
        self.engine = PdfDocument()
        self._icon_widgets: list[tuple] = []
        self.tool_buttons: dict[str, list] = {}
        self.place_base: QImage | None = None
        self.search_hits: list = []
        self.search_idx = -1
        self.last_text_style = {"family": "Arial", "size": 14, "color": (0, 0, 0), "bold": False, "italic": False}
        self._thumb_queue: list[int] = []
        self._thumb_timer = QTimer(self, interval=0, timeout=self._thumb_tick)
        self._moving_thumb = False
        self.mode = "read"
        self.selected_text = ""
        self._was_max = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(logo_pixmap(256)))
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.setDockOptions(QMainWindow.AnimatedDocks)

        from .background import BackgroundRecognizer
        self._build_view()
        self.bg = BackgroundRecognizer(self)
        self._build_ribbon()
        self._build_side_panel()
        self._build_props_panel()
        self._build_statusbar()
        self._build_shortcuts()
        self.apply_theme(self.theme_name)
        self.set_mode("read")
        self._update_state()

    # ================================================================= UI construction
    def ic(self) -> str:
        return th.color(self.theme_name, "icon")

    def _reg_icon(self, w, name):
        self._icon_widgets.append((w, name))
        w.setIcon(svg_icon(name, self.ic()))

    def _btn(self, icon, text, slot=None, tool=None, tip=None, small=False):
        """Pill tool button (Mesta style): icon + short text, turns icon-only on narrow windows."""
        b = QToolButton()
        b.setObjectName("TbBtn")
        text = text.replace("\n", " ")
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setIconSize(QSize(16, 16))
        b.setCursor(Qt.PointingHandCursor)
        self._reg_icon(b, icon)
        b.setToolTip(tip or text)
        if tool:
            b.setCheckable(True)
            self.tool_buttons.setdefault(tool, []).append(b)
            b.clicked.connect(lambda _=False, t=tool: self.set_tool(t))
        elif slot:
            b.clicked.connect(slot)
        return b

    def _menu_btn(self, icon, text, items, tip=None):
        """Tool button that opens a small menu: items = [(icon, text, slot) | None for separator]."""
        b = self._btn(icon, text, tip=tip)
        b.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(b)
        for it in items:
            if it is None:
                m.addSeparator()
                continue
            ic, t, slot = it
            a = m.addAction(t, slot)
            self._icon_actions.append((a, ic))
            a.setIcon(svg_icon(ic, self.ic()))
        b.setMenu(m)
        return b

    def _quick(self, icon, tip, slot):
        b = QToolButton()
        b.setObjectName("IconBtn")
        b.setToolTip(tip)
        b.setIconSize(QSize(18, 18))
        b.setCursor(Qt.PointingHandCursor)
        self._reg_icon(b, icon)
        b.clicked.connect(slot)
        return b

    def _side_button(self, icon, text, obj="SideBtn", slot=None):
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setIconSize(QSize(18, 18))
        b.setCursor(Qt.PointingHandCursor)
        self._reg_icon(b, icon)
        if slot:
            b.clicked.connect(slot)
        return b

    def _build_sidebar(self):
        from .i18n import LANGUAGES, chosen_language, system_language
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setMinimumWidth(236)
        side.setMaximumWidth(236)
        self._side_brand_widgets, self._side_titles, self._side_text_btns = [], [], []
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 18, 14, 12)
        sv.setSpacing(3)
        # brand
        brand = QHBoxLayout()
        brand.setSpacing(10)
        lg = QLabel()
        lg.setPixmap(logo_pixmap(40))
        brand.addWidget(lg)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        nr = QHBoxLayout()
        nr.setSpacing(6)
        nm = QLabel("Mesta PDF")
        nm.setObjectName("BrandName")
        badge = QLabel("PRO")
        badge.setObjectName("BadgePro")
        nr.addWidget(nm)
        nr.addWidget(badge)
        nr.addStretch(1)
        bt.addLayout(nr)
        tg = QLabel(tr("قارئ ومحرر PDF احترافي"))
        tg.setObjectName("BrandTag")
        bt.addWidget(tg)
        brand.addLayout(bt, 1)
        self._side_brand_widgets += [nm, badge, tg]
        sv.addLayout(brand)
        sv.addSpacing(14)
        # big gradient button
        self.btn_new = QPushButton("  " + tr("فتح ملف"))
        self.btn_new.setObjectName("BtnNew")
        self.btn_new.setIcon(svg_icon("open", "#ffffff"))
        self.btn_new.setIconSize(QSize(18, 18))
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.clicked.connect(self.open_dialog)
        self._side_text_btns.append((self.btn_new, self.btn_new.text()))
        self.btn_new.setToolTip(tr("فتح ملف (Ctrl+O)"))
        sv.addWidget(self.btn_new)
        # sections
        t = QLabel(tr("الأقسام"))
        t.setObjectName("NavTitle")
        sv.addWidget(t)
        self._side_titles.append(t)
        self.nav_btns = []
        for i, (ic, txt) in enumerate((("book", tr("قراءة")), ("edit_text", tr("تحرير")),
                                       ("highlight", tr("تعليقات")), ("thumbs", tr("الصفحات")))):
            b = self._side_button(ic, "  " + txt, "NavItem")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=i: self._nav_to(k))
            b.setToolTip(txt)
            sv.addWidget(b)
            self.nav_btns.append(b)
            self._side_text_btns.append((b, b.text()))
        self.nav_btns[0].setChecked(True)
        # recent files
        self.recent_title = QLabel(tr("الملفات الأخيرة"))
        self.recent_title.setObjectName("NavTitle")
        sv.addWidget(self.recent_title)
        self.side_recent = QVBoxLayout()
        self.side_recent.setSpacing(1)
        sv.addLayout(self.side_recent)
        sv.addStretch(1)
        # bottom: settings / theme
        bottom = QFrame()
        bottom.setObjectName("SideBottom")
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 10, 0, 0)
        bl.setSpacing(2)
        self.b_theme = self._side_button("theme", "  " + tr("تبديل المظهر (داكن/فاتح)"), slot=self.toggle_theme)
        self.b_settings = self._side_button("settings", "  " + tr("الإعدادات"))
        sm = QMenu(self.b_settings)
        lang_menu = sm.addMenu(tr("اللغة"))
        picked = chosen_language()
        la = lang_menu.addAction(tr("تلقائي — لغة النظام ({x})").format(x=LANGUAGES[system_language()]),
                                 lambda: self.change_language("system"))
        la.setCheckable(True)
        la.setChecked(picked == "system")
        lang_menu.addSeparator()
        for code, name in LANGUAGES.items():
            la = lang_menu.addAction(name, lambda c=code: self.change_language(c))
            la.setCheckable(True)
            la.setChecked(picked == code)
        self.act_auto_ocr = sm.addAction(tr("التعرف التلقائي على نصوص الملفات المصوّرة"))
        self.act_auto_ocr.setCheckable(True)
        self.act_auto_ocr.setChecked(self.settings.value("auto_ocr", "true") in (True, "true", "1", 1))
        self.act_auto_ocr.toggled.connect(self.toggle_auto_ocr)
        a = sm.addAction(tr("فتح ملفات PDF بهذا البرنامج"), self.make_default_reader)
        self._icon_actions.append((a, "default_app"))
        sm.addSeparator()
        sm.addAction(tr("التحقق من التحديثات"), self.check_updates)
        self.b_settings.setMenu(sm)
        self.b_collapse = self._side_button("next", "  " + tr("طي القائمة"), slot=self.toggle_sidebar)
        self.b_collapse.setToolTip(tr("طي / فتح القائمة (Ctrl+B)"))
        self.b_theme.setToolTip(tr("تبديل المظهر (داكن/فاتح)"))
        self.b_settings.setToolTip(tr("الإعدادات"))
        self._side_text_btns += [(self.b_theme, self.b_theme.text()), (self.b_settings, self.b_settings.text())]
        bl.addWidget(self.b_collapse)
        bl.addWidget(self.b_theme)
        bl.addWidget(self.b_settings)
        sv.addWidget(bottom)
        self.sidebar = side
        return side

    def _end_area(self):
        """Panels go on the side opposite the sidebar (left in Arabic, right in English/French)."""
        from .i18n import is_rtl
        return Qt.LeftDockWidgetArea if is_rtl() else Qt.RightDockWidgetArea

    def _nav_to(self, i):
        if i > 0 and not self.engine.is_open:
            self.nav_btns[i].setChecked(False)
            return
        self.rtabs.setCurrentIndex(i)
        self._sync_nav(i)

    def _sync_nav(self, i=None):
        i = self.rtabs.currentIndex() if i is None else i
        for k, b in enumerate(self.nav_btns):
            b.setChecked(k == i)

    def _refresh_side_recent(self):
        while self.side_recent.count():
            w = self.side_recent.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        rec = [p for p in (self.settings.value("recent", []) or []) if os.path.exists(p)][:5]
        full = getattr(self, "_side_full", True) is not False
        self.recent_title.setVisible(bool(rec) and full)
        for p in rec:
            name = os.path.basename(p)
            b = self._side_button("file", "  " + (name if len(name) <= 26 else name[:24] + "…"), "RecentItem",
                                  slot=lambda _=False, x=p: self.open_file(x))
            b.setIconSize(QSize(16, 16))
            b.setToolTip(p)
            b.setVisible(full)
            self.side_recent.addWidget(b)

    def _build_ribbon(self):
        """Mesta layout: sidebar | (header, section tools, page)."""
        self._icon_actions = []
        root = QWidget()
        root.setObjectName("Root")
        root.setAttribute(Qt.WA_StyledBackground, True)
        rl = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self._build_sidebar())
        main = QWidget()
        main.setObjectName("MainCol")
        main.setAttribute(Qt.WA_StyledBackground, True)
        main.setSizePolicy(QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred))
        mv = QVBoxLayout(main)
        mv.setContentsMargins(18, 14, 18, 0)
        mv.setSpacing(8)
        # header: title + search + quick actions
        header = QWidget()
        hh = QHBoxLayout(header)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.setSpacing(6)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        self.doc_label = QLabel(APP_NAME)
        self.doc_label.setObjectName("H1")
        self.doc_label.setSizePolicy(QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred))
        self.doc_sub = QLabel("")
        self.doc_sub.setObjectName("H1Sub")
        tv.addWidget(self.doc_label)
        tv.addWidget(self.doc_sub)
        hh.addLayout(tv, 1)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("Search")
        self.search_box.setPlaceholderText(tr("ابحث في المستند…"))
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(250)
        self.search_box.addAction(svg_icon("find", th.color(self.theme_name, "text3")), QLineEdit.LeadingPosition)
        self.search_box.returnPressed.connect(self._header_search)
        hh.addWidget(self.search_box)
        self.b_undo = self._quick("undo", tr("تراجع (Ctrl+Z)"), self.undo)
        self.b_redo = self._quick("redo", tr("إعادة (Ctrl+Y)"), self.redo)
        for b in (self.b_undo, self.b_redo,
                  self._quick("save", tr("حفظ (Ctrl+S)"), self.save),
                  self._quick("save_as", tr("حفظ باسم (Ctrl+Shift+S)"), self.save_as),
                  self._quick("print", tr("طباعة (Ctrl+P)"), self.print_doc)):
            hh.addWidget(b)
        self.header = header
        mv.addWidget(header)

        self.rtabs = QTabWidget()
        self.rtabs.setObjectName("RibbonTabs")
        self.rtabs.setDocumentMode(True)
        self.rtabs.tabBar().hide()
        self.rtabs.setSizePolicy(QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed))

        def tab(title):
            w = QWidget()
            w.setSizePolicy(QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred))
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 2)
            h.setSpacing(4)
            self.rtabs.addTab(w, title)
            return h

        def group(h, buttons):
            f = QFrame()
            f.setObjectName("RibbonGroup")
            row = QHBoxLayout(f)
            row.setContentsMargins(0, 0, 6, 0)
            row.setSpacing(4)
            for b in buttons:
                row.addWidget(b)
            h.addWidget(f)

        # ---- 0: قراءة
        h = tab(tr("قراءة"))
        group(h, [self._btn("text_cursor", tr("تحديد نص"), tool=Tool.TEXT, tip=tr("تحديد النص ونسخه")),
                  self._btn("hand", tr("يد"), tool=Tool.HAND, tip=tr("تحريك (H)"))])
        self.b_showtext = self._btn("text_cursor", tr("إظهار\nالنصوص"), self._update_text_overlay,
                                    tip=tr("إبراز كل النصوص الموجودة في الملف (ومنها نصوص السكان المتعرَّف عليها)"))
        self.b_showtext.setCheckable(True)
        group(h, [self._btn("copy", tr("نسخ نص\nالصفحة"), self.copy_page_text),
                  self._btn("ocr", tr("التعرف على\nالنص (OCR)"), self.run_ocr,
                            tip=tr("اجعل الملفات المصوّرة (سكانر) قابلة للبحث والنسخ والتعديل")),
                  self.b_showtext])
        self.b_night = self._btn("night", tr("قراءة ليلية"), self.toggle_night, tip=tr("عكس ألوان الصفحات لراحة العين"))
        self.b_night.setCheckable(True)
        group(h, [self._btn("fit_width", tr("ملء العرض"), lambda: self.view.fit_width()),
                  self._btn("fit_page", tr("صفحة كاملة"), lambda: self.view.fit_page()),
                  self._btn("fullscreen", tr("ملء الشاشة"), self.toggle_fullscreen, tip=tr("ملء الشاشة (F11)")),
                  self.b_night])
        h.addStretch(1)

        # ---- 1: تحرير
        h = tab(tr("تحرير"))
        group(h, [self._btn("select", tr("تحديد عنصر"), tool=Tool.SELECT,
                            tip=tr("اضغط على أي صورة أو ختم أو شعار أو توقيع لتحديده — حتى داخل السكان")),
                  self._btn("edit_text", tr("تعديل النص"), tool=Tool.EDIT_TEXT, tip=tr("تعديل أي نص موجود (T)")),
                  self._btn("add_text", tr("إضافة نص"), tool=Tool.ADD_TEXT)])
        group(h, [self._btn("image", tr("صورة"), self.insert_image),
                  self._btn("signature", tr("توقيع"), self.insert_signature),
                  self._btn("stamp", tr("ختم"), self.insert_stamp)])
        group(h, [self._btn("erase", tr("مسح منطقة"), tool=Tool.ERASE),
                  self._btn("replace", tr("بحث واستبدال"), lambda: self.open_find(True))])
        h.addStretch(1)

        # ---- 2: تعليقات
        h = tab(tr("تعليقات"))
        group(h, [self._btn("highlight", tr("تظليل"), tool=Tool.HIGHLIGHT),
                  self._btn("pen", tr("قلم حر"), tool=Tool.PEN),
                  self._btn("note", tr("ملاحظة"), tool=Tool.NOTE)])
        group(h, [self._menu_btn("rect", tr("أشكال"), [
            ("rect", tr("مستطيل"), lambda: self.set_tool(Tool.RECT)),
            ("ellipse", tr("دائرة"), lambda: self.set_tool(Tool.ELLIPSE)),
            ("line", tr("خط"), lambda: self.set_tool(Tool.LINE)),
            ("arrow", tr("سهم"), lambda: self.set_tool(Tool.ARROW))]),
            self._menu_btn("underline", tr("خطوط النص"), [
                ("underline", tr("تسطير"), lambda: self.set_tool(Tool.UNDERLINE)),
                ("strike", tr("شطب"), lambda: self.set_tool(Tool.STRIKE))])])
        h.addStretch(1)

        # ---- 3: الصفحات
        h = tab(tr("الصفحات"))
        group(h, [self._btn("rotate_right", tr("تدوير"), lambda: self.rotate_pages(90)),
                  self._btn("page_add", tr("صفحة فارغة"), self.insert_blank),
                  self._btn("page_delete", tr("حذف الصفحة"), self.delete_pages)])
        group(h, [self._btn("merge", tr("دمج ملفات"), self.merge_files),
                  self._menu_btn("split", tr("تقسيم"), [
                      ("split", tr("تقسيم"), self.split_doc),
                      ("extract", tr("استخراج صفحات"), self.extract_pages),
                      ("duplicate", tr("تكرار"), self.duplicate_page),
                      ("rotate_left", tr("تدوير يسار"), lambda: self.rotate_pages(-90))])])
        group(h, [self._menu_btn("settings", tr("أدوات"), [
            ("watermark", tr("علامة مائية"), self.watermark),
            ("numbers", tr("ترقيم الصفحات"), self.page_numbers),
            None,
            ("compress", tr("ضغط الملف"), self.compress),
            ("export_img", tr("PDF إلى صور"), self.export_images),
            ("img2pdf", tr("صور إلى PDF"), self.images_to_pdf),
            None,
            ("lock", tr("حماية بكلمة مرور"), self.protect),
            ("unlock", tr("إزالة الحماية"), self.unprotect),
            ("flatten", tr("دمج التعليقات في الصفحة"), self.flatten),
            ("ocr", tr("التعرف على النص يدوياً (اختيار اللغة)"), self.run_ocr),
            ("info", tr("الخصائص"), self.metadata)])])
        h.addStretch(1)

        self.rtabs.setCurrentIndex(0)
        self.rtabs.currentChanged.connect(self._on_tab_changed)
        self.rtabs.currentChanged.connect(lambda i: self._sync_nav(i))
        self.rtabs.currentChanged.connect(lambda _i: QTimer.singleShot(0, self._fit_tools))
        mv.addWidget(self.rtabs)
        mv.addWidget(self.stack, 1)
        rl.addWidget(main, 1)
        self.setCentralWidget(root)
        self._refresh_side_recent()
        self._side_texts(True)
        if self.settings.value("sidebar_collapsed", "false") in (True, "true"):
            self._set_sidebar(True, animate=False)

    def _header_search(self):
        if not self.engine.is_open:
            return
        self.findbar.open(False)
        self.findbar.ed.setText(self.search_box.text())
        self.do_search(self.search_box.text())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._fit_tools)

    def _fit_tools(self):
        """Show icon + text when the section's buttons fit, icons only when they don't (text stays in the tooltip)."""
        if not hasattr(self, "rtabs"):
            return
        avail = self.rtabs.width()
        for i in range(self.rtabs.count()):
            page = self.rtabs.widget(i)
            btns = page.findChildren(QToolButton, "TbBtn")
            for b in btns:
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            need = sum(b.sizeHint().width() + 4 for b in btns) + 16 * len(page.findChildren(QFrame, "RibbonGroup"))
            if need > avail:
                for b in btns:
                    b.setToolButtonStyle(Qt.ToolButtonIconOnly)

    def _build_view(self):
        self.stack = QStackedWidget()
        # welcome
        self.welcome = QWidget()
        self.welcome.setObjectName("Welcome")
        self.welcome.setAttribute(Qt.WA_StyledBackground, True)
        self.welcome.setSizePolicy(QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred))
        wl = QVBoxLayout(self.welcome)
        wl.addStretch(1)
        lg = QLabel()
        lg.setPixmap(logo_pixmap(96))
        lg.setAlignment(Qt.AlignCenter)
        wl.addWidget(lg)
        t = QLabel(APP_NAME)
        t.setObjectName("WelcomeTitle")
        t.setAlignment(Qt.AlignCenter)
        wl.addWidget(t)
        s = QLabel(tr("اقرأ ملفاتك • ثم عدّل النصوص وأضف الأختام والتوقيعات • واحذف أي ختم أو صورة قديمة بضغطة واحدة"))
        s.setObjectName("WelcomeSub")
        s.setAlignment(Qt.AlignCenter)
        wl.addWidget(s)
        wl.addSpacing(18)
        b = QPushButton(tr("  افتح ملف PDF"))
        b.setObjectName("BigOpen")
        b.setIcon(svg_icon("open", "#ffffff"))
        b.setIconSize(QSize(22, 22))
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(self.open_dialog)
        wl.addWidget(b, 0, Qt.AlignCenter)
        hint = QLabel(tr("أو اسحب الملف وأفلته هنا"))
        hint.setObjectName("Hint")
        hint.setAlignment(Qt.AlignCenter)
        wl.addWidget(hint)
        wl.addSpacing(22)
        cards = QHBoxLayout()
        cards.addStretch(1)
        for icon, title, desc in (("edit_text", tr("تعديل النصوص"), tr("اضغط على أي سطر وغيّره بنفس الخط والحجم")),
                                  ("stamp", tr("أختام وتوقيعات"), tr("صمّم ختماً أو استورد ختمك الحقيقي بدون خلفية")),
                                  ("delete", tr("حذف الأختام القديمة"), tr("حدّد الختم واحذفه — أو من كل الصفحات مرة واحدة")),
                                  ("ink_remove", tr("تنظيف السكان"), tr("إزالة الختم الأزرق مع الإبقاء على الكتابة"))):
            c = QFrame()
            c.setObjectName("Card")
            c.setFixedWidth(220)
            cl = QVBoxLayout(c)
            il = QLabel()
            il.setPixmap(svg_icon(icon, "#5b8cff").pixmap(30, 30))
            cl.addWidget(il)
            tl = QLabel(title)
            tl.setStyleSheet("font-weight:700; font-size:11pt;")
            cl.addWidget(tl)
            dl = QLabel(desc)
            dl.setObjectName("Hint")
            dl.setWordWrap(True)
            cl.addWidget(dl)
            cards.addWidget(c)
        cards.addStretch(1)
        wl.addLayout(cards)
        wl.addSpacing(20)
        self.recent_box = QVBoxLayout()
        rw = QWidget()
        rw.setLayout(self.recent_box)
        rw.setMaximumWidth(600)
        wl.addWidget(rw, 0, Qt.AlignCenter)
        wl.addStretch(2)
        self.stack.addWidget(self.welcome)
        # editor
        ed = QWidget()
        el = QVBoxLayout(ed)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(0)
        self.findbar = FindBar(self.ic())
        self.findbar.search.connect(self.do_search)
        self.findbar.nav.connect(self.search_nav)
        self.findbar.replaceAll.connect(self.do_replace_all)
        self.findbar.closed.connect(lambda: self.view.set_search_hits({}))
        self.findbar.setSizePolicy(QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed))
        el.addWidget(self.findbar)
        self._build_context_bar()
        el.addWidget(self.ctx_bar)
        self.scan_bar = QFrame()
        self.scan_bar.setObjectName("InfoBar")
        sbl = QHBoxLayout(self.scan_bar)
        sbl.setContentsMargins(14, 8, 14, 8)
        self.scan_icon = QLabel()
        self.scan_icon.setPixmap(svg_icon("ocr", "#f59e0b").pixmap(22, 22))
        sbl.addWidget(self.scan_icon)
        self.scan_lbl = QLabel(tr("هذا الملف صورة ممسوحة ضوئياً (سكانر) — الكلمات غير قابلة للبحث أو التعديل بعد."))
        sbl.addWidget(self.scan_lbl, 1)
        b_ocr = QPushButton(tr("التعرف على النص الآن"))
        b_ocr.setObjectName("Primary")
        b_ocr.clicked.connect(self.run_ocr)
        b_x = QToolButton()
        self._reg_icon(b_x, "close")
        b_x.clicked.connect(self.scan_bar.hide)
        sbl.addWidget(b_ocr)
        sbl.addWidget(b_x)
        self.scan_bar.hide()
        el.addWidget(self.scan_bar)
        self.view = PdfView()
        el.addWidget(self.view)
        self.stack.addWidget(ed)
        # the stack is placed inside the main column by _build_ribbon()
        v = self.view
        v.pageChanged.connect(self._on_page_changed)
        v.zoomChanged.connect(lambda z: self.zoom_lbl.setText(f"{z * 100:.0f}%"))
        v.selectionChanged.connect(self._on_selection)
        v.editTextRequested.connect(self.edit_text)
        v.addTextRequested.connect(self.add_text)
        v.areaSelected.connect(self.on_area)
        v.lineDrawn.connect(self.on_line)
        v.inkDrawn.connect(self.on_ink)
        v.noteRequested.connect(self.on_note)
        v.placeCommitted.connect(self.on_place_commit)
        v.placeCancelled.connect(lambda: self._show_props(self.view.tool))
        v.moveRequested.connect(self.on_move)
        v.floatAction.connect(self.on_float_action)
        v.contextRequested.connect(self.on_context)
        v.hoverInfo.connect(lambda s: self.hint_lbl.setText(s))
        v.filesDropped.connect(self.on_files_dropped)
        v.scanPicked.connect(self.on_scan_picked)
        self._refresh_recent()

    def _build_side_panel(self):
        dock = QDockWidget("", self)
        dock.setTitleBarWidget(QWidget())
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        side = QWidget()
        side.setObjectName("SidePanel")
        side.setAttribute(Qt.WA_StyledBackground, True)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        self.side_tabs = QTabWidget()
        sv.addWidget(self.side_tabs)
        # thumbnails
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListView.ListMode)
        self.thumbs.setIconSize(QSize(150, 190))
        self.thumbs.setSpacing(4)
        self.thumbs.setDragDropMode(QListWidget.InternalMove)
        self.thumbs.setDefaultDropAction(Qt.MoveAction)
        self.thumbs.setSelectionMode(QListWidget.ExtendedSelection)
        self.thumbs.itemClicked.connect(lambda it: self.view.go_to_page(self.thumbs.row(it)))
        self.thumbs.verticalScrollBar().valueChanged.connect(lambda _v: self._schedule_thumbs())
        self.thumbs.model().rowsMoved.connect(self._on_thumb_moved)
        self.thumbs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self._thumb_menu)
        self.side_tabs.addTab(self.thumbs, tr("الصفحات"))
        from PySide6.QtWidgets import QTreeWidget
        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderHidden(True)
        self.toc_tree.itemClicked.connect(
            lambda it, _c: it.data(0, Qt.UserRole) is not None and self.view.go_to_page(it.data(0, Qt.UserRole)))
        self.side_tabs.addTab(self.toc_tree, tr("الفهرس"))
        # objects
        ow = QWidget()
        ol = QVBoxLayout(ow)
        ol.setContentsMargins(6, 6, 6, 6)
        oh = QLabel(tr("الصور والأختام والعناصر في الصفحة الحالية:"))
        oh.setObjectName("Hint")
        oh.setWordWrap(True)
        ol.addWidget(oh)
        self.obj_list = QListWidget()
        self.obj_list.setIconSize(QSize(56, 56))
        self.obj_list.setWordWrap(True)
        self.obj_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.obj_list.setTextElideMode(Qt.ElideNone)
        self.obj_list.itemClicked.connect(self._on_obj_item)
        ol.addWidget(self.obj_list)
        b1 = QPushButton(tr("حذف المحدد"))
        b1.setObjectName("Danger")
        b1.clicked.connect(lambda: self._obj_action("delete"))
        b2 = QPushButton(tr("حذف المتشابه من كل الصفحات"))
        b2.clicked.connect(lambda: self._obj_action("delete_all"))
        b3 = QPushButton(tr("حذف كل صور الصفحة"))
        b3.clicked.connect(self.delete_all_images_on_page)
        ol.addWidget(b1)
        ol.addWidget(b2)
        ol.addWidget(b3)
        ow.hide()  # replaced by the Layers panel + "Select element"
        self.objects_tab = ow
        # layers
        lw = QWidget()
        ll = QVBoxLayout(lw)
        ll.setContentsMargins(6, 6, 6, 6)
        lh = QLabel(tr("كل ما تضيفه (نص، صورة، ختم، توقيع، شكل) طبقة مستقلة: "
                    "علّم/ألغِ العلامة للإظهار والإخفاء، اضغط لتحديدها ثم اسحبها أو عدّلها."))
        lh.setObjectName("Hint")
        lh.setWordWrap(True)
        ll.addWidget(lh)
        self.chk_all_layers = QCheckBox(tr("عرض طبقات كل الصفحات"))
        self.chk_all_layers.toggled.connect(lambda _: self._refresh_layers())
        ll.addWidget(self.chk_all_layers)
        self.layer_list = QListWidget()
        self.layer_list.setIconSize(QSize(28, 28))
        self.layer_list.setWordWrap(True)
        self.layer_list.itemChanged.connect(self._on_layer_check)
        self.layer_list.itemClicked.connect(self._on_layer_item)
        self.layer_list.itemDoubleClicked.connect(lambda it: self._layer_action("edit"))
        ll.addWidget(self.layer_list)
        lr = QGridLayout()
        for i, (k, t, st) in enumerate((("edit", tr("تعديل"), "Primary"), ("rename", tr("إعادة تسمية"), None),
                                        ("up", tr("للأمام"), None), ("down", tr("للخلف"), None),
                                        ("flatten", tr("دمج في الصفحة"), None), ("delete", tr("حذف"), "Danger"))):
            b = QPushButton(t)
            if st:
                b.setObjectName(st)
            b.clicked.connect(lambda _=False, kk=k: self._layer_action(kk))
            lr.addWidget(b, i // 2, i % 2)
        ll.addLayout(lr)
        self.side_tabs.addTab(lw, tr("الطبقات"))
        side.setMinimumWidth(230)
        side.setMaximumWidth(330)
        dock.setWidget(side)
        self.addDockWidget(self._end_area(), dock)
        self.side_dock = dock

    def _build_props_panel(self):
        dock = QDockWidget("", self)
        dock.setTitleBarWidget(QWidget())
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        pw = QWidget()
        pw.setObjectName("PropsPanel")
        pw.setAttribute(Qt.WA_StyledBackground, True)
        pw.setFixedWidth(250)
        v = QVBoxLayout(pw)
        v.setContentsMargins(14, 14, 14, 14)
        self.props_title = QLabel("")
        self.props_title.setObjectName("PanelTitle")
        self.props_desc = QLabel("")
        self.props_desc.setObjectName("Hint")
        self.props_desc.setWordWrap(True)
        v.addWidget(self.props_title)
        v.addWidget(self.props_desc)
        v.addSpacing(8)
        self.props_stack = QStackedWidget()
        v.addWidget(self.props_stack)
        v.addStretch(1)
        self.props_pages = {}

        # empty
        self.props_pages["none"] = self._add_prop_page(QWidget())
        # select: object info + actions
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(0, 0, 0, 0)
        legend = QLabel(tr("<span style='color:#22c55e'>■</span> صورة/ختم &nbsp; "
                        "<span style='color:#f59e0b'>■</span> تعليق مضاف &nbsp; "
                        "<span style='color:#c084fc'>■</span> رسم &nbsp; "
                        "<span style='color:#5b8cff'>■</span> نص"))
        legend.setWordWrap(True)
        sl.addWidget(legend)
        self.sel_info = QLabel(tr("لم يتم تحديد عنصر"))
        self.sel_info.setWordWrap(True)
        self.sel_info.setObjectName("Hint")
        sl.addWidget(self.sel_info)
        self.sel_btns = {}
        for key, text, style in (("delete", tr("حذف العنصر"), "Danger"), ("delete_all", tr("حذف من كل الصفحات"), None),
                                 ("replace", tr("استبدال الصورة…"), None), ("save", tr("حفظ الصورة…"), None),
                                 ("edit", tr("تعديل النص…"), "Primary")):
            b = QPushButton(text)
            if style:
                b.setObjectName(style)
            b.clicked.connect(lambda _=False, k=key: self.view.sel_obj and self.on_float_action(k, self.view.sel_obj))
            sl.addWidget(b)
            self.sel_btns[key] = b
        self.props_pages[Tool.SELECT] = self._add_prop_page(sw)
        # edit text
        ew = QWidget()
        elay = QVBoxLayout(ew)
        elay.setContentsMargins(0, 0, 0, 0)
        self.chk_block = QCheckBox(tr("تعديل فقرة كاملة بدل سطر واحد"))
        self.chk_block.toggled.connect(lambda b: setattr(self.view, "block_mode", b))
        elay.addWidget(self.chk_block)
        self.props_pages[Tool.EDIT_TEXT] = self._add_prop_page(ew)
        # erase
        self.erase_opts = EraseOptions()
        self.props_pages[Tool.ERASE] = self._add_prop_page(self.erase_opts)
        # ink remover
        iw = QWidget()
        il = QVBoxLayout(iw)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(QLabel(tr("الحساسية (أقل = يزيل ألواناً أفتح)")))
        self.sl_ink = QSlider(Qt.Horizontal)
        self.sl_ink.setRange(15, 120)
        self.sl_ink.setValue(45)
        il.addWidget(self.sl_ink)
        self.props_pages[Tool.INK] = self._add_prop_page(iw)
        # annotations
        aw = QWidget()
        al = QVBoxLayout(aw)
        al.setContentsMargins(0, 0, 0, 0)
        al.addWidget(QLabel(tr("اللون")))
        self.ann_color = ColorButton("#e11d48")
        self.ann_color.changed.connect(lambda c: setattr(self.view, "ann_color", c))
        al.addWidget(color_row(self.ann_color))
        al.addWidget(QLabel(tr("السُمك")))
        self.ann_width = QDoubleSpinBox()
        self.ann_width.setRange(0.5, 20)
        self.ann_width.setValue(2.0)
        al.addWidget(self.ann_width)
        al.addWidget(QLabel(tr("الشفافية")))
        self.ann_op = QSlider(Qt.Horizontal)
        self.ann_op.setRange(10, 100)
        self.ann_op.setValue(100)
        al.addWidget(self.ann_op)
        self.ann_page = self._add_prop_page(aw)
        for t in ANNOT_TOOLS:
            self.props_pages[t] = self.ann_page
        # place (image/stamp/signature)
        plw = QWidget()
        pll = QVBoxLayout(plw)
        pll.setContentsMargins(0, 0, 0, 0)
        pll.addWidget(QLabel(tr("الشفافية")))
        self.pl_op = QSlider(Qt.Horizontal)
        self.pl_op.setRange(10, 100)
        self.pl_op.setValue(100)
        pll.addWidget(self.pl_op)
        pll.addWidget(QLabel(tr("الدوران (درجة)")))
        self.pl_rot = QSlider(Qt.Horizontal)
        self.pl_rot.setRange(-180, 180)
        self.pl_rot.setValue(0)
        pll.addWidget(self.pl_rot)
        self.pl_op.valueChanged.connect(self._update_place)
        self.pl_rot.valueChanged.connect(self._update_place)
        b_ok = QPushButton(tr("تطبيق على الصفحة"))
        b_ok.setObjectName("Primary")
        b_ok.clicked.connect(lambda: self.view.commit_place(False))
        b_all = QPushButton(tr("تطبيق على كل الصفحات"))
        b_all.clicked.connect(lambda: self.view.commit_place(True))
        b_c = QPushButton(tr("إلغاء"))
        b_c.clicked.connect(lambda: self.view.cancel_place())
        for b in (b_ok, b_all, b_c):
            pll.addWidget(b)
        self.props_pages["place"] = self._add_prop_page(plw)
        dock.setWidget(pw)
        self.addDockWidget(self._end_area(), dock)
        self.props_dock = dock

    def _add_prop_page(self, w):
        self.props_stack.addWidget(w)
        return w

    def _show_props(self, key, title=None, desc=None):
        if key == "place":
            title = title or tr("ضبط الموضع والحجم")
            desc = desc or (tr("اسحب العنصر إلى المكان المطلوب واسحب الزوايا لتغيير الحجم.\n"
                            "اضغط Enter أو \"تطبيق\" للتثبيت، Esc للإلغاء."))
        else:
            t, d = TOOL_INFO.get(key, ("", ""))
            title, desc = title or t, desc or d
        self.props_title.setText(title)
        self.props_desc.setText(desc)
        self.props_stack.setCurrentWidget(self.props_pages.get(key, self.props_pages["none"]))
        # the side panel only appears when the tool has options
        needs = key == "place" or key == Tool.ERASE or key in ANNOT_TOOLS
        self.props_dock.setVisible(bool(needs and self.engine.is_open and not self.isFullScreen()))
        if not needs and desc and self.engine.is_open:
            self.statusBar().showMessage(desc.split("\n")[0], 8000)

    def _build_statusbar(self):
        sb = self.statusBar()
        self.hint_lbl = QLabel("")
        self.hint_lbl.setSizePolicy(QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred))
        sb.addWidget(self.hint_lbl, 1)
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(70)
        self.page_spin.editingFinished.connect(lambda: self.view.go_to_page(self.page_spin.value() - 1))
        self.page_total = QLabel("/ 0")
        sb.addPermanentWidget(QLabel(tr("صفحة")))
        sb.addPermanentWidget(self.page_spin)
        sb.addPermanentWidget(self.page_total)
        sb.addPermanentWidget(QLabel("   "))
        bz_out = QToolButton()
        self._reg_icon(bz_out, "zoom_out")
        bz_out.clicked.connect(lambda: self.view.zoom_out())
        self.zoom_lbl = QLabel("100%")
        self.zoom_lbl.setFixedWidth(48)
        self.zoom_lbl.setAlignment(Qt.AlignCenter)
        bz_in = QToolButton()
        self._reg_icon(bz_in, "zoom_in")
        bz_in.clicked.connect(lambda: self.view.zoom_in())
        for w in (bz_out, self.zoom_lbl, bz_in):
            sb.addPermanentWidget(w)

    def _build_shortcuts(self):
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(fn)

        sc("Ctrl+O", self.open_dialog)
        sc("Ctrl+S", self.save)
        sc("Ctrl+Shift+S", self.save_as)
        sc("Ctrl+P", self.print_doc)
        sc("Ctrl+Z", self.undo)
        sc("Ctrl+Y", self.redo)
        sc("Ctrl+Shift+Z", self.redo)
        sc("Ctrl+F", lambda: self.open_find(False))
        sc("Ctrl+H", lambda: self.open_find(True))
        sc("Ctrl+=", lambda: self.view.zoom_in())
        sc("Ctrl++", lambda: self.view.zoom_in())
        sc("Ctrl+-", lambda: self.view.zoom_out())
        sc("Ctrl+0", lambda: self.view.fit_width())
        sc("F11", self.toggle_fullscreen)
        sc("Ctrl+C", self.copy_selection)
        sc("Ctrl+A", self.select_all_text)
        sc("Ctrl+V", self.paste_object)
        sc("Ctrl+X", lambda: self.copy_object(cut=True))
        sc("Ctrl+D", self.duplicate_object)
        sc("Ctrl+]", lambda: self.arrange("forward"))
        sc("Ctrl+[", lambda: self.arrange("backward"))
        sc("Ctrl+Shift+]", lambda: self.arrange("front"))
        sc("Ctrl+Shift+[", lambda: self.arrange("back"))
        sc("Ctrl+B", self.toggle_sidebar)
        for key, tool in (("V", Tool.SELECT), ("H", Tool.HAND), ("T", Tool.EDIT_TEXT), ("E", Tool.ERASE)):
            sc(key, lambda t=tool: self._key_tool(t))

    def _key_tool(self, t):
        if isinstance(QApplication.focusWidget(), (QLineEdit,)):
            return
        self.set_tool(t)

    # ================================================================= reader mode
    def set_mode(self, mode):
        """Reading = text selection / hand tool; editing = every other tool. Tabs only group the buttons."""
        if mode == "edit":
            if not self.engine.is_open:
                return
            if self.view.tool in (Tool.TEXT, Tool.HAND):
                self.set_tool(Tool.SELECT)
            if self.rtabs.currentIndex() == 0:
                self.rtabs.setCurrentIndex(1)
        else:
            self.set_tool(Tool.TEXT)
            self.rtabs.setCurrentIndex(0)

    def _apply_mode(self):
        # the Read tab is read-only; everything that changes the file lives in the other tabs
        edit = self.engine.is_open and self.rtabs.currentIndex() > 0
        self.mode = "edit" if edit else "read"
        self.view.read_only = not edit
        self.side_tabs.setTabVisible(2, edit)
        if not edit and self.side_tabs.currentIndex() == 2:
            self.side_tabs.setCurrentIndex(0)
        if edit:
            self._refresh_layers()

    def _on_tab_changed(self, i):
        if not self.engine.is_open:
            return
        if i == 0:
            self.view.clear_selection()
            if self.view.placing():
                self.view.cancel_place(emit=False)
            self.set_tool(Tool.TEXT if self.view.tool not in (Tool.TEXT, Tool.HAND) else self.view.tool)
        elif self.view.tool in (Tool.TEXT, Tool.HAND):
            self.set_tool(Tool.SELECT)
        else:
            self._apply_mode()

    def copy_selection(self):
        if self.mode == "edit" and self.view.sel_obj is not None and not isinstance(QApplication.focusWidget(), QLineEdit):
            if self.copy_object():
                return
        if isinstance(QApplication.focusWidget(), (QLineEdit,)) or not self.selected_text:
            fw = QApplication.focusWidget()
            if hasattr(fw, "copy"):
                fw.copy()
            return
        QApplication.clipboard().setText(self.selected_text)
        self.status(tr("تم النسخ ✔"))

    def copy_page_text(self):
        if self.engine.is_open:
            QApplication.clipboard().setText(self.engine.page_text(self.view.current_page()))
            self.status(tr("تم نسخ نص الصفحة ✔"))

    def toggle_night(self):
        self.view.set_night(self.b_night.isChecked())

    def toggle_fullscreen(self):
        if not self.engine.is_open:
            return
        if self.isFullScreen():
            self.sidebar.show()
            self.header.show()
            self.rtabs.show()
            self.statusBar().show()
            self.side_dock.show()
            self._show_props(self.view.tool)
            self.showMaximized() if self._was_max else self.showNormal()
        else:
            self._was_max = self.isMaximized()
            self.sidebar.hide()
            self.header.hide()
            self.rtabs.hide()
            self.statusBar().hide()
            self.side_dock.hide()
            self.props_dock.hide()
            self.showFullScreen()
            self.status(tr("Esc أو F11 للخروج من ملء الشاشة"))
        QTimer.singleShot(150, self.view.fit_width)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
            return
        super().keyPressEvent(e)

    def _fill_toc(self):
        from PySide6.QtWidgets import QTreeWidgetItem
        self.toc_tree.clear()
        toc = self.engine.toc() if self.engine.is_open else []
        stack = [(0, self.toc_tree.invisibleRootItem())]
        for lvl, title, page in toc:
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            parent = stack[-1][1] if stack else self.toc_tree.invisibleRootItem()
            it = QTreeWidgetItem(parent, [f"{title}    ({page})"])
            it.setData(0, Qt.UserRole, max(0, page - 1))
            stack.append((lvl, it))
        if not toc:
            it = QTreeWidgetItem(self.toc_tree, [tr("لا يوجد فهرس في هذا الملف")])
            it.setData(0, Qt.UserRole, None)
        self.toc_tree.expandToDepth(0)

    def make_default_reader(self):
        if QMessageBox.question(
                self, tr("القارئ الافتراضي"),
                tr("سيتم تسجيل Mesta PDF Pro كبرنامج لفتح ملفات PDF (لحسابك فقط، بدون صلاحيات مدير).\n"
                "بعدها ستفتح إعدادات Windows لتختار Mesta PDF Pro لملفات ‎.pdf‏.\n\nمتابعة؟")) != QMessageBox.Yes:
            return
        try:
            from .system import open_default_apps_settings, register_pdf_reader
            register_pdf_reader()
            open_default_apps_settings()
            QMessageBox.information(self, tr("القارئ الافتراضي"),
                                    tr("تم التسجيل ✔\nفي الإعدادات التي فُتحت: ابحث عن ‎.pdf‏ واختر Mesta PDF Pro.\n"
                                    "أو: كليك يمين على أي ملف PDF ← فتح باستخدام ← Mesta PDF Pro ← استخدام دائماً."))
        except Exception as e:
            self.error(e)

    # ================================================================= theme / state
    def apply_theme(self, name):
        self.theme_name = name
        self.settings.setValue("theme", name)
        QApplication.instance().setStyleSheet(th.stylesheet(name))
        for w, icon in self._icon_widgets:
            try:
                w.setIcon(svg_icon(icon, self.ic()))
            except RuntimeError:
                pass
        for a, icon in getattr(self, "_icon_actions", []):
            try:
                a.setIcon(svg_icon(icon, self.ic()))
            except RuntimeError:
                pass

    def change_language(self, code):
        from .i18n import current_language, system_language
        self.settings.setValue("language", code)
        if code == "system":
            code = system_language()
        if code == current_language():
            self.status(tr("تم الحفظ ✔"))
            return
        msg = {"ar": tr("سيتم تطبيق اللغة العربية عند إعادة تشغيل البرنامج. إعادة التشغيل الآن؟"),
               "en": "English will be applied after restarting Mesta PDF Pro. Restart now?",
               "fr": "Le français sera appliqué au redémarrage de Mesta PDF Pro. Redémarrer maintenant ?"}[code]
        if QMessageBox.question(self, "Mesta PDF Pro", msg) == QMessageBox.Yes and self.maybe_save():
            import subprocess
            import sys
            args = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath(sys.argv[0])]
            if self.engine.is_open and self.engine.path and os.path.exists(self.engine.path):
                args.append(self.engine.path)
            self.engine.modified = False
            subprocess.Popen(args, close_fds=True)
            QApplication.quit()

    def toggle_theme(self):
        self.apply_theme("light" if self.theme_name == "dark" else "dark")

    def _update_state(self):
        has = self.engine.is_open
        self.stack.setCurrentIndex(1 if has else 0)
        fs = self.isFullScreen()
        self.side_dock.setVisible(has and not fs)
        for i in range(1, self.rtabs.count()):
            self.rtabs.setTabEnabled(i, has)
        for i, nb in enumerate(self.nav_btns):
            nb.setEnabled(i == 0 or has)
        self.rtabs.setVisible(has)
        self.search_box.setEnabled(has)
        self.doc_sub.setText(tr("{n} صفحة").format(n=self.engine.page_count) if has else
                             tr("قارئ ومحرر PDF احترافي"))
        if not has:
            self.props_dock.hide()
            self.rtabs.setCurrentIndex(0)
        self.b_undo.setEnabled(has and self.engine.can_undo())
        self.b_redo.setEnabled(has and self.engine.can_redo())
        name = os.path.basename(self.engine.path) if has and self.engine.path else (tr("مستند جديد") if has else "")
        star = " •" if has and self.engine.modified else ""
        self.doc_label.setText((name + star) if has else APP_NAME)
        self.setWindowTitle(f"{name}{star} — {APP_NAME}" if has else APP_NAME)
        n = self.engine.page_count
        self.page_spin.setRange(1, max(1, n))
        self.page_total.setText(f"/ {n}")

    def set_tool(self, tool):
        if self.view.placing():
            self.view.cancel_place(emit=False)
        if tool not in (Tool.TEXT, Tool.HAND) and self.rtabs.currentIndex() == 0 and self.engine.is_open:
            self.rtabs.blockSignals(True)
            self.rtabs.setCurrentIndex(1)  # editing tools only work in the Edit tab
            self.rtabs.blockSignals(False)
        self.view.set_tool(tool)
        for t, btns in self.tool_buttons.items():
            for b in btns:
                b.setChecked(t == tool)
        self._show_props(tool)
        self._apply_mode()
        self._update_context_bar()
        if tool == Tool.SELECT:
            self._on_selection(self.view.sel_obj)

    def status(self, msg, ms=4000):
        self.statusBar().showMessage(msg, ms)

    def error(self, e):
        traceback.print_exc()
        QMessageBox.critical(self, tr("خطأ"), tr("حدث خطأ أثناء التنفيذ:\n{e}").format(e=e))

    # ================================================================= document lifecycle
    def _refresh_recent(self):
        while self.recent_box.count():
            w = self.recent_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        rec = [p for p in (self.settings.value("recent", []) or []) if os.path.exists(p)][:6]
        if rec:
            lbl = QLabel(tr("الملفات الأخيرة"))
            lbl.setObjectName("Hint")
            self.recent_box.addWidget(lbl)
        for p in rec:
            b = QPushButton(f"{os.path.basename(p)}    —    {os.path.dirname(p)}")
            b.setObjectName("Recent")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, x=p: self.open_file(x))
            self.recent_box.addWidget(b)

    def _add_recent(self, path):
        rec = [p for p in (self.settings.value("recent", []) or []) if p != path]
        rec.insert(0, path)
        self.settings.setValue("recent", rec[:10])
        self._refresh_recent()
        self._refresh_side_recent()

    def maybe_save(self) -> bool:
        if not (self.engine.is_open and self.engine.modified):
            return True
        r = QMessageBox.question(self, tr("تغييرات غير محفوظة"), tr("هل تريد حفظ التغييرات على الملف الحالي؟"),
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def open_dialog(self):
        if not self.maybe_save():
            return
        start = os.path.dirname(self.engine.path) if self.engine.path else self.settings.value("lastdir", "")
        path, _ = QFileDialog.getOpenFileName(self, tr("فتح ملف"), start, OPEN_FILTER)
        if path:
            self.open_file(path, ask=False)

    def open_file(self, path, ask=True):
        if ask and not self.maybe_save():
            return
        eng = PdfDocument()
        pw = None
        while True:
            try:
                eng.open(path, pw)
                break
            except PasswordRequired:
                pw, ok = QInputDialog.getText(self, tr("ملف محمي"), tr("أدخل كلمة مرور الملف:"), QLineEdit.Password)
                if not ok:
                    return
            except Exception as e:
                self.error(e)
                return
        self._set_engine(eng)
        self.settings.setValue("lastdir", os.path.dirname(path))
        if path.lower().endswith(".pdf"):
            self._add_recent(path)

    def _set_engine(self, eng):
        self.engine = eng
        self.view.set_engine(eng)
        self._update_state()
        self.set_mode("read")
        last = 0
        if eng.path:
            try:
                last = int(self.settings.value("lastpage/" + eng.path, 0))
            except (TypeError, ValueError):
                last = 0
        last = min(max(0, last), max(0, eng.page_count - 1))

        def _initial_view():
            self.view.fit_width()
            if last:
                self.view.go_to_page(last)
                self.status(tr("تم الفتح عند آخر صفحة قرأتها ({n})").format(n=last + 1))

        QTimer.singleShot(0, _initial_view)
        self._rebuild_thumbs()
        self._fill_toc()
        self._refresh_objects()
        self.findbar.hide()
        self.selected_text = ""
        self._check_scanned()
        self._update_text_overlay()

    def save(self) -> bool:
        if not self.engine.is_open:
            return False
        if not self.engine.path or not self.engine.path.lower().endswith(".pdf") or not os.path.exists(
                os.path.dirname(self.engine.path) or "."):
            return self.save_as()
        try:
            self.engine.save()
            self.status(tr("تم الحفظ ✔"))
            self._update_state()
            return True
        except Exception as e:
            self.error(e)
            return False

    def save_as(self) -> bool:
        if not self.engine.is_open:
            return False
        path, _ = QFileDialog.getSaveFileName(self, tr("حفظ باسم"), self.engine.path or "document.pdf", "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.engine.save(path)
            self._add_recent(path)
            self.status(tr("تم الحفظ ✔"))
            self._update_state()
            return True
        except Exception as e:
            self.error(e)
            return False

    def closeEvent(self, e):
        if self.maybe_save():
            self.bg.shutdown()
            e.accept()
        else:
            e.ignore()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.on_files_dropped([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def on_files_dropped(self, files):
        pdfs = [f for f in files if f.lower().endswith(".pdf")]
        imgs = [f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"))]
        if self.engine.is_open and imgs and not pdfs:
            d = ImageImportDialog(self, imgs[0], "image", remove_bg=False)
            if d.exec() and d.result_image is not None:
                self.start_place(d.result_image)
            return
        if files:
            self.open_file((pdfs or files)[0])

    # ================================================================= after-change refresh
    def changed(self, pnos=None, structure=False, msg=None):
        self.view.refresh_pages(pnos)
        if structure:
            self._rebuild_thumbs()
        else:
            for p in (pnos if pnos is not None else range(self.engine.page_count)):
                self._queue_thumb(p)
        self._refresh_objects()
        self._refresh_layers()
        self._update_state()
        self.bg.refresh()
        if self.b_showtext.isChecked():
            self._update_text_overlay()
        if msg:
            self.status(msg)

    def run(self, fn, *a, pnos=None, structure=False, msg=None, **kw):
        if not self.engine.is_open:
            return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = fn(*a, **kw)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.error(e)
            self.changed(None, True)
            return None
        QApplication.restoreOverrideCursor()
        self.changed(pnos, structure, msg)
        return res

    def undo(self):
        if self.engine.is_open and self.engine.can_undo():
            label = self.engine.undo()
            self.changed(None, True, tr("تم التراجع: {x}").format(x=label))

    def redo(self):
        if self.engine.is_open and self.engine.can_redo():
            label = self.engine.redo()
            self.changed(None, True, tr("تمت الإعادة: {x}").format(x=label))

    # ================================================================= thumbnails
    # ================================================================= copy / paste / arrange elements
    MIME = "application/x-mesta-pdf-object"

    def copy_object(self, cut=False) -> bool:
        obj = self.view.sel_obj
        if obj is None or self.mode != "edit" or obj.kind in ("line", "block"):
            return False
        from PySide6.QtCore import QByteArray, QMimeData
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data = self.engine.copy_object(obj)
            md = QMimeData()
            md.setData(self.MIME, QByteArray(data))
            try:  # also as a picture, for pasting into other programs
                d = pymupdf.open("pdf", data)
                png = d[0].get_pixmap(dpi=150, alpha=True).tobytes("png")
                d.close()
                md.setImageData(QImage.fromData(png))
            except Exception:
                pass
            QApplication.clipboard().setMimeData(md)
            self._obj_clip = data
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.error(e)
            return False
        QApplication.restoreOverrideCursor()
        if cut:
            self.run(self.engine.delete_object, obj, pnos=[obj.pno], msg=tr("تم القص ✔ — الصقه بـ Ctrl+V"))
        else:
            self.status(tr("تم نسخ العنصر ✔ — الصقه بـ Ctrl+V هنا أو في ملف آخر"))
        return True

    def _clipboard_object(self):
        md = QApplication.clipboard().mimeData()
        if md is not None and md.hasFormat(self.MIME):
            return bytes(md.data(self.MIME))
        if md is not None and md.hasImage():
            img = QImage(md.imageData())
            if not img.isNull():
                return PdfDocument.snippet_from_image(qimage_to_png(img))
        return getattr(self, "_obj_clip", None)

    def paste_object(self, at=None):
        if not self.engine.is_open:
            return
        data = self._clipboard_object()
        if not data:
            self.status(tr("لا يوجد عنصر منسوخ"))
            return
        if self.rtabs.currentIndex() == 0:
            self.rtabs.setCurrentIndex(1)
        pno, pt = at if at else self.view.paste_target()
        before = {o.data["xref"] for o in self.engine.list_layers(pno)}
        self.run(self.engine.paste_object, pno, data, (pt.x(), pt.y()), pnos=[pno], msg=tr("تم اللصق ✔"))
        if self.view.tool not in (Tool.SELECT,):
            self.set_tool(Tool.SELECT)
        self._reselect(pno, None, before)

    def duplicate_object(self):
        obj = self.view.sel_obj
        if obj is None or not self.copy_object():
            return
        c = self.view._sel.rect.translated(-self.view.items_[obj.pno].pos()).center()
        self.paste_object((obj.pno, QPointF(c.x() + 14, c.y() + 14)))

    def arrange(self, where):
        obj = self.view.sel_obj
        if obj is None:
            return
        before = {o.data["xref"] for o in self.engine.list_layers(obj.pno)}
        keep = obj.data.get("xref") if obj.kind == "layer" else None
        msg = {"front": tr("تم إحضار العنصر للأمام ✔"), "back": tr("تم إرسال العنصر للخلف ✔"),
               "forward": tr("تم تقديم العنصر خطوة ✔"), "backward": tr("تم تأخير العنصر خطوة ✔")}[where]
        self.run(self.engine.reorder, obj, where, pnos=[obj.pno], msg=msg)
        self._reselect(obj.pno, keep, before)

    def _object_menu(self, m, obj, ic):
        """Copy / paste / arrange entries shared by the right-click menu."""
        if obj is not None and obj.kind not in ("line", "block"):
            m.addAction(svg_icon("copy", ic), tr("نسخ (Ctrl+C)"), self.copy_object)
            m.addAction(svg_icon("split", ic), tr("قص (Ctrl+X)"), lambda: self.copy_object(cut=True))
            m.addAction(svg_icon("duplicate", ic), tr("تكرار (Ctrl+D)"), self.duplicate_object)
        if self._clipboard_object():
            m.addAction(svg_icon("download", ic), tr("لصق (Ctrl+V)"), self.paste_object)
        if obj is not None and obj.kind not in ("line", "block"):
            arr = m.addMenu(svg_icon("layers", ic), tr("ترتيب"))
            arr.addAction(svg_icon("up", ic), tr("إحضار للأمام"), lambda: self.arrange("front"))
            arr.addAction(svg_icon("up", ic), tr("تقديم خطوة"), lambda: self.arrange("forward"))
            arr.addAction(svg_icon("down", ic), tr("تأخير خطوة"), lambda: self.arrange("backward"))
            arr.addAction(svg_icon("down", ic), tr("إرسال للخلف"), lambda: self.arrange("back"))
        m.addSeparator()

    # ================================================================= collapsible sidebar
    def _side_texts(self, full: bool):
        if getattr(self, "_side_full", None) == full:
            return
        self._side_full = full
        for w in self._side_brand_widgets + [self.recent_title] + self._side_titles:
            w.setVisible(full)
        if full:
            self.recent_title.setVisible(bool(self.side_recent.count()))
        for i in range(self.side_recent.count()):
            w = self.side_recent.itemAt(i).widget()
            if w:
                w.setVisible(full)
        for b, text in self._side_text_btns:
            b.setText(text if full else "")
        m = 14 if full else 10
        self.sidebar.layout().setContentsMargins(m, 18, m, 12)
        self.b_collapse.setText(("  " + tr("طي القائمة")) if full else "")
        self._reg_icon(self.b_collapse, ("next" if self.isRightToLeft() else "prev") if full
                       else ("prev" if self.isRightToLeft() else "next"))

    def toggle_sidebar(self):
        self._set_sidebar(not getattr(self, "_side_collapsed", False))

    def _set_sidebar(self, collapsed: bool, animate=True):
        from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation
        self._side_collapsed = collapsed
        self.settings.setValue("sidebar_collapsed", "true" if collapsed else "false")
        start, end = self.sidebar.width(), (68 if collapsed else 236)
        if not animate:
            self.sidebar.setMinimumWidth(end)
            self.sidebar.setMaximumWidth(end)
            self._side_texts(not collapsed)
            return
        if collapsed:
            self._side_texts(False)
        group = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            a = QPropertyAnimation(self.sidebar, prop, self)
            a.setDuration(280)
            a.setStartValue(start)
            a.setEndValue(end)
            a.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(a)
        if not collapsed:
            group.finished.connect(lambda: self._side_texts(True))
        group.finished.connect(lambda: QTimer.singleShot(0, self._fit_tools))
        group.start()
        self._side_anim = group

    # ================================================================= big files
    def _schedule_thumbs(self):
        """Render only the thumbnails that are on screen (keeps huge files light)."""
        if not self.engine.is_open or self.thumbs.count() == 0:
            return
        vp = self.thumbs.viewport().rect()
        top = self.thumbs.indexAt(vp.topLeft() + QPoint(8, 8)).row()
        bot = self.thumbs.indexAt(vp.bottomLeft() + QPoint(8, -8)).row()
        top = 0 if top < 0 else top
        bot = min(self.thumbs.count() - 1, (top + 8) if bot < 0 else bot + 2)
        for p in range(max(0, top - 2), bot + 1):
            if p in self._thumb_dirty and p not in self._thumb_queue:
                self._thumb_queue.append(p)
        if self._thumb_queue:
            self._thumb_timer.start()

    def _rebuild_thumbs(self):
        self._moving_thumb = True
        self.thumbs.clear()
        blank = QPixmap(10, 13)
        blank.fill(QColor("#ffffff"))
        for p in range(self.engine.page_count):
            it = QListWidgetItem(QIcon(blank), str(p + 1))
            it.setTextAlignment(Qt.AlignCenter)
            self.thumbs.addItem(it)
        self._moving_thumb = False
        self._thumb_queue = []
        self._thumb_dirty = set(range(self.engine.page_count))
        QTimer.singleShot(0, self._schedule_thumbs)

    def _queue_thumb(self, p):
        self._thumb_dirty.add(p)
        QTimer.singleShot(0, self._schedule_thumbs)

    def _thumb_tick(self):
        if not self._thumb_queue or not self.engine.is_open:
            self._thumb_timer.stop()
            return
        p = self._thumb_queue.pop(0)
        if p >= self.thumbs.count() or p >= self.engine.page_count:
            return
        self._thumb_dirty.discard(p)
        w, h = self.engine.page_display_size(p)
        z = min(150 / w, 190 / h) * self.devicePixelRatioF()
        try:
            pix = self.engine.render(p, z)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(self.devicePixelRatioF())
            self.thumbs.item(p).setIcon(QIcon(pm))
        except Exception:
            pass

    def _on_thumb_moved(self, parent, start, end, dest, row):
        if self._moving_thumb:
            return
        final = row if row < start else row - 1
        QTimer.singleShot(0, lambda: self.run(self.engine.move_page, start, final, structure=True,
                                              msg=tr("تم نقل الصفحة")))

    def _selected_pages(self):
        rows = sorted({self.thumbs.row(i) for i in self.thumbs.selectedItems()})
        return rows or [self.view.current_page()]

    def _thumb_menu(self, pos):
        if not self.engine.is_open:
            return
        m = QMenu(self)
        m.addAction(svg_icon("rotate_right", self.ic()), tr("تدوير يمين"), lambda: self.rotate_pages(90))
        m.addAction(svg_icon("rotate_left", self.ic()), tr("تدوير يسار"), lambda: self.rotate_pages(-90))
        m.addAction(svg_icon("duplicate", self.ic()), tr("تكرار"), self.duplicate_page)
        m.addAction(svg_icon("page_add", self.ic()), tr("إدراج صفحة فارغة بعدها"), self.insert_blank)
        m.addAction(svg_icon("extract", self.ic()), tr("استخراج إلى ملف…"), self.extract_selected)
        m.addSeparator()
        m.addAction(svg_icon("page_delete", self.ic()), tr("حذف"), self.delete_pages)
        m.exec(self.thumbs.mapToGlobal(pos))

    def _on_page_changed(self, p):
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(p + 1)
        self.page_spin.blockSignals(False)
        if 0 <= p < self.thumbs.count():
            self.thumbs.blockSignals(True)
            self.thumbs.setCurrentRow(p)
            self.thumbs.blockSignals(False)
        if self.engine.is_open and self.engine.path:
            self.settings.setValue("lastpage/" + self.engine.path, p)
        if hasattr(self, "bg"):
            self.bg.focus(p)
        if hasattr(self, "b_showtext") and self.b_showtext.isChecked():
            self._update_text_overlay()
        if self.mode == "edit":
            self._refresh_objects()
            if not self.chk_all_layers.isChecked():
                self._refresh_layers()

    # ================================================================= objects panel
    def _refresh_objects(self):
        return  # the old "Elements" panel was removed to keep the interface simple
        self.obj_list.clear()
        if not self.engine.is_open or self.engine.page_count == 0:
            return
        p = self.view.current_page()
        if p >= self.engine.page_count:
            return
        objs = self.view.objects(p)
        for o, r in objs["images"] + objs["annots"] + objs["drawings"]:
            try:
                clip = pymupdf.Rect(r.x(), r.y(), r.right(), r.bottom())
                z = min(4.0, 56 / max(1, clip.width), 56 / max(1, clip.height))
                pix = self.engine.render(p, max(z, 0.05), clip=clip)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
                icon = QIcon(QPixmap.fromImage(img))
            except Exception:
                icon = svg_icon("image", self.ic())
            extra = ""
            if o.kind == "image":
                n = self.engine.count_similar_images(o)
                extra = tr("\nموجودة في {n} موضع بالملف").format(n=n) if n > 1 else ""
                if o.data.get("full_page"):
                    extra += tr("\n(صورة الصفحة بالكامل — سكان)")
            it = QListWidgetItem(icon, o.label + extra)
            it.setData(Qt.UserRole, (o, r))
            self.obj_list.addItem(it)
        if self.obj_list.count() == 0:
            it = QListWidgetItem(tr("لا توجد صور أو أختام في هذه الصفحة"))
            it.setFlags(Qt.NoItemFlags)
            self.obj_list.addItem(it)

    def _on_obj_item(self, it):
        d = it.data(Qt.UserRole)
        if not d:
            return
        o, r = d
        if self.view.tool != Tool.SELECT:
            self.set_tool(Tool.SELECT)
        self.view.select(o, r)
        self.view.go_to_page(o.pno, r)

    def _obj_action(self, key):
        it = self.obj_list.currentItem()
        d = it.data(Qt.UserRole) if it else None
        if not d:
            QMessageBox.information(self, tr("العناصر"), tr("اختر عنصراً من القائمة أولاً."))
            return
        self.on_float_action(key, d[0])

    def delete_all_images_on_page(self):
        if not self.engine.is_open:
            return
        p = self.view.current_page()
        objs = self.engine.get_objects(p)["images"]
        if not objs:
            return
        if QMessageBox.question(self, tr("تأكيد"), tr("حذف {n} صورة/ختم من هذه الصفحة؟").format(n=len(objs))) != QMessageBox.Yes:
            return

        def work():
            self.engine.checkpoint(tr("حذف كل الصور"))
            for _ in range(len(objs) + 5):
                imgs = self.engine.get_objects(p)["images"]
                if not imgs:
                    break
                self.engine._delete_image_instance(self.engine.page(p), imgs[-1])
                self.engine.invalidate(p)

        self.run(work, pnos=[p], msg=tr("تم حذف الصور"))

    # ================================================================= selection / object actions
    def _on_selection(self, obj):
        self._update_context_bar()
        if self.view.tool != Tool.SELECT:
            return
        if obj is None:
            self.sel_info.setText(tr("لم يتم تحديد عنصر.\nاضغط على أي صورة أو ختم في الصفحة."))
            for b in self.sel_btns.values():
                b.setVisible(False)
            return
        self.sel_info.setText(obj.label)
        vis = {"image": {"delete", "delete_all", "replace", "save"}, "annot": {"delete"}, "drawing": {"delete"},
               "layer": {"delete", "edit"} if obj.data.get("meta", {}).get("kind") == "text" else {"delete"},
               "line": {"edit", "delete"}, "block": {"edit", "delete"}}.get(obj.kind, set())
        for k, b in self.sel_btns.items():
            b.setVisible(k in vis)

    def on_float_action(self, key, obj):
        if obj is None:
            return
        if key == "delete":
            self.run(self.engine.delete_object, obj, pnos=[obj.pno], msg=tr("تم الحذف ✔"))
        elif key == "delete_all":
            n = self.engine.count_similar_images(obj)
            if QMessageBox.question(self, tr("حذف من كل الصفحات"),
                                    tr("سيتم حذف هذه الصورة/الختم من {n} موضع في الملف. متابعة؟").format(n=n)) != QMessageBox.Yes:
                return
            c = self.run(self.engine.delete_similar_images, obj, msg=tr("تم الحذف من كل الصفحات ✔"))
            if c is not None:
                self.status(tr("تم حذف {n} نسخة ✔").format(n=c))
        elif key == "replace":
            path, _ = QFileDialog.getOpenFileName(self, tr("صورة بديلة"), "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
            if path:
                self.run(self.engine.replace_image, obj, path, pnos=[obj.pno], msg=tr("تم استبدال الصورة"))
        elif key == "save":
            path, _ = QFileDialog.getSaveFileName(self, tr("حفظ الصورة"), "image.png", "PNG (*.png);;JPEG (*.jpg)")
            if path:
                try:
                    self.engine.save_image(obj, path)
                    self.status(tr("تم حفظ الصورة"))
                except Exception as e:
                    self.error(e)
        elif key in ("edit", "edit_layer"):
            self.edit_text(obj)
        elif key == "hide_layer":
            self.run(self.engine.set_layer_visible, obj, False, pnos=[obj.pno], msg=tr("تم إخفاء الطبقة — أظهرها من لوحة الطبقات"))
        elif key == "flatten_layer":
            self.run(self.engine.flatten_layer, obj, pnos=[obj.pno], msg=tr("تم دمج الطبقة في الصفحة"))

    def on_move(self, obj, rect: QRectF):
        new = self.engine.to_pdf(obj.pno, (rect.x(), rect.y(), rect.right(), rect.bottom()))
        before = {o.data["xref"] for o in self.engine.list_layers(obj.pno)}
        keep = obj.data.get("xref") if obj.kind == "layer" else None
        self.run(self.engine.move_object, obj, new, pnos=[obj.pno], msg=tr("تم النقل"))
        self._reselect(obj.pno, keep, before)

    def _reselect(self, pno, xref=None, before=None):
        """Keep the moved / lifted item selected so it can be adjusted again right away."""
        lays = self.engine.list_layers(pno)
        hit = [o for o in lays if o.data["xref"] == xref] if xref else \
            [o for o in lays if before is not None and o.data["xref"] not in before]
        if hit:
            o = hit[-1]
            d = self.engine.to_display(pno, o.rect)
            self.view.select(o, QRectF(d.x0, d.y0, d.width, d.height))

    def on_context(self, obj, gpos):
        if not self.engine.is_open:
            return
        m = QMenu(self)
        ic = self.ic()
        if self.mode == "read":
            if self.selected_text:
                m.addAction(svg_icon("copy", ic), tr("نسخ النص المحدد"), self.copy_selection)
            m.addAction(svg_icon("copy", ic), tr("نسخ نص الصفحة"), self.copy_page_text)
            m.addAction(svg_icon("text_cursor", ic), tr("تحديد كل النص (Ctrl+A)"), self.select_all_text)
            m.addSeparator()
            m.addAction(svg_icon("fit_width", ic), tr("ملء العرض"), self.view.fit_width)
            m.addAction(svg_icon("fullscreen", ic), tr("ملء الشاشة"), self.toggle_fullscreen)
            m.addSeparator()
            m.addAction(svg_icon("edit_text", ic), tr("تحرير هذا الملف"), lambda: self.set_mode("edit"))
            m.exec(gpos)
            return
        self._object_menu(m, obj, ic)
        if obj is not None:
            if obj.kind in ("line", "block"):
                m.addAction(svg_icon("edit_text", ic), tr("تعديل النص"), lambda: self.edit_text(obj))
                m.addAction(svg_icon("duplicate", ic), tr("نسخ النص"),
                            lambda: QApplication.clipboard().setText(obj.data.get("text", "")))
            if obj.kind == "image":
                m.addAction(svg_icon("replace_image", ic), tr("استبدال الصورة…"), lambda: self.on_float_action("replace", obj))
                m.addAction(svg_icon("download", ic), tr("حفظ الصورة…"), lambda: self.on_float_action("save", obj))
                m.addAction(svg_icon("delete_all", ic), tr("حذف من كل الصفحات"),
                            lambda: self.on_float_action("delete_all", obj))
            m.addAction(svg_icon("delete", ic), tr("حذف"), lambda: self.on_float_action("delete", obj))
            m.addSeparator()
        m.addAction(svg_icon("add_text", ic), tr("إضافة نص هنا"), lambda: self.set_tool(Tool.ADD_TEXT))
        m.addAction(svg_icon("stamp", ic), tr("إدراج ختم"), self.insert_stamp)
        m.addAction(svg_icon("signature", ic), tr("إدراج توقيع"), self.insert_signature)
        m.addAction(svg_icon("image", ic), tr("إدراج صورة"), self.insert_image)
        m.exec(gpos)

    # ================================================================= layers
    def _refresh_layers(self):
        if not hasattr(self, "layer_list"):
            return
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        if self.engine.is_open and self.mode == "edit":
            lays = self.engine.all_layers() if self.chk_all_layers.isChecked() else \
                self.engine.list_layers(self.view.current_page())
            icons = {"text": "add_text", "image": "image", "stamp": "stamp", "signature": "signature",
                     "rect": "rect", "ellipse": "ellipse", "line": "line", "arrow": "arrow", "ink": "pen"}
            for o in reversed(lays):  # top-most first, like Photoshop
                m = o.data["meta"]
                txt = m.get("name", "")
                if m.get("kind") == "text" and m.get("text"):
                    txt += "  —  " + m["text"].replace("\n", " ")[:30]
                if self.chk_all_layers.isChecked():
                    txt += tr("   (ص {n})").format(n=o.pno + 1)
                it = QListWidgetItem(svg_icon(icons.get(m.get("kind"), "layers"), self.ic()), txt)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if o.data.get("visible", True) else Qt.Unchecked)
                it.setToolTip(tr("علّم للإظهار / ألغِ العلامة للإخفاء"))
                it.setData(Qt.UserRole, o)
                self.layer_list.addItem(it)
            if not lays:
                it = QListWidgetItem(tr("لا توجد طبقات بعد — أي نص أو ختم أو صورة أو شكل تضيفه سيظهر هنا"))
                it.setFlags(Qt.NoItemFlags)
                self.layer_list.addItem(it)
        self.layer_list.blockSignals(False)

    def _on_layer_check(self, it):
        o = it.data(Qt.UserRole)
        if o is None:
            return
        on = it.checkState() == Qt.Checked
        self.run(self.engine.set_layer_visible, o, on, msg=tr("تم إظهار الطبقة") if on else tr("تم إخفاء الطبقة"))

    def _on_layer_item(self, it):
        o = it.data(Qt.UserRole)
        if o is None:
            return
        if self.view.tool != Tool.SELECT:
            self.set_tool(Tool.SELECT)
        r = self.engine.to_display(o.pno, o.rect)
        qr = QRectF(r.x0, r.y0, r.width, r.height)
        self.view.go_to_page(o.pno, qr)
        if o.data.get("visible", True):
            self.view.select(o, qr)

    def _layer_action(self, key):
        it = self.layer_list.currentItem()
        o = it.data(Qt.UserRole) if it else None
        if o is None:
            QMessageBox.information(self, tr("الطبقات"), tr("اختر طبقة من القائمة أولاً."))
            return
        if key == "edit":
            if o.data["meta"].get("kind") == "text":
                self.edit_layer(o)
            else:
                self._on_layer_item(it)
                self.status(tr("اسحب الطبقة لنقلها أو اسحب زواياها لتغيير الحجم"))
        elif key == "rename":
            name, ok = QInputDialog.getText(self, tr("إعادة تسمية"), tr("اسم الطبقة:"), text=o.data["meta"].get("name", ""))
            if ok and name.strip():
                self.run(self.engine.rename_layer, o, name.strip(), pnos=[o.pno])
        elif key in ("up", "down"):
            self.run(self.engine.reorder, o, "forward" if key == "up" else "backward", pnos=[o.pno],
                     msg=tr("تم تقديم العنصر خطوة ✔") if key == "up" else tr("تم تأخير العنصر خطوة ✔"))
            for i in range(self.layer_list.count()):  # keep the same layer highlighted in the list
                lo = self.layer_list.item(i).data(Qt.UserRole)
                if lo is not None and lo.data.get("xref") == o.data.get("xref"):
                    self.layer_list.setCurrentRow(i)
        elif key == "flatten":
            self.run(self.engine.flatten_layer, o, pnos=[o.pno], msg=tr("تم دمج الطبقة في الصفحة"))
        elif key == "delete":
            self.run(self.engine.delete_layer, o, pnos=[o.pno], msg=tr("تم حذف الطبقة"))

    def _layer_at(self, obj):
        c = obj.rect.tl + (obj.rect.br - obj.rect.tl) * 0.5
        for lay in self.engine.list_layers(obj.pno):
            if lay.data["meta"].get("kind") == "text" and lay.rect.contains(c):
                return lay
        return None

    def edit_layer(self, obj):
        m = obj.data["meta"]
        st = dict(m.get("style", {}))
        if isinstance(st.get("color"), list):
            st["color"] = tuple(st["color"])
        st["align"] = m.get("align", "left")
        dlg = TextEditDialog(self, tr("تعديل {x}").format(x=m.get('name', '')), m.get("text", ""), st, multiline=True,
                             show_align=True, allow_original=False)
        place_near_cursor(dlg)
        if not dlg.exec():
            return
        if dlg.deleted:
            self.run(self.engine.delete_layer, obj, pnos=[obj.pno], msg=tr("تم حذف الطبقة"))
            return
        self.run(self.engine.edit_text_layer, obj, dlg.text(), dlg.style(), dlg.align(), pnos=[obj.pno],
                 msg=tr("تم تعديل الطبقة ✔"))

    # ================================================================= objects inside scans
    def on_scan_picked(self, pno, r: QRectF):
        self._separate(pno, r)

    # ================================================================= options bar (above the page)
    MM = 25.4 / 72.0

    def _build_context_bar(self):
        bar = QFrame()
        bar.setObjectName("ContextBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 5, 12, 5)
        h.setSpacing(8)
        # what a dragged box takes (Select element)
        self.ctx_take = QWidget()
        th = QHBoxLayout(self.ctx_take)
        th.setContentsMargins(0, 0, 0, 0)
        th.addWidget(QLabel(tr("عند سحب مربع خذ:")))
        self.take_el = QCheckBox(tr("العناصر"))
        self.take_el.setChecked(True)
        self.take_tx = QCheckBox(tr("النص"))
        self.take_ln = QCheckBox(tr("خطوط الجداول"))
        self.take_ln.setToolTip(tr("أو اضغط Shift أثناء السحب"))
        for w in (self.take_el, self.take_tx, self.take_ln):
            th.addWidget(w)
        h.addWidget(self.ctx_take)
        # size / position of the selected item
        self.ctx_geo = QWidget()
        gh = QHBoxLayout(self.ctx_geo)
        gh.setContentsMargins(0, 0, 0, 0)
        gh.setSpacing(4)
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setObjectName("CtxSep")
        gh.addWidget(sep)
        self.geo = {}
        for key, lbl in (("w", tr("العرض")), ("h", tr("الارتفاع")), ("x", tr("الموضع أفقياً")), ("y", tr("الموضع رأسياً"))):
            gh.addWidget(QLabel(lbl))
            sp = QDoubleSpinBox()
            sp.setRange(-2000, 5000)
            sp.setDecimals(1)
            sp.setSuffix(tr(" مم"))
            sp.setFixedWidth(84)
            sp.setButtonSymbols(QDoubleSpinBox.NoButtons)
            sp.setAlignment(Qt.AlignCenter)
            sp.setKeyboardTracking(False)
            sp.valueChanged.connect(lambda _v, k=key: self._geo_changed(k))
            gh.addWidget(sp)
            self.geo[key] = sp
        self.geo_lock = QCheckBox(tr("قفل النسبة"))
        self.geo_lock.setChecked(True)
        gh.addWidget(self.geo_lock)
        h.addWidget(self.ctx_geo)
        self.ctx_hint = QLabel("")
        self.ctx_hint.setObjectName("Hint")
        h.addWidget(self.ctx_hint)
        h.addStretch(1)
        self.ctx_bar = bar
        self._geo_obj = None
        self._geo_block = False
        # never let this bar force the window wider than the screen (it clips instead)
        bar.setSizePolicy(QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed))
        self.ctx_hint.setSizePolicy(QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred))
        bar.hide()

    def take_set(self, shift=False):
        s = set()
        if self.take_el.isChecked():
            s.add("elements")
        if self.take_tx.isChecked():
            s.add("text")
        if self.take_ln.isChecked() or shift:
            s.add("lines")
        return s or {"elements"}

    def _update_context_bar(self):
        t = self.view.tool
        has = self.engine.is_open
        sel = self.view.sel_obj
        movable = sel is not None and sel.kind in ("layer", "image", "drawing")
        self.ctx_take.setVisible(has and t == Tool.SELECT)
        self.ctx_geo.setVisible(has and t == Tool.SELECT and movable)
        hint = ""
        if t == Tool.EDIT_TEXT:
            hint = tr("اضغط على سطر لتعديله، أو اسحب مربعاً حول الجزء الذي تريد تعديله")
        elif t == Tool.SELECT and not movable:
            hint = tr("اضغط على عنصر، أو اسحب مربعاً — ثم اسحب الحواف لتمديد العرض أو الارتفاع")
        self.ctx_hint.setText(hint)
        self.ctx_hint.setVisible(bool(hint))
        self.ctx_bar.setVisible(has and t in (Tool.SELECT, Tool.EDIT_TEXT) and not self.isFullScreen())
        if movable:
            r = self.view._sel.rect.translated(-self.view.items_[sel.pno].pos())
            self._geo_obj = sel
            self._geo_block = True
            for k, v in (("w", r.width()), ("h", r.height()), ("x", r.x()), ("y", r.y())):
                self.geo[k].setValue(v * self.MM)
            self._geo_block = False
        else:
            self._geo_obj = None

    def _geo_changed(self, key):
        if self._geo_block or self._geo_obj is None:
            return
        obj = self._geo_obj
        r = self.view._sel.rect.translated(-self.view.items_[obj.pno].pos())
        w, h = self.geo["w"].value() / self.MM, self.geo["h"].value() / self.MM
        x, y = self.geo["x"].value() / self.MM, self.geo["y"].value() / self.MM
        if self.geo_lock.isChecked() and r.width() > 0 and r.height() > 0:
            if key == "w":
                h = w * r.height() / r.width()
            elif key == "h":
                w = h * r.width() / r.height()
        if w < 2 or h < 2:
            return
        self.on_move(obj, QRectF(x, y, w, h))

    def _lift(self, pno, r: QRectF, include):
        rect = (r.x(), r.y(), r.right(), r.bottom())
        before = {o.data["xref"] for o in self.engine.list_layers(pno)}
        ok = self.run(self.engine.lift_region, pno, rect, tuple(include), pnos=[pno])
        if not ok:
            self.status(tr("لا يوجد شيء من النوع المختار داخل هذا المربع"))
            return
        self._reselect(pno, None, before)
        self.status(tr("تم التحويل إلى طبقة ✔ — اسحب الحواف لتغيير العرض أو الارتفاع"))

    def edit_area(self, pno, r: QRectF):
        rect = (r.x(), r.y(), r.right(), r.bottom())
        text, style, lines = self.engine.area_text(pno, rect)
        st = dict(style)
        if not lines:  # nothing recognised: read this spot now and guess the size from the ink itself
            if self.engine._scan_under(pno, self.engine.to_pdf(pno, rect)):
                text = self.engine.ocr_snippet(pno, rect) or text
            box = self.engine.scan_text_box(pno, self.engine.to_pdf(pno, rect), grow=0)
            st["size"] = round(max(6.0, min(40.0, box.height * 1.3)), 1)
            _, st["color"] = self.engine.sample_colors(pno, box)
        st["align"] = "right" if (has_rtl(text) or not text) else "left"
        dlg = TextEditDialog(self, tr("تعديل نص المنطقة"), text, st, multiline=True, show_align=True,
                             allow_original=False)
        place_near_cursor(dlg)
        if not dlg.exec():
            return
        new = "" if dlg.deleted else dlg.text()
        before = {o.data["xref"] for o in self.engine.list_layers(pno)}
        self.run(self.engine.edit_text_area, pno, rect, new, dlg.style(), dlg.align(), pnos=[pno],
                 msg=tr("تم تعديل النص ✔ — يمكنك سحبه أو تمديده"))
        self.set_tool(Tool.SELECT)
        self._reselect(pno, None, before)

    def _separate(self, pno, r: QRectF, keep_lines=False):
        """Cut a stamp / logo / signature out of a scanned page into its own layer, then select it."""
        rect = (r.x(), r.y(), r.right(), r.bottom())
        before = {o.data["xref"] for o in self.engine.list_layers(pno)}
        ok = self.run(self.engine.auto_extract, pno, rect, keep_lines, pnos=[pno])
        if not ok:
            self.status(tr("لا يوجد عنصر داخل سكان هنا — اسحب مربعاً حول الختم أو الشعار"))
            return
        new = [o for o in self.engine.list_layers(pno) if o.data["xref"] not in before]
        if new:
            o = new[-1]
            d = self.engine.to_display(pno, o.rect)
            self.view.select(o, QRectF(d.x0, d.y0, d.width, d.height))
        self.status(tr("تم فصل العنصر ✔ — اسحبه لنقله، أو Delete لحذفه"))

    def detect_objects(self):
        if not self.engine.is_open:
            return
        p = self.view.current_page()
        found = self.engine.detect_scan_objects(p)
        if not found:
            QMessageBox.information(self, tr("اكتشاف الأختام والشعارات"),
                                    tr("لم يتم العثور على أختام أو شعارات ملونة في هذه الصفحة.\n"
                                       "للشعارات السوداء: استخدم أداة \"فصل عنصر كطبقة\" وارسم مستطيلاً حول الشعار."))
            return
        d = DetectDialog(self, self.engine, p, found)
        if not d.exec():
            return
        items = d.selected()
        kind = d.cb_kind.currentData()

        def work():
            n = 0
            self.engine.checkpoint(tr("فصل عنصر من السكان"))
            for r, thr in items:
                if self.engine.extract_from_scan(p, r, "color", thr, kind, checkpoint=False):
                    n += 1
            return n

        n = self.run(work, pnos=[p])
        if n:
            self.side_tabs.setCurrentIndex(2)
            self.status(tr("تم فصل {n} عنصر كطبقات مستقلة ✔").format(n=n))

    # ================================================================= OCR
    def _check_scanned(self):
        # scanned files are recognised silently in the background (no banner)
        self.scan_bar.hide()
        self.bg.restart()

    def check_updates(self):
        """Updates come through Mesta Launcher when it is installed; PDF Pro itself never depends on it."""
        import subprocess

        from .brand import VERSION
        from .system import find_mesta_launcher
        exe = find_mesta_launcher()
        if exe:
            try:
                subprocess.Popen([exe, "--updates"], close_fds=True)
                self.status(tr("جارٍ التحقق من التحديثات في Mesta Launcher…"))
                return
            except OSError:
                pass
        QMessageBox.information(
            self, tr("التحقق من التحديثات"),
            tr("الإصدار الحالي: {v}\n\nالتحديثات التلقائية لكل برامج Mesta متاحة عبر Mesta Launcher — ثبّته لتصلك التحديثات الموقّعة تلقائياً.").format(v=VERSION))

    def toggle_auto_ocr(self, on):
        self.settings.setValue("auto_ocr", "true" if on else "false")
        if on:
            self.bg.restart()
            self.status(tr("التعرف التلقائي على النص: مفعّل"))
        else:
            self.bg.queue = []
            self.bg.timer.stop()
            self.status(tr("التعرف التلقائي على النص: متوقف — يمكنك تشغيله يدوياً من الصفحات ← أدوات"))

    def _update_text_overlay(self):
        if not (self.engine.is_open and self.b_showtext.isChecked()):
            self.view.set_text_boxes({})
            return
        boxes = {}
        cur = self.view.current_page()  # only pages around the one being read (fast on huge files)
        for p in range(max(0, cur - 2), min(self.engine.page_count, cur + 3)):
            rects = []
            for o in self.engine.get_objects(p)["lines"]:
                d = self.engine.to_display(p, o.rect)
                rects.append(QRectF(d.x0, d.y0, d.width, d.height))
            boxes[p] = rects
        self.view.set_text_boxes(boxes)

    def on_background_page_ready(self, pno):
        self.view._objs.pop(pno, None)
        if self.b_showtext.isChecked():
            self._update_text_overlay()
        if self.findbar.isVisible() and self.findbar.ed.text():
            self.do_search(self.findbar.ed.text())

    def select_all_text(self):
        if not self.engine.is_open:
            return
        p = self.view.current_page()
        r = self.engine.doc[p].rect
        text, rects = self.engine.words_in(p, (r.x0, r.y0, r.x1, r.y1))
        self.view.set_text_selection(p, [QRectF(x.x0, x.y0, x.width, x.height) for x in rects])
        self.selected_text = text
        if text:
            QApplication.clipboard().setText(text)
            self.status(tr("تم نسخ {n} حرف ✔").format(n=len(text)))
        elif self.bg.busy_with(p):
            self.bg.focus(p)
            self.status(tr("جاري تجهيز نص هذه الصفحة للنسخ… حاول بعد لحظات"))

    def run_ocr(self):
        if not self.engine.is_open:
            return
        import threading
        import time
        from .engine import ocr_languages, ocr_run
        langs = ocr_languages()
        if not langs:
            QMessageBox.warning(self, "OCR", tr("ملفات لغات التعرف (tessdata) غير موجودة بجوار البرنامج."))
            return
        d = OcrDialog(self, langs)
        # pages already read in the background are read again only if the user wants
        d.chk_skip.setChecked(any(not self.engine.has_text(p) for p in range(self.engine.page_count)))
        if not d.exec():
            return
        lang, dpi = d.language(), d.dpi()
        pages = d.pages.pages(self.engine.page_count, self.view.current_page())
        if d.chk_skip.isChecked():
            pages = [p for p in pages if not self.engine.has_text(p)]
        if not pages:
            QMessageBox.information(self, "OCR", tr("كل الصفحات المحددة بها نص بالفعل."))
            return
        self.engine.checkpoint(tr("التعرف على النص"))
        self.bg.timer.stop()
        from PySide6.QtWidgets import QProgressDialog
        prog = QProgressDialog(tr("جاري التعرف على النص…"), tr("إلغاء"), 0, len(pages), self)
        prog.setWindowTitle(tr("التعرف على النص (OCR)"))
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        self.view._render_timer.stop()
        self._thumb_timer.stop()
        done = 0
        for i, p in enumerate(pages):
            prog.setValue(i)
            prog.setLabelText(tr("صفحة {p}   ({i} من {n})\nالعربية تحتاج حوالي 10-20 ثانية للصفحة…").format(p=p + 1, i=i + 1, n=len(pages)))
            QApplication.processEvents()
            if prog.wasCanceled():
                break
            pix = self.engine.ocr_prepare(p, dpi)
            box = {}

            def work(px=pix):
                try:
                    if lang == "auto":
                        from . import ocr_worker
                        from .engine import TESSDATA
                        box["data"] = ocr_worker.run_auto(px.tobytes("pnm"), TESSDATA, langs)[0]
                    else:
                        box["data"] = ocr_run(px, lang)
                except Exception as ex:  # noqa
                    box["err"] = ex

            th = threading.Thread(target=work, daemon=True)
            th.start()
            while th.is_alive():
                QApplication.processEvents()
                time.sleep(0.03)
            if "err" in box:
                prog.close()
                self.error(box["err"])
                break
            if prog.wasCanceled():
                break
            self.engine.ocr_apply(p, box["data"], replace=True)
            done += 1
        prog.setValue(len(pages))
        if not done:
            self.engine.drop_last_checkpoint()
        self.changed(None, True, tr("تم التعرف على النص في {n} صفحة ✔").format(n=done))
        self.bg.refresh()
        if done:  # show what was recognised
            self.b_showtext.setChecked(True)
        self._update_text_overlay()

    # ================================================================= text
    def edit_text(self, obj):
        if obj.kind == "layer":
            if obj.data["meta"].get("kind") == "text":
                self.edit_layer(obj)
            return
        lay = self._layer_at(obj)
        if lay is not None:
            self.edit_layer(lay)
            return
        is_block = obj.kind == "block" and len(obj.data.get("lines", [])) > 1
        d = obj.data
        style = {"family": ORIGINAL_FONT, "size": d.get("size", 12), "color": d.get("color", (0, 0, 0)),
                 "bold": bool(d.get("flags", 0) & 16), "italic": bool(d.get("flags", 0) & 2),
                 "align": "right" if has_rtl(d.get("text", "")) else "left"}
        if d.get("ocr") and self.view.last_click and self.view.last_click[0] == obj.pno:
            # does the recognised field really match the ink under the click? (OCR can mis-group words)
            p = self.view.last_click[1]
            self.view.last_click = None
            ink = self.engine.scan_text_box(obj.pno, self.engine.to_pdf(obj.pno, (p.x() - 1, p.y() - 1, p.x() + 1, p.y() + 1)), grow=4)
            inter = ink & obj.rect
            if abs(ink) > 9 and (not inter.is_valid or abs(inter) < 0.5 * abs(ink) or abs(obj.rect) > 5 * abs(ink)):
                di = self.engine.to_display(obj.pno, ink)
                self.edit_area(obj.pno, QRectF(di.x0, di.y0, di.width, di.height))
                return
        if d.get("ocr"):
            box = self.engine.scan_text_box(obj.pno, obj.rect)
            _, fg = self.engine.sample_colors(obj.pno, box)
            size = box.height * (1.0 if has_rtl(d.get("text", "")) else 1.3)
            style.update(family="Arial", color=fg, size=round(max(6.0, min(40.0, size)), 1))
        block = None
        if obj.kind == "line":
            block = next((b for b in self.engine.get_objects(obj.pno)["blocks"]
                          if any(ln is obj for ln in b.data.get("lines", [])) and len(b.data.get("lines", [])) > 1), None)
        dlg = TextEditDialog(self, tr("تعديل فقرة") if is_block else tr("تعديل النص"), d.get("text", ""), style,
                             multiline=is_block, show_align=is_block, allow_original=not d.get("ocr"),
                             allow_expand=block is not None)
        place_near_cursor(dlg)
        if not dlg.exec():
            if dlg.expand and block is not None:
                self.edit_text(block)
            return
        if dlg.deleted:
            self.run(self.engine.delete_text, obj, pnos=[obj.pno], msg=tr("تم حذف النص"))
            return
        new = dlg.text()
        if new == d.get("text", "") and dlg.style()["family"] == ORIGINAL_FONT and \
                abs(dlg.style()["size"] - d.get("size", 12)) < 0.05 and dlg.style()["color"] == tuple(style["color"]):
            return
        if is_block:
            self.run(self.engine.edit_text_block, obj, new, dlg.style(), dlg.align(), pnos=[obj.pno], msg=tr("تم التعديل ✔"))
        else:
            if obj.kind == "block":
                obj = obj.data["lines"][0]
            self.run(self.engine.edit_text_line, obj, new, dlg.style(), pnos=[obj.pno], msg=tr("تم التعديل ✔"))

    def add_text(self, pno, pt: QPointF):
        dlg = TextEditDialog(self, tr("إضافة نص"), "", self.last_text_style, multiline=True, show_align=True,
                             allow_original=False, allow_delete=False)
        place_near_cursor(dlg)
        if not dlg.exec() or not dlg.text().strip():
            return
        st = dlg.style()
        self.last_text_style = dict(st)
        self.run(self.engine.add_text, pno, (pt.x(), pt.y()), dlg.text(), st, st.get("align", "left"),
                 pnos=[pno], msg=tr("تمت إضافة النص"))

    # ================================================================= search
    def open_find(self, replace):
        if not self.engine.is_open:
            return
        self.findbar.open(replace)

    def do_search(self, text):
        """Search page by page in small chunks so even huge files never freeze."""
        self._search_gen = getattr(self, "_search_gen", 0) + 1
        gen = self._search_gen
        self.search_hits = []
        self.search_idx = -1
        if not text or not self.engine.is_open:
            self.view.set_search_hits({})
            return
        n = self.engine.page_count
        state = {"p": 0}

        def step():
            if gen != self._search_gen or not self.engine.is_open:
                return
            end = min(n, state["p"] + 25)
            for p in range(state["p"], end):
                for pp, r in self.engine.find_in_page(p, text):
                    self.search_hits.append((pp, QRectF(*self._disp(pp, r))))
            state["p"] = end
            if self.search_hits and self.search_idx < 0:
                self.search_idx = 0
                self._show_hits()
            if end < n:
                self.findbar.lbl.setText(tr("جاري البحث… {p} / {n}").format(p=end, n=n))
                QTimer.singleShot(0, step)
            else:
                self.findbar.lbl.setText(tr("{n} نتيجة").format(n=len(self.search_hits)) if self.search_hits
                                         else tr("لا توجد نتائج"))
                if self.search_hits:
                    self._show_hits()
        step()

    def _disp(self, p, r):
        d = self.engine.to_display(p, r)
        return d.x0, d.y0, d.width, d.height

    def _show_hits(self):
        grouped = {}
        for p, r in self.search_hits:
            grouped.setdefault(p, []).append(r)
        cur = self.search_hits[self.search_idx] if self.search_idx >= 0 else None
        self.view.set_search_hits(grouped, cur)
        if cur:
            self.view.go_to_page(cur[0], cur[1])
            self.findbar.lbl.setText(tr("{i} من {n}").format(i=self.search_idx + 1, n=len(self.search_hits)))

    def search_nav(self, d):
        if not self.search_hits:
            self.do_search(self.findbar.ed.text())
            return
        self.search_idx = (self.search_idx + d) % len(self.search_hits)
        self._show_hits()

    def do_replace_all(self, find, rep):
        if not find:
            return
        n = self.run(self.engine.replace_all, find, rep)
        self.view.set_search_hits({})
        self.search_hits = []
        QMessageBox.information(self, tr("استبدال"), tr("تم استبدال {n} موضع.").format(n=n or 0))

    # ================================================================= insert image / stamp / signature
    def start_place(self, img: QImage, width_pt=None, kind="image"):
        self.place_kind = kind
        if not self.engine.is_open or img is None or img.isNull():
            return
        if self.mode != "edit":
            self.set_mode("edit")
        self.place_base = img
        self.pl_op.blockSignals(True)
        self.pl_rot.blockSignals(True)
        self.pl_op.setValue(100)
        self.pl_rot.setValue(0)
        self.pl_op.blockSignals(False)
        self.pl_rot.blockSignals(False)
        self.view.start_place(img, width_pt)
        self._show_props("place")

    def _update_place(self):
        if self.place_base is not None and self.view.placing():
            self.view.update_place_image(
                apply_opacity_rotation(self.place_base, self.pl_op.value() / 100, self.pl_rot.value()))

    def insert_image(self):
        if not self.engine.is_open:
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("اختر صورة"), self.settings.value("imgdir", ""),
                                              "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.gif)")
        if not path:
            return
        self.settings.setValue("imgdir", os.path.dirname(path))
        d = ImageImportDialog(self, path, "image", remove_bg=False)
        if d.exec() and d.result_image is not None:
            self.start_place(d.result_image)

    def insert_stamp(self):
        if not self.engine.is_open:
            return
        d = StampDialog(self)
        if d.exec() and d.result_image is not None:
            self.start_place(d.result_image, 120, "stamp")

    def insert_signature(self):
        if not self.engine.is_open:
            return
        d = SignatureDialog(self)
        if d.exec() and d.result_image is not None:
            self.start_place(d.result_image, 150, "signature")

    def on_place_commit(self, pno, rect: QRectF, img: QImage, all_pages):
        png = qimage_to_png(img)
        r = (rect.x(), rect.y(), rect.right(), rect.bottom())
        kind = getattr(self, "place_kind", "image")
        self.run(self.engine.insert_image, pno, r, png, all_pages, {"stamp": tr("إضافة ختم"), "signature": tr("إضافة توقيع")}.get(kind, tr("إضافة صورة")),
                 kind, pnos=None if all_pages else [pno], msg=tr("تمت الإضافة كطبقة مستقلة ✔"))
        self._show_props(self.view.tool)

    # ================================================================= area / annotation tools
    def _ann(self):
        c = self.ann_color.color
        return (c.redF(), c.greenF(), c.blueF()), self.ann_width.value(), self.ann_op.value() / 100

    def on_area(self, tool, pno, r: QRectF):
        rect = (r.x(), r.y(), r.right(), r.bottom())
        col, w, op = self._ann()
        if tool == Tool.TEXT:
            text, rects = self.engine.words_in(pno, rect)
            self.view.set_text_selection(pno, [QRectF(x.x0, x.y0, x.width, x.height) for x in rects])
            self.selected_text = text
            if text:
                QApplication.clipboard().setText(text)
                self.status(tr("تم نسخ {n} حرف ✔").format(n=len(text)))
            elif self.bg.busy_with(pno):
                self.bg.focus(pno)
                self.status(tr("جاري تجهيز نص هذه الصفحة للنسخ… حاول بعد لحظات"))
            else:
                self.status(tr("لا يوجد نص قابل للنسخ هنا (قد تكون الصفحة صورة ممسوحة ضوئياً)"))
            return
        if tool == Tool.SELECT:
            inc = self.take_set(self.view.band_shift)
            if inc == {"elements"}:
                self._separate(pno, r, keep_lines=False)
            else:
                self._lift(pno, r, inc)
            return
        if tool == Tool.EDIT_TEXT:
            if r.width() * r.height() < 10:  # a click on text the OCR missed (e.g. a number)
                pr = self.engine.to_pdf(pno, rect)
                box = self.engine.scan_text_box(pno, pr, grow=4)
                if abs(box) <= abs(pr) * 4:
                    return
                d = self.engine.to_display(pno, box)
                r = QRectF(d.x0, d.y0, d.width, d.height)
            self.edit_area(pno, r)
            return
        if tool == Tool.EXTRACT:
            d = ExtractDialog(self, self.engine, pno, rect)
            if d.exec():
                ok = self.run(self.engine.extract_from_scan, pno, rect, d.mode(), d.sl.value(), d.cb_kind.currentData(),
                              pnos=[pno])
                if ok is False:
                    QMessageBox.information(self, tr("فصل عنصر من السكان"), tr("لم يتم العثور على شيء لفصله في هذه المنطقة."))
                elif ok:
                    self.status(tr("تم فصل العنصر كطبقة مستقلة ✔ — اسحبه أو أخفه من لوحة الطبقات"))
                    self.side_tabs.setCurrentIndex(2)
            return
        if tool == Tool.ERASE:
            self.run(self.engine.erase_area, pno, rect, self.erase_opts.mode(), pnos=[pno], msg=tr("تم المسح ✔"))
        elif tool == Tool.INK:
            n = self.run(self.engine.remove_color_ink, pno, rect, self.sl_ink.value(), pnos=[pno])
            if n == 0:
                QMessageBox.information(self, tr("إزالة الختم"),
                                        tr("لم يتم العثور على حبر ملون داخل صورة ممسوحة ضوئياً في هذه المنطقة.\n\n"
                                        "• إذا كان الختم عنصراً منفصلاً: استخدم أداة \"تحديد وحذف\".\n"
                                        "• إذا كان الختم أسود/رمادي: استخدم \"مسح منطقة\".\n"
                                        "• جرّب تقليل الحساسية من اللوحة الجانبية."))
            elif n:
                self.status(tr("تمت إزالة الحبر الملون ✔"))
        elif tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKE):
            kind = {Tool.HIGHLIGHT: "highlight", Tool.UNDERLINE: "underline", Tool.STRIKE: "strike"}[tool]
            if tool == Tool.HIGHLIGHT and self.ann_color.color.name() == "#e11d48":
                col = (1, 0.85, 0)
            self.run(self.engine.add_markup, pno, rect, kind, col, op, pnos=[pno])
        elif tool in (Tool.RECT, Tool.ELLIPSE):
            self.run(self.engine.add_shape, pno, "rect" if tool == Tool.RECT else "ellipse", rect, None, col, w, op,
                     pnos=[pno])

    def on_line(self, tool, pno, a: QPointF, b: QPointF):
        col, w, op = self._ann()
        self.run(self.engine.add_shape, pno, "arrow" if tool == Tool.ARROW else "line", (a.x(), a.y()),
                 (b.x(), b.y()), col, w, op, pnos=[pno])

    def on_ink(self, pno, pts):
        col, w, op = self._ann()
        self.run(self.engine.add_ink, pno, [(p.x(), p.y()) for p in pts], col, w, op, pnos=[pno])

    def on_note(self, pno, pt):
        text, ok = QInputDialog.getMultiLineText(self, tr("ملاحظة"), tr("نص الملاحظة:"))
        if ok and text.strip():
            col, _, _ = self._ann()
            self.run(self.engine.add_note, pno, (pt.x(), pt.y()), text, col, pnos=[pno])

    def flatten(self):
        if self.engine.is_open:
            self.run(self.engine.flatten_annotations, msg=tr("تم دمج التعليقات في محتوى الصفحات"))

    # ================================================================= pages
    def rotate_pages(self, delta):
        if self.engine.is_open:
            self.run(self.engine.rotate_pages, self._selected_pages(), delta, structure=True)

    def delete_pages(self):
        if not self.engine.is_open:
            return
        pages = self._selected_pages()
        if QMessageBox.question(self, tr("حذف"), tr("حذف {n} صفحة؟").format(n=len(pages))) == QMessageBox.Yes:
            self.run(self.engine.delete_pages, pages, structure=True, msg=tr("تم حذف الصفحات"))

    def insert_blank(self):
        if self.engine.is_open:
            self.run(self.engine.insert_blank, self.view.current_page(), structure=True)

    def duplicate_page(self):
        if self.engine.is_open:
            self.run(self.engine.duplicate_page, self.view.current_page(), structure=True)

    def move_current(self, d):
        if not self.engine.is_open:
            return
        p = self.view.current_page()
        t = p + d
        if 0 <= t < self.engine.page_count:
            self.run(self.engine.move_page, p, t, structure=True)
            self.view.go_to_page(t)

    def merge_files(self):
        if not self.engine.is_open:
            return
        files, _ = QFileDialog.getOpenFileNames(self, tr("اختر ملفات للدمج"), "", OPEN_FILTER)
        if not files:
            return
        at = self.engine.page_count
        for f in files:
            self.run(self.engine.insert_file, f, at, structure=True)
            at = self.engine.page_count
        self.status(tr("تم دمج {n} ملف").format(n=len(files)))

    def extract_selected(self):
        self._extract(self._selected_pages())

    def extract_pages(self):
        if not self.engine.is_open:
            return
        t, ok = QInputDialog.getText(self, tr("استخراج صفحات"), tr("أرقام الصفحات (مثال: 1-3, 7):"),
                                     text=str(self.view.current_page() + 1))
        if ok:
            self._extract(parse_pages(t, self.engine.page_count, self.view.current_page()))

    def _extract(self, pages):
        if not pages:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("حفظ الصفحات المستخرجة"), "extracted.pdf", "PDF (*.pdf)")
        if path:
            try:
                self.engine.extract_pages(pages, path)
                self.status(tr("تم الاستخراج ✔"))
            except Exception as e:
                self.error(e)

    def split_doc(self):
        if not self.engine.is_open:
            return
        d = SplitDialog(self)
        if not d.exec():
            return
        base = os.path.splitext(os.path.basename(self.engine.path or "document"))[0]
        if d.r_range.isChecked():
            self._extract(parse_pages(d.ed.text(), self.engine.page_count, self.view.current_page()))
            return
        folder = QFileDialog.getExistingDirectory(self, tr("اختر مجلد الحفظ"))
        if folder:
            try:
                files = self.engine.split_every(folder, base, d.sp_n.value())
                QMessageBox.information(self, tr("تقسيم"), tr("تم إنشاء {n} ملف في:\n{f}").format(n=len(files), f=folder))
            except Exception as e:
                self.error(e)

    # ================================================================= tools
    def watermark(self):
        if not self.engine.is_open:
            return
        d = WatermarkDialog(self)
        if not d.exec():
            return
        img = d.image()
        if img is None:
            return
        pages = d.pages.pages(self.engine.page_count, self.view.current_page())
        scale = d.sp_scale.value() / 100 if d.cb_place.currentData() in ("center", "tile") else d.sp_scale.value() / 300
        self.run(self.engine.add_overlay_image, qimage_to_png(img), pages, d.cb_place.currentData(),
                 scale if d.cb_place.currentData() != "tile" else d.sp_scale.value() / 250, msg=tr("تمت إضافة العلامة المائية"))

    def page_numbers(self):
        if not self.engine.is_open:
            return
        d = PageNumbersDialog(self)
        if d.exec():
            c = d.btn_color.color
            self.run(self.engine.add_page_numbers, d.cb_fmt.currentText(), d.cb_pos.currentData(), d.sp_size.value(),
                     (c.redF(), c.greenF(), c.blueF()), d.sp_start.value(), d.chk_skip.isChecked(),
                     msg=tr("تم ترقيم الصفحات"))

    def _ask_save_path(self, title, suffix):
        base = os.path.splitext(self.engine.path or "document.pdf")[0]
        path, _ = QFileDialog.getSaveFileName(self, title, base + suffix, "PDF (*.pdf)")
        return path

    def protect(self):
        if not self.engine.is_open:
            return
        d = ProtectDialog(self)
        if not d.exec():
            return
        if not d.user.text() and not d.owner.text():
            QMessageBox.warning(self, tr("حماية"), tr("أدخل كلمة مرور."))
            return
        path = self._ask_save_path(tr("حفظ النسخة المحمية"), "_protected.pdf")
        if path:
            try:
                self.engine.protect(path, d.user.text(), d.owner.text(), d.c_print.isChecked(), d.c_copy.isChecked(),
                                    d.c_edit.isChecked())
                QMessageBox.information(self, tr("حماية"), tr("تم حفظ نسخة محمية بكلمة مرور."))
            except Exception as e:
                self.error(e)

    def unprotect(self):
        if not self.engine.is_open:
            return
        path = self._ask_save_path(tr("حفظ نسخة بدون حماية"), "_unlocked.pdf")
        if path:
            try:
                self.engine.save_decrypted(path)
                QMessageBox.information(self, tr("إزالة الحماية"), tr("تم حفظ نسخة بدون كلمة مرور أو قيود."))
            except Exception as e:
                self.error(e)

    def compress(self):
        if not self.engine.is_open:
            return
        d = CompressDialog(self)
        if not d.exec():
            return
        path = self._ask_save_path(tr("حفظ الملف المضغوط"), "_compressed.pdf")
        if not path:
            return
        dpi, q = d.params()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            before = len(self.engine.doc.tobytes())
            self.engine.compress(path, dpi, q)
            after = os.path.getsize(path)
            QApplication.restoreOverrideCursor()
            QMessageBox.information(self, tr("ضغط"), tr("الحجم قبل: {x} MB\n").format(x=f"{before / 1048576:.2f}")
                                    + tr("الحجم بعد: {x} MB\n").format(x=f"{after / 1048576:.2f}")
                                    + tr("التوفير: {x}%").format(x=f"{max(0, 100 - after * 100 / max(1, before)):.0f}"))
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.error(e)

    def export_images(self):
        if not self.engine.is_open:
            return
        d = ExportImagesDialog(self)
        if not d.exec():
            return
        folder = QFileDialog.getExistingDirectory(self, tr("اختر مجلد الحفظ"))
        if not folder:
            return
        pages = d.pages.pages(self.engine.page_count, self.view.current_page())
        base = os.path.splitext(os.path.basename(self.engine.path or "document"))[0]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            files = self.engine.export_images(pages, folder, base, d.sp_dpi.value(), d.cb_fmt.currentText())
            QApplication.restoreOverrideCursor()
            QMessageBox.information(self, tr("تصدير"), tr("تم تصدير {n} صورة إلى:\n{f}").format(n=len(files), f=folder))
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.error(e)

    def images_to_pdf(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("اختر الصور"), "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)")
        if not files or not self.maybe_save():
            return
        try:
            doc = PdfDocument.images_to_pdf(files)
            eng = PdfDocument()
            eng.new_from_doc(doc, None)
            self._set_engine(eng)
            self.status(tr("تم إنشاء PDF من الصور — احفظه باسم"))
        except Exception as e:
            self.error(e)

    def metadata(self):
        if not self.engine.is_open:
            return
        d = MetadataDialog(self, self.engine.doc.metadata or {})
        if d.exec():
            self.run(self.engine.set_metadata, d.values(), msg=tr("تم حفظ الخصائص"))

    def print_doc(self):
        if not self.engine.is_open:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setMinMax(1, self.engine.page_count)
        if not dlg.exec():
            return
        first = max(1, printer.fromPage() or 1) - 1
        last = (printer.toPage() or self.engine.page_count) - 1
        painter = QPainter()
        if not painter.begin(printer):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, p in enumerate(range(first, last + 1)):
                if i:
                    printer.newPage()
                pix = self.engine.doc[p].get_pixmap(dpi=min(300, printer.resolution()), annots=True)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                area = painter.viewport()
                size = img.size().scaled(area.size(), Qt.KeepAspectRatio)
                painter.drawImage(QRectF((area.width() - size.width()) / 2, (area.height() - size.height()) / 2,
                                         size.width(), size.height()), img)
        finally:
            painter.end()
            QApplication.restoreOverrideCursor()
