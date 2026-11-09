"""LZT Market (https://lzt.market) — aged Telegram accounts for Telegram Server 3.

Flow: user picks a country -> bot buys the cheapest matching account from LZT
Market -> user logs in with the number -> taps "Get Code" -> bot fetches the
Telegram login code (+ 2FA password if the seller gave one).

ENV (set on your host, never in code):
  LZT_API_KEY        required  - API token from https://lolz.live/account/api (Market scope)
  LZT_API_URL        optional  - default https://api.lzt.market
  LZT_SEARCH_PARAMS  optional  - extra search filters, query-string style, to force
                                 "30+ days aged" accounts. Use /lztparams (admin) to see
                                 the filter names LZT offers, e.g.
                                 LZT_SEARCH_PARAMS="origin[]=self_registration&nsb=true"
  LZT_PAGES          optional  - search pages to scan for stock (default 3)

Admin: /lztbal  (LZT balance)   /lztparams  (available Telegram search filters)
"""
import asyncio
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from config import ADMIN_IDS, logger

LZT_PER_PAGE = 20
_cache = {"t": 0, "items": []}
lz_search_state = set()


# ───────────── API layer ─────────────
def lzt_enabled():
    return bool(os.getenv("LZT_API_KEY", "").strip())


def _base():
    return os.getenv("LZT_API_URL", "https://api.lzt.market").strip().rstrip("/")


def _request_sync(method, path, params=None, body=None):
    key = os.getenv("LZT_API_KEY", "").strip()
    if not key:
        raise Exception("LZT_API_KEY not configured")
    url = f"{_base()}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = urllib.parse.urlencode(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}", "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (BetaBot)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode(errors="ignore")
            status = r.status
    except urllib.error.HTTPError as ex:
        raw = ex.read().decode(errors="ignore")
        status = ex.code
    try:
        js = json.loads(raw) if raw.strip() else {}
    except Exception:
        js = {"raw": raw[:300]}
    return status, js


async def lzt_call(method, path, params=None, body=None):
    return await asyncio.to_thread(_request_sync, method, path, params, body)


def _err_text(js):
    if isinstance(js, dict):
        e = js.get("errors")
        if isinstance(e, list) and e:
            return "; ".join(str(x) for x in e)
        return str(js.get("error") or js.get("message") or js.get("raw") or js)[:200]
    return str(js)[:200]


def _extra_params():
    raw = os.getenv("LZT_SEARCH_PARAMS", "").strip().lstrip("?")
    return urllib.parse.parse_qsl(raw, keep_blank_values=True) if raw else []


async def lzt_balance():
    st, js = await lzt_call("GET", "/me")
    if st != 200:
        raise Exception(_err_text(js))
    u = js.get("user") or js
    return u.get("balance"), u.get("hold")


async def lzt_params():
    st, js = await lzt_call("GET", "/telegram/params")
    if st != 200:
        raise Exception(_err_text(js))
    return js


# ───────────── stock grouped by country ─────────────
def country_key(item):
    raw = str(item.get("telegram_country") or item.get("country") or "").strip()
    if len(raw) == 2 and raw.isalpha():
        return raw.upper(), raw.upper()
    if not raw:
        return "XX", "Unknown"
    return "x" + hashlib.md5(raw.lower().encode()).hexdigest()[:8], raw


async def lzt_stock(force=False):
    """List of items (cheapest first), cached 3 minutes."""
    if not force and _cache["items"] and time.time() - _cache["t"] < 180:
        return _cache["items"]
    pages = max(1, min(int(os.getenv("LZT_PAGES", "3") or 3), 10))
    items, seen = [], set()
    for page in range(1, pages + 1):
        params = [("order_by", "price_to_up"), ("currency", "usd"), ("page", page)] + _extra_params()
        st, js = await lzt_call("GET", "/telegram", params)
        if st != 200:
            if items:
                break
            raise Exception(_err_text(js))
        batch = js.get("items") or []
        for it in batch:
            iid = it.get("item_id")
            if iid and iid not in seen and float(it.get("price") or 0) > 0:
                seen.add(iid); items.append(it)
        if len(batch) < 20:
            break
    items.sort(key=lambda i: float(i["price"]))
    _cache.update(t=time.time(), items=items)
    return items


async def lzt_countries():
    """{key: {name, qty, price(usd), items:[...]}}"""
    out = {}
    for it in await lzt_stock():
        key, name = country_key(it)
        c = out.setdefault(key, {"name": name, "qty": 0, "price": float(it["price"]), "items": []})
        c["qty"] += 1
        c["items"].append(it)
    return out


def _drop_from_cache(item_id):
    _cache["items"] = [i for i in _cache["items"] if i.get("item_id") != item_id]


# ───────────── buy / code ─────────────
async def lzt_fast_buy(item_id, price):
    """Buys one item. Returns the purchased item dict; raises on failure."""
    last = "buy failed"
    for _ in range(5):  # LZT asks to repeat "retry_request" errors
        st, js = await lzt_call("POST", f"/{item_id}/fast-buy", {"currency": "usd"}, {"price": price})
        if st == 200 and (js.get("item") or js.get("status") == "ok"):
            return js.get("item") or js
        last = _err_text(js)
        if "retry_request" in json.dumps(js):
            await asyncio.sleep(1.5)
            continue
        break
    raise Exception(last)


async def lzt_get_item(item_id):
    st, js = await lzt_call("GET", f"/{item_id}", {"currency": "usd"})
    if st != 200:
        raise Exception(_err_text(js))
    return js.get("item") or js


def item_login_info(item):
    """(phone, 2fa/password) from a purchased item, best effort."""
    ld = item.get("loginData") or {}
    phone = str(item.get("telegram_phone") or ld.get("login") or "").replace(" ", "")
    pw = ld.get("password") or item.get("telegram_password_value") or ""
    if isinstance(pw, bool):
        pw = ""
    if phone and phone.lstrip("+").isdigit() and not phone.startswith("+"):
        phone = "+" + phone
    return phone, str(pw or "")


def _find_code(js):
    if not isinstance(js, dict):
        return None
    c = js.get("code")
    if isinstance(c, (str, int)) and str(c).strip():
        return str(c).strip()
    codes = js.get("codes")
    if isinstance(codes, list) and codes:
        newest = max((x for x in codes if isinstance(x, dict) and x.get("code")),
                     key=lambda x: x.get("date") or 0, default=None)
        if newest:
            return str(newest["code"])
        if isinstance(codes[0], (str, int)):
            return str(codes[0])
    return None


async def lzt_login_code(item_id):
    st, js = await lzt_call("GET", f"/{item_id}/telegram-login-code")
    if st != 200:
        return None
    return _find_code(js)


# ───────────── UI ─────────────
def _S():
    from plugins import social
    return social


def _sell(usd):
    """(sell_inr, cost_inr) for an LZT price in USD, using Server 3 profit rules."""
    sell, cost, _ = _S().gz_offer("tg", 3, usd)
    return sell, cost


def _buttons(items):
    S = _S()
    btns, row = [], []
    for key, c in items:
        sell, _ = _sell(c["price"])
        flag = S._flag_from_cc(key) if len(key) == 2 else "🌍"
        icon = S.premium_flag_id(flag) or S.premium_flag_id(S.get_plain_flag_by_country_name(c["name"]))
        label = f"{c['name']} {S.P_INR}{sell}" if icon else f"{flag} {c['name']} {S.P_INR}{sell}"
        row.append(S.style_btn(label, f"lz_c|{key}".encode(), "primary", icon))
        if len(row) == 2:
            btns.append(row); row = []
    if row: btns.append(row)
    return btns


async def _sorted():
    cs = await lzt_countries()
    return sorted(cs.items(), key=lambda kv: kv[1]["price"])


def _change_row(S):
    """'Change TG No' (Hero SMS Telegram number) button shown on Server 3, or [] if Hero SMS is off."""
    if not S.hero_enabled():
        return []
    return [[S.style_btn("🔄 Change TG No", b"gz_l|tc|3|1", "success", S.premium_service_id("🔄", S.ICON["buy"]))]]


async def lz_show_list(e, page=1):
    S = _S()
    import math
    items, err = [], None
    try:
        items = await _sorted()
    except Exception as ex:
        logger.warning("lzt: %s", ex)
        err = ex
    change = _change_row(S)
    if not items:
        if not change:
            return await e.answer("Server 3 is busy, try again." if err else "No accounts in stock right now.", alert=True)
        # aged accounts unavailable right now -> Server 3 still offers Change TG No
        btns = change + [[S.style_btn("Back", b"num_p|tg", "danger", S.ICON["back"])]]
        return await S._edit_or_send(
            e, "<blockquote>🗓 <b>Server 3</b></blockquote>\n\n"
               f"<blockquote>{S.P_WARN} Aged accounts are not available right now.\n"
               "🔄 You can still buy a number to <b>change the phone number</b> of your Telegram account.</blockquote>\n"
               f"<blockquote>{S.VPN_TIP}</blockquote>", btns)
    pages = max(1, math.ceil(len(items) / LZT_PER_PAGE))
    page = max(1, min(page, pages))
    btns = _buttons(items[(page - 1) * LZT_PER_PAGE: page * LZT_PER_PAGE])
    nav = []
    if page > 1: nav.append(S.style_btn("Prev", f"lz_pg|{page-1}".encode(), "primary", 6129627894349045589))
    if page < pages: nav.append(S.style_btn("Next", f"lz_pg|{page+1}".encode(), "primary", 6129732880529628243))
    if nav: btns.append(nav)
    btns += change
    btns.append([S.style_btn("🔍 Search Country", b"lz_search", "success", S.premium_service_id("🔍", S.ICON["type"]))])
    btns.append([S.style_btn("Back", b"num_p|tg", "danger", S.ICON["back"])])
    tip = "\n🔄 <b>Change TG No</b> — buy a number to change the phone number of your Telegram account." if change else ""
    await S._edit_or_send(
        e, f"<blockquote>🗓 <b>Server 3 · 30+ Days Aged Account</b> (Page {page}/{pages})</blockquote>\n\n"
           f"<blockquote>{S.PE_LIGHTNING} Aged accounts (1 month+ holding) — ideal for bulk botting / OTP panels. "
           f"Pick a country → log in on Telegram → tap <b>Get Code</b>.{tip}</blockquote>\n"
           f"<blockquote>{S.VPN_TIP}</blockquote>", btns)


async def lz_search(e, query):
    S = _S()
    q = query.strip().lower().lstrip("+")
    res = []
    for key, c in await _sorted():
        name = str(c["name"]).lower()
        if (q.isdigit() and len(key) == 2 and S._dial_code(key) == q) or q == key.lower() or (len(q) >= 2 and q in name):
            res.append((key, c))
    btns = _buttons(res[:40])
    btns.append([S.style_btn("🔍 Search Again", b"lz_search", "success", S.premium_service_id("🔍", S.ICON["type"]))])
    btns.append([S.style_btn("Back", b"lz_list", "danger", S.ICON["back"])])
    head = f"<blockquote>🔍 <b>Results for:</b> <code>{S.html.escape(query)}</code> ({len(res)})</blockquote>"
    if not res: head += "\n\n<blockquote>No country found. Try a name (India), code (IN) or dial code (+91).</blockquote>"
    await e.respond(head, buttons=btns)


async def lz_buy_flow(e, key):
    S = _S()
    from plugins.profit import notify_profit
    uid = e.sender_id
    cs = await lzt_countries()
    c = cs.get(key)
    if not c: return await e.answer("Out of stock for this country.", alert=True)
    price, _ = _sell(c["items"][0]["price"])
    async with S.get_user_lock(uid):
        S.cur.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?", (price, uid, price))
        if S.cur.rowcount == 0:
            from plugins.deposit import pay_for_item
            return await pay_for_item(e, price, f"Buy Telegram Acc · {c['name']} {S.P_INR}{price}")
        S.db.commit()
    bought, cost = None, 0
    for it in c["items"][:4]:
        sell_i, cost_i = _sell(it["price"])
        if sell_i > price:  # never charge more than the user already paid
            continue
        try:
            bought = await lzt_fast_buy(it["item_id"], it["price"])
            bought.setdefault("item_id", it["item_id"])
            cost = cost_i
            _drop_from_cache(it["item_id"])
            break
        except Exception as ex:
            logger.warning("lzt fast-buy %s: %s", it.get("item_id"), ex)
            _drop_from_cache(it["item_id"])
    if not bought:
        async with S.get_user_lock(uid):
            S.cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (price, uid)); S.db.commit()
        return await e.answer("No account available right now. Balance returned.", alert=True)
    item_id = str(bought.get("item_id"))
    phone, pw = item_login_info(bought)
    if not phone:
        try:
            phone, pw2 = item_login_info(await lzt_get_item(item_id))
            pw = pw or pw2
        except Exception as ex:
            logger.warning("lzt get item %s: %s", item_id, ex)
    S.cur.execute("INSERT INTO number_orders (user_id, platform, server, activation_id, phone, price, cost, status) VALUES (?,?,?,?,?,?,?,?)",
                  (uid, "tg", 3, item_id, (phone or "").lstrip("+"), price, cost, "waiting")); S.db.commit()
    pwline = f"\n🔐 2FA / Password: <code>{S.html.escape(pw)}</code>" if pw else ""
    await e.edit(f"<blockquote>🗓 <b>Aged Telegram Account</b> · {S.html.escape(c['name'])}</blockquote>\n\n"
                 f"<blockquote>📱 <code>{phone or 'see Get Code'}</code>{pwline}\n{S.P_INR}{price} paid\n\n"
                 f"1️⃣ Enter this number in Telegram\n2️⃣ Tap <b>Get Code</b> below</blockquote>",
                 buttons=[[S.copy_btn("📋 Copy Number", phone, "primary", S.ICON["type"]),
                           S.style_btn("🔢 Get Code", f"lz_g|{item_id}".encode(), "success", S.ICON["buy"])]]
                 if phone else [[S.style_btn("🔢 Get Code", f"lz_g|{item_id}".encode(), "success", S.ICON["buy"])]])
    shown = phone or f"item {item_id}"
    await notify_profit(uid, "Server 3 · Aged Telegram", shown, price, cost)
    await S._sale_log("Telegram ✈️", c["name"], S._flag_from_cc(key) if len(key) == 2 else "🌍", shown, price, "3 · Aged")


async def lz_get_code(e, item_id):
    S = _S()
    row = S.cur.execute("SELECT id, phone FROM number_orders WHERE activation_id=? AND user_id=? AND server=3 AND platform='tg'",
                        (item_id, e.sender_id)).fetchone()
    if not row: return await e.answer("Order not found.", alert=True)
    try:
        code = await lzt_login_code(item_id)
    except Exception:
        code = None
    if not code:
        return await e.answer("⏳ Code not received yet. Send the code in Telegram first, then tap again.", alert=True)
    S.cur.execute("UPDATE number_orders SET otp=?, status='done' WHERE id=?", (code, row[0])); S.db.commit()
    shown = ("+" + row[1].lstrip("+")) if row[1] else f"item {item_id}"
    rows = [[S.copy_btn("📋 Copy Code", code, "primary", S.ICON["type"])]]
    if row[1]:
        rows[0].insert(0, S.copy_btn("📋 Copy Number", shown, "primary", S.ICON["type"]))
    rows.append([S.style_btn("🔄 Get Again", f"lz_g|{item_id}".encode(), "success", S.ICON["buy"])])
    await e.edit(f"<blockquote>{S.PE_CHECK} <b>Login Code</b>\n📱 <code>{shown}</code>\n🔢 <code>{code}</code></blockquote>", buttons=rows)
    from config import bot
    await S.send_delivery_thanks(bot, e.sender_id, f"number:{row[0]}")


async def lz_price_lines():
    S = _S()
    lines = []
    for key, c in sorted((await lzt_countries()).items(), key=lambda kv: kv[1]["name"].lower()):
        sell, _ = _sell(c["price"])
        flag = S._flag_from_cc(key) if len(key) == 2 else "🌍"
        lines.append(f"{flag} <b>{S.html.escape(c['name'])}</b> — {S.P_INR}{sell} · {c['qty']} available")
    return lines or ["No accounts are currently in stock on this server."]


async def lz_lowest_price():
    cs = await lzt_countries()
    return min(_sell(c["price"])[0] for c in cs.values())


def register_lzt(bot):
    from telethon import events
    S = _S()

    @bot.on(events.NewMessage(pattern=r"^/lztbal$"))
    async def _bal(e):
        if e.sender_id not in ADMIN_IDS: return
        try:
            bal, hold = await lzt_balance()
            await e.reply(f"🗓 LZT Market balance: <b>{bal}</b> (hold: {hold})")
        except Exception as ex:
            await e.reply(f"⚠️ {ex}")

    @bot.on(events.NewMessage(pattern=r"^/lztparams$"))
    async def _params(e):
        if e.sender_id not in ADMIN_IDS: return
        try:
            js = await lzt_params()
            txt = json.dumps(js, ensure_ascii=False)[:3500]
            await e.reply("<b>LZT Telegram filters</b> — put the ones you need in <code>LZT_SEARCH_PARAMS</code> "
                          f"(e.g. <code>origin[]=self_registration</code>):\n\n<code>{S.html.escape(txt)}</code>")
        except Exception as ex:
            await e.reply(f"⚠️ {ex}")

    @bot.on(events.CallbackQuery(pattern=b"^lz_list$"))
    async def _list(e):
        lz_search_state.discard(e.sender_id)
        from utils.helpers import require_join
        if not await require_join(bot, e): return
        if not lzt_enabled():
            return await e.answer("This server is unavailable right now.", alert=True)
        await lz_show_list(e)

    @bot.on(events.CallbackQuery(pattern=rb"^lz_pg\|(\d+)$"))
    async def _pg(e):
        await lz_show_list(e, int(e.pattern_match.group(1)))

    @bot.on(events.CallbackQuery(pattern=b"^lz_search$"))
    async def _search(e):
        lz_search_state.add(e.sender_id)
        await e.answer()
        await e.respond("<blockquote>🔍 <b>𝐒ᴇᴀʀᴄʜ 𝐂ᴏᴜɴᴛʀʏ</b></blockquote>\n\n"
                        "<blockquote>𝐒ᴇɴᴅ ᴄᴏᴜɴᴛʀʏ <b>ɴᴀᴍᴇ</b> (India), <b>2-ʟᴇᴛᴛᴇʀ ᴄᴏᴅᴇ</b> (IN) ᴏʀ <b>ᴅɪᴀʟ ᴄᴏᴅᴇ</b> (+91).</blockquote>",
                        buttons=[[S.style_btn("❌ Cancel", b"lz_list", "danger", S.ICON["back"])]])

    @bot.on(events.NewMessage(func=lambda e: e.is_private and e.sender_id in lz_search_state and not (e.text or "").startswith("/")))
    async def _query(e):
        lz_search_state.discard(e.sender_id)
        try:
            await lz_search(e, e.text or "")
        except Exception as ex:
            logger.warning("lzt search: %s", ex)
            await e.respond("Server 3 is busy, try again.")

    @bot.on(events.CallbackQuery(pattern=rb"^lz_c\|([A-Za-z0-9]{2,12})$"))
    async def _buy(e):
        from utils.helpers import require_join
        if not await require_join(bot, e): return
        if not lzt_enabled():
            return await e.answer("This server is unavailable right now.", alert=True)
        await lz_buy_flow(e, e.pattern_match.group(1).decode())

    @bot.on(events.CallbackQuery(pattern=rb"^lz_g\|(\d+)$"))
    async def _code(e):
        await lz_get_code(e, e.pattern_match.group(1).decode())

    logger.info("LZT Market registered")
