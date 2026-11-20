"""PDF engine: every document operation lives here (no Qt imports).

Coordinate convention
---------------------
* "pdf space"     = un-rotated page coordinates used by PyMuPDF extraction,
                    redaction, insertion and annotations.
* "display space" = rotated page coordinates (what the user sees, page.rect).
Use to_display()/to_pdf() to convert.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field

import pymupdf
from .i18n import tr

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

# --------------------------------------------------------------------------- fonts
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

# family: (regular, bold, italic, bold-italic)
_FONT_TABLE = [
    ("Arial", "arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    ("Times New Roman", "times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    ("Calibri", "calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    ("Tahoma", "tahoma.ttf", "tahomabd.ttf", None, None),
    ("Segoe UI", "segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    ("Verdana", "verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    ("Georgia", "georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    ("Courier New", "cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    ("Traditional Arabic", "trado.ttf", "tradbdo.ttf", None, None),
    ("Simplified Arabic", "simpo.ttf", "simpbdo.ttf", None, None),
    ("Sakkal Majalla", "majalla.ttf", "majallab.ttf", None, None),
    ("Arabic Typesetting", "arabtype.ttf", None, None, None),
    ("Dubai", "DUBAI-REGULAR.TTF", "DUBAI-BOLD.TTF", None, None),
    ("Andalus", "andlso.ttf", None, None, None),
]


def _available_fonts():
    out = {}
    for fam, *files in _FONT_TABLE:
        paths = [os.path.join(FONT_DIR, f) if f and os.path.exists(os.path.join(FONT_DIR, f)) else None for f in files]
        if paths[0]:
            out[fam] = paths
    if not out:  # extremely unlikely on Windows; fall back to built-in helv
        out["Helvetica"] = [None, None, None, None]
    return out


FONTS = _available_fonts()
ORIGINAL_FONT = "__original__"


# --------------------------------------------------------------------------- OCR data
def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_tessdata() -> str | None:
    cands = [os.environ.get("PDFSTUDIO_TESSDATA", ""), os.path.join(app_dir(), "tessdata"),
             os.path.join(getattr(sys, "_MEIPASS", app_dir()), "tessdata"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tessdata"),
             r"C:\Program Files\Tesseract-OCR\tessdata"]
    for c in cands:
        if c and os.path.isdir(c) and any(f.endswith(".traineddata") for f in os.listdir(c)):
            return c
    return None


TESSDATA = find_tessdata()


def ocr_languages() -> list[str]:
    if not TESSDATA:
        return []
    return sorted(f[:-12] for f in os.listdir(TESSDATA) if f.endswith(".traineddata") and f != "osd.traineddata")


def ocr_run(pix: "pymupdf.Pixmap", language: str) -> bytes:
    """Thread-safe: runs Tesseract on a pixmap and returns a one-page PDF with an invisible text layer."""
    return pix.pdfocr_tobytes(language=language, tessdata=TESSDATA)


LAYER_KEY = "PSLayer"
LAYER_KINDS = {"text": tr("نص"), "image": tr("صورة"), "stamp": tr("ختم"), "logo": tr("شعار"), "element": tr("عنصر"), "region": tr("منطقة"), "signature": tr("توقيع"), "rect": tr("مستطيل"),
               "ellipse": tr("دائرة"), "line": tr("خط"), "arrow": tr("سهم"), "ink": tr("رسم حر")}


def font_path(family: str, bold=False, italic=False) -> str | None:
    paths = FONTS.get(family) or FONTS.get("Arial") or next(iter(FONTS.values()))
    idx = (1 if bold else 0) + (2 if italic else 0)
    for i in (idx, 1 if bold else 0, 0):
        if paths[i]:
            return paths[i]
    return None


def guess_family(fontname: str, flags: int = 0) -> tuple[str, bool, bool]:
    n = (fontname or "").lower()
    bold = bool(flags & 16) or any(k in n for k in ("bold", "black", "heavy", "semibold", "demi"))
    italic = bool(flags & 2) or "italic" in n or "oblique" in n
    table = [
        (("traditional", "trado"), "Traditional Arabic"),
        (("simplified arabic", "simpo", "simplifiedarabic"), "Simplified Arabic"),
        (("majalla",), "Sakkal Majalla"),
        (("typesetting", "arabtype"), "Arabic Typesetting"),
        (("dubai",), "Dubai"),
        (("calibri",), "Calibri"),
        (("tahoma",), "Tahoma"),
        (("verdana",), "Verdana"),
        (("georgia",), "Georgia"),
        (("segoe",), "Segoe UI"),
        (("courier", "mono", "consol"), "Courier New"),
        (("times", "roman", "serif", "cambria", "garamond", "book"), "Times New Roman"),
        (("arial", "helvetica", "sans"), "Arial"),
    ]
    fam = None
    for keys, f in table:
        if any(k in n for k in keys):
            fam = f
            break
    if fam is None:
        fam = "Times New Roman" if flags & 4 else ("Courier New" if flags & 8 else "Arial")
    if fam not in FONTS:
        fam = "Arial" if "Arial" in FONTS else next(iter(FONTS))
    return fam, bold, italic


# --------------------------------------------------------------------------- text helpers
_RTL_RE = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")


def _script(text: str):
    """"ar" / "lat" / None (digits, symbols) — used to split OCR fields."""
    if _RTL_RE.search(text or ""):
        return "ar"
    if re.search(r"[A-Za-z]", text or ""):
        return "lat"
    if len(re.findall(r"\d", text or "")) >= 3:
        return "num"  # numbers are their own field (phone, cost, dates)
    return None


def has_rtl(text: str) -> bool:
    return bool(_RTL_RE.search(text or ""))


def normalize_extracted(text: str) -> str:
    """Map Arabic presentation forms back to normal letters so text is editable."""
    out = []
    text = text.replace("\xa0", " ")
    for ch in text:
        o = ord(ch)
        if 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
            out.append(unicodedata.normalize("NFKC", ch))
        else:
            out.append(ch)
    return "".join(out)


def int_to_rgb(c: int) -> tuple:
    return (((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0)


def rgb_to_hex(rgb) -> str:
    r, g, b = [max(0, min(255, int(round(v * 255)))) for v in rgb[:3]]
    return f"#{r:02x}{g:02x}{b:02x}"


def _dir_to_rotate(d) -> int:
    ang = math.degrees(math.atan2(-d[1], d[0]))
    return int(round(ang / 90.0)) * 90 % 360


# --------------------------------------------------------------------------- objects
@dataclass
class PageObject:
    kind: str           # 'line' | 'block' | 'image' | 'annot' | 'drawing'
    pno: int
    rect: pymupdf.Rect  # pdf space
    data: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.kind == "layer":
            m = self.data.get("meta", {})
            return tr("طبقة: {x}").format(x=m.get('name', ''))
        if self.kind == "image":
            return tr("صورة / ختم  ({w}×{h} px)").format(w=self.data.get('width', 0), h=self.data.get('height', 0))
        if self.kind == "annot":
            return tr("تعليق/ختم مضاف: {x}").format(x=self.data.get('type', ''))
        if self.kind == "drawing":
            return tr("رسم متجه (قد يكون ختماً مرسوماً)")
        if self.kind == "scan":
            return tr("عنصر داخل السكان — اضغط لفصله وتحريكه")
        if self.kind in ("line", "block"):
            t = self.data.get("text", "")
            return tr("نص: ") + (t[:40] + "…" if len(t) > 40 else t)
        return self.kind


class PasswordRequired(Exception):
    pass


# Redaction constants (names stable across PyMuPDF versions)
IMG_NONE = getattr(pymupdf, "PDF_REDACT_IMAGE_NONE", 0)
IMG_REMOVE = getattr(pymupdf, "PDF_REDACT_IMAGE_REMOVE", 1)
IMG_PIXELS = getattr(pymupdf, "PDF_REDACT_IMAGE_PIXELS", 2)
ART_NONE = getattr(pymupdf, "PDF_REDACT_LINE_ART_NONE", 0)
ART_COVERED = getattr(pymupdf, "PDF_REDACT_LINE_ART_REMOVE_IF_COVERED", 1)
ART_TOUCHED = getattr(pymupdf, "PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED", 2)
TXT_REMOVE = getattr(pymupdf, "PDF_REDACT_TEXT_REMOVE", 0)
TXT_NONE = getattr(pymupdf, "PDF_REDACT_TEXT_NONE", 1)

ERASE_MODES = {
    # mode: (text, images, graphics, fill)
    "all_white": (TXT_REMOVE, IMG_PIXELS, ART_COVERED, (1, 1, 1)),
    "all": (TXT_REMOVE, IMG_PIXELS, ART_COVERED, False),
    "text": (TXT_REMOVE, IMG_NONE, ART_NONE, False),
    "images": (TXT_NONE, IMG_PIXELS, ART_NONE, False),
    "graphics": (TXT_NONE, IMG_NONE, ART_COVERED, False),
}


# =========================================================================== document
class PdfDocument:
    MAX_UNDO = 40

    def __init__(self):
        self.doc: pymupdf.Document | None = None
        self.path: str | None = None
        self.password: str | None = None
        self._undo: list[tuple[str, bytes]] = []
        self._redo: list[tuple[str, bytes]] = []
        self.modified = False
        self._objcache: dict[int, dict] = {}
        self._archive = None
        self._tmpdir = tempfile.mkdtemp(prefix="pdfstudio_")
        self._fontfile_cache: dict[int, str | None] = {}
        self._scan_cache: dict[int, dict] = {}
        self.epoch = 0  # bumps on every change: lets background work detect stale results

    # ------------------------------------------------------------------ open / save
    @staticmethod
    def _open_any(path: str) -> pymupdf.Document:
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            data = f.read()
        if ext == ".pdf" or data[:5] == b"%PDF-":
            return pymupdf.open("pdf", data)
        src = pymupdf.open(path)  # images, xps, epub, ...
        pdfbytes = src.convert_to_pdf()
        src.close()
        return pymupdf.open("pdf", pdfbytes)

    def open(self, path: str, password: str | None = None):
        doc = self._open_any(path)
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                doc.close()
                raise PasswordRequired(path)
        self.doc, self.path, self.password = doc, path, password
        self._undo.clear()
        self._redo.clear()
        self.modified = False
        self._objcache.clear()
        self._fontfile_cache.clear()
        if not path.lower().endswith(".pdf"):
            self.path = os.path.splitext(path)[0] + ".pdf"
            self.modified = True

    def new_from_doc(self, doc: pymupdf.Document, path_hint: str | None = None):
        self.doc = pymupdf.open("pdf", doc.tobytes())
        self.path = path_hint
        self.password = None
        self._undo.clear()
        self._redo.clear()
        self._objcache.clear()
        self.modified = True

    def _load_bytes(self, data: bytes) -> pymupdf.Document:
        doc = pymupdf.open("pdf", data)
        if doc.needs_pass and self.password:
            doc.authenticate(self.password)
        return doc

    def _save_opts(self):
        # very large files: lighter clean-up so saving stays quick
        big = self.page_count > 400 or (self.path and os.path.exists(self.path) and os.path.getsize(self.path) > 80 * 1024 * 1024)
        return dict(garbage=1 if big else 3, deflate=True)

    def save(self, path: str | None = None, **kw):
        target = path or self.path
        if not target:
            raise ValueError("no path")
        opts = self._save_opts()
        opts.update(kw)
        tmp = target + ".pdfstudio.tmp"
        self._write_compact(tmp, opts)
        os.replace(tmp, target)
        self.path = target
        self.modified = False

    def save_copy(self, path: str, **kw):
        opts = self._save_opts()
        opts.update(kw)
        self._write_compact(path, opts)

    def _write_compact(self, path, opts):
        """Save with fonts reduced to the letters actually used (added text would otherwise embed whole
        fonts). Done on a copy so later edits still have every letter available."""
        if self.page_count <= 400 and "encryption" not in opts:
            try:
                work = pymupdf.open("pdf", self.doc.tobytes())
                work.subset_fonts()
                work.save(path, **opts)
                work.close()
                return
            except Exception:
                pass
        self.doc.save(path, **opts)

    @property
    def is_open(self) -> bool:
        return self.doc is not None

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.doc else 0

    def page(self, pno: int) -> pymupdf.Page:
        return self.doc[pno]

    # ------------------------------------------------------------------ undo / redo
    UNDO_BUDGET = 700 * 1024 * 1024  # bytes kept for undo (big files keep fewer steps)

    def checkpoint(self, label: str):
        self.epoch += 1
        self._undo.append((label, self.doc.tobytes(garbage=0)))
        total = sum(len(d) for _, d in self._undo)
        while len(self._undo) > 2 and (len(self._undo) > self.MAX_UNDO or total > self.UNDO_BUDGET):
            total -= len(self._undo.pop(0)[1])
        self._redo.clear()
        self.modified = True

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return None
        self.epoch += 1
        label, data = self._undo.pop()
        self._redo.append((label, self.doc.tobytes()))
        self.doc = self._load_bytes(data)
        self.invalidate()
        self.modified = True
        return label

    def redo(self):
        if not self._redo:
            return None
        self.epoch += 1
        label, data = self._redo.pop()
        self._undo.append((label, self.doc.tobytes()))
        self.doc = self._load_bytes(data)
        self.invalidate()
        self.modified = True
        return label

    def drop_last_checkpoint(self):
        """Used when an operation turned out to change nothing."""
        if self._undo:
            self._undo.pop()

    def invalidate(self, pno: int | None = None):
        if pno is None:
            self._objcache.clear()
            self._scan_cache.clear()
        else:
            self._objcache.pop(pno, None)
            self._scan_cache.pop(pno, None)

    # ------------------------------------------------------------------ coordinates
    def to_display(self, pno: int, r) -> pymupdf.Rect:
        p = self.doc[pno]
        return (pymupdf.Rect(r) * p.rotation_matrix).normalize()

    def to_pdf(self, pno: int, r) -> pymupdf.Rect:
        p = self.doc[pno]
        return (pymupdf.Rect(r) * p.derotation_matrix).normalize()

    def point_to_pdf(self, pno: int, pt) -> pymupdf.Point:
        return pymupdf.Point(pt) * self.doc[pno].derotation_matrix

    def page_display_size(self, pno: int):
        r = self.doc[pno].rect
        return r.width, r.height

    # ------------------------------------------------------------------ rendering
    def render(self, pno: int, zoom: float, clip=None, annots=True) -> pymupdf.Pixmap:
        page = self.doc[pno]
        mat = pymupdf.Matrix(zoom, zoom)
        return page.get_pixmap(matrix=mat, alpha=False, annots=annots, clip=clip)

    # ------------------------------------------------------------------ object discovery
    def get_objects(self, pno: int) -> dict:
        if pno in self._objcache:
            return self._objcache[pno]
        page = self.doc[pno]
        res = {"lines": [], "blocks": [], "images": [], "annots": [], "drawings": []}
        prect = page.rect * page.derotation_matrix
        parea = max(1.0, abs(prect))

        ocr_data = self._ocr_data(pno)

        # ---- text
        flags =(pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES) | pymupdf.TEXT_PRESERVE_WHITESPACE
        try:
            d = page.get_text("dict", flags=flags)
        except Exception:
            d = {"blocks": []}
        for bi, b in enumerate(d.get("blocks", [])):
            if b.get("type", 0) != 0:
                continue
            blines = []
            for li, ln in enumerate(b.get("lines", [])):
                spans = [s for s in ln.get("spans", []) if s.get("text", "").strip() != "" or len(ln["spans"]) == 1]
                if not spans:
                    continue
                if all(s.get("alpha", 255) == 0 for s in spans):
                    if ocr_data is None:  # OCR made by another program
                        blines.extend(self._ocr_line_objects(pno, ln, spans, bi))
                    continue
                text = normalize_extracted("".join(s["text"] for s in ln["spans"]))
                if not text.strip():
                    continue
                main = max(spans, key=lambda s: len(s["text"].strip()))
                obj = PageObject("line", pno, pymupdf.Rect(ln["bbox"]), {
                    "text": text,
                    "size": round(main["size"], 2),
                    "color": int_to_rgb(main.get("color", 0)),
                    "font": main.get("font", ""),
                    "flags": main.get("flags", 0),
                    "origin": tuple(ln["spans"][0]["origin"]),
                    "dir": tuple(ln.get("dir", (1, 0))),
                    "spans": ln["spans"],
                    "block": bi,
                })
                blines.append(obj)
            if blines:
                res["lines"].extend(blines)
                brect = pymupdf.Rect(blines[0].rect)
                for o in blines[1:]:
                    brect |= o.rect
                res["blocks"].append(PageObject("block", pno, brect, {
                    "text": "\n".join(o.data["text"] for o in blines),
                    "lines": blines,
                    "size": blines[0].data["size"],
                    "color": blines[0].data["color"],
                    "font": blines[0].data["font"],
                    "flags": blines[0].data["flags"],
                    "origin": blines[0].data["origin"],
                    "dir": blines[0].data["dir"],
                }))

        # ---- text recognised by Mesta PDF Pro OCR (stored in reading order)
        if ocr_data:
            try:
                ocr_vlines = self._analyze_scan(pno)["vlines"] if np is not None else []
            except Exception:
                ocr_vlines = []
            segs = []
            for line in ocr_data.get("lines", []):
                segs.extend(self._ocr_line_objects(pno, {"dir": (1, 0)}, line, -1, ocr_vlines))
            for o in self._merge_ocr_fields(segs):
                res["lines"].append(o)
                res["blocks"].append(PageObject("block", pno, pymupdf.Rect(o.rect), dict(o.data, lines=[o])))

        # ---- layers (objects added with Mesta PDF Pro, each one independent)
        res["layers"] = self.list_layers(pno)

        # ---- images
        try:
            infos = page.get_image_info(hashes=True, xrefs=True)
        except Exception:
            infos = []
        seen = {}
        for info in infos:
            r = pymupdf.Rect(info["bbox"])
            if r.is_empty or r.is_infinite:
                continue
            xref = info.get("xref", 0)
            nth = seen.get(xref, 0)
            seen[xref] = nth + 1
            digest = info.get("digest")
            res["images"].append(PageObject("image", pno, r & prect if (r & prect).is_valid else r, {
                "xref": xref,
                "nth": nth,
                "digest": digest.hex() if isinstance(digest, (bytes, bytearray)) else str(digest),
                "transform": tuple(info.get("transform", (1, 0, 0, 1, 0, 0))),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "full_page": abs(r & prect) > 0.85 * parea,
            }))

        # ---- annotations
        for a in page.annots() or []:
            try:
                res["annots"].append(PageObject("annot", pno, pymupdf.Rect(a.rect), {
                    "xref": a.xref, "type": a.type[1], "content": a.info.get("content", ""),
                }))
            except Exception:
                pass

        # ---- vector drawings (cheap guard for very heavy pages)
        try:
            if len(page.get_cdrawings()) < 4000:
                for r in page.cluster_drawings():
                    r = pymupdf.Rect(r)
                    if r.width < 8 or r.height < 8 or abs(r) > 0.5 * parea:
                        continue
                    if any(abs(a.rect.x0 - r.x0) < 3 and abs(a.rect.y0 - r.y0) < 3 and abs(a.rect.x1 - r.x1) < 3
                           and abs(a.rect.y1 - r.y1) < 3 for a in res["annots"]):
                        continue
                    res["drawings"].append(PageObject("drawing", pno, r, {}))
        except Exception:
            pass

        # images/drawings that belong to a layer are handled through the layer
        if res["layers"]:
            lrects = [o.rect for o in res["layers"]]

            def in_layer(r):
                return any((r & lr).is_valid and abs(r & lr) >= 0.8 * max(abs(r), 1e-6) for lr in lrects)

            res["images"] = [o for o in res["images"] if not in_layer(o.rect)]
            res["drawings"] = [o for o in res["drawings"] if not in_layer(o.rect)]

        # ---- stamps / logos / signatures printed inside a scan (click to separate them)
        res["scan"] = []
        if np is not None and any(o.data.get("full_page") for o in res["images"]):
            try:
                for dr, _col in self.detect_scan_objects(pno):
                    pr = self.to_pdf(pno, dr)
                    if not any(abs(pr & o.rect) > 0.5 * abs(pr) for o in res["layers"]):
                        res["scan"].append(PageObject("scan", pno, pr, {}))
            except Exception:
                pass

        self._objcache[pno] = res
        return res

    @staticmethod
    def _merge_ocr_fields(segs):
        """Tesseract sometimes gives one word a box covering the whole field: merge overlapping pieces
        of the same script and size into one editable field."""
        segs = list(segs)
        changed = True
        while changed:
            changed = False
            for i in range(len(segs)):
                a = segs[i]
                for j in range(i + 1, len(segs)):
                    b = segs[j]
                    inter = a.rect & b.rect
                    if not inter.is_valid or inter.is_empty:
                        continue
                    small = min(abs(a.rect), abs(b.rect))
                    hs = min(a.rect.height, b.rect.height) / max(a.rect.height, b.rect.height)
                    if abs(inter) < 0.3 * small or hs < 0.6 or _script(a.data["text"]) != _script(b.data["text"]):
                        continue
                    first, second = (a, b) if a.rect.x0 <= b.rect.x0 else (b, a)
                    rtl = _script(a.data["text"]) == "ar"
                    text = (second.data["text"] + " " + first.data["text"]) if rtl else \
                        (first.data["text"] + " " + second.data["text"])
                    m = PageObject("line", a.pno, a.rect | b.rect, dict(first.data, text=text,
                                                                         spans=a.data["spans"] + b.data["spans"]))
                    segs[i] = m
                    del segs[j]
                    changed = True
                    break
                if changed:
                    break
        return segs

    def _ocr_line_objects(self, pno, ln, spans, bi, vlines=()):
        """OCR text comes as one long line across columns: split it into fields at big gaps
        and put Arabic words back in reading order."""
        spans = sorted(spans, key=lambda s: s["bbox"][0])
        segs, cur = [], [spans[0]]
        for s in spans[1:]:
            prev = cur[-1]
            gap = s["bbox"][0] - prev["bbox"][2]
            sa, sb = _script(prev["text"]), _script(s["text"])
            y0 = max(prev["bbox"][1], s["bbox"][1])
            y1 = min(prev["bbox"][3], s["bbox"][3])
            ruled = any(v.x0 >= prev["bbox"][2] - 1.5 and v.x1 <= s["bbox"][0] + 1.5 and v.y0 < y1 and v.y1 > y0
                        for v in vlines)
            if gap > 1.6 * max(prev["size"], s["size"], 4) or ruled or (sa and sb and sa != sb):
                segs.append(cur)
                cur = [s]
            else:
                cur.append(s)
        segs.append(cur)
        out = []
        for seg in segs:
            words = [normalize_extracted(s["text"]).strip() for s in seg if s["text"].strip()]
            if not words:
                continue
            rtl = sum(has_rtl(w) for w in words) >= max(1, len(words) / 2)
            text = " ".join(reversed(words) if rtl else words)
            r = pymupdf.Rect(seg[0]["bbox"])
            for s in seg[1:]:
                r |= pymupdf.Rect(s["bbox"])
            sizes = sorted(s.get("size", r.height) for s in seg)
            size = min(max(sizes[len(sizes) // 2] * 0.95, r.height * 0.9), r.height * 1.6)
            out.append(PageObject("line", pno, r, {
                "text": text, "size": round(size, 1), "color": (0, 0, 0), "font": "Arial", "flags": 0,
                "origin": (r.x0, r.y1 - r.height * 0.2), "dir": tuple(ln.get("dir", (1, 0))), "spans": seg,
                "block": bi, "ocr": True,
            }))
        return out

    # ------------------------------------------------------------------ fonts for editing
    @property
    def archive(self):
        if self._archive is None:
            self._archive = pymupdf.Archive(FONT_DIR)
        return self._archive

    def _font_resource_name(self, path: str) -> str:
        return "PS" + hashlib.md5(path.encode("utf-8")).hexdigest()[:10]

    def _original_font_file(self, page: pymupdf.Page, span_font: str, sample_text: str, new_text: str) -> str | None:
        """Try to reuse the embedded font of the edited text. Returns a temp font file or None."""
        base = span_font.split("+", 1)[-1]
        for f in page.get_fonts(full=True):
            xref, ext, ftype, basefont = f[0], f[1], f[2], f[3]
            if basefont.split("+", 1)[-1] != base:
                continue
            if ext in ("n/a", "") or ftype == "Type3":
                return None
            if xref in self._fontfile_cache:
                path = self._fontfile_cache[xref]
            else:
                path = None
                try:
                    name, fext, _, buf = self.doc.extract_font(xref)
                    if buf:
                        path = os.path.join(self._tmpdir, f"f{xref}.{fext or 'ttf'}")
                        with open(path, "wb") as fh:
                            fh.write(buf)
                except Exception:
                    path = None
                self._fontfile_cache[xref] = path
            if not path:
                return None
            try:
                font = pymupdf.Font(fontfile=path)
                for ch in set(sample_text + new_text):
                    if ch.isspace():
                        continue
                    if not font.has_glyph(ord(ch)):
                        return None
                return path
            except Exception:
                return None
        return None

    def _resolve_font(self, page, style: dict, sample_text: str, new_text: str) -> str | None:
        fam = style.get("family") or "Arial"
        if fam == ORIGINAL_FONT:
            p = self._original_font_file(page, style.get("orig_font", ""), sample_text, new_text)
            if p:
                return p
            fam, b, i = guess_family(style.get("orig_font", ""), style.get("orig_flags", 0))
            return font_path(fam, style.get("bold", b), style.get("italic", i))
        return font_path(fam, style.get("bold", False), style.get("italic", False))

    def resolve_family(self, style: dict) -> str:
        fam = style.get("family") or "Arial"
        if fam == ORIGINAL_FONT:
            fam, _, _ = guess_family(style.get("orig_font", ""), style.get("orig_flags", 0))
        return fam

    # ------------------------------------------------------------------ html insertion (Arabic + paragraphs)
    def _css_fontface(self, family: str) -> str:
        paths = FONTS.get(family)
        if not paths:
            return ""
        out = []
        variants = [("normal", "normal"), ("bold", "normal"), ("normal", "italic"), ("bold", "italic")]
        for p, (w, s) in zip(paths, variants):
            if p:
                out.append("@font-face {font-family: '%s'; src: url('%s'); font-weight: %s; font-style: %s;}"
                           % (family, os.path.basename(p), w, s))
        return "\n".join(out)

    def _build_html(self, text, size, color, family, bold, italic, align, rtl, line_height):
        esc = html.escape(text).replace("\n", "<br>")
        st = [f"font-family:'{family}'", f"font-size:{size:.2f}px", f"color:{rgb_to_hex(color)}",
              f"text-align:{align}", "margin:0", "padding:0", f"line-height:{line_height:.3f}"]
        if bold:
            st.append("font-weight:bold")
        if italic:
            st.append("font-style:italic")
        if rtl:
            st.append("direction:rtl")
        return f'<p dir="{"rtl" if rtl else "ltr"}" style="{";".join(st)}">{esc}</p>'

    def _ensure_arabic_family(self, family: str, text: str) -> str:
        if not has_rtl(text):
            return family
        p = font_path(family)
        try:
            ch = next(c for c in text if _RTL_RE.match(c))
            if p and pymupdf.Font(fontfile=p).has_glyph(ord(ch)):
                return family
        except Exception:
            pass
        for f in ("Arial", "Tahoma", "Simplified Arabic", "Traditional Arabic", "Segoe UI"):
            if f in FONTS:
                return f
        return family

    def _insert_html(self, page, rect, text, style, align="left", line_height=1.2, rotate=0,
                     baseline=None, anchor_x=None):
        size = float(style.get("size", 12))
        color = style.get("color", (0, 0, 0))
        family = self._ensure_arabic_family(self.resolve_family(style), text)
        bold, italic = style.get("bold", False), style.get("italic", False)
        if style.get("family") == ORIGINAL_FONT:
            _, b, i = guess_family(style.get("orig_font", ""), style.get("orig_flags", 0))
            bold = style.get("bold", b)
            italic = style.get("italic", i)
        rtl = has_rtl(text)
        css = self._css_fontface(family)
        body = self._build_html(text, size, color, family, bold, italic, align, rtl, line_height)
        rect = pymupdf.Rect(rect)
        if rotate == 0 and (baseline is not None or anchor_x is not None):
            # dry run on a scratch page to measure where the text lands, then correct
            tmp = pymupdf.open()
            tp = tmp.new_page(width=max(rect.x1 + 50, 200), height=max(rect.y1 + 50, 200))
            try:
                tp.insert_htmlbox(rect, body, css=css, archive=self.archive)
                lines = [ln for b in tp.get_text("dict")["blocks"] if b.get("type") == 0 for ln in b["lines"]]
                if lines:
                    first = lines[0]
                    dx = dy = 0.0
                    if baseline is not None:
                        dy = baseline - first["spans"][0]["origin"][1]
                    if anchor_x is not None:
                        x0 = min(ln["bbox"][0] for ln in lines)
                        x1 = max(ln["bbox"][2] for ln in lines)
                        if align == "right":
                            dx = anchor_x - x1
                        elif align == "center":
                            dx = anchor_x - (x0 + x1) / 2
                        else:
                            dx = anchor_x - x0
                    rect = pymupdf.Rect(rect.x0 + dx, rect.y0 + dy, rect.x1 + dx, rect.y1 + dy)
            except Exception:
                pass
            finally:
                tmp.close()
        page.insert_htmlbox(rect, body, css=css, archive=self.archive, rotate=rotate)

    def text_width(self, text: str, style: dict) -> float:
        p = font_path(self.resolve_family(style), style.get("bold", False), style.get("italic", False))
        size = float(style.get("size", 12))
        try:
            f = pymupdf.Font(fontfile=p) if p else pymupdf.Font("helv")
            return max(f.text_length(line, size) for line in (text.split("\n") or [""]))
        except Exception:
            return len(text) * size * 0.55

    # ------------------------------------------------------------------ text editing
    @staticmethod
    def _shrink_for_redact(r: pymupdf.Rect) -> pymupdf.Rect:
        h = r.height
        return pymupdf.Rect(r.x0 + 0.2, r.y0 + h * 0.22, r.x1 - 0.2, r.y1 - h * 0.22)

    def _remove_text(self, page, rects):
        for r in rects:
            page.add_redact_annot(self._shrink_for_redact(pymupdf.Rect(r)), fill=False, cross_out=False)
        page.apply_redactions(images=IMG_NONE, graphics=ART_NONE, text=TXT_REMOVE)

    def _insert_line(self, page, text, origin, style, rotate, anchor_right=None, sample=""):
        """Insert one line of text whose baseline starts at origin (pdf space)."""
        size = float(style.get("size", 12))
        color = style.get("color", (0, 0, 0))
        if has_rtl(text):
            w = self.text_width(text, style) * 1.35 + 30
            if anchor_right is not None:  # right-aligned field (Arabic): keep the right edge
                right = anchor_right
                rect = pymupdf.Rect(right - w, origin[1] - size * 1.6, right + 2, origin[1] + size * 1.2)
                self._insert_html(page, rect, text, style, align="right", line_height=1.15, rotate=rotate,
                                  baseline=origin[1], anchor_x=right)
            else:  # left-aligned field (numbers / English): start where the old text started
                rect = pymupdf.Rect(origin[0] - 2, origin[1] - size * 1.6, origin[0] + w, origin[1] + size * 1.2)
                self._insert_html(page, rect, text, style, align="left", line_height=1.15, rotate=rotate,
                                  baseline=origin[1], anchor_x=origin[0])
            return
        fpath = self._resolve_font(page, style, sample, text)
        if fpath:
            page.insert_text(origin, text, fontsize=size, fontname=self._font_resource_name(fpath),
                             fontfile=fpath, color=color, rotate=rotate)
        else:
            page.insert_text(origin, text, fontsize=size, fontname="helv", color=color, rotate=rotate)

    def edit_text_line(self, obj: PageObject, new_text: str, style: dict):
        self.checkpoint(tr("تعديل نص"))
        self._edit_line(obj, new_text, style)

    def _edit_line(self, obj: PageObject, new_text: str, style: dict):
        page = self.doc[obj.pno]
        d = obj.data
        box = obj.rect
        origin = d["origin"]
        self._remove_text(page, [obj.rect])
        if d.get("ocr"):
            # OCR boxes can be off: use the real ink of the words on the scan
            box = self.scan_text_box(obj.pno, obj.rect)
            self._remove_text(page, [box])
            self._erase_scan_area(obj.pno, box)
            rtl_old = has_rtl(d.get("text", ""))
            origin = (box.x0, box.y1 - (box.height * 0.22 if rtl_old else 0.0))
            old = d.get("text", "")
            if new_text.strip() and len(new_text) <= len(old) + 2:  # same-length value: fit the old width
                wn = self.text_width(new_text, style)
                if wn > box.width * 1.04:
                    style = dict(style, size=float(style.get("size", 12)) * box.width * 1.02 / wn)
        if new_text.strip():
            rotate = _dir_to_rotate(d.get("dir", (1, 0)))
            style = dict(style, orig_font=d.get("font", ""), orig_flags=d.get("flags", 0))
            anchor_right = box.x1 if rotate == 0 and has_rtl(d.get("text", "")) else None
            self._insert_line(page, new_text, origin, style, rotate, anchor_right=anchor_right,
                              sample=d.get("text", ""))
        self.invalidate(obj.pno)

    def scan_text_box(self, pno: int, pdf_rect, grow=40.0):
        """Exact box of the printed words around an (approximate) OCR box, measured on the scan pixels.
        Table / underline rules are ignored. Returns a pdf-space Rect."""
        if np is None:
            return pymupdf.Rect(pdf_rect)
        page = self.doc[pno]
        dr = self.to_display(pno, pdf_rect)
        g_an = max(grow, 30.0)  # analyse a wider strip so paper vs ink is measured correctly
        area = pymupdf.Rect(dr.x0 - g_an, dr.y0 - 8, dr.x1 + g_an, dr.y1 + 8) & page.rect
        if area.is_empty:
            return pymupdf.Rect(pdf_rect)
        dpi = 200
        ppt = dpi / 72.0
        pix = page.get_pixmap(clip=area, dpi=dpi, alpha=False, annots=False)
        rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].astype(np.float32)
        _, text, elem, lines = self._classify_ink(rgb, ppt)
        m = (text | elem) & ~lines
        f = area.width / pix.width
        tx0, tx1 = (dr.x0 - area.x0) / f, (dr.x1 - area.x0) / f
        ty0, ty1 = (dr.y0 - area.y0) / f, (dr.y1 - area.y0) / f
        cy = (ty0 + ty1) / 2
        if tx1 - tx0 < 3 * ppt:  # a click, not a box: allow a little slack sideways
            tx0, tx1 = tx0 - 3 * ppt, tx1 + 3 * ppt
        ref_h = max(ty1 - ty0, 14 * ppt)
        hits = []
        gx = max(1, int(round(1.2 * ppt)))  # joins letters of a word, not separate words
        for x0, y0, x1, y1, n in self._components(self._box_any(m, gx, 0)):
            if y1 - y0 > 3 * ref_h:  # a logo / stamp, not a word
                continue
            if y0 <= cy <= y1 and x1 > tx0 and x0 < tx1:
                hits.append((x0, y0, x1, y1))
        if not hits:
            return pymupdf.Rect(pdf_rect)
        x0 = min(h[0] for h in hits); y0 = min(h[1] for h in hits)
        x1 = max(h[2] for h in hits); y1 = max(h[3] for h in hits)
        g = gx  # undo the sideways growth
        r = pymupdf.Rect(area.x0 + (x0 + g) * f, area.y0 + y0 * f, area.x0 + (x1 - g) * f, area.y0 + y1 * f)
        # keep the height close to the recognised line (underlines / dots touching the digits must not count)
        if dr.height > 3:
            r.y0 = max(r.y0, dr.y0 - 0.25 * dr.height)
            r.y1 = min(r.y1, dr.y1 + 0.25 * dr.height)
        return self.to_pdf(pno, r + (-0.8, -0.8, 0.8, 0.8))

    def edit_text_block(self, obj: PageObject, new_text: str, style: dict, align="left"):
        page = self.doc[obj.pno]
        self.checkpoint(tr("تعديل فقرة"))
        d = obj.data
        lines = d.get("lines", [])
        self._remove_text(page, [ln.rect for ln in lines] or [obj.rect])
        if new_text.strip():
            rotate = _dir_to_rotate(d.get("dir", (1, 0)))
            size = float(style.get("size", d.get("size", 12)))
            lh = 1.2
            if len(lines) > 1:
                gaps = [lines[i + 1].data["origin"][1] - lines[i].data["origin"][1] for i in range(len(lines) - 1)]
                gaps = [g for g in gaps if g > 0]
                if gaps:
                    lh = max(0.9, min(2.5, (sum(gaps) / len(gaps)) / max(size, 1)))
            r = obj.rect
            rect = pymupdf.Rect(r.x0 - 1, r.y0 - size, r.x1 + 2, r.y1 + size * 6)
            style = dict(style, orig_font=d.get("font", ""), orig_flags=d.get("flags", 0))
            anchor = {"left": r.x0, "right": r.x1, "center": (r.x0 + r.x1) / 2}.get(align)
            self._insert_html(page, rect, new_text, style, align=align, line_height=lh, rotate=rotate,
                              baseline=d["origin"][1] if rotate == 0 else None,
                              anchor_x=anchor if rotate == 0 and align != "justify" else None)
        self.invalidate(obj.pno)

    def delete_text(self, obj: PageObject):
        page = self.doc[obj.pno]
        self.checkpoint(tr("حذف نص"))
        lines = obj.data.get("lines", []) or [obj]
        self._remove_text(page, [ln.rect for ln in lines])
        for ln in lines:
            if ln.data.get("ocr"):
                self._erase_scan_area(obj.pno, ln.rect)
        self.invalidate(obj.pno)

    # ------------------------------------------------------------------ scanned pages
    def sample_colors(self, pno: int, pdf_rect):
        """(background, ink) colours of a region of the rendered page, as 0..1 tuples."""
        try:
            clip = self.to_display(pno, pdf_rect)
            pix = self.doc[pno].get_pixmap(clip=clip, dpi=150, alpha=False)
            a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].reshape(-1, 3)
            lum = a.mean(axis=1)
            bg = np.median(a[lum >= np.percentile(lum, 70)], axis=0) / 255
            fg = np.median(a[lum <= np.percentile(lum, 6)], axis=0) / 255
            return tuple(float(v) for v in bg), tuple(float(v) for v in fg)
        except Exception:
            return (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)

    def _erase_scan_area(self, pno, pdf_rect):
        # remove the ink of the old words from the scan pixels, keeping table / underline rules
        d = self.to_display(pno, pymupdf.Rect(pdf_rect) + (-1, -1, 1, 1))
        if np is not None and self.remove_color_ink(pno, d, 45, checkpoint=False, mode="all"):
            self._ocr_drop(pno, pdf_rect)
            return
        page = self.doc[pno]
        bg, _ = self.sample_colors(pno, pdf_rect)
        r = pymupdf.Rect(pdf_rect) + (-1.2, -1.2, 1.2, 1.2)
        page.add_redact_annot(r, fill=bg, cross_out=False)
        page.apply_redactions(images=IMG_PIXELS, graphics=ART_NONE, text=TXT_NONE)
        self._ocr_drop(pno, pdf_rect)

    def _ocr_data(self, pno: int):
        try:
            t, v = self.doc.xref_get_key(self.doc[pno].xref, "PSOCRData")
            if t != "xref":
                return None
            return json.loads(self.doc.xref_stream(int(v.split()[0])).decode("utf-8"))
        except Exception:
            return None

    def _ocr_save(self, pno: int, data: dict):
        page = self.doc[pno]
        t, v = self.doc.xref_get_key(page.xref, "PSOCRData")
        if t == "xref":
            x = int(v.split()[0])
        else:
            x = self.doc.get_new_xref()
            self.doc.update_object(x, "<<>>")
            self.doc.xref_set_key(page.xref, "PSOCRData", f"{x} 0 R")
        self.doc.update_stream(x, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _ocr_drop(self, pno: int, pdf_rect):
        """Forget recognised words inside an area (after it was edited / erased)."""
        data = self._ocr_data(pno)
        if not data:
            return
        r = pymupdf.Rect(pdf_rect)

        def keep(sp):
            b = pymupdf.Rect(sp["bbox"])
            i = b & r
            return not (i.is_valid and abs(i) >= 0.4 * max(abs(b), 1e-6))

        data["lines"] = [ln for ln in ([sp for sp in line if keep(sp)] for line in data["lines"]) if ln]
        self._ocr_save(pno, data)

    def ocr_lines(self, pno: int) -> list:
        return [o for o in self.get_objects(pno)["lines"] if o.data.get("ocr")]

    def has_text(self, pno: int) -> bool:
        return bool(self.doc[pno].get_text("text").strip())

    def is_scanned(self, pno: int) -> bool:
        page = self.doc[pno]
        if self.has_text(pno):
            return False
        area = abs(page.rect)
        cover = sum(abs(pymupdf.Rect(i["bbox"]) & page.rect * page.derotation_matrix)
                    for i in page.get_image_info() if pymupdf.Rect(i["bbox"]).is_valid)
        return cover >= 0.5 * area

    def ocr_prepare(self, pno: int, dpi=300) -> pymupdf.Pixmap:
        return self.doc[pno].get_pixmap(dpi=dpi, alpha=False)

    def ocr_apply(self, pno: int, ocr_pdf: bytes, replace=False):
        """Add Tesseract's invisible text layer directly into the page content
        (the scan itself is untouched). Inlined (not a Form) so Arabic extracts in the right order."""
        o = pymupdf.open("pdf", ocr_pdf)
        op = o[0]
        # 1) remember the recognised words (correct reading order) in our own page data
        Wd, Hd = self.page_display_size(pno)
        fx, fy = Wd / op.rect.width, Hd / op.rect.height
        lines = []
        for b in op.get_text("dict")["blocks"]:
            if b.get("type"):
                continue
            for ln in b["lines"]:
                spans = []
                for sp in ln["spans"]:
                    t = normalize_extracted(sp["text"]).strip()
                    if not t:
                        continue
                    r = pymupdf.Rect(sp["bbox"])
                    pr = self.to_pdf(pno, (r.x0 * fx, r.y0 * fy, r.x1 * fx, r.y1 * fy))
                    spans.append({"text": t, "bbox": [round(v, 2) for v in pr], "size": round(sp["size"] * fy, 2)})
                if spans:
                    lines.append(spans)
        prev = {"lines": []} if replace else (self._ocr_data(pno) or {"lines": []})
        self._ocr_save(pno, {"lines": prev["lines"] + lines})
        # 2) the standard invisible text layer for other PDF readers
        op.clean_contents()
        s = o.xref_stream(op.get_contents()[0]).decode("latin-1")
        for item in op.get_images(full=True):
            s = re.sub(r"/" + re.escape(item[7]) + r"\s+Do\b", "", s)
        fonts = op.get_fonts(full=True)
        Wo, Ho = op.rect.width, op.rect.height
        # copy the OCR page in temporarily so its font objects come along
        self.doc.insert_pdf(o)
        tmp_pno = self.doc.page_count - 1
        new_fonts = {f[4]: f[0] for f in self.doc[tmp_pno].get_fonts(full=True)}
        page = self.doc[pno]
        for f in fonts:
            res = f[4]
            nx = new_fonts.get(res)
            if not nx:
                continue
            alias = f"PSOCR{nx}"
            s = re.sub(r"/" + re.escape(res) + r"(?=[\s\[(<])", "/" + alias, s)
            self.doc.xref_set_key(page.xref, f"Resources/Font/{alias}", f"{nx} 0 R")
        self.doc.delete_page(tmp_pno)
        page = self.doc[pno]
        W, H = page.rect.width, page.rect.height
        M = (pymupdf.Matrix(1, 0, 0, -1, 0, Ho) * pymupdf.Matrix(W / Wo, 0, 0, H / Ho, 0, 0)
             * page.derotation_matrix * ~page.transformation_matrix)
        page.wrap_contents()
        data = ("\nq %s cm\n" % " ".join(f"{v:.6f}" for v in tuple(M)) + s + "\nQ\n").encode("latin-1")
        cx = self.doc.get_new_xref()
        self.doc.update_object(cx, "<<>>")
        self.doc.update_stream(cx, data)
        conts = page.get_contents()
        self.doc.xref_set_key(page.xref, "Contents", "[%s]" % " ".join(f"{x} 0 R" for x in conts + [cx]))
        self.doc.xref_set_key(page.xref, "PSOCR", "true")
        o.close()
        self.invalidate(pno)

    def add_text(self, pno: int, display_pt, text: str, style: dict, align="left"):
        """Add new text; display_pt is the top-left (LTR) or top-right (RTL) corner in display space."""
        page = self.doc[pno]
        self.checkpoint(tr("إضافة نص"))
        size = float(style.get("size", 12))
        w = self.text_width(text, style) * (1.3 if has_rtl(text) else 1.08) + 12
        nlines = text.count("\n") + 1
        h = nlines * size * 1.45 + size
        x, y = display_pt
        if has_rtl(text) and align == "left":
            align = "right"
        drect = pymupdf.Rect(x - w, y, x, y + h) if align == "right" else pymupdf.Rect(x, y, x + w, y + h)
        W, H = page.rect.width, page.rect.height
        dx = -drect.x0 + 4 if drect.x0 < 0 else (W - 4 - drect.x1 if drect.x1 > W else 0)
        drect = pymupdf.Rect(drect.x0 + dx, drect.y0, drect.x1 + dx, drect.y1)
        self._text_layer(pno, drect, text, style, align, {"kind": "text"})
        self.invalidate(pno)

    # ------------------------------------------------------------------ layers
    # ------------------------------------------------------------------ stacking order
    def _ensure_layer(self, obj: PageObject):
        """Return a layer for obj (objects that are not layers yet are lifted into one, without moving)."""
        if obj.kind == "layer":
            return obj
        before = {o.data["xref"] for o in self.list_layers(obj.pno)}
        inc = ("text",) if obj.kind in ("line", "block") else ("elements",)
        if obj.kind == "image" and not obj.data.get("full_page") and obj.data.get("xref"):
            # a separate picture: re-place it as a layer with full quality
            pix = self.image_pixmap(obj.data["xref"])
            if pix is not None:
                page = self.doc[obj.pno]
                dr = self.to_display(obj.pno, obj.rect)
                self._delete_image_instance(page, obj)
                tmp = pymupdf.open()
                tp = tmp.new_page(width=dr.width, height=dr.height)
                tp.insert_image(tp.rect, pixmap=pix, keep_proportion=False)
                self._place_layer(obj.pno, dr, tmp, {"kind": "image"})
        else:
            self.lift_region(obj.pno, self.to_display(obj.pno, obj.rect) + (-1, -1, 1, 1), inc, checkpoint=False)
        new = [o for o in self.list_layers(obj.pno) if o.data["xref"] not in before]
        return new[-1] if new else None

    def reorder(self, obj: PageObject, where: str) -> bool:
        """where: front | back | forward | backward — for overlapping elements."""
        self.checkpoint(tr("ترتيب العناصر"))
        lay = self._ensure_layer(obj)
        if lay is None:
            self.drop_last_checkpoint()
            return False
        page = self.doc[lay.pno]
        page.clean_contents()
        cx = page.get_contents()[0]
        s = self.doc.xref_stream(cx).decode("latin-1")
        res = lay.data["res"]
        pat = re.compile(r"q\s+/" + re.escape(res) + r"\s+Do\s+Q\s*")
        m = pat.search(s)
        block = m.group(0) if m else None
        if not m:
            m = re.search(r"/" + re.escape(res) + r"\s+Do\b\s*", s)
            if not m:
                self.drop_last_checkpoint()
                return False
            block = "q " + m.group(0).strip() + " Q\n"
        s2 = s[:m.start()] + s[m.end():]
        if where in ("front", "back"):
            s2 = (s2.rstrip() + "\n" + block.strip() + "\n") if where == "front" else (block.strip() + "\n" + s2)
        else:
            # neighbouring layer in the stacking order
            names = [o.data["res"] for o in self.list_layers(lay.pno)]
            pos = []
            for n in names:
                mm = re.search(r"q\s+/" + re.escape(n) + r"\s+Do\s+Q\s*", s2)
                if mm and n != res:
                    pos.append((mm.start(), mm.end(), n))
            pos.sort()
            at = m.start()
            if where == "forward":
                nxt = [p for p in pos if p[0] >= at]
                ins = nxt[0][1] if nxt else len(s2)
            else:
                prv = [p for p in pos if p[1] <= at]
                ins = prv[-1][0] if prv else 0
            s2 = s2[:ins] + "\n" + block.strip() + "\n" + s2[ins:]
        self.doc.update_stream(cx, s2.encode("latin-1"))
        self.invalidate(lay.pno)
        return True

    # ------------------------------------------------------------------ copy / paste
    def copy_object(self, obj: PageObject) -> bytes:
        """A one-page PDF 'snippet' holding just this element (vector / text kept); pasteable anywhere."""
        pno = obj.pno
        r = pymupdf.Rect(obj.rect)
        out = pymupdf.open()
        meta = {"kind": "element"}
        if obj.kind == "layer":
            meta = {k: v for k, v in obj.data.get("meta", {}).items() if k not in ("name", "ocg")}
            tmp = pymupdf.open()
            tmp.insert_pdf(self.doc, from_page=pno, to_page=pno)
            tp = tmp[0]
            for a in list(tp.annots() or []):
                tp.delete_annot(a)
            tp.set_rotation(0)
            tp.clean_contents()
            tmp.update_stream(tp.get_contents()[0], f"q /{obj.data['res']} Do Q".encode("latin-1"))
            # keep only what the element uses (drop the page's other images / fonts)
            tp.clean_contents(sanitize=True)
            tmp = pymupdf.open("pdf", tmp.tobytes(garbage=4))
            op = out.new_page(width=r.width, height=r.height)
            op.show_pdf_page(op.rect, tmp, 0, clip=r)
        elif obj.kind == "image" and not obj.data.get("full_page") and obj.data.get("xref"):
            pix = self.image_pixmap(obj.data["xref"])
            op = out.new_page(width=r.width, height=r.height)
            op.insert_image(op.rect, pixmap=pix, keep_proportion=False)
            meta = {"kind": "image"}
        elif self._scan_under(pno, r) and np is not None:
            dr = self.to_display(pno, r)
            res = self.scan_object_image(pno, dr, "all", 45)
            if res:
                w, h, data, tight = res
                png = pymupdf.Pixmap(pymupdf.csRGB, w, h, data, 1).tobytes("png")
                op = out.new_page(width=tight.width, height=tight.height)
                op.insert_image(op.rect, stream=png, keep_proportion=False)
            else:
                op = out.new_page(width=r.width, height=r.height)
                op.show_pdf_page(op.rect, self.doc, pno, clip=r)
        else:
            op = out.new_page(width=r.width, height=r.height)
            op.show_pdf_page(op.rect, self.doc, pno, clip=r)
            if obj.kind in ("line", "block"):
                meta = {"kind": "text"}
        out.set_metadata({"subject": "mesta-object", "keywords": json.dumps(meta, ensure_ascii=False)})
        try:
            out.subset_fonts()
        except Exception:
            pass
        data = out.tobytes(garbage=3, deflate=True)
        out.close()
        return data

    @staticmethod
    def snippet_from_image(png: bytes, width_pt: float = 0) -> bytes:
        pix = pymupdf.Pixmap(png)
        w = width_pt or min(pix.width * 0.75, 400)
        h = w * pix.height / max(1, pix.width)
        out = pymupdf.open()
        op = out.new_page(width=w, height=h)
        op.insert_image(op.rect, stream=png, keep_proportion=False)
        out.set_metadata({"subject": "mesta-object", "keywords": json.dumps({"kind": "image"})})
        return out.tobytes()

    def paste_object(self, pno: int, data: bytes, display_center=None) -> int:
        """Paste a copied element as a new independent layer, centred on display_center."""
        src = pymupdf.open("pdf", data)
        sp = src[0]
        w, h = sp.rect.width, sp.rect.height
        page = self.doc[pno]
        W, H = page.rect.width, page.rect.height
        if w > W * 0.95 or h > H * 0.95:  # too big for this page: scale down
            f = min(W * 0.9 / w, H * 0.9 / h)
            w, h = w * f, h * f
        cx, cy = display_center if display_center else (W / 2, H / 2)
        x0 = min(max(2, cx - w / 2), W - w - 2)
        y0 = min(max(2, cy - h / 2), H - h - 2)
        try:
            meta = json.loads(src.metadata.get("keywords") or "{}")
        except Exception:
            meta = {}
        meta = {k: v for k, v in meta.items() if k not in ("name", "ocg")}
        meta.setdefault("kind", "element")
        self.checkpoint(tr("لصق"))
        x = self._place_layer(pno, pymupdf.Rect(x0, y0, x0 + w, y0 + h), src, meta)
        src.close()
        self.invalidate(pno)
        return x

    def _layer_name(self, kind: str) -> str:
        # counted from the PDF layer list (fast even for documents with thousands of pages)
        base = LAYER_KINDS.get(kind, kind)
        names = {v.get("name", "") for v in self.doc.get_ocgs().values()}
        n = 1
        while f"{base} {n}" in names:
            n += 1
        return f"{base} {n}"

    def _place_layer(self, pno: int, drect, tmpdoc, meta: dict) -> int:
        """Put page 0 of tmpdoc onto the page as an independent layer (own Form XObject + PDF layer)."""
        page = self.doc[pno]
        before = {x[0] for x in page.get_xobjects()}
        meta = dict(meta)
        meta["name"] = meta.get("name") or self._layer_name(meta.get("kind", "image"))
        ocg = meta.get("ocg")
        if not ocg or ocg not in self.doc.get_ocgs():
            ocg = self.doc.add_ocg(meta["name"], on=True)
        meta["ocg"] = ocg
        page.show_pdf_page(self.to_pdf(pno, drect), tmpdoc, 0, keep_proportion=False, oc=ocg, rotate=page.rotation)
        new = [x for x in page.get_xobjects() if x[0] not in before and x[2] == 0]
        wrapper = new[0][0] if new else 0
        if wrapper:
            self.doc.xref_set_key(wrapper, LAYER_KEY, pymupdf.get_pdf_str(json.dumps(meta, ensure_ascii=False)))
        self.invalidate(pno)
        return wrapper

    def _text_layer(self, pno, drect, text, style, align, meta):
        """Build a tightly-cropped text layer whose box starts at drect (display space)."""
        w, h = max(drect.width, 20), max(drect.height, 10)
        probe = pymupdf.open()
        pp = probe.new_page(width=w, height=h)
        self._insert_html(pp, pp.rect, text, style, align=align, line_height=1.25)
        bb = None
        for b in pp.get_text("dict")["blocks"]:
            if b.get("type") == 0:
                bb = pymupdf.Rect(b["bbox"]) if bb is None else bb | pymupdf.Rect(b["bbox"])
        probe.close()
        pad = 2.0
        if bb is None:
            bb = pymupdf.Rect(0, 0, w, h)
        tmp = pymupdf.open()
        tp = tmp.new_page(width=bb.width + 2 * pad, height=bb.height + 2 * pad)
        self._insert_html(tp, pymupdf.Rect(pad - bb.x0, pad - bb.y0, pad - bb.x0 + w, pad - bb.y0 + h), text, style,
                          align=align, line_height=1.25)
        final = pymupdf.Rect(drect.x0 + bb.x0 - pad, drect.y0 + bb.y0 - pad, drect.x0 + bb.x1 + pad, drect.y0 + bb.y1 + pad)
        st = {k: (list(v) if isinstance(v, tuple) else v) for k, v in style.items()}
        meta = dict(meta, kind="text", text=text, style=st, align=align)
        self._place_layer(pno, final, tmp, meta)

    def list_layers(self, pno: int) -> list:
        page = self.doc[pno]
        out = []
        xobjs = [x for x in page.get_xobjects() if x[2] == 0]
        if not xobjs:
            return out
        try:
            content = page.read_contents().decode("latin-1")
        except Exception:
            content = ""
        ocgs = self.doc.get_ocgs()
        F = page.transformation_matrix
        for xref, name, _, bbox in xobjs:
            t, v = self.doc.xref_get_key(xref, LAYER_KEY)
            if t in ("null", None) or not v:
                continue
            mpos = re.search(r"/" + re.escape(name) + r"\s+Do\b", content)
            if not mpos:
                continue
            try:
                meta = json.loads(v)
            except Exception:
                continue
            r = (pymupdf.Rect(bbox) * F).normalize()  # get_xobjects bbox already includes /Matrix
            out.append(PageObject("layer", pno, r, {
                "xref": xref, "res": name, "meta": meta, "z": mpos.start(),
                "visible": ocgs.get(meta.get("ocg"), {}).get("on", True)}))
        out.sort(key=lambda o: o.data["z"])  # back-to-front, as drawn on the page
        return out

    def _xref_matrix(self, xref) -> pymupdf.Matrix:
        t, v = self.doc.xref_get_key(xref, "Matrix")
        if t == "array":
            try:
                return pymupdf.Matrix(*[float(x) for x in v.strip("[]").split()])
            except Exception:
                pass
        return pymupdf.Matrix(1, 0, 0, 1, 0, 0)

    def all_layers(self) -> list:
        out = []
        for p in range(self.page_count):
            out.extend(self.list_layers(p))
        return out

    def delete_layer(self, obj: PageObject, checkpoint=True):
        page = self.doc[obj.pno]
        if checkpoint:
            self.checkpoint(tr("حذف طبقة"))
        page.clean_contents()
        cx = page.get_contents()[0]
        s = self.doc.xref_stream(cx).decode("latin-1")
        s = re.sub(r"/" + re.escape(obj.data["res"]) + r"\s+Do\b", "", s, count=1)
        self.doc.update_stream(cx, s.encode("latin-1"))
        self.invalidate(obj.pno)

    def move_layer(self, obj: PageObject, new_pdf_rect):
        self.checkpoint(tr("نقل طبقة"))
        self._move_layer_raw(obj, new_pdf_rect)

    def _move_layer_raw(self, obj: PageObject, new_pdf_rect):
        page = self.doc[obj.pno]
        xref = obj.data["xref"]
        t, v = self.doc.xref_get_key(xref, "BBox")
        bbox = pymupdf.Rect(*[float(x) for x in v.strip("[]").split()])
        dst = (pymupdf.Rect(new_pdf_rect) * ~page.transformation_matrix).normalize()
        sx, sy = dst.width / max(bbox.width, 1e-6), dst.height / max(bbox.height, 1e-6)
        M = pymupdf.Matrix(sx, 0, 0, sy, dst.x0 - bbox.x0 * sx, dst.y0 - bbox.y0 * sy)
        self.doc.xref_set_key(xref, "Matrix", "[%s]" % " ".join(f"{x:.5f}" for x in tuple(M)))
        self.invalidate(obj.pno)

    def set_layer_visible(self, obj: PageObject, on: bool):
        ocg = obj.data["meta"].get("ocg")
        ocgs = self.doc.get_ocgs()
        if ocg not in ocgs:
            return
        self.checkpoint(tr("إظهار طبقة") if on else tr("إخفاء طبقة"))
        state = {x: v["on"] for x, v in ocgs.items()}
        state[ocg] = on
        self.doc.set_layer(-1, on=[x for x, s in state.items() if s], off=[x for x, s in state.items() if not s])
        # MuPDF applies the default layer configuration when a document is (re)loaded
        self.doc = self._load_bytes(self.doc.tobytes())
        self.invalidate()

    def rename_layer(self, obj: PageObject, name: str):
        self.checkpoint(tr("إعادة تسمية طبقة"))
        meta = dict(obj.data["meta"], name=name)
        self.doc.xref_set_key(obj.data["xref"], LAYER_KEY, pymupdf.get_pdf_str(json.dumps(meta, ensure_ascii=False)))
        if meta.get("ocg"):
            try:
                self.doc.xref_set_key(meta["ocg"], "Name", pymupdf.get_pdf_str(name))
            except Exception:
                pass
        self.invalidate(obj.pno)

    def flatten_layer(self, obj: PageObject):
        """Merge the layer into the page: it becomes normal page content."""
        self.checkpoint(tr("دمج طبقة"))
        self.doc.xref_set_key(obj.data["xref"], LAYER_KEY, "null")
        self.invalidate(obj.pno)

    def edit_text_layer(self, obj: PageObject, text: str, style: dict, align: str):
        self.checkpoint(tr("تعديل طبقة نص"))
        meta = obj.data["meta"]
        d = self.to_display(obj.pno, obj.rect)
        self.delete_layer(obj, checkpoint=False)
        if not text.strip():
            return
        size = float(style.get("size", 12))
        w = self.text_width(text, style) * (1.3 if has_rtl(text) else 1.08) + 12
        h = (text.count("\n") + 1) * size * 1.45 + size
        right = align == "right" or (has_rtl(text) and align != "center")
        drect = pymupdf.Rect(d.x1 - w, d.y0, d.x1, d.y0 + h) if right else pymupdf.Rect(d.x0, d.y0, d.x0 + w, d.y0 + h)
        self._text_layer(obj.pno, drect, text, style, "right" if right else align,
                         {"name": meta.get("name"), "ocg": meta.get("ocg")})
        self.invalidate(obj.pno)

    def words_in(self, pno: int, display_rect):
        """Text inside a display-space rectangle (reading order) + display rects of the words."""
        page = self.doc[pno]
        r = self.to_pdf(pno, display_rect)
        ocr = self.ocr_lines(pno) if self._ocr_data(pno) else []
        if ocr:
            hit = [o for o in ocr if (o.rect & r).is_valid and abs(o.rect & r) >= 0.3 * max(abs(o.rect), 1e-6)]
            hit.sort(key=lambda o: (round(o.rect.y0 / max(o.rect.height, 4)), -o.rect.x0))
            rows, last = [], None
            for o in hit:
                key = round(o.rect.y0 / max(o.rect.height, 4))
                if key != last:
                    rows.append([])
                    last = key
                rows[-1].append(o.data["text"])
            return "\n".join("   ".join(x) for x in rows), [self.to_display(pno, o.rect) for o in hit]
        words = []
        for w in page.get_text("words", sort=True):
            wr = pymupdf.Rect(w[:4])
            inter = wr & r
            if inter.is_valid and not inter.is_empty and abs(inter) >= 0.4 * max(abs(wr), 1e-6):
                words.append((w[5], w[6], w[7], normalize_extracted(w[4]), wr))
        lines, last = [], None
        for b, l, _, t, _ in words:
            if (b, l) != last:
                lines.append([])
                last = (b, l)
            lines[-1].append(t)
        text = "\n".join(" ".join(x) for x in lines)
        return text, [self.to_display(pno, w[4]) for w in words]

    def page_text(self, pno: int) -> str:
        if self._ocr_data(pno):  # scanned page: use the recognised words in reading order
            return self.words_in(pno, self.doc[pno].rect)[0]
        return normalize_extracted(self.doc[pno].get_text("text", sort=True))

    def toc(self):
        try:
            return self.doc.get_toc(simple=True)
        except Exception:
            return []

    def find_in_page(self, pno: int, needle: str):
        """Search one page (used page by page so huge files never freeze the window)."""
        hits = []
        low = needle.lower()
        ocr = self.ocr_lines(pno) if self._ocr_data(pno) else []
        for o in ocr:
            if low in o.data["text"].lower():
                hits.append((pno, pymupdf.Rect(o.rect)))
        for r in self.doc[pno].search_for(needle):
            r = pymupdf.Rect(r)
            if not any(r.intersects(o.rect) for o in ocr):
                hits.append((pno, r))
        return hits

    def find_text(self, needle: str):
        hits = []
        if not needle:
            return hits
        low = needle.lower()
        for pno in range(self.page_count):
            ocr = self.ocr_lines(pno) if self._ocr_data(pno) else []
            for o in ocr:
                if low in o.data["text"].lower():
                    hits.append((pno, pymupdf.Rect(o.rect)))
            for r in self.doc[pno].search_for(needle):
                r = pymupdf.Rect(r)
                if not any(r.intersects(o.rect) for o in ocr):
                    hits.append((pno, r))
        return hits

    def _span_at(self, pno, rect):
        best, best_area = None, 0
        for ln in self.get_objects(pno)["lines"]:
            for s in ln.data["spans"]:
                inter = pymupdf.Rect(s["bbox"]) & rect
                a = abs(inter) if inter.is_valid else 0
                if a > best_area:
                    best, best_area = (s, ln), a
        return best

    def replace_all(self, needle: str, replacement: str, style_override: dict | None = None,
                    pages: list[int] | None = None) -> int:
        if not needle:
            return 0
        pages = pages if pages is not None else list(range(self.page_count))
        todo, ocr_todo = {}, {}
        for pno in pages:
            ocr = self.ocr_lines(pno) if self._ocr_data(pno) else []
            segs = [o for o in ocr if needle in o.data["text"]]
            if segs:
                ocr_todo[pno] = segs
            hits = [pymupdf.Rect(h) for h in self.doc[pno].search_for(needle)
                    if not any(pymupdf.Rect(h).intersects(o.rect) for o in ocr)]
            if hits:
                todo[pno] = hits
        if not todo and not ocr_todo:
            return 0
        self.checkpoint(tr("استبدال الكل"))
        count = 0
        for pno, segs in ocr_todo.items():  # scanned text: rewrite the whole recognised field
            for o in segs:
                _, fg = self.sample_colors(pno, o.rect)
                style = {"family": "Arial", "size": o.data["size"], "color": fg}
                if style_override:
                    style.update(style_override)
                self._edit_line(o, o.data["text"].replace(needle, replacement), style)
                count += o.data["text"].count(needle)
        for pno, hits in todo.items():
            page = self.doc[pno]
            infos = []
            for h in hits:
                found = self._span_at(pno, h)
                if found:
                    s, ln = found
                    style = {"family": ORIGINAL_FONT, "size": s["size"], "color": int_to_rgb(s.get("color", 0)),
                             "orig_font": s.get("font", ""), "orig_flags": s.get("flags", 0)}
                    origin = (h.x0, s["origin"][1])
                    rot = _dir_to_rotate(ln.data.get("dir", (1, 0)))
                    sample = s["text"]
                else:
                    style = {"family": "Arial", "size": h.height * 0.8, "color": (0, 0, 0)}
                    origin = (h.x0, h.y1 - h.height * 0.22)
                    rot = 0
                    sample = ""
                if style_override:
                    style.update(style_override)
                infos.append((h, origin, style, rot, sample))
            self._remove_text(page, hits)
            self.invalidate(pno)
            if replacement:
                for h, origin, style, rot, sample in infos:
                    if rot != 0:
                        origin = (origin[0], origin[1])
                    self._insert_line(page, replacement, origin, style, rot,
                                      anchor_right=h.x1 if has_rtl(replacement) else None, sample=sample)
            count += len(hits)
            self.invalidate(pno)
        return count

    # ------------------------------------------------------------------ images
    def _image_name(self, page, xref):
        for item in page.get_images(full=True):
            if item[0] == xref:
                return item[7], item[9]
        return None, None

    def _do_target(self, page, xref):
        """Return (stream_xref, text, matches) for the 'Do' operators that paint image xref."""
        name, ref = self._image_name(page, xref)
        if not name:
            return None
        if not ref:
            page.clean_contents()
            conts = page.get_contents()
            if not conts:
                return None
            target = conts[0]
        else:
            target = ref
        text = self.doc.xref_stream(target).decode("latin-1")
        matches = list(re.finditer(r"/" + re.escape(name) + r"\s+Do\b", text))
        return (target, text, matches) if matches else None

    def _delete_image_instance(self, page, obj: PageObject) -> bool:
        xref = obj.data["xref"]
        if xref:
            found = self._do_target(page, xref)
            if found:
                target, text, matches = found
                m = matches[min(obj.data.get("nth", 0), len(matches) - 1)]
                text = text[:m.start()] + text[m.end():]
                self.doc.update_stream(target, text.encode("latin-1"))
                return True
        # fallback (inline images or unusual structure): redact image area
        r = obj.rect
        inner = pymupdf.Rect(r.x0 + r.width * 0.3, r.y0 + r.height * 0.3, r.x1 - r.width * 0.3, r.y1 - r.height * 0.3)
        page.add_redact_annot(inner, fill=False, cross_out=False)
        page.apply_redactions(images=IMG_REMOVE, graphics=ART_NONE, text=TXT_NONE)
        return True

    def delete_image(self, obj: PageObject):
        page = self.doc[obj.pno]
        self.checkpoint(tr("حذف صورة"))
        self._delete_image_instance(page, obj)
        self.invalidate(obj.pno)

    def delete_similar_images(self, obj: PageObject) -> int:
        """Delete every occurrence of the same image (same pixels) on all pages."""
        digest, xref = obj.data.get("digest"), obj.data.get("xref")
        self.checkpoint(tr("حذف الصورة من كل الصفحات"))
        count = 0
        for pno in range(self.page_count):
            page = self.doc[pno]
            for _ in range(200):
                self.invalidate(pno)
                cands = [o for o in self.get_objects(pno)["images"]
                         if (digest and o.data.get("digest") == digest) or (xref and o.data.get("xref") == xref)]
                if not cands:
                    break
                before = len(self.get_objects(pno)["images"])
                self._delete_image_instance(page, cands[-1])
                self.invalidate(pno)
                count += 1
                if len(self.get_objects(pno)["images"]) >= before:
                    break
        self.invalidate()
        return count

    def count_similar_images(self, obj: PageObject) -> int:
        digest = obj.data.get("digest")
        n = 0
        for pno in range(self.page_count):
            n += sum(1 for o in self.get_objects(pno)["images"] if o.data.get("digest") == digest)
        return n

    def image_pixmap(self, xref: int) -> pymupdf.Pixmap | None:
        try:
            pix = pymupdf.Pixmap(self.doc, xref)
            smask = self.doc.xref_get_key(xref, "SMask")
            if smask[0] == "xref":
                try:
                    mask = pymupdf.Pixmap(self.doc, int(smask[1].split()[0]))
                    pix = pymupdf.Pixmap(pix, mask)
                except Exception:
                    pass
            if pix.colorspace and pix.colorspace.n not in (1, 3):
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            return pix
        except Exception:
            return None

    def save_image(self, obj: PageObject, path: str):
        pix = self.image_pixmap(obj.data["xref"])
        if pix is None:
            pix = self.doc[obj.pno].get_pixmap(clip=self.to_display(obj.pno, obj.rect), dpi=200)
        if pix.alpha and path.lower().endswith((".jpg", ".jpeg")):
            pix = pymupdf.Pixmap(pix, 0)
        pix.save(path)

    def move_image(self, obj: PageObject, new_pdf_rect) -> bool:
        """Move/resize an image instance, keeping original quality & orientation."""
        page = self.doc[obj.pno]
        self.checkpoint(tr("نقل/تحجيم صورة"))
        new = pymupdf.Rect(new_pdf_rect)
        old = pymupdf.Rect(obj.rect)
        ok = False
        if obj.data.get("xref") and old.width > 0 and old.height > 0:
            found = self._do_target(page, obj.data["xref"])
            if found:
                target, text, matches = found
                m = matches[min(obj.data.get("nth", 0), len(matches) - 1)]
                sx, sy = new.width / old.width, new.height / old.height
                T = pymupdf.Matrix(sx, 0, 0, sy, new.x0 - old.x0 * sx, new.y0 - old.y0 * sy)
                C = pymupdf.Matrix(obj.data["transform"])
                flip = pymupdf.Matrix(1, 0, 0, -1, 0, 1)
                for cand in (C, flip * C):
                    try:
                        M = cand * T * ~cand
                    except Exception:
                        continue
                    inj = "q %s cm %s Q" % (" ".join(f"{v:.6f}" for v in tuple(M)), m.group(0))
                    self.doc.update_stream(target, (text[:m.start()] + inj + text[m.end():]).encode("latin-1"))
                    self.invalidate(obj.pno)
                    imgs = [o for o in self.get_objects(obj.pno)["images"] if o.data["xref"] == obj.data["xref"]]
                    if any(abs(o.rect.x0 - new.x0) < 1.5 and abs(o.rect.y1 - new.y1) < 1.5
                           and abs(o.rect.width - new.width) < 2 for o in imgs):
                        ok = True
                        break
                    self.doc.update_stream(target, text.encode("latin-1"))
                    self.invalidate(obj.pno)
        if not ok:  # fallback: re-insert pixels
            pix = self.image_pixmap(obj.data["xref"]) if obj.data.get("xref") else None
            if pix is None:
                pix = page.get_pixmap(clip=self.to_display(obj.pno, old), dpi=200)
            self._delete_image_instance(page, obj)
            page.insert_image(new, pixmap=pix, keep_proportion=False, rotate=page.rotation)
        self.invalidate(obj.pno)
        return True

    def replace_image(self, obj: PageObject, filename: str):
        page = self.doc[obj.pno]
        self.checkpoint(tr("استبدال صورة"))
        r = obj.rect
        self._delete_image_instance(page, obj)
        page.insert_image(r, filename=filename, keep_proportion=True, rotate=page.rotation)
        self.invalidate(obj.pno)

    def insert_image(self, pno: int, display_rect, png_bytes: bytes, all_pages=False, label=tr("إضافة صورة"),
                     kind="image"):
        """Insert an image / stamp / signature as an independent layer (one per page)."""
        self.checkpoint(label)
        dr0 = pymupdf.Rect(display_rect)
        tmp = pymupdf.open()
        tp = tmp.new_page(width=dr0.width, height=dr0.height)
        tp.insert_image(tp.rect, stream=png_bytes, keep_proportion=False)
        meta = {"kind": kind, "name": self._layer_name(kind)}
        pages = range(self.page_count) if all_pages else [pno]
        for p in pages:
            dr = dr0
            if all_pages and p != pno:
                # keep the same relative position on pages of different size
                w0, h0 = self.page_display_size(pno)
                w1, h1 = self.page_display_size(p)
                fx, fy = w1 / w0, h1 / h0
                dr = pymupdf.Rect(dr0.x0 * fx, dr0.y0 * fy, dr0.x0 * fx + dr0.width, dr0.y0 * fy + dr0.height)
            self._place_layer(p, dr, tmp, meta)
            meta.setdefault("ocg", None)
            if meta["ocg"] is None:  # share one PDF layer across pages
                lay = [o for o in self.list_layers(p) if o.data["meta"].get("name") == meta["name"]]
                if lay:
                    meta["ocg"] = lay[-1].data["meta"].get("ocg")
            self.invalidate(p)

    # ------------------------------------------------------------------ annotations / drawings
    def delete_annot(self, obj: PageObject):
        page = self.doc[obj.pno]
        self.checkpoint(tr("حذف تعليق"))
        for a in page.annots() or []:
            if a.xref == obj.data["xref"]:
                page.delete_annot(a)
                break
        self.invalidate(obj.pno)

    def delete_drawing(self, obj: PageObject, with_text=False):
        """Remove the vector paths of a drawn stamp/shape without touching anything outside it."""
        pno = obj.pno
        self.checkpoint(tr("حذف رسم"))
        saved = self._undo[-1][1]
        r = pymupdf.Rect(obj.rect)

        def paths():
            return [pymupdf.Rect(d["rect"]) for d in self.doc[pno].get_drawings()]

        before = paths()
        inside = lambda pr: (pr & r).is_valid and abs(pr & r) >= 0.9 * max(abs(pr), 1e-6) if not pr.is_empty \
            else r.contains(pr.tl)
        target = [p for p in before if inside(p) or (r + (-2, -2, 2, 2)).contains(p)]
        outside = [p for p in before if p not in target]
        maxw = max([d.get("width") or 1 for d in self.doc[pno].get_drawings()
                    if pymupdf.Rect(d["rect"]) in target] or [1])
        attempts = [(ART_COVERED, 4 + 0.03 * max(r.width, r.height) + 6 * maxw), (ART_TOUCHED, 1.0)]
        for mode, m in attempts:
            page = self.doc[pno]
            page.add_redact_annot(r + (-m, -m, m, m), fill=False, cross_out=False)
            page.apply_redactions(images=IMG_NONE, graphics=mode, text=TXT_REMOVE if with_text else TXT_NONE)
            after = paths()
            gone = len(after) <= len(before) - max(1, len(target))
            kept_outside = sum(1 for p in after if p not in target) >= len(outside)
            if gone and kept_outside:
                break
            self.doc = self._load_bytes(saved)  # revert and try the next strategy
        else:
            self.drop_last_checkpoint()
            self.invalidate()
            raise RuntimeError(tr("تعذر فصل هذا الرسم عن باقي الصفحة.\nاستخدم أداة \"مسح منطقة\" حوله بدلاً من ذلك."))
        self.invalidate()

    def delete_object(self, obj: PageObject):
        if obj.kind == "layer":
            self.delete_layer(obj)
        elif obj.kind == "image":
            self.delete_image(obj)
        elif obj.kind == "annot":
            self.delete_annot(obj)
        elif obj.kind == "drawing":
            self.delete_drawing(obj)
        elif obj.kind in ("line", "block"):
            self.delete_text(obj)

    def erase_area(self, pno: int, display_rect, mode="all_white"):
        page = self.doc[pno]
        self.checkpoint(tr("مسح منطقة"))
        r = self.to_pdf(pno, display_rect)
        if mode == "whiteout":
            page.draw_rect(r, color=None, fill=(1, 1, 1), overlay=True)
        else:
            text, images, graphics, fill = ERASE_MODES.get(mode, ERASE_MODES["all_white"])
            page.add_redact_annot(r, fill=fill, cross_out=False)
            page.apply_redactions(images=images, graphics=graphics, text=text)
            if text == TXT_REMOVE:
                self._ocr_drop(pno, r)
        self.invalidate(pno)

    # ------------------------------------------------------------------ objects inside scans
    @staticmethod
    def _box_any(mask, r: int, ry: int | None = None):
        """Binary dilation with a (2r+1) x (2ry+1) box, numpy only."""
        ry = r if ry is None else ry
        if r <= 0 and ry <= 0:
            return mask
        m = np.pad(mask.astype(np.int32), ((ry + 1, ry + 1), (r + 1, r + 1)))
        c = m.cumsum(0).cumsum(1)
        kx, ky = 2 * r + 1, 2 * ry + 1
        s = c[ky:, kx:] - c[:-ky, kx:] - c[ky:, :-kx] + c[:-ky, :-kx]
        return s[:mask.shape[0], :mask.shape[1]] > 0

    @staticmethod
    def _runs_h(dark, L: int):
        """Pixels that belong to horizontal dark runs at least ~L long (table / form lines)."""
        H, W = dark.shape
        if W <= L:
            return np.zeros_like(dark)
        c = np.pad(np.cumsum(dark, axis=1, dtype=np.int32), ((0, 0), (1, 0)))
        seed = (c[:, L:] - c[:, :-L]) >= int(0.8 * L)          # window [x, x+L) mostly dark
        n = seed.shape[1]
        cs = np.pad(np.cumsum(seed, axis=1, dtype=np.int32), ((0, 0), (1, 0)))
        x = np.arange(W)
        cov = (cs[:, np.minimum(x + 1, n)] - cs[:, np.maximum(x - L + 1, 0)]) > 0
        return cov & dark

    def _line_mask(self, rgb, px_per_pt: float):
        """Long horizontal / vertical lines (tables, frames, underlines) in a rendered or scanned image."""
        lum = rgb[..., :3].mean(axis=2)
        dark = lum < 170
        # horizontal rules must be long (Arabic words with stretched baselines are not lines); vertical ones shorter
        Lh, Lv = max(20, int(75 * px_per_pt)), max(10, int(24 * px_per_pt))
        lines = self._runs_h(dark, Lh) | self._runs_h(dark.T, Lv).T
        return self._box_any(lines, max(1, int(round(px_per_pt * 0.6))))

    @staticmethod
    def _components(mask):
        """Connected components (8-connectivity) via run-length union-find. Returns [(x0,y0,x1,y1,count)]."""
        parent = []

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        runs = []
        prev = []
        m8 = mask.view(np.int8)
        for y in range(mask.shape[0]):
            row = m8[y]
            if not row.any():
                prev = []
                continue
            d = np.diff(np.concatenate(([0], row, [0])))
            starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
            cur, j = [], 0
            for s, e in zip(starts.tolist(), ends.tolist()):
                idx = len(runs)
                runs.append((y, s, e))
                parent.append(idx)
                cur.append(idx)
                while j < len(prev) and runs[prev[j]][2] < s:  # prev run ends before (8-conn: touching corner counts)
                    j += 1
                k = j
                while k < len(prev) and runs[prev[k]][1] <= e:
                    a, b = find(idx), find(prev[k])
                    if a != b:
                        parent[a] = b
                    k += 1
            prev = cur
        boxes = {}
        for i, (y, s, e) in enumerate(runs):
            r = find(i)
            b = boxes.get(r)
            if b is None:
                boxes[r] = [s, y, e, y + 1, e - s]
            else:
                b[0] = min(b[0], s); b[1] = min(b[1], y); b[2] = max(b[2], e); b[3] = max(b[3], y + 1); b[4] += e - s
        return [tuple(b) for b in boxes.values()]

    def _analyze_scan(self, pno: int, dpi=100):
        """Cached analysis of a scanned page: elements (logos, stamps, signatures…) and table lines."""
        if pno in self._scan_cache:
            return self._scan_cache[pno]
        page = self.doc[pno]
        pix = page.get_pixmap(dpi=dpi, alpha=False, annots=False)
        rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].astype(np.int16)
        ppt = dpi / 72.0
        sc = 1.0 / ppt
        lum = rgb.mean(axis=2)
        chroma = rgb.max(axis=2) - rgb.min(axis=2)
        lines = self._line_mask(rgb, ppt)
        colored = (chroma > 28) & (lum < 238)
        ink = ((lum < 190) | colored) & ~lines
        grown = self._box_any(ink, max(1, int(round(2 * ppt))), 0)   # join letters/strokes sideways only
        comps = self._components(grown)
        pw, ph = page.rect.width, page.rect.height

        def is_graphic(b):
            x0, y0, x1, y1 = b[:4]
            h = (y1 - y0) * sc
            if h < 14:  # ordinary text line
                return False
            prof = grown[y0:y1, x0:x1].sum(axis=1)
            empty = (prof < 0.02 * (x1 - x0)).mean()
            return empty < 0.12 or (x1 - x0) < 1.3 * (y1 - y0)  # paragraphs have blank rows between lines

        def near(a, b, g):
            return a[0] <= b[2] + g and b[0] <= a[2] + g and a[1] <= b[3] + g and b[1] <= a[3] + g

        def overlap(a, b):
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            return max(0, w) * max(0, h)

        def merge(boxes, g):
            changed = True
            while changed:
                changed = False
                out = []
                for bx in boxes:
                    for o in out:
                        if near(bx, o, g):
                            o[0], o[1], o[2], o[3] = min(o[0], bx[0]), min(o[1], bx[1]), max(o[2], bx[2]), max(o[3], bx[3])
                            changed = True
                            break
                    else:
                        out.append(bx)
                boxes = out
            return boxes

        def ok_size(bx, min_h=14):
            w, h = (bx[2] - bx[0]) * sc, (bx[3] - bx[1]) * sc
            return h >= min_h and w >= 12 and w <= pw * 0.65 and h <= ph * 0.45 and 0.15 <= w / h <= 6

        # 1) coloured ink (stamps, signatures, coloured logos): boxed by colour alone so overlapped text stays out
        cmask = colored & ~lines
        cboxes = [list(b[:4]) for b in self._components(self._box_any(cmask, max(2, int(dpi * 0.09))))]
        def texty(bx, m):
            """coloured paragraphs / titles: wide boxes whose rows alternate ink and blank (text lines)"""
            x0, y0, x1, y1 = bx
            prof = m[y0:y1, x0:x1].sum(axis=1)
            empty = (prof < 0.015 * (x1 - x0)).mean()
            return (x1 - x0) > 1.6 * (y1 - y0) and empty >= 0.12

        cboxes = [bx for bx in merge(cboxes, int(2 * ppt)) if ok_size(bx, 18)
                  and cmask[bx[1]:bx[3], bx[0]:bx[2]].sum() >= 0.025 * (bx[2] - bx[0]) * (bx[3] - bx[1])
                  and not texty(bx, cmask)]
        # 2) dark graphics (black / grey logos, drawings): compact shapes that are not text lines
        seeds = [list(b[:4]) for b in comps if is_graphic(b)]
        seeds = [s for s in seeds if not any(overlap(s, cb) > 0.2 * (s[2] - s[0]) * (s[3] - s[1]) for cb in cboxes)]
        seeds = merge(seeds, int(3 * ppt))
        # a logo's caption (e.g. "Dubai Municipality" under the mark) belongs to it
        small = [b[:4] for b in comps if not is_graphic(b)]
        g = int(4 * ppt)
        for s in seeds:
            sx0, sy0, sx1, sy1 = s
            for t in small:
                cx, cy = (t[0] + t[2]) / 2, (t[1] + t[3]) / 2
                if near(s, t, g) and (t[3] - t[1]) <= (sy1 - sy0) and (sx0 <= cx <= sx1 or sy0 <= cy <= sy1):
                    s[0], s[1], s[2], s[3] = min(s[0], t[0]), min(s[1], t[1]), max(s[2], t[2]), max(s[3], t[3])
        objects = []
        for x0, y0, x1, y1 in cboxes + [s for s in seeds if ok_size(s)]:
            sub = ink[y0:y1, x0:x1]
            if sub.sum() < 0.04 * sub.size:
                continue
            col = rgb[y0:y1, x0:x1][sub].mean(axis=0) / 255.0
            objects.append((pymupdf.Rect(x0 * sc, y0 * sc, x1 * sc, y1 * sc) + (-2, -2, 2, 2),
                            tuple(float(v) for v in col)))        # vertical table lines, used to split recognised text into cells
        vl = self._runs_h(lum.T < 170, max(12, int(30 * ppt))).T
        vlines = [pymupdf.Rect(b[0] * sc, b[1] * sc, b[2] * sc, b[3] * sc)
                  for b in self._components(vl) if (b[3] - b[1]) * sc >= 14]
        res = {"objects": objects, "vlines": [self.to_pdf(pno, r) for r in vlines]}
        self._scan_cache[pno] = res
        return res

    def detect_scan_objects(self, pno: int, dpi=100):
        """Any element printed inside a scan (logo, stamp, signature, drawing…), whatever its colour or shape.
        Table lines and normal text lines are ignored. Returns [(display Rect, (r,g,b))]."""
        objs = self._analyze_scan(pno, dpi)["objects"]
        objs = sorted(objs, key=lambda t: -abs(t[0]))
        res = []
        page_rect = self.doc[pno].rect
        for r, c in objs:
            if not any(abs(r & q) > 0.6 * abs(r) for q, _ in res):
                res.append((r & page_rect, c))
        return res

    @staticmethod
    def _ink_alpha(rgb, mode: str, threshold: float):
        """0..1 'is ink' map. color: coloured ink only (stamps); all: anything darker than the paper (logos)."""
        lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
        if mode == "color":
            chroma = rgb.max(axis=2) - rgb.min(axis=2)
            a = np.clip((chroma - threshold * 0.55) / max(threshold * 0.9, 1.0), 0, 1)
            return a * (lum < 247)
        paper = float(np.percentile(lum, 92))
        return np.clip((paper - 14 - lum) / 95.0, 0, 1)

    def suggest_threshold(self, pno: int, display_rect) -> int:
        """Colour sensitivity that fits the ink inside the area (pale scanned stamps need a lower one)."""
        try:
            pix = self.doc[pno].get_pixmap(clip=pymupdf.Rect(display_rect) & self.doc[pno].rect, dpi=72, alpha=False)
            a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].astype(np.int16)
            ch = a.max(axis=2) - a.min(axis=2)
            inky = ch[a.mean(axis=2) < 225]
            if not len(inky):
                return 45
            return int(max(16, min(45, np.percentile(inky, 90) * 0.55)))
        except Exception:
            return 45

    def scan_object_image(self, pno: int, display_rect, mode="color", threshold=45, dpi=300, keep_lines=False):
        """Cut the ink inside an area of the page into a transparent RGBA image.
        Returns (w, h, rgba_bytes, tight display Rect) or None."""
        page = self.doc[pno]
        clip = pymupdf.Rect(display_rect) & page.rect
        if clip.is_empty:
            return None
        pix = page.get_pixmap(clip=clip, dpi=dpi, alpha=False, annots=False)
        rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].astype(np.float32)
        a = self._ink_alpha(rgb, mode, threshold)
        if not keep_lines:  # table / frame lines stay in the scan
            a[self._line_mask(rgb, dpi / 72.0)] = 0
        ys, xs = np.nonzero(a > 0.12)
        if len(xs) == 0:
            return None
        pad = 4
        x0, x1 = max(0, xs.min() - pad), min(rgb.shape[1], xs.max() + pad + 1)
        y0, y1 = max(0, ys.min() - pad), min(rgb.shape[0], ys.max() + pad + 1)
        sub, al = rgb[y0:y1, x0:x1], a[y0:y1, x0:x1]
        # un-blend the paper so semi-transparent edges keep the true ink colour
        ink = sub[al > 0.6].mean(axis=0) if (al > 0.6).any() else sub.mean(axis=(0, 1))
        col = np.where(al[..., None] > 0.6, sub, ink[None, None, :])
        rgba = np.dstack([np.clip(col, 0, 255), al * 255]).astype(np.uint8)
        f = clip.width / pix.width
        tight = pymupdf.Rect(clip.x0 + x0 * f, clip.y0 + y0 * f, clip.x0 + x1 * f, clip.y0 + y1 * f)
        return int(x1 - x0), int(y1 - y0), np.ascontiguousarray(rgba).tobytes(), tight

    def extract_from_scan(self, pno: int, display_rect, mode="color", threshold=45, kind="stamp", name=None,
                          checkpoint=True, keep_lines=False):
        """Separate a stamp / logo printed inside a scan into its own movable layer."""
        res = self.scan_object_image(pno, display_rect, mode, threshold, keep_lines=keep_lines)
        if not res:
            return False
        w, h, data, tight = res
        png = pymupdf.Pixmap(pymupdf.csRGB, w, h, data, 1).tobytes("png")
        if checkpoint:
            self.checkpoint(tr("فصل عنصر من السكان"))
        self.remove_color_ink(pno, display_rect, threshold, checkpoint=False, mode=mode, keep_lines=keep_lines)
        self._ocr_drop(pno, self.to_pdf(pno, tight))
        tmp = pymupdf.open()
        tp = tmp.new_page(width=tight.width, height=tight.height)
        tp.insert_image(tp.rect, stream=png, keep_proportion=False)
        meta = {"kind": kind}
        if name:
            meta["name"] = name
        self._place_layer(pno, tight, tmp, meta)
        self.invalidate(pno)
        return True

    def auto_extract(self, pno: int, display_rect, keep_lines=False) -> bool:
        """One-click separation: picks coloured-ink or full mode by itself. Only works on scanned images."""
        dr = pymupdf.Rect(display_rect) & self.doc[pno].rect
        pr = self.to_pdf(pno, dr)
        under = [o for o in self.get_objects(pno)["images"] if abs(o.rect & pr) >= 0.6 * max(abs(pr), 1e-6)]
        if not under:
            return False
        thr = self.suggest_threshold(pno, dr)
        # coloured-only (stamp / signature over text) when most of the ink is coloured, otherwise take it all (logo)
        pix = self.doc[pno].get_pixmap(clip=dr, dpi=72, alpha=False, annots=False)
        rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].astype(np.float32)
        lines = self._line_mask(rgb, 1.0) if not keep_lines else np.zeros(rgb.shape[:2], bool)
        col_a = self._ink_alpha(rgb, "color", thr)
        all_a = self._ink_alpha(rgb, "all", thr)
        colored = ((col_a > 0.5) & ~lines).sum()
        total = ((all_a > 0.3) & ~lines).sum()
        mode = "color" if colored > 40 and colored >= 0.55 * max(total, 1) else "all"
        return self.extract_from_scan(pno, dr, mode, thr, "element", keep_lines=keep_lines)

    # ------------------------------------------------------------------ lift any region into a layer
    def _classify_ink(self, rgb, ppt: float):
        """Split the ink of a scanned region into (alpha, text, elements, lines) masks."""
        alpha = self._ink_alpha(rgb, "all", 45)
        ink = alpha > 0.08
        lines = self._line_mask(rgb, ppt) & ink
        lum = rgb.mean(axis=2)
        chroma = rgb.max(axis=2) - rgb.min(axis=2)
        colored = (chroma > 28) & (lum < 238)
        core = ink & ~lines
        H, W = core.shape
        k = max(1, int(math.ceil(math.sqrt(H * W / 2.0e6))))  # work on a smaller copy for big areas
        small = core[::k, ::k]
        sp = ppt / k
        grown = self._box_any(small, max(1, int(round(2 * sp))), 0)
        textbox = np.zeros(small.shape, bool)
        for x0, y0, x1, y1, _ in self._components(grown):
            if (y1 - y0) / sp < 16:  # height of a line of text
                textbox[y0:y1, x0:x1] = True
        if k > 1:
            textbox = textbox.repeat(k, 0).repeat(k, 1)[:H, :W]
        text = core & textbox & ~colored
        elem = core & ~text
        return alpha, text, elem, lines

    @staticmethod
    def _pick(masks, include):
        _, text, elem, lines = masks
        m = np.zeros(text.shape, bool)
        if "text" in include:
            m |= text
        if "elements" in include:
            m |= elem
        if "lines" in include:
            m |= lines
        return m

    def _scan_under(self, pno, pdf_rect):
        return [o for o in self.get_objects(pno)["images"]
                if abs(o.rect & pdf_rect) >= 0.6 * max(abs(pdf_rect), 1e-6)]

    def lift_region(self, pno: int, display_rect, include=("elements",), checkpoint=True):
        """Turn whatever is inside the area (elements / text / table lines — as chosen) into an
        independent layer that can be moved, resized and stretched. Works on scans and normal PDFs."""
        include = set(include) or {"elements"}
        page = self.doc[pno]
        dr = pymupdf.Rect(display_rect) & page.rect
        if dr.is_empty or dr.width < 3 or dr.height < 3:
            return False
        pr = self.to_pdf(pno, dr)
        kind = "element" if include == {"elements"} else ("text" if include == {"text"} else "region")
        if self._scan_under(pno, pr) and np is not None:
            pix = page.get_pixmap(clip=dr, dpi=300, alpha=False, annots=False)
            rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].astype(np.float32)
            masks = self._classify_ink(rgb, 300 / 72.0)
            sel = self._pick(masks, include)
            a = np.where(sel, masks[0], 0)
            ys, xs = np.nonzero(a > 0.1)
            if len(xs) == 0:
                return False
            pad = 4
            x0, x1 = max(0, xs.min() - pad), min(rgb.shape[1], xs.max() + pad + 1)
            y0, y1 = max(0, ys.min() - pad), min(rgb.shape[0], ys.max() + pad + 1)
            sub, al = rgb[y0:y1, x0:x1], a[y0:y1, x0:x1]
            ink = sub[al > 0.6].mean(axis=0) if (al > 0.6).any() else sub.mean(axis=(0, 1))
            col = np.where(al[..., None] > 0.6, sub, ink[None, None, :])
            rgba = np.ascontiguousarray(np.dstack([np.clip(col, 0, 255), al * 255]).astype(np.uint8))
            f = dr.width / pix.width
            tight = pymupdf.Rect(dr.x0 + x0 * f, dr.y0 + y0 * f, dr.x0 + x1 * f, dr.y0 + y1 * f)
            png = pymupdf.Pixmap(pymupdf.csRGB, int(x1 - x0), int(y1 - y0), rgba.tobytes(), 1).tobytes("png")
            if checkpoint:
                self.checkpoint(tr("تحويل منطقة إلى طبقة"))

            def builder(reg, ppt):
                m = self._pick(self._classify_ink(reg, ppt), include)
                return self._box_any(m, 1) if m.any() else m

            self.remove_color_ink(pno, dr, checkpoint=False, mask_fn=builder)
            if "text" in include:
                self._remove_text(page, [pr])
                self._ocr_drop(pno, pr)
            tmp = pymupdf.open()
            tp = tmp.new_page(width=tight.width, height=tight.height)
            tp.insert_image(tp.rect, stream=png, keep_proportion=False)
            self._place_layer(pno, tight, tmp, {"kind": kind})
            self.invalidate(pno)
            return True
        # ---- normal (vector) PDF: copy the area as vector content, then remove it from the page
        if checkpoint:
            self.checkpoint(tr("تحويل منطقة إلى طبقة"))
        src = pymupdf.open()
        src.insert_pdf(self.doc, from_page=pno, to_page=pno)
        sp = src[0]
        sp.set_rotation(0)
        for a in list(sp.annots() or []):
            sp.delete_annot(a)
        keep_text, keep_img = "text" in include, "elements" in include
        keep_art = "elements" in include or "lines" in include
        sp.add_redact_annot(pr, fill=False, cross_out=False)
        sp.apply_redactions(images=IMG_NONE if keep_img else IMG_REMOVE,
                            graphics=ART_NONE if keep_art else ART_TOUCHED,
                            text=TXT_NONE if keep_text else TXT_REMOVE)
        # remove the original content from the page first (only what was taken) ...
        page.add_redact_annot(pr, fill=False, cross_out=False)
        page.apply_redactions(images=IMG_PIXELS if keep_img else IMG_NONE,
                              graphics=ART_COVERED if keep_art else ART_NONE,
                              text=TXT_REMOVE if keep_text else TXT_NONE)
        # ... then put the copied content back as its own layer
        page = self.doc[pno]
        before = {x[0] for x in page.get_xobjects()}
        meta = {"kind": kind, "name": self._layer_name(kind)}
        ocg = self.doc.add_ocg(meta["name"], on=True)
        meta["ocg"] = ocg
        page.show_pdf_page(pr, src, 0, clip=pr, keep_proportion=False, oc=ocg)
        new = [x for x in page.get_xobjects() if x[0] not in before and x[2] == 0]
        if new:
            self.doc.xref_set_key(new[0][0], LAYER_KEY, pymupdf.get_pdf_str(json.dumps(meta, ensure_ascii=False)))
        self.invalidate(pno)
        return bool(new)

    def area_text(self, pno: int, display_rect):
        """Text inside an area + the style of its first line (for 'edit text by area')."""
        text, _ = self.words_in(pno, display_rect)
        pr = self.to_pdf(pno, display_rect)
        lines = [o for o in self.get_objects(pno)["lines"] if abs(o.rect & pr) >= 0.4 * max(abs(o.rect), 1e-6)]
        lines.sort(key=lambda o: (o.rect.y0, o.rect.x0))
        style = {"family": "Arial", "size": 12.0, "color": (0, 0, 0)}
        if lines:
            d = lines[0].data
            fam, b, i = guess_family(d.get("font", ""), d.get("flags", 0))
            style = {"family": fam, "size": float(d.get("size", 12)), "color": tuple(d.get("color", (0, 0, 0))),
                     "bold": b, "italic": i}
            if d.get("ocr"):
                _, fg = self.sample_colors(pno, lines[0].rect)
                style.update(family="Arial", color=fg)
        return text, style, lines

    def ocr_snippet(self, pno: int, display_rect) -> str:
        """Quickly read a small spot of a scanned page (used when the page-wide OCR missed it)."""
        if not TESSDATA:
            return ""
        try:
            r = pymupdf.Rect(display_rect) + (-3, -3, 3, 3)
            pix = self.doc[pno].get_pixmap(clip=r & self.doc[pno].rect, dpi=400, alpha=False)
            langs = ocr_languages()
            lang = "+".join(l for l in ("eng", "ara") if l in langs) or langs[0]
            o = pymupdf.open("pdf", pix.pdfocr_tobytes(language=lang, tessdata=TESSDATA))
            words = [normalize_extracted(w[4]) for w in o[0].get_text("words", sort=True)]
            o.close()
            if any(has_rtl(w) for w in words):
                words = list(reversed(words))
            return " ".join(words).strip()
        except Exception:
            return ""

    def edit_text_area(self, pno: int, display_rect, new_text: str, style: dict, align="right"):
        """Replace all text inside an area with new text, placed as a movable / resizable text layer."""
        page = self.doc[pno]
        self.checkpoint(tr("تعديل نص المنطقة"))
        dr = pymupdf.Rect(display_rect)
        pr = self.to_pdf(pno, dr)
        _, _, lines = self.area_text(pno, dr)
        self._remove_text(page, [ln.rect for ln in lines] or [pr])
        if self._scan_under(pno, pr) and np is not None:
            def builder(reg, ppt):
                m = self._pick(self._classify_ink(reg, ppt), {"text"})
                return self._box_any(m, 1) if m.any() else m
            self.remove_color_ink(pno, dr, checkpoint=False, mask_fn=builder)
            self._ocr_drop(pno, pr)
        if new_text.strip():
            if "\n" not in new_text:  # one line: keep it inside the old width
                wn = self.text_width(new_text, style)
                if wn > dr.width * 1.04 and dr.width > 8:
                    style = dict(style, size=float(style.get("size", 12)) * dr.width * 1.0 / wn)
            size = float(style.get("size", 12))
            w = max(dr.width, self.text_width(new_text, style) * (1.3 if has_rtl(new_text) else 1.08) + 12)
            h = max(dr.height, (new_text.count("\n") + 1) * size * 1.45 + size)
            right = align == "right" or (has_rtl(new_text) and align != "center" and align != "left")
            box = pymupdf.Rect(dr.x1 - w, dr.y0, dr.x1, dr.y0 + h) if right else pymupdf.Rect(dr.x0, dr.y0, dr.x0 + w, dr.y0 + h)
            self._text_layer(pno, box, new_text, style, "right" if right else align, {"kind": "text"})
        self.invalidate(pno)

    def move_object(self, obj: PageObject, new_pdf_rect):
        """Move / resize / stretch anything selected. Things that are not layers yet become layers first."""
        if obj.kind == "layer":
            return self.move_layer(obj, new_pdf_rect)
        if obj.kind == "image" and not obj.data.get("full_page"):
            return self.move_image(obj, new_pdf_rect)
        self.checkpoint(tr("نقل/تحجيم"))
        before = {o.data["xref"] for o in self.list_layers(obj.pno)}
        inc = ("elements",) if obj.kind in ("drawing", "scan", "image") else ("text",)
        if not self.lift_region(obj.pno, self.to_display(obj.pno, obj.rect) + (-1, -1, 1, 1), inc, checkpoint=False):
            self.drop_last_checkpoint()
            return False
        new = [o for o in self.list_layers(obj.pno) if o.data["xref"] not in before]
        if new:
            old, nr, lr = pymupdf.Rect(obj.rect), pymupdf.Rect(new_pdf_rect), new[-1].rect
            sx, sy = nr.width / max(old.width, 1e-6), nr.height / max(old.height, 1e-6)
            tr_ = lambda x, y: (nr.x0 + (x - old.x0) * sx, nr.y0 + (y - old.y0) * sy)
            self._move_layer_raw(new[-1], pymupdf.Rect(*tr_(lr.x0, lr.y0), *tr_(lr.x1, lr.y1)))
        return True

    def remove_color_ink(self, pno: int, display_rect, threshold=45, checkpoint=True, mode="color",
                         keep_lines=False, mask_fn=None) -> int:
        """Remove ink from scanned images inside the area, replacing it with the paper colour.
        mode='color': only coloured ink (stamps) — black/grey text stays.  mode='all': everything (logos)."""
        if np is None:
            raise RuntimeError(tr("numpy غير متوفر"))
        page = self.doc[pno]
        area = self.to_pdf(pno, display_rect)
        cands = [o for o in self.get_objects(pno)["images"] if o.data.get("xref") and (o.rect & area).is_valid
                 and not (o.rect & area).is_empty]
        if not cands:
            return 0
        if checkpoint:
            self.checkpoint(tr("إزالة حبر ملون"))
        changed_total = 0
        done = set()
        for obj in sorted(cands, key=lambda o: -abs(o.rect)):
            xref = obj.data["xref"]
            if xref in done:
                continue
            done.add(xref)
            try:
                base = pymupdf.Pixmap(self.doc, xref)
            except Exception:
                continue
            if base.colorspace is None or base.colorspace.n == 1:
                continue
            if base.colorspace.n != 3:
                base = pymupdf.Pixmap(pymupdf.csRGB, base)
            if base.alpha:
                base = pymupdf.Pixmap(base, 0)
            w, h = base.width, base.height
            arr = np.frombuffer(base.samples, dtype=np.uint8).reshape(h, w, base.n).copy()
            # page rect -> image pixel rect
            M = pymupdf.Matrix(obj.data["transform"])
            inv = ~M
            pts = [pymupdf.Point(p) * inv for p in (area.tl, area.tr, area.bl, area.br)]
            us = [p.x for p in pts]
            vs = [p.y for p in pts]
            x0, x1 = int(max(0, min(us)) * w), int(math.ceil(min(1, max(us)) * w))
            # MuPDF unit image space has v pointing up relative to image rows -> try both
            ya0, ya1 = int(max(0, min(vs)) * h), int(math.ceil(min(1, max(vs)) * h))
            yb0, yb1 = int(max(0, 1 - max(vs)) * h), int(math.ceil(min(1, 1 - min(vs)) * h))
            y0, y1 = (yb0, yb1) if self._image_rows_flipped(M) else (ya0, ya1)
            if x1 <= x0 or y1 <= y0:
                continue
            reg = arr[y0:y1, x0:x1, :3].astype(np.float32)
            if mask_fn is not None:  # caller decides exactly which pixels go (text / elements / lines)
                mask = mask_fn(reg, w / max(obj.rect.width, 1e-6))
                a = mask.astype(np.float32)
                mode = "custom"
                keep_lines = True
            else:
                a = self._ink_alpha(reg, mode, threshold)
                mask = a > (0.25 if mode == "color" else 0.08)
            protect = None
            if not keep_lines:
                protect = self._line_mask(reg, w / max(obj.rect.width, 1e-6))
                mask &= ~protect
            if mode == "color":  # take the faint halo around the stamp lines too
                mask = mask | (self._box_any(mask, 1) & (a > 0.05))
            n = int(mask.sum())
            if not n:
                continue
            lum = reg.mean(axis=2)
            paper_px = reg[(~mask) & (lum >= np.percentile(lum, 60))]
            paper = np.median(paper_px, axis=0) if len(paper_px) else np.array([255, 255, 255], np.float32)
            if mode == "color":  # light-grey anti-aliasing left around the stamp strokes (dark text is kept)
                halo = self._box_any(mask, 3) & (lum > 95) & (lum < float(paper.mean()) - 4)
                mask = mask | halo
                if protect is not None:
                    mask &= ~protect
                n = int(mask.sum())
            sub = arr[y0:y1, x0:x1, :3]
            sub[mask] = paper.astype(np.uint8)
            arr[y0:y1, x0:x1, :3] = sub
            newpix = pymupdf.Pixmap(pymupdf.csRGB, w, h, arr.tobytes(), 0)
            self._write_image(xref, newpix, "DCT" in self.doc.xref_get_key(xref, "Filter")[1])
            changed_total += n
        if not changed_total and checkpoint:
            self.drop_last_checkpoint()
        self.invalidate(pno)
        return changed_total

    def _write_image(self, xref: int, pix: "pymupdf.Pixmap", as_jpeg: bool):
        """Overwrite an image object in place (keeps the file small: no orphaned copies)."""
        if as_jpeg:
            self.doc.update_stream(xref, pix.tobytes("jpeg", jpg_quality=92), compress=False)
            self.doc.xref_set_key(xref, "Filter", "/DCTDecode")
        else:
            self.doc.update_stream(xref, pix.samples, compress=True)
            self.doc.xref_set_key(xref, "Filter", "/FlateDecode")
        for k, v in (("Width", str(pix.width)), ("Height", str(pix.height)), ("ColorSpace", "/DeviceRGB"),
                     ("BitsPerComponent", "8"), ("DecodeParms", "null"), ("Decode", "null")):
            self.doc.xref_set_key(xref, k, v)

    @staticmethod
    def _image_rows_flipped(M: pymupdf.Matrix) -> bool:
        # MuPDF reports a transform that maps the unit square to the bbox in top-down page space;
        # image row 0 sits at unit y=0 when d>0 (no flip) for normal upright images.
        return M.d < 0 if abs(M.b) < 1e-6 else M.b < 0

    # ------------------------------------------------------------------ annotations creation
    def _annot_common(self, a, color, width=None, opacity=1.0, fill=None):
        try:
            if fill is not None:
                a.set_colors(stroke=color, fill=fill)
            else:
                a.set_colors(stroke=color)
            if width is not None:
                a.set_border(width=width)
            a.set_opacity(opacity)
        except Exception:
            pass
        a.update()

    def add_markup(self, pno, display_rect, kind, color=(1, 0.9, 0), opacity=1.0):
        page = self.doc[pno]
        r = self.to_pdf(pno, display_rect)
        words = [pymupdf.Rect(w[:4]) for w in page.get_text("words") if pymupdf.Rect(w[:4]).intersects(r)]
        self.checkpoint(tr("تظليل"))
        quads = words or [r]
        fn = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
              "strike": page.add_strikeout_annot}[kind]
        a = fn(quads)
        if a:
            a.set_colors(stroke=color)
            a.set_opacity(opacity)
            a.update()
        self.invalidate(pno)

    def _shape_layer(self, pno, kind, pts, color, width, opacity, fill=None):
        """Draw a vector shape on its own layer. pts are display-space points."""
        head = max(8.0, width * 4) if kind == "arrow" else 0
        m = width / 2 + 1.5 + head
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        box = pymupdf.Rect(min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
        tmp = pymupdf.open()
        tp = tmp.new_page(width=box.width, height=box.height)
        loc = [pymupdf.Point(x - box.x0, y - box.y0) for x, y in pts]
        sh = tp.new_shape()
        if kind == "rect":
            sh.draw_rect(pymupdf.Rect(loc[0], loc[1]).normalize())
        elif kind == "ellipse":
            sh.draw_oval(pymupdf.Rect(loc[0], loc[1]).normalize())
        elif kind in ("line", "arrow"):
            a, b = loc[0], loc[1]
            if kind == "arrow":
                d = b - a
                ln = max(1e-6, math.hypot(d.x, d.y))
                u = pymupdf.Point(d.x / ln, d.y / ln)
                n = pymupdf.Point(-u.y, u.x)
                base = b - u * head
                sh.draw_line(a, base)
                sh.finish(color=color, width=width, stroke_opacity=opacity, lineCap=1)
                sh.draw_polyline([b, base + n * (head * 0.5), base - n * (head * 0.5), b])
                sh.finish(color=color, fill=color, width=width * 0.5, closePath=True,
                          stroke_opacity=opacity, fill_opacity=opacity)
                sh.commit()
                self._place_layer(pno, box, tmp, {"kind": kind})
                return
            sh.draw_line(a, b)
        else:  # ink
            sh.draw_polyline(loc)
        sh.finish(color=color, fill=fill if kind in ("rect", "ellipse") else None, width=width, closePath=False,
                  lineCap=1, lineJoin=1, stroke_opacity=opacity, fill_opacity=opacity)
        sh.commit()
        self._place_layer(pno, box, tmp, {"kind": kind})

    def add_shape(self, pno, kind, display_a, display_b=None, color=(1, 0, 0), width=1.5, opacity=1.0, fill=None):
        self.checkpoint(tr("إضافة شكل"))
        if kind in ("rect", "ellipse"):
            r = pymupdf.Rect(display_a)
            pts = [(r.x0, r.y0), (r.x1, r.y1)]
        else:
            pts = [tuple(display_a), tuple(display_b)]
        self._shape_layer(pno, kind, pts, color, width, opacity, fill)
        self.invalidate(pno)

    def add_ink(self, pno, display_points, color=(0, 0, 1), width=2.0, opacity=1.0):
        self.checkpoint(tr("رسم حر"))
        self._shape_layer(pno, "ink", [tuple(p) for p in display_points], color, width, opacity)
        self.invalidate(pno)

    def add_note(self, pno, display_pt, text, color=(1, 0.8, 0)):
        page = self.doc[pno]
        self.checkpoint(tr("إضافة ملاحظة"))
        a = page.add_text_annot(self.point_to_pdf(pno, display_pt), text, icon="Comment")
        a.set_colors(stroke=color)
        a.update()
        self.invalidate(pno)

    def flatten_annotations(self):
        self.checkpoint(tr("دمج التعليقات"))
        try:
            self.doc.bake(annots=True, widgets=True)
        except Exception:
            # fallback: render nothing, just keep
            pass
        self.invalidate()

    # ------------------------------------------------------------------ pages
    def rotate_pages(self, pnos, delta):
        self.checkpoint(tr("تدوير"))
        for p in pnos:
            page = self.doc[p]
            page.set_rotation((page.rotation + delta) % 360)
        self.invalidate()

    def delete_pages(self, pnos):
        if len(pnos) >= self.page_count:
            raise ValueError(tr("لا يمكن حذف كل الصفحات"))
        self.checkpoint(tr("حذف صفحات"))
        self.doc.delete_pages(sorted(set(pnos)))
        self.invalidate()

    def insert_blank(self, after: int):
        self.checkpoint(tr("صفحة فارغة"))
        ref = self.doc[max(0, min(after, self.page_count - 1))].rect if self.page_count else pymupdf.paper_rect("a4")
        self.doc.new_page(after + 1, width=ref.width, height=ref.height)
        self.invalidate()

    def duplicate_page(self, pno: int):
        self.checkpoint(tr("تكرار صفحة"))
        self.doc.fullcopy_page(pno, pno + 1)
        self.invalidate()

    def move_page(self, src: int, dst: int):
        """dst = final index of the page."""
        if src == dst:
            return
        self.checkpoint(tr("نقل صفحة"))
        to = dst + 1 if dst > src else dst
        if to >= self.page_count:
            self.doc.move_page(src, -1)
        else:
            self.doc.move_page(src, to)
        self.invalidate()

    def insert_file(self, path: str, at: int, password=None):
        other = self._open_any(path)
        if other.needs_pass and not (password and other.authenticate(password)):
            raise PasswordRequired(path)
        self.checkpoint(tr("دمج ملف"))
        self.doc.insert_pdf(other, start_at=at)
        other.close()
        self.invalidate()

    def extract_pages(self, pnos, path):
        out = pymupdf.open()
        for p in pnos:
            out.insert_pdf(self.doc, from_page=p, to_page=p)
        out.save(path, garbage=3, deflate=True)
        out.close()

    def split_every(self, folder, base, n=1):
        files = []
        for start in range(0, self.page_count, n):
            end = min(self.page_count, start + n) - 1
            out = pymupdf.open()
            out.insert_pdf(self.doc, from_page=start, to_page=end)
            name = os.path.join(folder, f"{base}_{start + 1}-{end + 1}.pdf" if n > 1 else f"{base}_{start + 1}.pdf")
            out.save(name, garbage=3, deflate=True)
            out.close()
            files.append(name)
        return files

    def export_images(self, pnos, folder, base, dpi=150, fmt="png"):
        files = []
        for p in pnos:
            pix = self.doc[p].get_pixmap(dpi=dpi, alpha=False)
            name = os.path.join(folder, f"{base}_page{p + 1}.{fmt}")
            if fmt in ("jpg", "jpeg"):
                pix.save(name, jpg_quality=92)
            else:
                pix.save(name)
            files.append(name)
        return files

    @staticmethod
    def images_to_pdf(paths) -> pymupdf.Document:
        out = pymupdf.open()
        for p in paths:
            img = pymupdf.open(p)
            rect = img[0].rect
            pdfbytes = img.convert_to_pdf()
            img.close()
            imgpdf = pymupdf.open("pdf", pdfbytes)
            page = out.new_page(width=rect.width, height=rect.height)
            page.show_pdf_page(page.rect, imgpdf, 0)
            imgpdf.close()
        return out

    # ------------------------------------------------------------------ document tools
    def add_overlay_image(self, png_bytes: bytes, pages, placement="center", scale=0.7, margin=36, label=tr("علامة مائية")):
        """Stamp an image on many pages. placement: center|tile|<corner names>."""
        self.checkpoint(label)
        xref = 0
        probe = pymupdf.Pixmap(png_bytes)
        iw, ih = probe.width, probe.height
        for p in pages:
            page = self.doc[p]
            W, H = page.rect.width, page.rect.height
            rects = []
            if placement == "tile":
                tw = W * scale
                th = tw * ih / iw
                y = margin
                while y < H:
                    x = margin
                    while x < W:
                        rects.append(pymupdf.Rect(x, y, x + tw, y + th))
                        x += tw * 1.25
                    y += th * 1.6
            else:
                tw = W * scale
                th = tw * ih / iw
                if th > H * 0.9:
                    th = H * 0.9
                    tw = th * iw / ih
                cx = {"left": margin + tw / 2, "right": W - margin - tw / 2}.get(placement.split("-")[-1], W / 2)
                cy = {"top": margin + th / 2, "bottom": H - margin - th / 2}.get(placement.split("-")[0], H / 2)
                rects.append(pymupdf.Rect(cx - tw / 2, cy - th / 2, cx + tw / 2, cy + th / 2))
            for dr in rects:
                r = self.to_pdf(p, dr)
                if xref:
                    page.insert_image(r, xref=xref, rotate=page.rotation)
                else:
                    xref = page.insert_image(r, stream=png_bytes, rotate=page.rotation)
            self.invalidate(p)

    def add_page_numbers(self, fmt="{n}", position="bottom-center", size=11, color=(0, 0, 0), start=1,
                         skip_first=False, family="Arial", margin=24):
        self.checkpoint(tr("ترقيم الصفحات"))
        total = self.page_count
        for p in range(total):
            if skip_first and p == 0:
                continue
            page = self.doc[p]
            n = p + start - (1 if skip_first else 0)
            text = fmt.replace("{n}", str(n)).replace("{total}", str(total - (1 if skip_first else 0) + start - 1))
            W, H = page.rect.width, page.rect.height
            v, hpos = position.split("-")
            y0 = margin - size * 0.3 if v == "top" else H - margin - size * 1.2
            dr = pymupdf.Rect(margin, y0, W - margin, y0 + size * 2.2)
            style = {"family": family, "size": size, "color": color}
            self._insert_html(page, self.to_pdf(p, dr), text, style,
                              align={"left": "left", "right": "right"}.get(hpos, "center"), rotate=page.rotation)
            self.invalidate(p)

    def compress(self, path, dpi_target=120, quality=70):
        work = pymupdf.open("pdf", self.doc.tobytes())
        try:
            work.rewrite_images(dpi_threshold=dpi_target + 30, dpi_target=dpi_target, quality=quality,
                                lossy=True, lossless=True, bitonal=True, color=True, gray=True)
        except Exception:
            pass
        try:
            work.subset_fonts()
        except Exception:
            pass
        work.save(path, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True, use_objstms=1)
        work.close()

    def protect(self, path, user_pw="", owner_pw="", allow_print=True, allow_copy=True, allow_edit=False):
        perm = pymupdf.PDF_PERM_ACCESSIBILITY
        if allow_print:
            perm |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
        if allow_copy:
            perm |= pymupdf.PDF_PERM_COPY
        if allow_edit:
            perm |= pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_ANNOTATE | pymupdf.PDF_PERM_FORM | pymupdf.PDF_PERM_ASSEMBLE
        self.doc.save(path, garbage=3, deflate=True, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                      owner_pw=owner_pw or user_pw or "owner", user_pw=user_pw, permissions=perm)

    def save_decrypted(self, path):
        self.doc.save(path, garbage=3, deflate=True, encryption=pymupdf.PDF_ENCRYPT_NONE)

    def set_metadata(self, meta: dict):
        self.checkpoint(tr("بيانات المستند"))
        m = dict(self.doc.metadata or {})
        m.update(meta)
        self.doc.set_metadata(m)
