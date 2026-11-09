"""Admin full health-check (/health).

Checks:
  * Bot smoothness  - event-loop lag, Telegram connection, uptime, memory
  * API stability   - several pings to every external API -> success rate,
                      average latency, jitter -> STABLE / SLOW / UNSTABLE / DOWN
  * Database        - local DB integrity, row counts, MongoDB connection,
                      local vs MongoDB counts, pending writes, last sync age
  * Configuration   - required / optional variables (set / missing)

SECURITY: secret values are NEVER returned or printed. Secrets show only as
"set" / "missing"; URLs are reduced to scheme://host; errors show only the
exception class name (messages can contain credentials).
"""
import asyncio
import html
import os
import statistics
import time
from urllib.parse import urlsplit

import aiohttp

START_TIME = time.time()
PING_COUNT = 3
SLOW_MS = 1500
KEY_TABLES = ["users", "stock", "orders", "deposits", "settings"]

REQUIRED_VARS = [
    ("API_ID", "Telegram API ID"),
    ("API_HASH", "Telegram API hash"),
    ("BOT_TOKEN", "Bot token"),
    ("ADMIN_ID", "Admin ID"),
    ("MONGO_URI", "MongoDB URI"),
    ("PAYGATE_API_KEY", "Payment gateway key"),
]
OPTIONAL_VARS = [
    ("MONGO_DB", "MongoDB database name"),
    ("PAYGATE_URL", "Payment gateway URL"),
    ("LOG_CHANNEL_ID", "Admin log channel"),
    ("SALE_LOG_CHANNEL", "Sale log channel"),
    ("DATA_DIR", "Persistent data dir"),
    ("UPI_ID", "UPI ID"),
    ("BINANCE_ID", "Binance Pay ID"),
    ("HERO_SMS_API_KEY", "Hero SMS key"),
    ("SMM_API_KEY", "SMM panel key"),
    ("TGLION_API_KEY", "TG-Lion key"),
]


# ------------------------------------------------------------------ helpers
def safe_host(url: str) -> str:
    """Return only scheme://host[:port] — strips user:password, path, query."""
    try:
        p = urlsplit(url or "")
        if not p.scheme or not p.hostname:
            return "not set"
        return f"{p.scheme}://{p.hostname}" + (f":{p.port}" if p.port else "")
    except Exception:
        return "invalid"


def _is_set(name: str) -> bool:
    return bool(str(os.getenv(name, "") or "").strip())


def _err(ex) -> str:
    return f"error: {type(ex).__name__}"


def _fmt_age(sec) -> str:
    if sec is None: return "never"
    sec = int(sec)
    if sec < 60: return f"{sec}s ago"
    if sec < 3600: return f"{sec // 60}m ago"
    return f"{sec // 3600}h {sec % 3600 // 60}m ago"


def _fmt_uptime(sec) -> str:
    sec = int(sec); d, sec = divmod(sec, 86400); h, sec = divmod(sec, 3600); m = sec // 60
    return (f"{d}d " if d else "") + f"{h}h {m}m"


def rate_stability(results: list) -> dict:
    """results: list of latency_ms (int) or None for failure."""
    ok = [r for r in results if r is not None]
    n = len(results)
    avg = int(sum(ok) / len(ok)) if ok else None
    jitter = int(statistics.pstdev(ok)) if len(ok) > 1 else 0
    if not ok:
        verdict = "DOWN"
    elif len(ok) < n:
        verdict = "UNSTABLE"
    elif avg > SLOW_MS or jitter > SLOW_MS / 2:
        verdict = "SLOW"
    else:
        verdict = "STABLE"
    return {"success": f"{len(ok)}/{n}", "avg_ms": avg, "jitter_ms": jitter, "verdict": verdict}


# ------------------------------------------------------------------ config
def check_config() -> dict:
    required = []
    for name, label in REQUIRED_VARS:
        ok = _is_set(name)
        if name == "PAYGATE_API_KEY" and not ok:
            try:
                from utils.paygate import is_enabled
                ok = is_enabled()  # key may be saved via /setpaykey
            except Exception:
                pass
        required.append({"name": name, "label": label, "ok": ok})
    optional = [{"name": n, "label": l, "ok": _is_set(n)} for n, l in OPTIONAL_VARS]
    return {"ok": all(r["ok"] for r in required), "required": required, "optional": optional}


# ------------------------------------------------------------------ bot
async def measure_loop_lag(samples: int = 5, interval: float = 0.05) -> int:
    """Max extra delay (ms) of the asyncio loop. High = bot is blocked/laggy."""
    worst = 0.0
    loop = asyncio.get_running_loop()
    for _ in range(samples):
        t = loop.time()
        await asyncio.sleep(interval)
        worst = max(worst, loop.time() - t - interval)
    return int(worst * 1000)


def _memory_mb():
    try:
        import resource, sys
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024)
    except Exception:
        return None


async def check_bot(client=None) -> dict:
    lag = await measure_loop_lag()
    res = {"loop_lag_ms": lag, "uptime": _fmt_uptime(time.time() - START_TIME),
           "memory_mb": _memory_mb(), "telegram": "unknown", "tg_ms": None}
    if client is not None:
        try:
            if not client.is_connected():
                res["telegram"] = "disconnected"
            else:
                t = time.monotonic()
                await asyncio.wait_for(client.get_me(), 10)
                res["tg_ms"] = int((time.monotonic() - t) * 1000)
                res["telegram"] = "connected"
        except asyncio.TimeoutError:
            res["telegram"] = "timeout"
        except Exception as ex:
            res["telegram"] = _err(ex)
    smooth = lag < 300 and res["telegram"] in ("connected", "unknown")
    res["verdict"] = "SMOOTH" if smooth and lag < 100 else ("OK" if smooth else "LAGGY")
    res["ok"] = smooth
    return res


# ------------------------------------------------------------------ APIs
def api_targets() -> list:
    """(label, url, key_present). Only URL hosts are ever shown."""
    from utils import paygate
    t = [("Payment server", paygate.PAYGATE_URL + "/", paygate.is_enabled(), True)]
    t.append(("Hero SMS", os.getenv("HERO_SMS_API_URL", "https://hero-sms.com/stubs/handler_api.php"),
              True, False))
    t.append(("SMM panel", os.getenv("SMM_API_URL", "https://cheapestsmmpanels.com/api/v2"),
              _is_set("SMM_API_KEY") or _is_set("CHEAPESTSMM_API_KEY"), False))
    t.append(("TG-Lion", os.getenv("TGLION_API_URL", "https://tg-lion.net/"), _is_set("TGLION_API_KEY"), False))
    return t


async def _ping(session, url) -> tuple:
    t = time.monotonic()
    try:
        async with session.get(url, allow_redirects=True) as r:
            await r.read()
            ms = int((time.monotonic() - t) * 1000)
            return (ms if r.status < 500 else None), f"HTTP {r.status}"
    except asyncio.TimeoutError:
        return None, "timeout"
    except Exception as ex:
        return None, _err(ex)


async def check_api(label, url, key_set, required, timeout=8.0, count=PING_COUNT) -> dict:
    res = {"label": label, "host": safe_host(url), "key": "set" if key_set else "missing",
           "required": required, "last_status": "", "auth": "n/a"}
    lat = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
        for i in range(count):
            ms, status = await _ping(s, url)
            lat.append(ms); res["last_status"] = status
            if i < count - 1: await asyncio.sleep(0.2)
        if label == "Payment server" and key_set and any(lat):
            from utils import paygate
            base = paygate.PAYGATE_URL
            try:
                async with s.get(base + "/api/v1/payments/healthcheck-probe",
                                 headers={"Authorization": f"Bearer {paygate._key()}"}) as r2:
                    res["auth"] = "rejected" if r2.status in (401, 403) else "accepted"
            except Exception as ex:
                res["auth"] = _err(ex)
    res.update(rate_stability(lat))
    res["ok"] = res["verdict"] in ("STABLE", "SLOW") and res["auth"] != "rejected" and (key_set or not required)
    return res


async def check_apis() -> list:
    targets = api_targets()
    return list(await asyncio.gather(*(check_api(*t) for t in targets)))


# ------------------------------------------------------------------ database
def _local_db_sync() -> dict:
    from database import db
    res = {"integrity": "unknown", "counts": {}, "ok": False}
    try:
        res["integrity"] = db.execute("PRAGMA quick_check").fetchone()[0]
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in KEY_TABLES:
            if t in names:
                res["counts"][t] = db.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
        res["ok"] = res["integrity"] == "ok"
    except Exception as ex:
        res["integrity"] = _err(ex)
    return res


def _mongo_sync(timeout_ms: int, local_counts: dict) -> dict:
    import mongo_store
    uri = getattr(mongo_store, "MONGO_URI", "") or os.getenv("MONGO_URI", "")
    res = {"ok": False, "status": "not configured", "latency_ms": None, "db": None,
           "sync": "n/a", "mismatch": {}, "pending": False, "last_sync": None,
           "failures": 0, "last_error": ""}
    if not uri:
        return res
    st = getattr(mongo_store, "stats", {}) or {}
    res["failures"] = st.get("failures", 0)
    res["last_error"] = st.get("last_error", "")
    res["last_sync"] = (time.time() - st["last_sync"]) if st.get("last_sync") else None
    res["pending"] = bool(getattr(mongo_store, "pending_changes", lambda: False)())
    client = getattr(mongo_store, "_client", None); own = False
    t = time.monotonic()
    try:
        if client is None:
            from pymongo import MongoClient
            client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms, connectTimeoutMS=timeout_ms)
            own = True
        client.admin.command("ping")
        res["latency_ms"] = int((time.monotonic() - t) * 1000)
        dbname = getattr(mongo_store, "MONGO_DB", "betabot"); res["db"] = dbname
        active = bool(getattr(mongo_store, "enabled", False))
        res["status"] = "connected" if active else "reachable (sync not active)"
        mdb = client[dbname]
        for tbl, n in local_counts.items():
            m = mdb[tbl].count_documents({})
            if m != n:
                res["mismatch"][tbl] = {"local": n, "mongo": m}
        if not active:
            res["sync"] = "NOT SYNCING"
        elif res["mismatch"] or res["pending"]:
            res["sync"] = "SYNCING (pending changes)"
        else:
            res["sync"] = "UP TO DATE"
        recent_err = st.get("last_error_at", 0) > st.get("last_sync", 0)
        res["ok"] = active and not recent_err and (not res["mismatch"] or res["pending"])
        if recent_err: res["sync"] = "FAILING"
    except Exception as ex:
        res["status"] = _err(ex)
    finally:
        if own and client is not None:
            try: client.close()
            except Exception: pass
    return res


async def check_database(timeout: float = 8.0) -> dict:
    local = await asyncio.to_thread(_local_db_sync)
    try:
        mongo = await asyncio.wait_for(
            asyncio.to_thread(_mongo_sync, int(timeout * 1000), local["counts"]), timeout * 3)
    except asyncio.TimeoutError:
        mongo = {"ok": False, "status": "timeout", "latency_ms": None, "db": None, "sync": "unknown",
                 "mismatch": {}, "pending": False, "last_sync": None, "failures": 0, "last_error": ""}
    return {"ok": local["ok"] and mongo["ok"], "local": local, "mongo": mongo}


# ------------------------------------------------------------------ run + format
async def check_panels() -> list:
    """Balance of every supplier panel (see utils/panels.py). Never raises."""
    try:
        from utils.panels import fetch_balances
        return await fetch_balances()
    except Exception:
        return []


async def run_health_check(client=None) -> dict:
    bot, apis, dbr, panels = await asyncio.gather(check_bot(client), check_apis(), check_database(), check_panels())
    cfg = check_config()
    required_apis_ok = all(a["ok"] for a in apis if a["required"])
    low_panel = any(p.get("low") for p in panels)
    return {"ok": bot["ok"] and required_apis_ok and dbr["ok"] and cfg["ok"] and not low_panel,
            "bot": bot, "apis": apis, "db": dbr, "config": cfg, "panels": panels}


def format_report(r: dict) -> str:
    e = html.escape
    y = lambda b: "✅" if b else "❌"
    ms = lambda v: f"{v} ms" if v is not None else "n/a"
    b, d, c = r["bot"], r["db"], r["config"]
    L = [f"<b>🩺 Full Health Check</b> — {'✅ ALL GOOD' if r['ok'] else '⚠️ ATTENTION NEEDED'}", ""]

    L.append(f"<b>{y(b['ok'])} Bot: {b['verdict']}</b>")
    L.append(f"   Response lag: {b['loop_lag_ms']} ms | Uptime: {b['uptime']}")
    mem = f"{b['memory_mb']} MB" if b["memory_mb"] is not None else "n/a"
    L.append(f"   Telegram: {e(b['telegram'])} ({ms(b['tg_ms'])}) | Memory: {mem}")

    L += ["", "<b>🌐 API stability</b> (" + str(PING_COUNT) + " pings each)"]
    icon = {"STABLE": "✅", "SLOW": "🐢", "UNSTABLE": "⚠️", "DOWN": "❌"}
    for a in r["apis"]:
        if not a["required"] and a["key"] == "missing" and a["verdict"] == "DOWN":
            L.append(f"   ⚪ {e(a['label'])}: not configured"); continue
        L.append(f"   {icon[a['verdict']]} <b>{e(a['label'])}: {a['verdict']}</b> — {a['success']} ok, "
                 f"avg {ms(a['avg_ms'])}, jitter {a['jitter_ms']} ms")
        extra = f" | Auth: {e(a['auth'])}" if a["auth"] != "n/a" else ""
        L.append(f"      <code>{e(a['host'])}</code> | Key: {a['key']} | {e(a['last_status'])}{extra}")

    from utils.panels import format_balances
    L += ["", format_balances(r.get("panels") or [])]

    lo, mo = d["local"], d["mongo"]
    L += ["", f"<b>{y(d['ok'])} Database</b>"]
    L.append(f"   Local DB: {y(lo['ok'])} integrity {e(str(lo['integrity']))}")
    if lo["counts"]:
        L.append("   Rows: " + ", ".join(f"{k} {v}" for k, v in lo["counts"].items()))
    L.append(f"   MongoDB: {e(mo['status'])} ({ms(mo['latency_ms'])})" + (f" | DB <code>{e(mo['db'])}</code>" if mo.get("db") else ""))
    L.append(f"   Sync: <b>{e(mo['sync'])}</b> | Last save: {_fmt_age(mo['last_sync'])} | Failures: {mo['failures']}"
             + (f" ({e(mo['last_error'])})" if mo.get("last_error") else ""))
    for t, v in mo.get("mismatch", {}).items():
        L.append(f"   ⚠️ {e(t)}: local {v['local']} vs MongoDB {v['mongo']}")

    L += ["", f"<b>{y(c['ok'])} Required config</b>"]
    L += [f"   {y(v['ok'])} {e(v['label'])} (<code>{v['name']}</code>)" for v in c["required"]]
    L += ["", "<b>Optional config</b>"]
    L += [f"   {'🟢' if v['ok'] else '⚪'} {e(v['label'])} (<code>{v['name']}</code>)" for v in c["optional"]]
    L += ["", "<i>Secret values are never shown — only set/missing.</i>"]
    return "\n".join(L)
