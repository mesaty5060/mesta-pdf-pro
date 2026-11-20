"""Text recognition that runs in a separate process (so reading stays smooth and safe).

The page image is recognised with Arabic + English first; if the text turns out to be another
language (French, German, Spanish, Italian, Portuguese, Dutch, Turkish, Persian, Urdu) it is
recognised again with that language added. Only small, plain-Python helpers live here.
"""
from __future__ import annotations

import re

STOPWORDS = {
    "fra": {"le", "la", "les", "des", "est", "une", "et", "du", "pour", "dans", "que", "qui", "sur", "pas", "au", "avec"},
    "deu": {"der", "die", "das", "und", "ist", "nicht", "mit", "den", "von", "ein", "eine", "für", "auf", "dem", "zu"},
    "spa": {"el", "los", "las", "del", "que", "y", "en", "por", "con", "una", "para", "es", "se", "al", "como"},
    "ita": {"il", "di", "che", "e", "la", "per", "non", "un", "una", "sono", "della", "con", "del", "gli", "nel"},
    "por": {"o", "os", "as", "de", "que", "e", "do", "da", "em", "um", "uma", "para", "com", "não", "dos", "das"},
    "nld": {"de", "het", "een", "en", "van", "is", "dat", "niet", "op", "te", "zijn", "met", "voor", "aan"},
    "tur": {"ve", "bir", "bu", "için", "ile", "da", "de", "olarak", "olan", "gibi", "daha", "çok", "değil"},
}
ENGLISH = {"the", "and", "of", "to", "in", "is", "for", "that", "with", "on", "are", "be", "this", "by", "all"}


def detect_extra_language(text: str, available) -> str | None:
    words = re.findall(r"[^\W\d_]+", text.lower())
    if any(ch in text for ch in "پچژگ") and "fas" in available:
        return "fas"
    if any(ch in text for ch in "ٹڈڑںےھ") and "urd" in available:
        return "urd"
    if len(words) < 8:
        return None
    eng = sum(w in ENGLISH for w in words)
    scores = {k: sum(w in v for w in words) for k, v in STOPWORDS.items() if k in available}
    if not scores:
        return None
    best = max(scores, key=scores.get)
    if scores[best] >= 5 and scores[best] > 1.5 * eng:
        return best
    return None


def run_auto(image_bytes: bytes, tessdata: str, available: list[str]) -> tuple[bytes, str]:
    import pymupdf

    pix = pymupdf.Pixmap(image_bytes)
    base = "+".join(l for l in ("ara", "eng") if l in available) or available[0]
    data = pix.pdfocr_tobytes(language=base, tessdata=tessdata)
    try:
        doc = pymupdf.open("pdf", data)
        text = doc[0].get_text()
        doc.close()
    except Exception:
        return data, base
    extra = detect_extra_language(text, available)
    if extra:
        has_ar = bool(re.search(r"[؀-ۿ]", text))
        lang = f"{extra}+ara+eng" if extra in ("fas", "urd") else (f"{extra}+eng+ara" if has_ar else f"{extra}+eng")
        lang = "+".join(l for l in lang.split("+") if l in available)
        data = pix.pdfocr_tobytes(language=lang, tessdata=tessdata)
        return data, lang
    return data, base
