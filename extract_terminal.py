#!/usr/bin/env python3
"""Prototype d'extraction OCR par zones pour les PNL cards Terminal (ex-Padre).
Usage: python extract_terminal.py <dossier_ou_fichiers...> [--json out.json] [--csv out.csv]
Dépendances: pillow, numpy, pytesseract (+ binaire tesseract)."""
import sys, os, re, json, csv, glob
import numpy as np
from PIL import Image
import pytesseract
import shutil
def _find_tesseract():
    """PATH, variable TESSERACT_CMD, puis les dossiers d'installation Windows habituels."""
    env = os.environ.get("TESSERACT_CMD")
    if env and os.path.exists(env): return env
    w = shutil.which("tesseract")
    if w: return w
    if os.name == "nt":
        roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "ProgramW6432")]
        cands = []
        for r in filter(None, roots):
            cands += [os.path.join(r, "Tesseract-OCR", "tesseract.exe"), os.path.join(r, "Programs", "Tesseract-OCR", "tesseract.exe")]
        cands += [r"C:\Tesseract-OCR\tesseract.exe", os.path.expanduser(r"~\Tesseract-OCR\tesseract.exe")]
        for p in cands:
            if os.path.exists(p): return p
    return None
_t = _find_tesseract()
if _t: pytesseract.pytesseract.tesseract_cmd = _t

W, H = 1980, 1320  # gabarit de référence
# zones (x0, y0, x1, y1) en pixels de référence
Z = {
    "ticker":   (150, 505, 1130, 668),
    "pnl_sol":  (160, 680, 1136, 910),
    "invested": (222, 1040, 545, 1110),
    "position": (617, 1040, 945, 1110),
    "pnl_pct":  (955, 1040, 1330, 1110),
    "inv_usd":  (150, 1120, 540, 1190),
    "pnl_usd":  (945, 1120, 1300, 1190),
}


import cv2

def _clean(mask, min_big=22, drop_sign=False, drop_pct=False):
    """Garde la ligne de glyphes (grands composants + point/virgule dans leur bande) ; supprime la texture
    et les formes touchant le bord de la zone."""
    m = (mask.astype(np.uint8) * 255)
    Hh, Ww = m.shape
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    def touches(i):
        l, t, w, h, a = st[i]
        return l <= 0 or t <= 0 or l + w >= Ww or t + h >= Hh
    big = [i for i in range(1, n) if st[i, cv2.CC_STAT_HEIGHT] >= min_big and not touches(i)]
    out = np.full(m.shape, 255, np.uint8)
    if not big:
        return out
    ref = sorted(st[i, cv2.CC_STAT_HEIGHT] for i in big)[len(big)//2]
    big = [i for i in big if 0.6*ref <= st[i, cv2.CC_STAT_HEIGHT] <= 1.5*ref]
    if not big:
        return out
    # regroupe par proximité horizontale, garde le plus gros groupe
    big.sort(key=lambda i: st[i, cv2.CC_STAT_LEFT])
    groups, cur = [], [big[0]]
    for i in big[1:]:
        prev = cur[-1]
        gap = st[i, cv2.CC_STAT_LEFT] - (st[prev, cv2.CC_STAT_LEFT] + st[prev, cv2.CC_STAT_WIDTH])
        if gap > 1.1*ref:
            groups.append(cur); cur = [i]
        else:
            cur.append(i)
    groups.append(cur)
    big = max(groups, key=lambda g: sum(st[i, cv2.CC_STAT_WIDTH] for i in g))
    if drop_sign and len(big) > 1:
        i = big[0]; w, h, a = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT], st[i, cv2.CC_STAT_AREA]
        if w/h > 0.85 and a/(w*h) < 0.55:
            big = big[1:]
    if drop_pct and len(big) > 1:
        i = big[-1]; w, h = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if w/h > 0.95:
            big = big[:-1]
    y0 = min(st[i, cv2.CC_STAT_TOP] for i in big); y1 = max(st[i, cv2.CC_STAT_TOP]+st[i, cv2.CC_STAT_HEIGHT] for i in big)
    x0 = min(st[i, cv2.CC_STAT_LEFT] for i in big); x1 = max(st[i, cv2.CC_STAT_LEFT]+st[i, cv2.CC_STAT_WIDTH] for i in big)
    keep = set(big)
    for i in range(1, n):
        if i in keep or touches(i):
            continue
        l, t, w, h, a = st[i]
        cy = t + h/2
        if a >= 6 and y0 <= cy <= y1+6 and x0-4 <= l <= x1+4 and w <= 0.45*ref and h <= 0.45*ref:
            keep.add(i)
    for i in keep:
        out[lab == i] = 0
    return out

def _finish(out, pad=14, scale=2):
    ys, xs = np.where(out == 0)
    if len(xs) == 0:
        im = Image.fromarray(out)
    else:
        im = Image.fromarray(out).crop((max(xs.min()-pad, 0), max(ys.min()-pad, 0), min(xs.max()+pad, out.shape[1]), min(ys.max()+pad, out.shape[0])))
    im = im.resize((im.width*scale, im.height*scale), Image.LANCZOS)
    canvas = Image.new("L", (im.width+40, im.height+40), 255); canvas.paste(im, (20, 20))
    return canvas

def crop(im, z):
    sx, sy = im.width / W, im.height / H
    x0, y0, x1, y1 = z
    return im.crop((int(x0*sx), int(y0*sy), int(x1*sx), int(y1*sy)))

def ocr(img, cfg):
    return pytesseract.image_to_string(img, config=cfg).strip()

def bright_text(img, thr=232):
    a = np.array(img.convert("RGB")).astype(int)
    return _finish(_clean(a.min(axis=2) >= thr, min_big=40))

def banner_text(img):
    """gros chiffre noir sur bandeau vert/rouge; on retire le logo SOL à gauche"""
    a = np.array(img.convert("RGB")).astype(int)
    dark = (a.max(axis=2) < 90)
    out = np.where(dark, 0, 255).astype(np.uint8)
    im = Image.fromarray(out)
    return im.crop((int(im.width*0.20), 0, im.width, im.height))

def small_value(img, thr=246, drop_sign=False, drop_pct=False, tone=None):
    """tone=None : texte blanc (Invested, Position, USD) ; tone='green'|'red' : texte coloré (PnL % et PnL USD)."""
    a = np.array(img.convert("RGB")).astype(int)
    if tone == "green":
        mask = (a[:, :, 1] - a[:, :, 0] > 40) & (a[:, :, 1] - a[:, :, 2] > 20) & (a[:, :, 1] > 120)
    elif tone == "red":
        mask = (a[:, :, 0] > 200) & (a[:, :, 1] < 90) & (a[:, :, 2] < 110)
    else:
        mask = a.min(axis=2) >= thr
    return _finish(_clean(mask, min_big=24, drop_sign=drop_sign, drop_pct=drop_pct))

def num(s):
    s = s.replace(",", ".").replace(" ", "")
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None

ZP = {  # carte "période" (mois) Terminal
    "pnl":    (160, 735, 1136, 975),
    "bought": (160, 1040, 550, 1180),
    "sold":   (555, 1040, 945, 1180),
    "pct":    (945, 1040, 1300, 1180),
}
MONTH = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*20\d\d", re.I)

def digits(img, cfg="--psm 7 -c tessedit_char_whitelist=0123456789."):
    return re.sub(r"[^0-9]", "", ocr(img, cfg))


def read_glyphs(img, dec):
    """Lecture glyphe par glyphe (plus robuste que la ligne entière sur '77.49' etc.).
    Retourne (valeur, texte) ; `dec` = nombre de décimales attendu après le point."""
    arr = np.array(img.convert("L"))
    mask = (arr < 128).astype(np.uint8) * 255
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = [tuple(st[i][:5]) for i in range(1, n)]
    if not boxes:
        return None, ""
    maxh = max(b[3] for b in boxes)
    items = []
    for (l, t, w, h, a) in boxes:
        if h >= 0.55 * maxh:
            items.append((l, "d", (l, t, w, h)))
        elif h <= 0.3 * maxh and w <= 0.3 * maxh and (t + h) >= 0.8 * (max(bb[1] + bb[3] for bb in boxes)):
            items.append((l, ".", (l, t, w, h)))
    items.sort()
    out, seen_dot, dec_count = "", False, 0
    for k, (l, kind, (x, y, w, h)) in enumerate(items):
        if kind == ".":
            if not seen_dot and out:
                out += "."; seen_dot = True
            continue
        if not out and not seen_dot and w / h > 0.85 and (a_fill := (mask[y:y+h, x:x+w] > 0).mean()) < 0.55:
            continue  # signe '+'
        if seen_dot and dec_count >= dec:
            break
        pad = 10
        g = Image.fromarray(255 - mask[max(y-pad, 0):y+h+pad, max(x-pad, 0):x+w+pad])
        g = g.resize((g.width*2, g.height*2), Image.LANCZOS)
        t = ""
        for cfg in ("--psm 10 -c tessedit_char_whitelist=0123456789", "--psm 8 -c tessedit_char_whitelist=0123456789",
                    "--psm 13 -c tessedit_char_whitelist=0123456789", "--psm 10"):
            t = re.sub(r"[^0-9]", "", ocr(g, cfg))
            if t:
                break
        if not t:
            return None, out
        out += t[0]
        if seen_dot:
            dec_count += 1
    if "." in out and dec_count == dec:
        try:
            return float(out), out
        except ValueError:
            pass
    return None, out

def read_fixed(img, dec, alt=(), glyphs=False):
    """lit un nombre à `dec` décimales ; essaie d'abord le motif avec point, sinon reconstruit les décimales."""
    if glyphs:
        for d in (dec,) + tuple(alt):
            gv, gtxt = read_glyphs(img, d)
            if gv is not None:
                return gv, gtxt
    raw = ocr(img, "--psm 7 -c tessedit_char_whitelist=0123456789.")
    for d in (dec,) + tuple(alt):
        m = re.search(r"(\d+)\.(\d{%d})" % d, raw)
        if m:
            return float(m.group(1) + "." + m.group(2)), raw
    d = re.sub(r"[^0-9]", "", raw)
    return (with_decimals(d, dec) if d else None), raw

def with_decimals(d, dec):
    if not d:
        return None
    d = d.zfill(dec + 1)
    return int(d) / (10 ** dec)

def color_sign(img):
    a = np.array(img.convert("RGB")).astype(int)
    red = ((a[:, :, 0] > 180) & (a[:, :, 1] < 110) & (a[:, :, 2] < 120)).sum()
    green = ((a[:, :, 1] > 150) & (a[:, :, 0] < 140)).sum()
    return -1 if red > green else 1

def banner_digits(img):
    a = np.array(img.convert("RGB")).astype(int)
    dark = a.max(axis=2) < 90
    return _finish(_clean(dark, min_big=40, drop_sign=True), pad=12, scale=1)

def extract(path):
    import datetime
    im = Image.open(path).convert("RGB")
    r = {"file": os.path.basename(path), "terminal": "terminal"}
    flags = []
    t = ocr(bright_text(crop(im, Z["ticker"])), "--psm 7")
    t_clean = re.sub(r"[^A-Za-z0-9\-_. ]", "", t).strip(" .-_")
    if MONTH.match(t_clean):
        r.update(card_type="period", currency="USD", period_label=t_clean)
        sign = color_sign(crop(im, ZP["pnl"]))
        r["pnl_value"] = sign * (read_fixed(banner_digits(crop(im, ZP["pnl"])), 2)[0] or 0)
        for k in ("bought", "sold"):
            txt = ocr(small_value(crop(im, ZP[k])), "--psm 7 -c tessedit_char_whitelist=0123456789.KMk$")
            m = re.search(r"([0-9.]+)\s*([KMk])?", txt)
            if m:
                v = float(m.group(1)) if m.group(1).count(".") <= 1 and m.group(1) else None
                v = v * {"K": 1e3, "k": 1e3, "M": 1e6}.get(m.group(2) or "", 1) if v is not None else None
                r["total_" + k] = v
        r["pnl_percent"] = color_sign(crop(im, ZP["pct"])) * (read_fixed(small_value(crop(im, ZP["pct"]), drop_sign=True, drop_pct=True, tone=("red" if color_sign(crop(im, ZP["pct"])) < 0 else "green")), 2)[0] or 0)
        r["flags"] = flags + ["abbreviated_amounts"]
        return r
    if re.fullmatch(r"[A-Zl]+", t_clean) and "l" in t_clean:
        t_clean = t_clean.replace("l", "I")   # "Al" -> "AI" (l minuscule/I majuscule indiscernables)
    r.update(card_type="trade", currency="SOL", token_symbol=t_clean or None)
    if re.search(r"[Il1]", t_clean):
        flags.append("ticker_ambiguous_I_l")
    ban = crop(im, Z["pnl_sol"])
    sign = color_sign(ban)
    pnl, _ = read_fixed(banner_digits(ban), 4)
    r["pnl_value"] = None if pnl is None else sign * pnl
    pc_img = crop(im, Z["pnl_pct"])
    tone = "red" if sign < 0 else "green"
    # plusieurs variantes de prétraitement pour le % (les chiffres de gauche touchent parfois le fond texturé)
    pc_variants = []
    for x0 in (955,):
        zimg = crop(im, (x0, Z["pnl_pct"][1], Z["pnl_pct"][2], Z["pnl_pct"][3]))
        for ds in (True, False):
            pc_variants.append(read_fixed(small_value(zimg, drop_sign=ds, drop_pct=True, tone=tone), 2))
    pc_val, pc_raw = pc_variants[0]
    r["position"], _ = read_fixed(small_value(crop(im, Z["position"])), 2)
    r["inv_usd"], _ = read_fixed(small_value(crop(im, Z["inv_usd"])), 2)
    r["pnl_usd"], _ = read_fixed(small_value(crop(im, Z["pnl_usd"]), tone=tone), 2)
    if r["pnl_usd"] is not None and sign < 0:
        r["pnl_usd"] = -abs(r["pnl_usd"])
    inv_val4, inv_raw = read_fixed(small_value(crop(im, Z["invested"])), 4, alt=(2,))
    # candidats pour l'investi et pour le %, puis choix du couple cohérent avec le PnL SOL (PnL = investi x % / 100)
    dI = re.sub(r"[^0-9]", "", inv_raw)
    inv_c = [v for v in dict.fromkeys([inv_val4, with_decimals(dI, 4), with_decimals(dI, 2)]) if v]
    pc_c = []
    for v, raw in pc_variants:
        if v:
            pc_c.append(v)
        dP = re.sub(r"[^0-9]", "", raw)
        for dd in (dP, dP[:-1], dP[1:]):
            if len(dd) >= 3:
                pc_c.append(with_decimals(dd, 2))
    pc_c = [v for v in dict.fromkeys(pc_c) if v]
    exp_usd = None
    if r["inv_usd"] and r["pnl_usd"] not in (None, 0):
        exp_usd = abs(r["pnl_usd"]) / r["inv_usd"] * 100      # le % affiché est cohérent avec les montants USD
    pnl_abs = abs(r["pnl_value"]) if r["pnl_value"] is not None else None

    def score(iv, pv):
        eS = abs(pnl_abs - iv * pv / 100) / max(pnl_abs, 1e-9) if pnl_abs else 9.0
        eU = abs(pv - exp_usd) / exp_usd if exp_usd else None
        okS = eS <= (0.025 if iv >= 1 else 0.012)
        okU = eU is not None and eU <= 0.004
        return (0 if (okS and okU) else 1 if okS else 2 if okU else 3, eS), okS, okU

    def pick_pair():
        b = None
        for iv in inv_c:
            for pv in pc_c:
                sc = score(iv, pv)
                if b is None or sc[0] < b[0][0]:
                    b = (sc, iv, pv)
        return b

    best = pick_pair() if (inv_c and pc_c) else None
    if best is None or best[0][0][0] > 0:              # repli lent : lecture glyphe par glyphe
        for x0 in (955, 970):
            zimg = crop(im, (x0, Z["pnl_pct"][1], Z["pnl_pct"][2], Z["pnl_pct"][3]))
            gv, _ = read_fixed(small_value(zimg, drop_sign=True, drop_pct=True, tone=tone), 2, glyphs=True)
            if gv and gv not in pc_c:
                pc_c.append(gv)
        gv_inv, _ = read_fixed(small_value(crop(im, Z["invested"])), 4, alt=(2,), glyphs=True)
        if gv_inv and gv_inv not in inv_c:
            inv_c.append(gv_inv)
        if inv_c and pc_c:
            best = pick_pair()
    if best:
        _, iv, pv = best
        r["invested"] = iv
        r["pnl_percent"] = -pv if sign < 0 else pv
        r["invested_derived"] = round(pnl_abs / (pv / 100), 4) if pv and pnl_abs else None
        if best[0][0][0] == 3:
            flags.append("amount_mismatch")
        elif best[0][0][0] == 2:
            flags.append("invested_unverified")
        elif best[0][0][0] == 1:
            flags.append("usd_unverified")
    else:
        r["invested"] = inv_c[0] if inv_c else None
        r["pnl_percent"] = None
        r["invested_derived"] = None
    r["position_meaning"] = "remaining"
    r["status"] = "closed" if r["position"] == 0 else "open_or_unknown"
    if r["invested"] and r["inv_usd"]:
        r["implied_sol_usd"] = round(r["inv_usd"] / r["invested"], 1)
    if None in (r["token_symbol"], r["pnl_value"], r["invested"], r["pnl_percent"], r["position"]):
        flags.append("low_confidence")
    r["sold_derived"] = round(r["invested"] + r["pnl_value"], 4) if (r["invested"] and r["pnl_value"] is not None and r["position"] == 0) else None
    r["flags"] = flags
    try:
        r["mtime_estimate"] = datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        r["mtime_estimate"] = None
    return r

def main(argv):
    out_json = out_csv = None
    args = []
    it = iter(argv)
    for a in it:
        if a == "--json": out_json = next(it)
        elif a == "--csv": out_csv = next(it)
        else: args.append(a)
    files = []
    for a in args:
        files += sorted(glob.glob(os.path.join(a, "*.png"))) if os.path.isdir(a) else [a]
    rows = [extract(f) for f in files]
    if out_json:
        json.dump(rows, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if out_csv:
        keys = []
        for r in rows:
            for k in r:
                if k not in keys: keys.append(k)
        w = csv.DictWriter(open(out_csv, "w", newline="", encoding="utf-8"), fieldnames=keys)
        w.writeheader(); [w.writerow({k: (",".join(r[k]) if isinstance(r.get(k), list) else r.get(k)) for k in keys}) for r in rows]
    for r in rows:
        print(r["file"], r.get("token_symbol") or r.get("period_label"), r.get("pnl_value"), r.get("invested"), r.get("position"), r.get("pnl_percent"), r.get("flags"))
    return rows

if __name__ == "__main__":
    main(sys.argv[1:])
