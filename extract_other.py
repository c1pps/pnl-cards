"""Lecture des cartes Axiom (trade) et GMGN (mensuelle) + détection du terminal.
Gabarits calés sur un seul exemple chacun : à valider sur davantage de cartes."""
import re, os
import numpy as np
from PIL import Image
import pytesseract
from extract_terminal import ocr, _clean, _finish, read_fixed

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
SUF = {"K": 1e3, "M": 1e6, "B": 1e9}

def zone(im, box):
    w, h = im.size
    return im.crop((int(box[0]*w), int(box[1]*h), int(box[2]*w), int(box[3]*h)))

def full_text(im):
    big = im.resize((im.width*2, im.height*2), Image.LANCZOS)
    return ocr(big, "--psm 11")

def detect_terminal(im):
    """'axiom' | 'gmgn' | 'terminal' | 'unknown' d'après le texte de la carte."""
    small = im.resize((min(im.width, 1400), int(im.height * min(im.width, 1400) / im.width)))
    t = (ocr(small, "--psm 11") + " " + ocr(Image.fromarray(255 - np.array(small.convert("L"))), "--psm 11")).lower()
    if "axiom" in t or "axio" in t: return "axiom"
    if "gmgn" in t: return "gmgn"
    if "padre" in t or "terminal" in t or "cashback" in t: return "terminal"
    return "unknown"

def money(txt):
    """'$48.3K' -> 48300.0"""
    m = re.search(r"([0-9][0-9,]*\.?[0-9]*)\s*([KMBkmb])?", txt or "")
    if not m: return None
    try: v = float(m.group(1).replace(",", ""))
    except ValueError: return None
    return v * SUF.get((m.group(2) or "").upper(), 1)

def mask_text(img, kind):
    a = np.array(img.convert("RGB")).astype(int)
    if kind == "dark":      mask = a.max(axis=2) < 90
    elif kind == "white":   mask = a.min(axis=2) >= 215
    elif kind == "green":   mask = (a[:, :, 1] - a[:, :, 0] > 40) & (a[:, :, 1] - a[:, :, 2] > 15) & (a[:, :, 1] > 130)
    else:                   mask = (a[:, :, 0] > 200) & (a[:, :, 1] < 110)
    return _finish(_clean(mask, min_big=max(14, int(img.height * 0.25))), pad=10, scale=2)

def parse_axiom(im):
    row = {"terminal": "axiom", "card_type": "trade", "currency": "USD", "flags": ["gabarit_a_valider"]}
    txt = full_text(im)
    m = re.search(r"PNL\s*([+\-−])?\s*(\d[\d,]*)\.?(\d{2})\s*%", txt)
    pct = None
    if m:
        pct = float(f"{m.group(2).replace(',', '')}.{m.group(3)}")
        if m.group(1) in ("-", "−"): pct = -pct
    m = re.search(r"Invested\s*\$?\s*([0-9.,]+\s*[KMBkmb]?)", txt); inv = money(m.group(1)) if m else None
    m = re.search(r"Position\s*\$?\s*([0-9.,]+\s*[KMBkmb]?)", txt); pos = money(m.group(1)) if m else None
    # bandeau du PnL (texte sombre sur fond vert ou rouge)
    ban = zone(im, (0.04, 0.30, 0.50, 0.46))
    a = np.array(ban.convert("RGB")).astype(int)
    neg = (a[:, :, 0] > 200).sum() > (a[:, :, 1] > 200).sum() * 1.5 and (a[:, :, 1] < 110).sum() > 200
    btxt = ocr(mask_text(ban, "dark"), "--psm 7 -c tessedit_char_whitelist=0123456789.KMB$+-")
    pnl = money(btxt)
    if pnl is not None and neg: pnl = -pnl
    tk = ocr(mask_text(zone(im, (0.03, 0.19, 0.52, 0.31)), "white"), "--psm 7")
    row.update(token_symbol=re.sub(r"[^A-Za-z0-9\-_.]", "", tk).strip(".-_") or None,
               pnl_value=pnl, pnl_percent=pct, invested=inv, position=pos, position_meaning="total_value")
    # contrôle : PnL ~ investi x %
    if pnl is not None and inv and pct:
        if abs(abs(pnl) - inv * abs(pct) / 100) / abs(pnl) > 0.04: row["flags"].append("amount_mismatch")
    if None in (row["token_symbol"], pnl, inv, pct): row["flags"].append("low_confidence")
    return row

def parse_gmgn(im):
    row = {"terminal": "gmgn", "card_type": "period", "currency": "USD", "flags": ["gabarit_a_valider", "abbreviated_amounts"]}
    txt = full_text(im)
    m = re.search(r"(%s)\s*(20\d\d)" % MONTHS, txt, re.I)
    row["period_label"] = f"{m.group(1).title()} {m.group(2)}" if m else "Période"
    ban = zone(im, (0.03, 0.46, 0.45, 0.62))
    neg = False
    btxt = ocr(mask_text(ban, "green"), "--psm 7 -c tessedit_char_whitelist=0123456789.KMB$+-")
    if not money(btxt):
        btxt = ocr(mask_text(ban, "red"), "--psm 7 -c tessedit_char_whitelist=0123456789.KMB$+-"); neg = money(btxt) is not None
    v = money(btxt)
    row["pnl_value"] = (-v if neg else v) if v is not None else None
    m = re.search(r"(\d+)\s*/\s*(\d+)", txt)
    if m: row["profit_days"] = f"{m.group(1)}/{m.group(2)}"
    if row["pnl_value"] is None: row["flags"].append("low_confidence")
    return row
