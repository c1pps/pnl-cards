#!/usr/bin/env python3
"""PnL Cards — serveur local (127.0.0.1 uniquement). Lecture des PNL cards + stockage JSON local."""
import os, json, uuid, tempfile, threading
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, send_from_directory
from extract_terminal import extract
from extract_other import detect_terminal, parse_axiom, parse_gmgn
from PIL import Image
import pytesseract
import wallet

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "cards.json")
IMG = os.path.join(HERE, "data", "images")
os.makedirs(IMG, exist_ok=True)
app = Flask(__name__, static_folder=os.path.join(HERE, "static"), static_url_path="")
lock = threading.Lock()
pool = ThreadPoolExecutor(max_workers=4)


def to_card(row, mtime_ms=None):
    """Format commun serveur / interface."""
    base = {"id": uuid.uuid4().hex[:10], "file": row.get("file"), "terminal": row.get("terminal", "terminal"),
            "flags": [f for f in row.get("flags", []) if f != "ticker_ambiguous_I_l"], "dateMs": mtime_ms, "edited": False}
    if row.get("card_type") == "period":
        base.update(type="period", currency="USD", label=row.get("period_label"), pnl=row.get("pnl_value"),
                    pct=row.get("pnl_percent"), bought=row.get("total_bought"), sold=row.get("total_sold"),
                    profitDays=row.get("profit_days"))
    else:
        base.update(type="trade", currency=row.get("currency", "SOL"), token=row.get("token_symbol"), pnl=row.get("pnl_value"),
                    invested=row.get("invested"), pct=row.get("pnl_percent"), usdPnl=row.get("pnl_usd"),
                    usdInv=row.get("inv_usd"), position=row.get("position"),
                    positionMeaning=row.get("position_meaning", "remaining"))
    if base["type"] == "trade" and not isinstance(base.get("pnl"), (int, float)):
        base["error"] = "unreadable"
    return base


def read_any(path):
    """Détecte le terminal puis applique le bon gabarit. Terminal (ex-Padre) par défaut."""
    im = Image.open(path).convert("RGB")
    term = detect_terminal(im)
    if term == "axiom":
        return parse_axiom(im)
    if term == "gmgn":
        return parse_gmgn(im)
    return extract(path)


def save_img(path, cid):
    """Copie réduite de la carte (1000 px, JPEG) pour l'afficher dans l'app. Reste sur ce disque."""
    try:
        im = Image.open(path).convert("RGB")
        im.thumbnail((1000, 1000))
        im.save(os.path.join(IMG, cid + ".jpg"), "JPEG", quality=82)
        return "/api/img/" + cid
    except Exception:
        return None


@app.get("/api/img/<cid>")
def get_img(cid):
    return send_from_directory(IMG, "".join(ch for ch in cid if ch.isalnum()) + ".jpg", max_age=86400)


def read_cards():
    try:
        with open(DATA, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


@app.get("/")
def index():
    r = send_from_directory(app.static_folder, "index.html", max_age=0)
    r.headers["Cache-Control"] = "no-store"
    return r


@app.get("/api/cards")
def get_cards():
    return jsonify(read_cards())


@app.put("/api/cards")
def put_cards():
    data = request.get_json(force=True)
    with lock:
        with open(DATA, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    # supprime les photos des cartes effacées (sauf les très récentes, pas encore enregistrées par l'interface)
    import time
    used = {(c.get("img") or "").rsplit("/", 1)[-1] for c in data if isinstance(c, dict)}
    for fn in os.listdir(IMG):
        p = os.path.join(IMG, fn)
        if fn.endswith(".jpg") and fn[:-4] not in used and time.time() - os.path.getmtime(p) > 600:
            try: os.remove(p)
            except OSError: pass
    return jsonify(ok=True)


@app.post("/api/sheet")
def api_sheet():
    """Télécharge une feuille Google Sheets partagée par lien (export CSV). Uniquement docs.google.com."""
    import re, urllib.request
    url = (request.get_json(force=True, silent=True) or {}).get("url", "")
    m = re.search(r"docs\.google\.com/spreadsheets/d/([\w-]+)", url)
    if not m:
        return jsonify(error="bad_url"), 400
    g = re.search(r"[#&?]gid=(\d+)", url)
    u = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv" + (f"&gid={g.group(1)}" if g else "")
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read(5_000_000).decode("utf-8", "replace")
    except Exception as e:
        return jsonify(error="fetch", detail=str(e)[:120]), 502
    if raw.lstrip().lower().startswith(("<!doctype", "<html")):
        return jsonify(error="private"), 403
    return jsonify(csv=raw)


@app.post("/api/wallet/sync")
def wallet_sync():
    b = request.get_json(force=True, silent=True) or {}
    try:
        pages = max(1, min(int(b.get("pages", 10)), 100))
        return jsonify(job=wallet.start_job(b.get("address"), b.get("key"), pages))
    except wallet.WalletError as e:
        return jsonify(error=e.code, detail=e.detail), 400


@app.get("/api/wallet/job/<jid>")
def wallet_job(jid):
    j = wallet.JOBS.get(jid)
    if not j:
        return jsonify(error="unknown"), 404
    return jsonify(j)


@app.post("/api/extract")
def api_extract():
    files = request.files.getlist("files")
    mtimes = json.loads(request.form.get("mtimes", "[]"))
    tmp = tempfile.mkdtemp(prefix="pnlcards_")
    jobs = []
    for i, f in enumerate(files):
        path = os.path.join(tmp, f"{i}.png")
        f.save(path)
        jobs.append((f.filename, path, mtimes[i] if i < len(mtimes) else None))

    def run(job):
        name, path, mt = job
        try:
            row = read_any(path)
            row["file"] = name
            card = to_card(row, mt)
            card["img"] = save_img(path, card["id"])
            return card
        except Exception as e:  # une carte illisible ne bloque pas les autres
            code = "no_tesseract" if isinstance(e, pytesseract.TesseractNotFoundError) else "error"
            cid = uuid.uuid4().hex[:10]
            return {"id": cid, "file": name, "type": "trade", "currency": "SOL", "flags": ["low_confidence"], "img": save_img(path, cid),
                    "error": code, "detail": str(e)[:200], "dateMs": mt, "token": None, "pnl": None, "edited": False}
        finally:
            try: os.remove(path)
            except OSError: pass

    out = list(pool.map(run, jobs))
    try: os.rmdir(tmp)
    except OSError: pass
    return jsonify(out)


if __name__ == "__main__":
    print("PnL Cards sur http://127.0.0.1:5173  (Ctrl+C pour arrêter)")
    app.run(host="127.0.0.1", port=5173, debug=False, threaded=True)
