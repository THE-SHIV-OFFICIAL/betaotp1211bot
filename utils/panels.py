"""Supplier panel balances + low-balance alert for the owner.

Panels checked (only the configured ones):
  Hero SMS · TG-Lion · LZT Market · SMM panel (CheapestSMMPanels)

* /health shows the balance of every panel in ₹ (and the raw amount).
* A background task re-checks every PANEL_CHECK_INTERVAL seconds (default 600).
  If a panel has less than LOW_BALANCE_INR (default ₹50) the owner gets a DM
  alert (repeated at most every LOW_BALANCE_REPEAT seconds, default 6 h).

ENV (all optional)
  LOW_BALANCE_INR        alert threshold in rupees            (default 50)
  PANEL_CHECK_INTERVAL   seconds between checks               (default 600)
  LOW_BALANCE_REPEAT     seconds between repeated alerts      (default 21600)
  LZT_BALANCE_CURRENCY   usd | rub | inr  — currency of your LZT wallet (default usd)
  LZT_RUB_INR            ₹ per 1 RUB, only if LZT_BALANCE_CURRENCY=rub (default 1.0)
  TGLION_BALANCE_CURRENCY usd | inr                           (default usd)
"""
import asyncio
import html
import os
import time

from config import ADMIN_IDS, OWNER_ID, logger

LOW_BALANCE_INR = float(os.getenv("LOW_BALANCE_INR", "50") or 50)
CHECK_INTERVAL = int(os.getenv("PANEL_CHECK_INTERVAL", "600") or 600)
REPEAT_SECONDS = int(os.getenv("LOW_BALANCE_REPEAT", "21600") or 21600)
_last_alert = {}


def _rate():
    from database import get_usdt_rate
    return get_usdt_rate()


def _to_inr(amount, currency):
    """Convert a panel balance to ₹. None if the currency is unknown."""
    cur_ = (currency or "usd").strip().lower()
    amount = float(amount)
    if cur_ in ("inr", "rs", "₹"):
        return amount
    if cur_ in ("usd", "usdt", "$"):
        return amount * _rate()
    if cur_ in ("rub", "rur"):
        return amount * float(os.getenv("LZT_RUB_INR", "1.0") or 1.0)
    return None


def _fmt_raw(amount, currency):
    c = (currency or "usd").upper()
    return f"${float(amount):.2f}" if c in ("USD", "USDT") else f"{float(amount):.2f} {c}"


# ───────────── one fetcher per panel (each returns (amount, currency)) ─────────────
async def _hero():
    from plugins.herosms import get_balance
    return float(await get_balance()), "usd"


async def _tglion():
    from plugins.tglion import tl_call
    r = await tl_call(action="get_balance")
    return float(r.get("balance")), os.getenv("TGLION_BALANCE_CURRENCY", "usd")


async def _lzt():
    from plugins.lztmarket import lzt_balance
    bal, _hold = await lzt_balance()
    return float(bal), os.getenv("LZT_BALANCE_CURRENCY", "usd")


async def _smm():
    from plugins.smm import fansmm_request
    r = await fansmm_request({"action": "balance"})
    return float(r.get("balance")), str(r.get("currency") or "usd")


def _configured():
    """[(label, fetcher)] for the panels that have credentials set."""
    out = []
    try:
        from plugins.social import hero_enabled
        if hero_enabled():
            out.append(("Hero SMS", _hero))
    except Exception:
        pass
    if os.getenv("TGLION_API_KEY", "").strip():
        out.append(("TG-Lion", _tglion))
    if os.getenv("LZT_API_KEY", "").strip():
        out.append(("LZT Market", _lzt))
    if os.getenv("SMM_API_KEY") or os.getenv("CHEAPESTSMM_API_KEY"):
        out.append(("SMM panel", _smm))
    return out


async def _one(label, fn):
    res = {"label": label, "ok": False, "inr": None, "raw": "", "error": "", "low": False}
    try:
        amount, currency = await asyncio.wait_for(fn(), 25)
        res["raw"] = _fmt_raw(amount, currency)
        inr = _to_inr(amount, currency)
        if inr is None:
            res["error"] = f"unknown currency {currency}"
        else:
            res["ok"] = True
            res["inr"] = round(inr, 2)
            res["low"] = inr < LOW_BALANCE_INR
    except Exception as ex:
        res["error"] = type(ex).__name__ + (f": {str(ex)[:60]}" if str(ex) and "key" not in str(ex).lower() else "")
    return res


async def fetch_balances():
    """List of {label, ok, inr, raw, error, low} for every configured panel."""
    tasks = [_one(label, fn) for label, fn in _configured()]
    return list(await asyncio.gather(*tasks)) if tasks else []


def format_balances(rows):
    """HTML block for /health."""
    if not rows:
        return "<b>💰 Panel balances</b>\n   ⚪ No panel configured"
    L = [f"<b>💰 Panel balances</b> (alert below ₹{LOW_BALANCE_INR:g})"]
    for r in rows:
        if r["ok"]:
            flag = "🔴 LOW" if r["low"] else "🟢"
            L.append(f"   {flag} <b>{html.escape(r['label'])}:</b> ₹{r['inr']:,.2f}  <code>({html.escape(r['raw'])})</code>")
        else:
            L.append(f"   ⚠️ <b>{html.escape(r['label'])}:</b> balance unavailable — {html.escape(r['error'])}")
    return "\n".join(L)


# ───────────── owner alert ─────────────
def _owner_ids():
    return [OWNER_ID] if OWNER_ID else list(ADMIN_IDS)[:1]


async def check_and_alert(bot, rows=None, force=False):
    """DM the owner for every panel under the threshold. Returns the balance rows."""
    rows = rows if rows is not None else await fetch_balances()
    now = time.time()
    for r in rows:
        if not r["low"]:
            _last_alert.pop(r["label"], None)
            continue
        if not force and now - _last_alert.get(r["label"], 0) < REPEAT_SECONDS:
            continue
        _last_alert[r["label"]] = now
        text = (f"<blockquote>🚨 <b>Low Panel Balance!</b></blockquote>\n"
                f"<blockquote>🏷 <b>Panel:</b> {html.escape(r['label'])}\n"
                f"💰 <b>Balance:</b> ₹{r['inr']:,.2f} <code>({html.escape(r['raw'])})</code>\n"
                f"⚠️ Below ₹{LOW_BALANCE_INR:g} — recharge it now or orders from this panel will start failing.</blockquote>")
        for uid in _owner_ids():
            try:
                await bot.send_message(uid, text)
            except Exception as ex:
                logger.warning("low balance alert to %s failed: %s", uid, ex)
    return rows


async def _monitor(bot):
    await asyncio.sleep(30)
    while True:
        try:
            await check_and_alert(bot)
        except Exception as ex:
            logger.warning("panel balance monitor: %s", ex)
        await asyncio.sleep(max(60, CHECK_INTERVAL))


def start_monitor(bot):
    asyncio.ensure_future(_monitor(bot))
    logger.info("Panel balance monitor started (alert below ₹%g)", LOW_BALANCE_INR)
