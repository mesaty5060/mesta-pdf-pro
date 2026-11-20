"""Mesta look (same design language as Mesta Download Manager Pro): dark / light Qt stylesheets."""

# Palette shared by the Mesta apps (accent violet -> cyan gradient, 14px radius, Segoe UI Variable)
THEMES = {
    "dark": dict(
        bg="#0d0f14", bg2="#12151c", panel="#161a23", panel2="#1b2030", hover="#1f2433",
        line="#242a38", line2="#2e3546", text="#e8eaf0", text2="#a3a9b8", text3="#6b7285",
        accent="#7c5cff", accent2="#22d3ee", accentmix="#5491f7", ok="#22c55e", warn="#f59e0b", err="#ef4444",
        sel="rgba(124, 92, 255, 0.16)", sel2="rgba(124, 92, 255, 0.28)", icon="#c9cdd8", canvas="#0d0f14",
    ),
    "light": dict(
        bg="#f4f5f9", bg2="#eceef4", panel="#ffffff", panel2="#f7f8fb", hover="#eef0f6",
        line="#e3e6ee", line2="#d6dae4", text="#1a1c22", text2="#555c6e", text3="#8b91a1",
        accent="#7c5cff", accent2="#22d3ee", accentmix="#5491f7", ok="#16a34a", warn="#d97706", err="#dc2626",
        sel="rgba(124, 92, 255, 0.12)", sel2="rgba(124, 92, 255, 0.22)", icon="#3a4050", canvas="#e4e7ef",
    ),
}
FONT = "'Segoe UI Variable Text', 'Segoe UI', 'Tahoma', sans-serif"


def stylesheet(name: str) -> str:
    from .i18n import is_rtl
    c = dict(THEMES[name])
    c["start"] = "right" if is_rtl() else "left"
    c["end"] = "left" if is_rtl() else "right"
    c["font"] = FONT
    return """
* { font-family: %(font)s; font-size: 10.5pt; color: %(text)s; }
QMainWindow, QDialog { background: %(bg)s; }
QWidget#Root, QWidget#MainCol { background: %(bg)s; }

/* ---------------- sidebar ---------------- */
QWidget#Sidebar { background: %(bg2)s; border-%(end)s: 1px solid %(line)s; }
QLabel#BrandName { font-size: 13pt; font-weight: 700; }
QLabel#BadgePro { color: #ffffff; font-size: 7.5pt; font-weight: 800; padding: 2px 6px; border-radius: 6px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 %(accent)s, stop:1 %(accent2)s); }
QLabel#BrandTag { color: %(text3)s; font-size: 8.5pt; }
QPushButton#BtnNew { color: #ffffff; font-weight: 600; border: none; border-radius: 12px; padding: 12px 14px;
    text-align: %(start)s; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 %(accent)s, stop:1 %(accentmix)s); }
QPushButton#BtnNew:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8d71ff, stop:1 #66a2ff); }
QLabel#Kbd { color: #ffffff; font-size: 8pt; background: rgba(255,255,255,0.16); border-radius: 6px; padding: 2px 6px; }
QLabel#NavTitle { color: %(text3)s; font-size: 8pt; font-weight: 700; padding: 14px 10px 4px 10px; }
QPushButton#NavItem, QPushButton#SideBtn { text-align: %(start)s; border: none; border-radius: 10px; padding: 8px 10px;
    color: %(text2)s; background: transparent; font-weight: 500; }
QPushButton#NavItem:hover, QPushButton#SideBtn:hover { background: %(hover)s; color: %(text)s; }
QPushButton#NavItem:checked { background: %(sel)s; color: %(text)s; font-weight: 600; }
QPushButton#NavItem:disabled { color: %(text3)s; }
QPushButton#RecentItem { text-align: %(start)s; border: none; border-radius: 10px; padding: 7px 10px; color: %(text2)s;
    background: transparent; font-size: 9.5pt; font-weight: 400; }
QPushButton#RecentItem:hover { background: %(hover)s; color: %(text)s; }
QFrame#SideBottom { border-top: 1px solid %(line)s; }
QPushButton::menu-indicator { image: none; width: 0; }

/* ---------------- header + tool row ---------------- */
QLabel#H1 { font-size: 16pt; font-weight: 700; }
QLabel#H1Sub { color: %(text3)s; font-size: 9.5pt; }
QLineEdit#Search { background: %(panel)s; border: 1px solid %(line)s; border-radius: 11px; padding: 8px 12px; }
QLineEdit#Search:focus { border: 1px solid %(accent)s; }
QToolButton#IconBtn { border: none; border-radius: 10px; padding: 7px; background: transparent; }
QToolButton#IconBtn:hover { background: %(hover)s; }
QToolButton#IconBtn::menu-indicator { image: none; width: 0; }
QTabWidget#RibbonTabs, QTabWidget#RibbonTabs::pane { border: none; background: transparent; }
QTabWidget#RibbonTabs > QTabBar { height: 0; }
QToolButton#TbBtn { background: %(panel)s; border: 1px solid %(line)s; border-radius: 10px; padding: 6px 11px;
    color: %(text2)s; font-size: 9.5pt; font-weight: 500; }
QToolButton#TbBtn:hover { background: %(hover)s; border-color: %(line2)s; color: %(text)s; }
QToolButton#TbBtn:checked { background: %(sel2)s; border-color: %(accent)s; color: %(text)s; }
QToolButton#TbBtn:disabled { color: %(text3)s; }
QToolButton#TbBtn::menu-indicator { image: none; width: 0; }
QFrame#RibbonGroup { background: transparent; border: none; border-%(end)s: 1px solid %(line)s; margin: 0 2px; padding: 0 4px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 4px 6px; }
QToolButton:hover { background: %(hover)s; }
QToolButton:checked { background: %(sel2)s; border-color: %(accent)s; }
QToolButton::menu-indicator { image: none; }

/* ---------------- panels ---------------- */
QWidget#SidePanel, QWidget#PropsPanel { background: %(bg2)s; border-%(start)s: 1px solid %(line)s; }
QDockWidget { titlebar-close-icon: none; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { background: transparent; padding: 8px 12px; border: none; border-bottom: 2px solid transparent; color: %(text3)s; font-weight: 600; }
QTabBar::tab:selected { color: %(text)s; border-bottom: 2px solid %(accent)s; }
QTabBar::tab:hover { color: %(text)s; }
QListWidget, QTreeWidget { background: transparent; border: none; outline: none; }
QListWidget::item, QTreeWidget::item { border-radius: 10px; padding: 5px; margin: 2px; }
QListWidget::item:hover, QTreeWidget::item:hover { background: %(hover)s; }
QListWidget::item:selected, QTreeWidget::item:selected { background: %(sel2)s; color: %(text)s; }
QGraphicsView#PdfView { background: %(canvas)s; border: none; border-radius: 14px; }
QStatusBar { background: %(bg)s; border-top: 1px solid %(line)s; color: %(text3)s; }
QStatusBar QLabel { color: %(text3)s; }
QLabel#AppTitle { font-size: 11pt; font-weight: 700; }
QLabel#DocTitle { color: %(text3)s; }
QLabel#Hint { color: %(text3)s; }
QLabel#PanelTitle { font-size: 11.5pt; font-weight: 700; }

/* ---------------- inputs & buttons ---------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit, QDateEdit {
    background: %(panel)s; border: 1px solid %(line)s; border-radius: 10px; padding: 6px 9px;
    selection-background-color: %(accent)s; selection-color: #fff; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid %(accent)s; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: %(panel)s; border: 1px solid %(line)s; selection-background-color: %(sel2)s; }
QPushButton { background: %(panel)s; border: 1px solid %(line)s; border-radius: 10px; padding: 8px 16px; font-weight: 600; color: %(text2)s; }
QPushButton:hover { background: %(hover)s; border-color: %(line2)s; color: %(text)s; }
QPushButton:disabled { color: %(text3)s; }
QPushButton#Primary { color: #ffffff; border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 %(accent)s, stop:1 %(accent2)s); }
QPushButton#Primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8d71ff, stop:1 #45dcf2); }
QPushButton#Danger { background: transparent; border: 1px solid %(err)s; color: %(err)s; }
QPushButton#Danger:hover { background: %(err)s; color: #fff; }
QGroupBox { border: 1px solid %(line)s; border-radius: 12px; margin-top: 14px; padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top %(start)s; padding: 0 6px; color: %(text3)s; }
QCheckBox, QRadioButton { spacing: 7px; color: %(text2)s; }
QSlider::groove:horizontal { height: 4px; background: %(line)s; border-radius: 2px; }
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 2px; }
QSlider::handle:horizontal { background: #fff; border: 2px solid %(accent)s; width: 12px; height: 12px; margin: -6px 0; border-radius: 8px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: %(line2)s; border-radius: 5px; min-height: 30px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: %(text3)s; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: %(line2)s; border-radius: 5px; min-width: 30px; margin: 2px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMenu { background: %(panel)s; border: 1px solid %(line)s; border-radius: 12px; padding: 6px; }
QMenu::item { padding: 8px 26px 8px 18px; border-radius: 8px; color: %(text2)s; }
QMenu::item:selected { background: %(hover)s; color: %(text)s; }
QMenu::separator { height: 1px; background: %(line)s; margin: 4px 8px; }
QToolTip { background: %(panel)s; color: %(text)s; border: 1px solid %(line)s; padding: 6px; border-radius: 8px; }

/* ---------------- floating / bars ---------------- */
QWidget#FloatBar { background: %(panel)s; border: 1px solid %(accent)s; border-radius: 12px; }
QWidget#FindBar, QFrame#ContextBar { background: %(bg)s; border: none; }
QFrame#CtxSep { color: %(line)s; }
QFrame#InfoBar { background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.45); border-radius: 12px; }
QFrame#Card { background: %(panel)s; border: 1px solid %(line)s; border-radius: 14px; }
QWidget#Welcome { background: %(bg)s; }
QLabel#WelcomeTitle { font-size: 22pt; font-weight: 800; }
QLabel#WelcomeSub { color: %(text3)s; font-size: 11pt; }
QPushButton#BigOpen { color: #fff; border: none; border-radius: 14px; padding: 14px 34px; font-size: 12pt;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 %(accent)s, stop:1 %(accent2)s); }
QPushButton#BigOpen:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8d71ff, stop:1 #45dcf2); }
QPushButton#Recent { text-align: %(start)s; background: %(panel)s; border: 1px solid %(line)s; border-radius: 12px; padding: 10px 14px; font-weight: 400; }
QPushButton#Recent:hover { border-color: %(accent)s; }
QSplitter::handle { background: %(line)s; }
""" % c


def color(name: str, key: str) -> str:
    return THEMES[name][key]
