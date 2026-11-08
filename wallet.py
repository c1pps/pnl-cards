#!/usr/bin/env python3
"""Lecture d'un wallet Solana (adresse publique, lecture seule) et reconstruction des trades.

Source des données : API « Enhanced Transactions » de Helius, avec TA clé personnelle (gratuite sur helius.dev).
On ne demande jamais de clé privée ni de phrase secrète. L'adresse et la clé ne quittent pas ce PC, sauf pour
interroger Helius / DexScreener.

Méthode : pour chaque transaction, on calcule la variation nette du wallet (SOL et token). Un seul token qui bouge
en sens inverse du SOL = un achat ou une vente. Les trades sont ensuite reconstruits token par token, au coût moyen :
un trade commence au premier achat et se termine quand la position est (presque) entièrement vendue.
Les frais réseau, pourboires et frais du terminal sont inclus, car ils sont dans la variation de SOL du wallet."""
import re, json, time, threading, uuid, urllib.request, urllib.error

BASE = "https://api-mainnet.helius-rpc.com"
DAS = "https://mainnet.helius-rpc.com"
WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
DUST_SOL = 0.001       # achats plus petits : ignorés
CLOSE_RATIO = 0.02     # position considérée soldée sous 2 % de son pic


class WalletError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


def check_address(a):
    """Refuse tout ce qui ressemble à une clé privée ou à une phrase secrète."""
    a = (a or "").strip()
    if len(a.split()) >= 6:
        raise WalletError("secret_phrase")
    if len(a) > 50 and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]+", a):
        raise WalletError("private_key")
    if not B58.match(a):
        raise WalletError("bad_address")
    return a


def _http(url, body=None, timeout=25, tries=4):
    for i in range(tries):
        try:
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "pnl-cards/1.0", "Accept": "application/json", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise WalletError("bad_key")
            if e.code == 429:
                time.sleep(1.6 * (i + 1)); continue
            if i == tries - 1:
                raise WalletError("http_%d" % e.code)
            time.sleep(1)
        except Exception:
            if i == tries - 1:
                raise WalletError("network")
            time.sleep(1)


def fetch_txs(address, key, max_pages, on_page=None):
    out, before = [], None
    for p in range(max_pages):
        url = f"{BASE}/v0/addresses/{address}/transactions?api-key={key}&limit=100&token-accounts=balanceChanged"
        if before:
            url += f"&before-signature={before}"
        batch = _http(url)
        if isinstance(batch, dict):   # message d'erreur de l'API
            raise WalletError("bad_response", str(batch.get("error", ""))[:120])
        if not batch:
            break
        out.extend(batch)
        before = batch[-1].get("signature")
        if on_page:
            on_page(p + 1, len(out))
    return out


PUBLIC_RPCS = ["https://solana-rpc.publicnode.com", "https://api.mainnet-beta.solana.com"]
PUBLIC_MAX = 300   # sans clé : les RPC publics limitent le débit, on lit moins d'historique


def _rpc(urls, method, params):
    """Appel JSON-RPC sur les RPC publics, avec repli d'un serveur à l'autre."""
    last = "network"
    for u in urls:
        try:
            r = _http(u, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, tries=3)
        except WalletError as e:
            last = "rpc_blocked" if e.code == "bad_key" else e.code
            continue
        if isinstance(r, dict) and r.get("error"):
            last = "rpc_limited"
            continue
        if isinstance(r, dict) and "result" in r:
            return r["result"]
    raise WalletError(last)


def _raw_to_helius(sig, raw, address):
    """Transaction RPC brute -> même forme que Helius (variations de SOL et de tokens du wallet)."""
    meta = raw.get("meta") or {}
    ts = raw.get("blockTime")
    keys = [(k.get("pubkey") if isinstance(k, dict) else k) for k in ((raw.get("transaction") or {}).get("message") or {}).get("accountKeys", [])]
    if address not in keys or not ts:
        return None
    i = keys.index(address)
    pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
    dsol = (post[i] - pre[i]) if i < len(pre) and i < len(post) else 0
    acc = {}
    for side, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        for tb in meta.get(side) or []:
            if tb.get("owner") != address:
                continue
            ui = tb.get("uiTokenAmount") or {}
            key = tb.get("mint")
            d = acc.setdefault(key, [0, int(ui.get("decimals") or 0)])
            d[0] += sign * int(ui.get("amount") or 0)
    changes = [{"userAccount": address, "mint": m, "rawTokenAmount": {"tokenAmount": str(v[0]), "decimals": v[1]}} for m, v in acc.items() if v[0]]
    return {"signature": sig, "timestamp": ts, "transactionError": meta.get("err"),
            "accountData": [{"account": address, "nativeBalanceChange": dsol, "tokenBalanceChanges": changes}]}


def fetch_txs_public(address, max_pages, on_page=None):
    from concurrent.futures import ThreadPoolExecutor
    limit = min(max_pages * 100, PUBLIC_MAX)
    sigs, before = [], None
    while len(sigs) < limit:
        opt = {"limit": min(100, limit - len(sigs))}
        if before:
            opt["before"] = before
        batch = _rpc(PUBLIC_RPCS, "getSignaturesForAddress", [address, opt])
        if not batch:
            break
        sigs += [b["signature"] for b in batch if not b.get("err")]
        before = batch[-1]["signature"]
        if len(batch) < opt["limit"]:
            break
    out, done = [], [0]

    def one(sg):
        try:
            raw = _rpc(PUBLIC_RPCS, "getTransaction", [sg, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        except WalletError:
            raw = None
        done[0] += 1
        if on_page:
            on_page(done[0], done[0])
        return _raw_to_helius(sg, raw, address) if raw else None

    with ThreadPoolExecutor(max_workers=3) as ex:
        out = [t for t in ex.map(one, sigs) if t]
    return out


def parse_events(txs, address):
    """Transactions Helius -> [{ts, sig, mint, tok, sol}] (sol > 0 : le wallet reçoit du SOL)."""
    events, skipped = [], 0
    for tx in txs:
        if tx.get("transactionError"):
            continue
        ts, sig = tx.get("timestamp"), tx.get("signature")
        if not ts or not sig:
            continue
        sol, toks, seen_ad = 0.0, {}, False
        for ad in tx.get("accountData") or []:
            seen_ad = True
            if ad.get("account") == address:
                sol += float(ad.get("nativeBalanceChange") or 0)
            for tb in ad.get("tokenBalanceChanges") or []:
                if tb.get("userAccount") != address:
                    continue
                raw = tb.get("rawTokenAmount") or {}
                try:
                    amt = int(raw.get("tokenAmount") or 0) / (10 ** int(raw.get("decimals") or 0))
                except (ValueError, TypeError):
                    continue
                toks[tb.get("mint")] = toks.get(tb.get("mint"), 0.0) + amt
        if not seen_ad:   # repli : transferts parsés
            for t in tx.get("nativeTransfers") or []:
                if t.get("toUserAccount") == address: sol += float(t.get("amount") or 0)
                if t.get("fromUserAccount") == address: sol -= float(t.get("amount") or 0)
            for t in tx.get("tokenTransfers") or []:
                a = float(t.get("tokenAmount") or 0)
                if t.get("toUserAccount") == address: toks[t.get("mint")] = toks.get(t.get("mint"), 0.0) + a
                if t.get("fromUserAccount") == address: toks[t.get("mint")] = toks.get(t.get("mint"), 0.0) - a
        sol_total = sol / 1e9 + toks.pop(WSOL, 0.0)
        others = {m: a for m, a in toks.items() if m and m not in STABLES and abs(a) > 0}
        if not others:
            continue
        if len(others) != 1:
            skipped += 1
            continue
        mint, tok = next(iter(others.items()))
        if tok > 0 and sol_total < -DUST_SOL:
            events.append({"ts": ts, "sig": sig, "mint": mint, "tok": tok, "sol": sol_total})
        elif tok < 0 and sol_total > -0.01:
            events.append({"ts": ts, "sig": sig, "mint": mint, "tok": tok, "sol": max(sol_total, 0.0)})
        else:
            skipped += 1
    return events, skipped


def build_trades(events):
    """Événements -> trades fermés/ouverts au coût moyen, + positions encore détenues."""
    by = {}
    for e in sorted(events, key=lambda e: e["ts"]):
        by.setdefault(e["mint"], []).append(e)
    trades, holdings = [], []
    for mint, evs in by.items():
        qty = basis = 0.0
        cyc = None
        def close(c, closed):
            sold = c["proceeds"] is not None and c["nSells"] > 0
            if not sold:
                return
            pnl = c["proceeds"] - c["costOut"]
            inv = c["invested"] if closed else c["costOut"]   # position ouverte : seule la part déjà vendue compte
            trades.append({"mint": mint, "firstSig": c["firstSig"], "openedTs": c["openedTs"], "closedTs": c["lastSellTs"], "invested": round(inv, 6),
                           "proceeds": round(c["proceeds"], 6), "pnl": round(pnl, 6), "pct": round(pnl / c["costOut"] * 100, 2) if c["costOut"] else None,
                           "nBuys": c["nBuys"], "nSells": c["nSells"], "open": not closed, "noBasis": c["noBasis"],
                           "holdSec": max((c["lastSellTs"] or c["openedTs"]) - c["openedTs"], 0)})
        for e in evs:
            if e["tok"] > 0:
                if cyc is None or qty <= 1e-12:
                    cyc = {"openedTs": e["ts"], "firstSig": e["sig"], "invested": 0.0, "proceeds": 0.0, "costOut": 0.0, "nBuys": 0, "nSells": 0, "peak": 0.0, "lastSellTs": None, "noBasis": False}
                    qty = basis = 0.0
                qty += e["tok"]; basis += -e["sol"]
                cyc["invested"] += -e["sol"]; cyc["nBuys"] += 1; cyc["peak"] = max(cyc["peak"], qty)
            else:
                if cyc is None:   # vente sans achat connu (transfert reçu, historique tronqué)
                    cyc = {"openedTs": e["ts"], "firstSig": e["sig"], "invested": 0.0, "proceeds": 0.0, "costOut": 0.0, "nBuys": 0, "nSells": 0, "peak": 0.0, "lastSellTs": None, "noBasis": True}
                    qty = basis = 0.0
                sell = min(-e["tok"], qty) if qty > 0 else 0.0
                frac = (sell / qty) if qty > 0 else 0.0
                out = basis * frac
                basis -= out; qty -= sell
                cyc["costOut"] += out; cyc["proceeds"] += e["sol"]; cyc["nSells"] += 1; cyc["lastSellTs"] = e["ts"]
                if cyc["noBasis"] or qty <= cyc["peak"] * CLOSE_RATIO or qty <= 1e-12:
                    close(cyc, True); cyc = None; qty = basis = 0.0
        if cyc is not None:
            if cyc["nSells"]:
                close(cyc, False)
            if qty > 1e-12 and basis > DUST_SOL:
                holdings.append({"mint": mint, "qty": qty, "cost": round(basis, 6), "openedTs": cyc["openedTs"]})
    trades.sort(key=lambda t: t["closedTs"])
    return trades, holdings


def symbols(mints, key):
    """mint -> ticker. Helius DAS d'abord, DexScreener en repli. Jamais bloquant."""
    out = {}
    mints = list(dict.fromkeys(mints))
    for i in range(0, len(mints) if key else 0, 100):
        chunk = mints[i:i + 100]
        try:
            r = _http(f"{DAS}/?api-key={key}", {"jsonrpc": "2.0", "id": "pnl", "method": "getAssetBatch", "params": {"ids": chunk}}, tries=2)
            for m, a in zip(chunk, (r or {}).get("result") or []):
                md = ((a or {}).get("content") or {}).get("metadata") or {}
                if md.get("symbol"):
                    out[m] = md["symbol"].strip()
        except Exception:
            pass
    rest = [m for m in mints if m not in out]
    for i in range(0, len(rest), 30):
        try:
            r = _http("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(rest[i:i + 30]), tries=2)
            for p in r or []:
                b = p.get("baseToken") or {}
                if b.get("address") in rest and b.get("symbol"):
                    out.setdefault(b["address"], b["symbol"].strip())
        except Exception:
            pass
    return out


JOBS = {}


def start_job(address, key, pages):
    address = check_address(address)
    jid = uuid.uuid4().hex[:10]
    key = key or ""
    JOBS[jid] = {"state": "running", "pages": 0, "txs": 0, "max": pages, "phase": "fetch"}

    def run():
        j = JOBS[jid]
        try:
            def on_page(p, n):
                j["pages"], j["txs"] = p, n
            txs = fetch_txs(address, key.strip(), pages, on_page) if key.strip() else fetch_txs_public(address, pages, on_page)
            j["phase"] = "build"
            events, skipped = parse_events(txs, address)
            trades, holdings = build_trades(events)
            j["phase"] = "names"
            sy = symbols([t["mint"] for t in trades] + [h["mint"] for h in holdings], key.strip())
            for t in trades: t["symbol"] = sy.get(t["mint"]) or t["mint"][:4] + "…" + t["mint"][-4:]
            for h in holdings: h["symbol"] = sy.get(h["mint"]) or h["mint"][:4] + "…" + h["mint"][-4:]
            j.update(state="done", trades=trades, holdings=holdings, stats={"txs": len(txs), "swaps": len(events), "skipped": skipped, "reachedEnd": len(txs) < pages * 100, "public": not key.strip()})
        except WalletError as e:
            j.update(state="error", error=e.code, detail=e.detail)
        except Exception as e:   # ne jamais faire planter le serveur
            j.update(state="error", error="unknown", detail=str(e)[:120])

    threading.Thread(target=run, daemon=True).start()
    return jid
