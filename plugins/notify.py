"""'New Country Added!' notifications for Telegram & WhatsApp stock.

Every NOTIFY_INTERVAL seconds the bot looks at the country lists of

    Telegram  Server 1 (your own stock) · Server 2 (TG-Lion) · Server 3 (LZT aged)
    WhatsApp  Server 1 / Server 2 (Hero SMS)

and when a country shows up that was not there before, every subscribed user
gets:

    ❗ New Country Added!
    🌐 Country: 🇲🇷 Mauritania
    📦 Stock: 3 accounts
    💰 Price: ₹109.5
    ✈️ Service: Telegram · Server 1
    Grab it before it runs out!
    [ Buy Now ]
    [ 🔕 Turn Off Notifications ]

The first scan of a source only remembers what already exists (no alert storm).
A country that goes out of stock and comes back is announced again only after
NOTIFY_COOLDOWN seconds (default 6 h).

Users: /notify toggles alerts · Settings → "New Country Alerts".
Admin: /testnotify sends a sample alert to yourself.

ENV (all optional)
  NOTIFY_ENABLED=1        master switch
  NOTIFY_DEFAULT=1        1 = everybody gets alerts until they turn them off
                          0 = only users who turned them ON get alerts
  NOTIFY_INTERVAL=120     seconds between scans
  NOTIFY_COOLDOWN=21600   re-announce delay for a country that left and came back
  NOTIFY_MAX_PER_SCAN=5   safety cap of alerts per scan
"""
import asyncio
import html
import os
import time
from telethon import events
from telethon.errors import (FloodWaitError, InputUserDeactivatedError, MessageNotModifiedError,
                             PeerIdInvalidError, UserIsBlockedError)
from database import cur, db, get_plain_flag_by_country_name
from config import ADMIN_IDS, P_INR, logger
from utils.keyboards import style_btn

ENABLED = os.getenv("NOTIFY_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
DEFAULT_ON = os.getenv("NOTIFY_DEFAULT", "1").strip().lower() not in {"0", "false", "no", "off"}
INTERVAL = max(30, int(os.getenv("NOTIFY_INTERVAL", "120") or 120))
COOLDOWN = int(os.getenv("NOTIFY_COOLDOWN", "21600") or 21600)
MAX_PER_SCAN = max(1, int(os.getenv("NOTIFY_MAX_PER_SCAN", "5") or 5))
BUY_ICON = 5440627033111557670


def _S():
    from plugins import social
    return social


# ───────────── user preference ─────────────
def is_enabled(uid):
    r = cur.execute("SELECT enabled FROM notif_users WHERE user_id=?", (uid,)).fetchone()
    return DEFAULT_ON if r is None else bool(r[0])


def set_pref(uid, on):
    cur.execute("INSERT OR REPLACE INTO notif_users (user_id, enabled) VALUES (?,?)", (uid, 1 if on else 0))
    db.commit()


def toggle_pref(uid):
    new = not is_enabled(uid)
    set_pref(uid, new)
    return new


def toggle_label(on):
    return "🔕 Turn Off Notifications" if on else "🔔 Turn On Notifications"


def alert_buttons(buy_cb, on):
    return [[style_btn("🛒 Buy Now", buy_cb, "success", BUY_ICON)],
            [style_btn(toggle_label(on), b"nt_tgl", None, 6129399728506412489)]]


def alert_text(it):
    return (f"<blockquote>❗ <b>New Country Added!</b></blockquote>\n"
            f"<blockquote>🌐 <b>Country:</b> {it['flag']} {html.escape(str(it['country']))}\n"
            f"📦 <b>Stock:</b> {it['stock']} accounts\n"
            f"💰 <b>Price:</b> {P_INR}{it['price']:g}\n"
            f"{it['em']} <b>Service:</b> {it['service']} · Server {it['server']}</blockquote>\n"
            f"<i>Grab it before it runs out!</i>")


# ───────────── stock snapshots: {key: item} per source ─────────────
def _item(service, em, server, country, flag, stock, price, cb):
    cb = cb if isinstance(cb, bytes) else cb.encode()
    if len(cb) > 64:   # Telegram callback-data limit -> open the server list instead
        cb = f"num_p|{'tg' if service == 'Telegram' else 'wa'}".encode()
    return {"service": service, "em": em, "server": server, "country": country, "flag": flag_or_globe(flag),
            "stock": int(stock), "price": float(price), "cb": cb}


def flag_or_globe(flag):
    return flag or "🌍"


async def _snap_tg1():
    rows = cur.execute("SELECT country_name, COUNT(*), MIN(price) FROM stock "
                       "WHERE available=1 AND country_name IS NOT NULL GROUP BY country_name").fetchall()
    return {f"tg|1|{n}": _item("Telegram", "✈️", 1, n, get_plain_flag_by_country_name(n), c, p, f"bc|single|{n}")
            for n, c, p in rows}


async def _snap_tg2():
    if not os.getenv("TGLION_API_KEY", "").strip():
        return None
    S = _S()
    from plugins.tglion import tl_countries, tl_sell_price
    out = {}
    for cc, v in (await tl_countries()).items():
        out[f"tg|2|{cc.upper()}"] = _item("Telegram", "✈️", 2, v.get("name") or cc, S._flag_from_cc(cc),
                                          v.get("qty") or 0, tl_sell_price(v["price"])[0], f"tl_c|{cc}")
    return out


async def _snap_tg3():
    from plugins.lztmarket import lzt_enabled, lzt_countries, _sell
    if not lzt_enabled():
        return None
    S = _S()
    out = {}
    for key, c in (await lzt_countries()).items():
        flag = S._flag_from_cc(key) if len(key) == 2 else "🌍"
        out[f"tg|3|{key}"] = _item("Telegram", "✈️", 3, c["name"], flag, c["qty"], _sell(c["price"])[0], f"lz_c|{key}")
    return out


def _snap_wa(server):
    async def run():
        S = _S()
        if not S.hero_enabled():
            return None
        out = {}
        for r in await S.gz_rows("wa", server):
            stock = r[5] if server == 1 else r[4]
            out[f"wa|{server}|{r[0]}"] = _item("WhatsApp", "💬", server, r[1], S._flag_from_cc(r[2]), stock,
                                                S.gz_offer("wa", server, r[3])[0], f"gz_c|wa|{server}|{r[0]}")
        return out
    return run


SOURCES = {"tg|1": _snap_tg1, "tg|2": _snap_tg2, "tg|3": _snap_tg3, "wa|1": _snap_wa(1), "wa|2": _snap_wa(2)}


def _setting(key):
    r = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else None


def diff_source(src, snap, now=None):
    """Update notif_seen for one source and return the items that are NEW (should be announced)."""
    now = now or time.time()
    seed_key = f"notif_seeded_{src}"
    first_scan = _setting(seed_key) is None
    new_items = []
    for key, it in snap.items():
        if it["stock"] <= 0:
            continue
        row = cur.execute("SELECT present, last_notified FROM notif_seen WHERE key=?", (key,)).fetchone()
        if row is None:
            cur.execute("INSERT INTO notif_seen (key, present, last_notified) VALUES (?,1,?)", (key, now))
            if not first_scan:
                new_items.append(it)
        elif not row[0]:
            cur.execute("UPDATE notif_seen SET present=1 WHERE key=?", (key,))
            if now - (row[1] or 0) > COOLDOWN:
                cur.execute("UPDATE notif_seen SET last_notified=? WHERE key=?", (now, key))
                new_items.append(it)
    # countries that left stock
    live = {k for k, it in snap.items() if it["stock"] > 0}
    n = len(src) + 1
    for (key,) in cur.execute("SELECT key FROM notif_seen WHERE present=1 AND substr(key,1,?)=?", (n, src + "|")).fetchall():
        if key not in live:
            cur.execute("UPDATE notif_seen SET present=0 WHERE key=?", (key,))
    if first_scan:
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (seed_key, "1"))
    db.commit()
    return new_items


def recipients():
    return [r[0] for r in cur.execute(
        "SELECT u.user_id FROM users u LEFT JOIN notif_users n ON n.user_id=u.user_id "
        "WHERE COALESCE(u.banned,0)=0 AND COALESCE(u.terms_accepted,0)=1 AND COALESCE(n.enabled, ?)=1",
        (1 if DEFAULT_ON else 0,)).fetchall()]


async def broadcast(bot, it, users=None):
    """Send one 'New Country Added!' alert. Returns number of users reached."""
    users = recipients() if users is None else users
    text = alert_text(it)
    sent = 0
    for uid in users:
        try:
            await bot.send_message(uid, text, buttons=alert_buttons(it["cb"], True))
            sent += 1
        except FloodWaitError as ex:
            await asyncio.sleep(ex.seconds + 1)
            try:
                await bot.send_message(uid, text, buttons=alert_buttons(it["cb"], True))
                sent += 1
            except Exception:
                pass
        except (UserIsBlockedError, InputUserDeactivatedError, PeerIdInvalidError):
            set_pref(uid, False)   # blocked the bot -> stop trying
        except Exception as ex:
            logger.debug("notify to %s failed: %s", uid, ex)
        await asyncio.sleep(0.06)   # ~16 msgs/s, below Telegram's broadcast limit
    return sent


async def scan_once(bot):
    announced = []
    for src, fn in SOURCES.items():
        try:
            snap = await fn()
        except Exception as ex:
            logger.debug("notify snapshot %s: %s", src, ex)
            continue
        if snap is None:
            continue
        announced += diff_source(src, snap)
    for it in announced[:MAX_PER_SCAN]:
        n = await broadcast(bot, it)
        logger.info("new country alert %s %s S%s -> %d users", it["service"], it["country"], it["server"], n)
    return announced


async def _loop(bot):
    await asyncio.sleep(45)
    while True:
        try:
            await scan_once(bot)
        except Exception as ex:
            logger.warning("notify scan: %s", ex)
        await asyncio.sleep(INTERVAL)


def register_notify(bot):
    @bot.on(events.NewMessage(pattern=r"(?i)^/notify(?:@\w+)?$"))
    async def _cmd(e):
        on = toggle_pref(e.sender_id)
        await e.respond("<blockquote>🔔 <b>New Country Alerts: ON</b>\nYou will be told when a new country is added.</blockquote>" if on else
                        "<blockquote>🔕 <b>New Country Alerts: OFF</b>\nSend /notify again to turn them back on.</blockquote>")

    @bot.on(events.NewMessage(pattern=r"(?i)^/testnotify(?:@\w+)?$"))
    async def _test(e):
        if e.sender_id not in ADMIN_IDS:
            return
        it = _item("Telegram", "✈️", 1, "Mauritania", "🇲🇷", 3, 109.5, "num_p|tg")
        await bot.send_message(e.sender_id, alert_text(it), buttons=alert_buttons(it["cb"], is_enabled(e.sender_id)))

    @bot.on(events.CallbackQuery(pattern=b"^nt_tgl$"))
    async def _toggle(e):
        on = toggle_pref(e.sender_id)
        await e.answer("🔔 Notifications ON" if on else "🔕 Notifications OFF")
        try:
            m = await e.get_message()
            buy_cb = m.buttons[0][0].data
            await e.edit(buttons=alert_buttons(buy_cb, on))
        except MessageNotModifiedError:
            pass
        except Exception as ex:
            logger.debug("notify toggle edit: %s", ex)

    if ENABLED:
        asyncio.ensure_future(_loop(bot))
        logger.info("New-country notifications started (every %ss)", INTERVAL)
