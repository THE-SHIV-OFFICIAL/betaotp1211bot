"""Hero SMS number order lifecycle (WhatsApp S1/S2, all-apps numbers, Change TG No).

While a number waits for its OTP the user sees:

    💡 Tip: Use VPN while logging in for the first time.
    [📋 Copy No]  [🔄 Change No]
    [❌ Cancel]

"Change No" and "Cancel" are locked for the first 2 minutes (Hero SMS itself
refuses to cancel an activation earlier than that). After 2 minutes:

  * Change No -> current number is cancelled at Hero SMS and a fresh number for
                 the same country is issued. The user pays nothing extra.
  * Cancel    -> number cancelled, full price returned to the bot balance.

When the OTP arrives the user gets  [📋 Copy No] [📋 Copy Code]  and  [Back].

All state lives in the `number_orders` table, so buttons keep working and
waiting orders are resumed after a restart (see resume_waiting()).
"""
import asyncio
import html
import json
import os
import time
from telethon import events
from telethon.errors import MessageNotModifiedError
from database import cur, db
from config import P_INR, P_WARN, PE_CHECK, logger
from utils.keyboards import style_btn, copy_btn
from utils.states import get_user_lock

LOCK_SECONDS = int(os.getenv("NUM_CHANGE_LOCK_SECONDS", "120") or 120)   # Change No / Cancel timer
WAIT_SECONDS = 600                                                        # no OTP after 10 min -> auto refund
MAX_POLLS = 400                                                           # hard safety stop for the poll loop
VPN_TIP = "💡 <b>Tip:</b> Use VPN while logging in for the first time."
HERO_PLATFORMS = ("wa", "ig", "fb", "go", "tc")

_unlocked = set()   # order ids whose buttons were already unlocked in the chat
_pollers = set()    # order ids with a running poll loop
_locks = {}         # order id -> asyncio.Lock


def _S():
    from plugins import social
    return social


def _lock(oid):
    if oid not in _locks:
        _locks[oid] = asyncio.Lock()
    return _locks[oid]


_COLS = ("id", "user_id", "platform", "server", "activation_id", "phone", "price", "cost", "status", "started", "meta", "changes")


def load(oid):
    r = cur.execute("SELECT id, user_id, platform, server, activation_id, phone, price, cost, status, "
                    "COALESCE(started, CAST(strftime('%s', date) AS REAL)), meta, COALESCE(changes, 0) "
                    "FROM number_orders WHERE id=?", (oid,)).fetchone()
    if not r:
        return None
    o = dict(zip(_COLS, r))
    try:
        o["meta"] = json.loads(o["meta"] or "{}")
    except Exception:
        o["meta"] = {}
    o["phone"] = str(o["phone"] or "").lstrip("+")
    return o


def _save_meta(o):
    cur.execute("UPDATE number_orders SET meta=? WHERE id=?", (json.dumps(o["meta"]), o["id"]))
    db.commit()


def fmt_left(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def time_left(o):
    return LOCK_SECONDS - (time.time() - (o["started"] or time.time()))


# ───────────── rendering ─────────────
def _is_change(o):
    return o["platform"] == "tc"


def _header(o):
    S = _S()
    meta = o["meta"]
    country = html.escape(str(meta.get("cname") or ""))
    flag = S._flag_from_cc(meta.get("iso") or "")
    where = f" · {country} {flag}" if country else ""
    if _is_change(o):
        return f"🔄 <b>Change TG No · Server 3</b>{where}"
    em, name = S.ALL_CODES[o["platform"]]
    return f"{em} <b>{name} · {S.server_title(o['platform'], o['server'])}</b>{where}"


def waiting_text(o, locked):
    S = _S()
    phone = o["phone"]
    if _is_change(o):
        steps = ("1️⃣ In Telegram open <b>Settings → Change Number</b>\n"
                 "2️⃣ Enter this number\n3️⃣ The code arrives here automatically")
    else:
        name = S.ALL_CODES[o["platform"]][1]
        steps = f"1️⃣ Enter this number in {name}\n2️⃣ The OTP arrives here automatically"
    warn = f"\n\n{S.RISK_WARNING}" if (o["platform"], o["server"]) in S.RISKY else ""
    lock = (f"\n🔒 <b>Change No</b> / <b>Cancel</b> unlock in {fmt_left(time_left(o))} min"
            if locked else "\n🔓 <b>Change No</b> or <b>Cancel</b> available now")
    chg = f" · changed {o['changes']}x" if o["changes"] else ""
    return (f"<blockquote>{_header(o)}</blockquote>\n\n"
            f"<blockquote>📱 <code>+{phone}</code>\n{P_INR}{o['price']:g} paid{chg}\n\n{steps}\n"
            f"⏳ Waiting for {'code' if _is_change(o) else 'OTP'}… (10 min, else auto refund)\n\n"
            f"{VPN_TIP}{lock}{warn}</blockquote>")


def waiting_buttons(o, locked):
    S = _S()
    oid = o["id"]
    mark = " ⏳" if locked else ""
    return [[copy_btn("📋 Copy No", f"+{o['phone']}", "primary", S.ICON["type"]),
             style_btn(f"🔄 Change No{mark}", f"nf_chg|{oid}".encode(), "primary", S.ICON["buy"])],
            [style_btn(f"❌ Cancel{mark}", f"nf_can|{oid}".encode(), "danger", S.ICON["close"])]]


def back_target(o):
    if _is_change(o):
        from plugins.lztmarket import lzt_enabled
        return b"num_s|tg|3" if lzt_enabled() else b"num_p|tg"
    return f"num_p|{o['platform']}".encode()


def back_button(o):
    S = _S()
    return [style_btn("⬅️ Back", back_target(o), "danger", S.ICON["back"])]


async def _edit(bot, o, text, buttons=None):
    mid = (o["meta"] or {}).get("msg_id")
    if not mid:
        return
    try:
        await bot.edit_message(o["user_id"], mid, text, buttons=buttons)
    except MessageNotModifiedError:
        pass
    except Exception as ex:
        logger.debug("numflow edit failed: %s", ex)


# ───────────── start ─────────────
async def begin(bot, e, code, server, act_id, phone, price, cost_inr, meta):
    """Called right after a Hero SMS number was bought and paid. Shows the order
    screen and then polls for the OTP (returns when the order is finished)."""
    uid = e.sender_id
    cur.execute("INSERT INTO number_orders (user_id, platform, server, activation_id, phone, price, cost, status, started, meta) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (uid, code, server, act_id, phone, price, cost_inr, "waiting", time.time(), json.dumps(meta)))
    oid = cur.lastrowid
    db.commit()
    o = load(oid)
    msg = await e.edit(waiting_text(o, True), buttons=waiting_buttons(o, True))
    mid = getattr(msg, "id", None)
    if not isinstance(mid, int):
        mid = getattr(e, "message_id", None)
    if isinstance(mid, int):
        o["meta"]["msg_id"] = mid
        _save_meta(o)
    await run_poll(bot, oid)


# ───────────── finishing helpers (caller holds the order lock) ─────────────
async def _refund_cancel(bot, o, cancel_at_provider, text):
    """Atomically mark a waiting order cancelled, refund the user. False if it was not waiting."""
    from plugins.herosms import set_status
    cur.execute("UPDATE number_orders SET status='cancelled' WHERE id=? AND status='waiting'", (o["id"],))
    if cur.rowcount == 0:
        return False
    db.commit()
    if cancel_at_provider:
        try:
            await set_status(o["activation_id"], 8)
        except Exception:
            pass
    async with get_user_lock(o["user_id"]):
        cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (o["price"], o["user_id"]))
        db.commit()
    _unlocked.discard(o["id"])
    await _edit(bot, o, f"<blockquote>{_header(o)}</blockquote>\n\n<blockquote>{P_WARN} {text}</blockquote>",
                [back_button(o)])
    return True


async def _deliver(bot, o, otp):
    from plugins.herosms import set_status
    from plugins.profit import notify_profit
    from utils.delivery import send_delivery_thanks
    S = _S()
    cur.execute("UPDATE number_orders SET otp=?, status='done' WHERE id=? AND status='waiting'", (otp, o["id"]))
    if cur.rowcount == 0:
        return
    db.commit()
    try:
        await set_status(o["activation_id"], 6)
    except Exception:
        pass
    _unlocked.discard(o["id"])
    phone = o["phone"]
    chg = _is_change(o)
    await _edit(bot, o, f"<blockquote>{_header(o)}</blockquote>\n\n"
                        f"<blockquote>📱 <code>+{phone}</code>\n{PE_CHECK} {'Code' if chg else 'OTP'} received — see the message below 👇</blockquote>")
    await bot.send_message(
        o["user_id"],
        f"<blockquote>{PE_CHECK} <b>{'Login Code' if chg else 'OTP Received'}</b>\n📱 <code>+{phone}</code>\n🔢 <code>{html.escape(str(otp))}</code></blockquote>",
        buttons=[[copy_btn("📋 Copy No", f"+{phone}", "primary", S.ICON["type"]),
                  copy_btn("📋 Copy Code", str(otp), "success", S.ICON["type"])],
                 back_button(o)])
    await send_delivery_thanks(bot, o["user_id"], f"number:{o['id']}")
    meta = o["meta"]
    em, name = S.ALL_CODES[o["platform"]]
    title = "Server 3 · Change TG No" if chg else f"{name} · {S.server_title(o['platform'], o['server'])}"
    await notify_profit(o["user_id"], title, f"{meta.get('cname', '')} +{phone}", o["price"], o["cost"])
    if chg:
        srv = "3 · Change No"
        app = "Telegram Change No 🔄"
    else:
        t = S.server_title(o["platform"], o["server"])
        srv = t.split("·")[0].replace("Server", "").strip() + " · " + t.split("·")[-1].strip()
        app = f"{name} {em}"
    await S._sale_log(app, meta.get("cname", ""), S._flag_from_cc(meta.get("iso") or ""), phone, o["price"], srv)


# ───────────── polling ─────────────
async def run_poll(bot, oid):
    from plugins.herosms import get_status
    if oid in _pollers:
        return
    _pollers.add(oid)
    try:
        for _ in range(MAX_POLLS):
            await asyncio.sleep(5)
            o = load(oid)
            if not o or o["status"] != "waiting":
                return
            elapsed = time.time() - o["started"]
            if oid not in _unlocked and elapsed >= LOCK_SECONDS:
                _unlocked.add(oid)
                await _edit(bot, o, waiting_text(o, False), waiting_buttons(o, False))
            if elapsed > WAIT_SECONDS + 10:
                break
            try:
                res = await get_status(o["activation_id"])
            except Exception:
                continue
            async with _lock(oid):
                cur_o = load(oid)  # may have been changed / cancelled by the user meanwhile
                if not cur_o or cur_o["status"] != "waiting" or cur_o["activation_id"] != o["activation_id"]:
                    continue
                if res.startswith("STATUS_OK"):
                    await _deliver(bot, cur_o, res.split(":", 1)[1])
                    return
                if res.startswith("STATUS_CANCEL"):
                    await _refund_cancel(bot, cur_o, False, "Number was cancelled by the provider.")
                    await _notify_refund(bot, cur_o)
                    return
        async with _lock(oid):
            cur_o = load(oid)
            if cur_o and cur_o["status"] == "waiting":
                if await _refund_cancel(bot, cur_o, True, "No OTP received. Number cancelled and balance returned."):
                    await _notify_refund(bot, cur_o)
    finally:
        _pollers.discard(oid)
        _unlocked.discard(oid)
        _locks.pop(oid, None)


async def _notify_refund(bot, o):
    try:
        await bot.send_message(o["user_id"], f"<blockquote>{P_WARN} No OTP for +{o['phone']}. Number cancelled, "
                                             f"{P_INR}{o['price']:g} returned to your balance.</blockquote>")
    except Exception:
        pass


# ───────────── button handlers ─────────────
async def _check_cancellable(e, o):
    """Common guard for Change No / Cancel. Returns True if the action may go ahead."""
    if not o or o["user_id"] != e.sender_id:
        await e.answer("Order not found.", alert=True)
        return False
    if o["status"] != "waiting":
        await e.answer("This order is already finished.", alert=True)
        return False
    left = time_left(o)
    if left > 0:
        await e.answer(f"⏳ Available in {fmt_left(left)} min.\nYou can change / cancel the number after 2 minutes.", alert=True)
        return False
    return True


async def _provider_cancel(e, o):
    """Cancel the activation at Hero SMS. Returns True when it is cancelled."""
    from plugins.herosms import set_status, get_status
    try:
        res = await set_status(o["activation_id"], 8)
    except Exception:
        await e.answer("Server busy, try again in a moment.", alert=True)
        return False
    if res.startswith("ACCESS_CANCEL"):
        return True
    if "EARLY_CANCEL" in res:
        await e.answer("⏳ Provider allows cancel only after 2 minutes. Try again shortly.", alert=True)
        return False
    try:
        st = await get_status(o["activation_id"])
    except Exception:
        st = ""
    if st.startswith("STATUS_OK"):
        await e.answer("✅ Code already received — it is being delivered.", alert=True)
    else:
        await e.answer("Could not cancel right now. Try again in a moment.", alert=True)
    return False


async def on_cancel(bot, e, oid):
    async with _lock(oid):
        o = load(oid)
        if not await _check_cancellable(e, o):
            return
        if not await _provider_cancel(e, o):
            return
        if await _refund_cancel(bot, o, False, f"Order cancelled. {P_INR}{o['price']:g} returned to your balance."):
            await e.answer(f"✅ Cancelled — {P_INR}{o['price']:g} returned.", alert=True)


async def on_change(bot, e, oid):
    from plugins.herosms import get_number
    from database import get_usdt_rate
    S = _S()
    async with _lock(oid):
        o = load(oid)
        if not await _check_cancellable(e, o):
            return
        if not await _provider_cancel(e, o):
            return
        meta = o["meta"]
        svc = meta.get("svc") or ("tg" if o["platform"] == "tc" else o["platform"])
        try:
            d = await get_number(svc, meta.get("cid"), meta.get("max_usd"))
            act_id, phone = str(d["activationId"]), str(d["phoneNumber"]).lstrip("+")
            cost = round(float(d.get("activationCost", 0)) * get_usdt_rate(), 2) or o["cost"]
        except Exception as ex:
            logger.warning("numflow change number %s: %s", oid, ex)
            if await _refund_cancel(bot, o, False, f"No new number available. {P_INR}{o['price']:g} returned to your balance."):
                await e.answer("No new number available. Balance returned.", alert=True)
            return
        cur.execute("UPDATE number_orders SET activation_id=?, phone=?, cost=?, started=?, changes=changes+1 "
                    "WHERE id=? AND status='waiting'", (act_id, phone, cost, time.time(), oid))
        db.commit()
        _unlocked.discard(oid)
        o = load(oid)
        if not o["meta"].get("msg_id") and isinstance(getattr(e, "message_id", None), int):
            o["meta"]["msg_id"] = e.message_id
            _save_meta(o)
        try:
            await e.edit(waiting_text(o, True), buttons=waiting_buttons(o, True))
        except MessageNotModifiedError:
            pass
        await e.answer("✅ New number assigned.")
    if oid not in _pollers:   # poll loop ended meanwhile (e.g. after a restart) -> start again
        asyncio.create_task(run_poll(bot, oid))


# ───────────── startup ─────────────
async def resume_waiting(bot):
    """After a restart pick up orders that were still waiting (last 30 min) so the
    OTP is delivered or the money is refunded instead of staying stuck."""
    try:
        marks = ",".join("?" * len(HERO_PLATFORMS))
        rows = cur.execute(f"SELECT id FROM number_orders WHERE status='waiting' AND platform IN ({marks}) "
                           "AND date >= datetime('now','-30 minutes')", HERO_PLATFORMS).fetchall()
    except Exception as ex:
        logger.warning("numflow resume: %s", ex)
        return
    for (oid,) in rows:
        asyncio.create_task(run_poll(bot, oid))
    if rows:
        logger.info("numflow: resumed %d waiting number order(s)", len(rows))


def register_numflow(bot):
    @bot.on(events.CallbackQuery(pattern=rb"^nf_chg\|(\d+)$"))
    async def _chg(e):
        await on_change(bot, e, int(e.pattern_match.group(1)))

    @bot.on(events.CallbackQuery(pattern=rb"^nf_can\|(\d+)$"))
    async def _can(e):
        await on_cancel(bot, e, int(e.pattern_match.group(1)))

    asyncio.ensure_future(resume_waiting(bot))
    logger.info("Number flow (change / cancel) registered")
