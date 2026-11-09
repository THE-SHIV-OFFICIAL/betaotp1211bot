import re
import os
import aiohttp
import asyncio
import html
from telethon import events, Button
from telethon.errors import MessageNotModifiedError
from database import cur, db
from config import PE_LIGHTNING, PE_CHECK, PE_GIFT, P_MONEY, P_INR, P_NO, P_YES, P_WARN, P_CART, P_STATS, bot, logger
from utils.keyboards import style_btn
from utils.states import get_user_lock

# SMM panel: https://cheapestsmmpanels.com (standard API v2)
SMM_URL = os.getenv("SMM_API_URL", "https://cheapestsmmpanels.com/api/v2")
FANSMM_URL = SMM_URL  # backward compat

def get_api_key():
    return os.getenv("SMM_API_KEY") or os.getenv("CHEAPESTSMM_API_KEY") or ""

_svc_cache = {"t": 0, "data": []}

async def panel_services(force=False):
    """Full service list from the panel (cached 10 min)."""
    import time
    if force or time.time() - _svc_cache["t"] > 600 or not _svc_cache["data"]:
        data = await fansmm_request({"action": "services"})
        if isinstance(data, list):
            _svc_cache.update(t=time.time(), data=data)
    return _svc_cache["data"]

async def panel_rate(service_id):
    for x in await panel_services():
        if str(x.get("service")) == str(service_id):
            return float(x.get("rate", 0))
    return None

async def fansmm_request(params: dict):
    """POST to the SMM panel API (CheapestSMMPanels)."""
    api_key = get_api_key()
    if not api_key:
        raise Exception("SMM_API_KEY not configured")
    params["key"] = api_key
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SMM_URL, data=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                return await resp.json(content_type=None)
    except Exception as e:
        logger.error(f"SMM panel API error: {e}")
        raise

# ── Category browsing ──

smm_request = fansmm_request

async def show_smm_categories(event):
    rows = cur.execute("SELECT DISTINCT category FROM smm_services WHERE available=1 AND trim(coalesce(fansmm_service_id,''))<>'' ORDER BY category").fetchall()
    if not rows:
        msg = (f"<blockquote>📊 <b>𝐒𝐌𝐌 𝐒ᴇʀᴠɪᴄᴇs</b></blockquote>\n\n"
               f"<blockquote>{P_WARN} 𝐍ᴏ sᴇʀᴠɪᴄᴇs ᴀᴠᴀɪʟᴀʙʟᴇ ʏᴇᴛ. 𝐂ʜᴇᴄᴋ ʙᴀᴄᴋ ʟᴀᴛᴇʀ!</blockquote>")
        if isinstance(event, events.CallbackQuery.Event):
            try: return await event.edit(msg)
            except MessageNotModifiedError: pass
        else: return await event.respond(msg)
        return

    btns = []
    for (cat,) in rows:
        count = cur.execute("SELECT COUNT(*) FROM smm_services WHERE category=? AND available=1", (cat,)).fetchone()[0]
        btns.append([style_btn(f"📌 {cat} ({count})", f"smm_cat|{cat}", "primary", icon=5409098988156629257)])

    msg = (f"<blockquote>📊 <b>𝐒𝐌𝐌 𝐒ᴇʀᴠɪᴄᴇs</b>\n\n"
           f"⚡ 𝐈ɴsᴛᴀɴᴛ ᴅᴇʟɪᴠᴇʀʏ | 🔒 𝐒ᴀғᴇ & 𝐑ᴇʟɪᴀʙʟᴇ\n\n"
           f"𝐒ᴇʟᴇᴄᴛ ᴀ ᴄᴀᴛᴇɢᴏʀʏ ʙᴇʟᴏᴡ:</blockquote>")

    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass
    else:
        await event.respond(msg, buttons=btns)

async def show_smm_services(event, category):
    rows = cur.execute(
        "SELECT id, name, min_qty, max_qty, price_per_1000 FROM smm_services WHERE category=? AND available=1 ORDER BY id",
        (category,)
    ).fetchall()
    if not rows:
        return await event.answer("No services in this category.", alert=True)

    btns = []
    for sid, name, min_q, max_q, price in rows:
        cost_min = round(min_q * price / 1000, 2)
        btns.append([style_btn(f"⚡ {name[:35]} — {P_INR}{price}/1K", f"smm_svc|{sid}", "primary", icon=5409271925014801629)])
    btns.append([style_btn("🔙 𝐁ᴀᴄᴋ", b"smm_cats", "danger", icon=6129812419028982717)])

    msg = f"<blockquote>📌 <b>{category}</b>\n\n𝐒ᴇʟᴇᴄᴛ ᴀ sᴇʀᴠɪᴄᴇ:</blockquote>"
    try: await event.edit(msg, buttons=btns)
    except MessageNotModifiedError: pass

def _back_for(cat):
    if "•" in cat:
        plat, typ = [x.strip() for x in cat.split("•", 1)]
        return f"soc_t|{plat.lower()}|{typ}"
    return f"smm_cat|{cat}"

async def show_smm_service_detail(event, svc_id):
    try: await sync_limits(svc_id)
    except Exception: pass
    row = cur.execute(
        "SELECT id, name, category, min_qty, max_qty, price_per_1000, description FROM smm_services WHERE id=? AND available=1",
        (svc_id,)
    ).fetchone()
    if not row:
        return await event.answer("Service not found.", alert=True)
    sid, name, cat, min_q, max_q, price, desc = row
    import html as _h
    from utils.svcinfo import service_info_lines
    pid = cur.execute("SELECT fansmm_service_id FROM smm_services WHERE id=?", (sid,)).fetchone()
    try: panel = await panel_service(pid[0]) if pid and (pid[0] or "").strip() else None
    except Exception: panel = None
    raw_name = _h.unescape(str(name or ""))
    raw_desc = _h.unescape(str(desc or "")).strip()
    info = "\n".join(service_info_lines(raw_name, raw_desc, panel))
    per_unit = round(float(price) / 1000, 3)
    msg = (f"<blockquote>⚡ <b>{_h.escape(raw_name)}</b>\n\n"
           f"📌 <b>𝐂ᴀᴛᴇɢᴏʀʏ:</b> {_h.escape(str(cat))}\n"
           f"{P_MONEY} <b>𝐏ʀɪᴄᴇ:</b> {P_INR}{price} / 1000 ({P_INR}{per_unit:g} ᴇᴀᴄʜ)\n"
           f"📉 <b>𝐌ɪɴ:</b> {min_q} | 📈 <b>𝐌ᴀx:</b> {max_q}</blockquote>\n\n"
           f"<blockquote>📋 <b>𝐒ᴇʀᴠɪᴄᴇ 𝐃ᴇᴛᴀɪʟs</b>\n{info}</blockquote>\n\n"
           + (f"<blockquote>📝 {_h.escape(raw_desc[:600])}</blockquote>\n\n" if raw_desc else "")
           + f"<blockquote>🔒 𝐁ᴀʟᴀɴᴄᴇ ɪs ᴄᴜᴛ ᴏɴʟʏ ᴀғᴛᴇʀ ʏᴏᴜ ᴄᴏɴғɪʀᴍ. 𝐅ᴀɪʟᴇᴅ ᴏʀᴅᴇʀs ᴀʀᴇ ʀᴇғᴜɴᴅᴇᴅ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ.</blockquote>\n\n"
           f"<blockquote>{link_prompt(service_kind(name, cat or ''))}</blockquote>\n\n"
           f"<blockquote>💬 𝐓ᴀᴘ <b>𝐎ʀᴅᴇʀ</b> ᴀɴᴅ sᴇɴᴅ ʏᴏᴜʀ <b>ʟɪɴᴋ</b> + <b>ǫᴜᴀɴᴛɪᴛʏ</b>.</blockquote>")
    btns = [
        [style_btn(f"🛒 𝐎ʀᴅᴇʀ 𝐍ᴏᴡ", f"smm_order|{sid}", "success", icon=5409320020058584473)],
        [style_btn("🔙 𝐁ᴀᴄᴋ", _back_for(cat), "danger", icon=6129812419028982717)]
    ]
    try: await event.edit(msg, buttons=btns)
    except MessageNotModifiedError: pass

# ── Link helpers (rules in utils/smm_links.py) ──
from utils.smm_links import (link_rule, link_prompt, check_link, normalize_tg as _norm4,
                             username_from_link, TG_RE, RULES)

def service_kind(name, category=""):
    return link_rule(name, category or "")

def normalize_tg(text):
    r = _norm4(text)
    return r[:3] if r else None

URL_RE = re.compile(r"(?i)\b((?:https?://|www\.)\S+|[a-z0-9-]+(?:\.[a-z0-9-]+)+/\S*)")

async def extract_link(e):
    """Pull a usable link out of a message: forwarded post, link entities, or text anywhere."""
    # 1) forwarded channel post
    fwd = getattr(e.message, "fwd_from", None)
    if fwd and getattr(fwd, "channel_post", None):
        try:
            ch = await e.message.get_forward_sender() or None
        except Exception:
            ch = None
        if ch is None:
            try:
                ch = await bot.get_entity(fwd.from_id)
            except Exception:
                ch = None
        uname = getattr(ch, "username", None) if ch else None
        if not uname and ch is not None and getattr(ch, "usernames", None):
            uname = ch.usernames[0].username
        if uname:
            return f"https://t.me/{uname}/{fwd.channel_post}"
        if ch is not None and getattr(ch, "id", None):
            return f"https://t.me/c/{ch.id}/{fwd.channel_post}"
    # 2) hidden link entities (text links) + plain text
    candidates = []
    for ent, txt in (e.message.get_entities_text() or []):
        url = getattr(ent, "url", None)
        candidates.append(url or txt)
    candidates.append(e.raw_text or "")
    for c in candidates:
        r = normalize_tg(c)
        if r:
            return r[0]
    for c in candidates:
        m = URL_RE.search(c or "")
        if m:
            u = m.group(1).rstrip(").,]>")
            return u if u.lower().startswith("http") else "https://" + u
    return None

# ── Live min / max from the panel ──
async def panel_service(pid):
    for x in await panel_services():
        if str(x.get("service")) == str(pid):
            return x
    return None

async def sync_limits(sid):
    """Copy the panel's exact min/max/type into our DB so the bot never allows a qty the panel rejects."""
    row = cur.execute("SELECT fansmm_service_id, min_qty, max_qty FROM smm_services WHERE id=?", (sid,)).fetchone()
    if not row or not (row[0] or "").strip():
        return None
    try:
        x = await panel_service(row[0])
    except Exception:
        x = None
    if not x:
        return None
    try:
        mn = int(float(x.get("min") or row[1])); mx = int(float(x.get("max") or row[2]))
    except Exception:
        return None
    ptype = str(x.get("type") or "Default")
    cur.execute("UPDATE smm_services SET min_qty=?, max_qty=?, panel_type=? WHERE id=?", (mn, mx, ptype, sid))
    db.commit()
    return mn, mx, ptype

# ── Order states ──
smm_order_state = {}

async def start_smm_order(event, svc_id):
    uid = event.sender_id
    try: lim = await sync_limits(svc_id)
    except Exception: lim = None
    row = cur.execute("SELECT id, name, category, min_qty, max_qty, price_per_1000 FROM smm_services WHERE id=? AND available=1", (svc_id,)).fetchone()
    if not row:
        return await event.answer("Service not found.", alert=True)
    sid, name, cat, min_q, max_q, price = row
    ptype = (lim[2] if lim else "Default").lower()
    kind = service_kind(name, cat or "")
    smm_order_state[uid] = {"step": "link", "svc_id": sid, "name": name, "kind": kind, "ptype": ptype,
                            "min_q": min_q, "max_q": max_q, "price": price}
    txt = (f"<blockquote>⚡ <b>{name}</b>\n📉 Min: <b>{min_q}</b> | 📈 Max: <b>{max_q}</b></blockquote>\n\n"
           f"<blockquote>{link_prompt(kind)}</blockquote>")
    bt = [[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", b"smm_cancel")]]
    try: await event.edit(txt, buttons=bt)
    except Exception: await event.respond(txt, buttons=bt)


# ── Status + auto refund ──
FINAL_REFUND = ("canceled", "cancelled", "refunded", "fail", "failed", "error")

async def refresh_order(order_id, uid=None):
    """Fetch live status, auto-refund cancelled/partial orders once. Returns dict or raises."""
    q = "SELECT user_id, service_name, quantity, price, status, coalesce(refunded,0), link FROM smm_orders WHERE fansmm_order_id=?"
    args = [str(order_id)]
    if uid is not None:
        q += " AND user_id=?"; args.append(uid)
    row = cur.execute(q, args).fetchone()
    if not row:
        return None
    owner, svc, qty, price, status, refunded, link = row
    info = {"id": order_id, "service": svc, "qty": qty, "price": price, "status": status,
            "remains": "?", "refund": 0, "link": link, "owner": owner, "live": False}
    r = await fansmm_request({"action": "status", "order": str(order_id)})
    if isinstance(r, dict) and r.get("error"):
        raise Exception(r["error"])
    live = str(r.get("status") or status)
    rem = r.get("remains")
    info.update(status=live, live=True, remains=rem if rem is not None else "?")
    try: rem_i = max(0, min(int(float(rem)), qty))
    except Exception: rem_i = None
    low = live.lower()
    refund_due = 0
    if any(w in low for w in FINAL_REFUND):
        refund_due = price
    elif low == "partial" and rem_i:
        refund_due = round(price * rem_i / qty, 2) if qty else 0
    async with get_user_lock(owner):
        cur.execute("UPDATE smm_orders SET status=?, remains=? WHERE fansmm_order_id=?", (live, rem_i, str(order_id)))
        give = round(refund_due - (refunded or 0), 2)
        if give > 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (give, owner))
            cur.execute("UPDATE smm_orders SET refunded=? WHERE fansmm_order_id=?", (refund_due, str(order_id)))
            info["refund"] = give
        db.commit()
    info["refunded_total"] = max(refund_due, refunded or 0)
    return info

STATUS_ICON = {"completed": "✅", "pending": "⏳", "in progress": "🔄", "processing": "🔄",
               "partial": "🟡", "canceled": "❌", "cancelled": "❌", "refunded": "↩️"}

def status_text(info):
    st = str(info["status"])
    icon = STATUS_ICON.get(st.lower(), "📌")
    txt = (f"<blockquote>📊 <b>𝐎ʀᴅᴇʀ 𝐒ᴛᴀᴛᴜs</b>\n\n"
           f"🆔 <b>ID:</b> <code>{info['id']}</code>\n"
           f"⚡ <b>𝐒ᴇʀᴠɪᴄᴇ:</b> {html.escape(str(info['service']))}\n"
           f"🔗 <b>𝐋ɪɴᴋ:</b> <code>{html.escape(str(info.get('link') or '-'))}</code>\n"
           f"📊 <b>𝐐ᴛʏ:</b> {info['qty']} | 🔄 𝐑ᴇᴍᴀɪɴs: {info['remains']}\n"
           f"{P_MONEY} <b>𝐏ᴀɪᴅ:</b> {P_INR}{info['price']}\n"
           f"{icon} <b>𝐒ᴛᴀᴛᴜs:</b> {html.escape(st)}</blockquote>")
    low = st.lower()
    if any(w in low for w in FINAL_REFUND) or low == "partial":
        amt = info.get("refunded_total", 0)
        txt += (f"\n\n<blockquote>↩️ <b>{P_INR}{amt}</b> ʀᴇғᴜɴᴅᴇᴅ ᴛᴏ ʏᴏᴜʀ ʙᴀʟᴀɴᴄᴇ."
                + ("\n💡 𝐔sᴜᴀʟʟʏ ᴄᴀɴᴄᴇʟʟᴇᴅ ʙᴇᴄᴀᴜsᴇ ᴛʜᴇ ʟɪɴᴋ ᴡᴀs ᴡʀᴏɴɢ / ᴘʀɪᴠᴀᴛᴇ. 𝐔sᴇ ᴀ ᴘᴜʙʟɪᴄ <b>ᴘᴏsᴛ ʟɪɴᴋ</b> ᴀɴᴅ ᴏʀᴅᴇʀ ᴀɢᴀɪɴ." if low != "partial" else "")
                + "</blockquote>")
    return txt

def status_buttons(order_id):
    return [[style_btn("🔄 𝐑ᴇғʀᴇsʜ 𝐒ᴛᴀᴛᴜs", f"smm_st|{order_id}".encode(), "primary")]]

async def auto_status_loop():
    """Every 5 min: refresh open orders so cancelled ones get refunded + user notified."""
    await asyncio.sleep(60)
    while True:
        try:
            rows = cur.execute(
                "SELECT fansmm_order_id, user_id FROM smm_orders WHERE fansmm_order_id NOT IN ('', 'N/A') AND "
                "lower(coalesce(status,'pending')) NOT IN ('completed','canceled','cancelled','refunded','partial','fail','failed') "
                "ORDER BY id DESC LIMIT 100").fetchall()
            for oid, uid in rows:
                try:
                    info = await refresh_order(oid)
                    if info and info.get("refund"):
                        await bot.send_message(uid, status_text(info), buttons=status_buttons(oid))
                except Exception as ex:
                    logger.debug("auto status %s: %s", oid, ex)
                await asyncio.sleep(1)
        except Exception as ex:
            logger.error("auto status loop: %s", ex)
        await asyncio.sleep(300)

def _confirm_text(st):
    extra = ""
    if st.get("answer"): extra += f"\n🗳 <b>Option:</b> {st['answer']}"
    if st.get("comments"): extra += f"\n💬 <b>Comments:</b> {len(st['comments'].splitlines())}"
    return (f"<blockquote>{PE_GIFT} <b>𝐎ʀᴅᴇʀ 𝐒ᴜᴍᴍᴀʀʏ</b>\n\n"
            f"⚡ <b>𝐒ᴇʀᴠɪᴄᴇ:</b> {st['name']}\n"
            f"🔗 <b>𝐋ɪɴᴋ:</b> <code>{html.escape(st['link'])}</code>\n"
            f"📊 <b>𝐐ᴛʏ:</b> {st['qty']}{extra}\n"
            f"{P_MONEY} <b>𝐂ᴏsᴛ:</b> {P_INR}{st['total_cost']}</blockquote>\n\n"
            f"<blockquote>✅ 𝐂ᴏɴғɪʀᴍ ᴛᴏ ᴘʟᴀᴄᴇ ʏᴏᴜʀ ᴏʀᴅᴇʀ!</blockquote>")

def _confirm_btns(st):
    return [[style_btn(f"✅ 𝐂ᴏɴғɪʀᴍ ({P_INR}{st['total_cost']})", b"smm_confirm", "success", icon=5409320020058584473)],
            [style_btn("❌ 𝐂ᴀɴᴄᴇʟ", b"smm_cancel", "danger", icon=6129888444245089008)]]

def register_smm(bot):
    @bot.on(events.NewMessage(pattern=r"(?i)^/(linkguide|links)(?:@\w+)?$"))
    async def cmd_linkguide(e):
        from utils.smm_links import link_guide_text
        await e.reply(link_guide_text(), link_preview=False)

    @bot.on(events.NewMessage(pattern=r"(?i)^(𝐒𝐌𝐌 𝐒ᴇʀᴠɪᴄᴇs|📊 𝐒𝐌𝐌 𝐒ᴇʀᴠɪᴄᴇs|📊 SMM Services)$"))
    async def msg_smm(e):
        await show_smm_categories(e)

    @bot.on(events.CallbackQuery(pattern=b"^smm_cats$"))
    async def cb_smm_cats(e):
        await show_smm_categories(e)

    @bot.on(events.CallbackQuery(pattern=r"^smm_cat\|(.+)$"))
    async def cb_smm_cat(e):
        cat = e.pattern_match.group(1).decode()
        await show_smm_services(e, cat)

    @bot.on(events.CallbackQuery(pattern=r"^smm_svc\|(\d+)$"))
    async def cb_smm_svc(e):
        svc_id = int(e.pattern_match.group(1).decode())
        await show_smm_service_detail(e, svc_id)

    from utils.helpers import require_join

    @bot.on(events.CallbackQuery(pattern=r"^smm_order\|(\d+)$"))
    async def cb_smm_order(e):
        try: await e.answer()
        except Exception: pass
        if not await require_join(bot, e): return
        svc_id = int(e.pattern_match.group(1).decode())
        try:
            await start_smm_order(e, svc_id)
        except Exception as ex:
            logger.warning("smm order start failed: %s", ex)
            await e.respond(f"{P_WARN} Could not start order, please try again.")

    @bot.on(events.CallbackQuery(pattern=b"^smm_cancel$"))
    async def cb_smm_cancel(e):
        uid = e.sender_id
        st = smm_order_state.pop(uid, None)
        await e.answer("Cancelled.", alert=False)
        if st and st.get("svc_id"):
            try:
                return await show_smm_service_detail(e, st["svc_id"])   # back to the service
            except Exception:
                pass
        try: await e.delete()
        except Exception: pass

    @bot.on(events.NewMessage(func=lambda e: e.sender_id in smm_order_state))
    async def msg_smm_flow(e):
        uid = e.sender_id
        st = smm_order_state.get(uid)
        if not st: return
        text = (e.raw_text or "").strip()
        if text.startswith("/") and text.lower() != "/cancel":
            return  # let other commands through
        if text.lower() == "/cancel":
            smm_order_state.pop(uid, None)
            return await e.reply(f"{P_NO} Cancelled.")

        if st["step"] == "link":
            kind = st.get("kind", "other")
            link = await extract_link(e)
            if not link:
                return await e.reply(f"{P_WARN} No link found in your message.\n\n<blockquote>{link_prompt(kind)}</blockquote>",
                                     buttons=[[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", b"smm_cancel")]])
            fixed, err = check_link(kind, link)
            if err:
                return await e.reply(f"{P_WARN} {err}", buttons=[[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", b"smm_cancel")]])
            text = fixed
            st["link"] = text
            st["step"] = "qty"
            smm_order_state[uid] = st
            return await e.reply(
                f"<blockquote>📊 <b>𝐒ᴛᴇᴘ 2:</b> 𝐄ɴᴛᴇʀ <b>ǫᴜᴀɴᴛɪᴛʏ</b>:\n\n"
                f"📉 𝐌ɪɴ: <b>{st['min_q']}</b> | 📈 𝐌ᴀx: <b>{st['max_q']}</b></blockquote>",
                buttons=[[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", b"smm_cancel")]]
            )

        if st["step"] == "qty":
            try:
                qty = int(text)
            except ValueError:
                return await e.reply(f"{P_WARN} Please enter a valid number.")
            if qty < st["min_q"] or qty > st["max_q"]:
                return await e.reply(f"{P_WARN} Quantity must be between <b>{st['min_q']}</b> and <b>{st['max_q']}</b>.")
            import math
            total_cost = math.ceil(qty * st["price"] / 1000)
            if total_cost < 1:
                total_cost = 1
            st["qty"] = qty
            st["total_cost"] = total_cost
            pt = st.get("ptype", "")
            if "comment" in pt and "like" not in pt:
                st["step"] = "comments"; smm_order_state[uid] = st
                return await e.reply(f"<blockquote>💬 <b>Step 3:</b> Send exactly <b>{qty}</b> comments, <b>one per line</b>.\n\nExample:\n<code>Nice post 🔥\nGreat 👍\nAwesome ❤️</code></blockquote>",
                                     buttons=[[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", b"smm_cancel")]])
            if "poll" in pt:
                st["step"] = "answer"; smm_order_state[uid] = st
                return await e.reply("<blockquote>🗳 <b>Step 3:</b> Kaunse option ko vote chahiye? Number bhejo (1 = pehla option, 2 = doosra…)</blockquote>",
                                     buttons=[[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", b"smm_cancel")]])
            st["step"] = "confirm"; smm_order_state[uid] = st
            return await e.reply(_confirm_text(st), buttons=_confirm_btns(st))

        if st["step"] == "comments":
            lines = [x.strip() for x in (e.raw_text or "").splitlines() if x.strip()]
            if len(lines) != st["qty"]:
                return await e.reply(f"{P_WARN} Aapne <b>{len(lines)}</b> comments bheje, chahiye <b>{st['qty']}</b> (ek line = ek comment).")
            st["comments"] = "\n".join(lines); st["step"] = "confirm"; smm_order_state[uid] = st
            return await e.reply(_confirm_text(st), buttons=_confirm_btns(st))

        if st["step"] == "answer":
            if not text.isdigit() or int(text) < 1:
                return await e.reply(f"{P_WARN} Sirf option number bhejo, jaise <code>1</code>.")
            st["answer"] = text; st["step"] = "confirm"; smm_order_state[uid] = st
            return await e.reply(_confirm_text(st), buttons=_confirm_btns(st))

    @bot.on(events.CallbackQuery(pattern=b"^smm_confirm$"))
    async def cb_smm_confirm(e):
        if not await require_join(bot, e): return
        uid = e.sender_id
        st = smm_order_state.get(uid)
        if not st or st.get("step") != "confirm":
            return await e.answer("Session expired. Please start again.", alert=True)

        svc_row = cur.execute(
            "SELECT fansmm_service_id FROM smm_services WHERE id=? AND available=1", (st["svc_id"],)
        ).fetchone()
        if not svc_row:
            smm_order_state.pop(uid, None)
            return await e.answer("Service no longer available.", alert=True)
        if not (svc_row[0] or "").strip():
            return await e.answer("⚠️ This service is being set up. You were NOT charged. Please try another service or contact support.", alert=True)

        total_cost = st["total_cost"]
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (total_cost, uid, total_cost))
            if cur.rowcount == 0:
                from plugins.deposit import pay_for_item
                return await pay_for_item(e, total_cost, f"Place Order · {str(st.get('name',''))[:25]} ₹{total_cost}")
            db.commit()

        smm_order_state.pop(uid, None)
        await e.edit(f"{PE_LIGHTNING} <b>𝐏ʟᴀᴄɪɴɢ ʏᴏᴜʀ ᴏʀᴅᴇʀ...</b>")

        try:
            params = {"action": "add", "service": svc_row[0], "link": st["link"]}
            if st.get("comments"):
                params["comments"] = st["comments"]          # custom comments: qty = number of lines
            else:
                params["quantity"] = st["qty"]
            if st.get("answer"):
                params["answer_number"] = st["answer"]
            if any(w in st.get("ptype", "") for w in ("mention", "subscription")):
                params["username"] = username_from_link(st["link"])
            result = await fansmm_request(params)
            if not isinstance(result, dict):
                raise Exception("Panel returned an invalid response")
            error = result.get("error")
            if error:
                raise Exception(error)
            fansmm_order_id = result.get("order")
            if not fansmm_order_id:
                raise Exception("Panel did not return an order ID")

            cur.execute(
                "INSERT INTO smm_orders (user_id, service_id, service_name, link, quantity, price, fansmm_order_id, status) VALUES (?,?,?,?,?,?,?,?)",
                (uid, st["svc_id"], st["name"], st["link"], st["qty"], total_cost, str(fansmm_order_id), "pending")
            )
            db.commit()
            try:
                from plugins.profit import notify_profit
                c_row = cur.execute("SELECT cost_per_1000 FROM smm_services WHERE id=?", (st["svc_id"],)).fetchone()
                cost_k = (c_row[0] if c_row else 0) or (await panel_rate(svc_row[0])) or 0
                await notify_profit(uid, "Social Media", f"{st['name']} x{st['qty']}", total_cost, round(cost_k * st["qty"] / 1000, 2))
            except Exception as ex2:
                logger.error(f"profit log: {ex2}")
            try:
                from plugins.salelog import post_sale
                await post_sale("New SMM Order Placed Successfully", f"➖ <b>Service:</b> {html.escape(str(st['name']))} 🚀\n➖ <b>Quantity:</b> {st['qty']} 📊\n➕ <b>Price:</b> {P_INR}{total_cost} 💰")
            except Exception: pass
            await e.edit(
                f"<blockquote>{PE_CHECK} <b>𝐎ʀᴅᴇʀ 𝐏ʟᴀᴄᴇᴅ!</b>\n\n"
                f"⚡ <b>𝐒ᴇʀᴠɪᴄᴇ:</b> {st['name']}\n"
                f"📊 <b>𝐐ᴛʏ:</b> {st['qty']}\n"
                f"{P_MONEY} <b>𝐏ᴀɪᴅ:</b> {P_INR}{total_cost}\n"
                f"🆔 <b>𝐎ʀᴅᴇʀ 𝐈𝐃:</b> <code>{fansmm_order_id}</code>\n\n"
                f"<i>Your order is being processed. Tap the button below or use /smm_status {fansmm_order_id} to check status.</i></blockquote>",
                buttons=status_buttons(fansmm_order_id)
            )
        except Exception as ex:
            logger.error(f"SMM order error: {ex}")
            async with get_user_lock(uid):
                cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (total_cost, uid))
                db.commit()
            msg = str(ex)
            hint = ""
            if "username" in msg.lower() or "link" in msg.lower():
                hint = "\n\n💡 Check that your link is correct and the channel is <b>public</b>."
            await e.edit(f"{P_NO} <b>Order failed:</b> {html.escape(msg)}\n<b>Your balance has been refunded.</b>{hint}")

    from config import ADMIN_IDS

    @bot.on(events.NewMessage(pattern=r"^/smmbal$"))
    async def cmd_smmbal(e):
        if e.sender_id not in ADMIN_IDS: return
        try:
            r = await fansmm_request({"action": "balance"})
            await e.reply(f"💰 CheapestSMMPanels balance: <b>{r.get('balance')} {r.get('currency', '')}</b>")
        except Exception as ex:
            await e.reply(f"{P_WARN} {html.escape(str(ex))}")

    @bot.on(events.NewMessage(pattern=r"^/smmfind (.+)$"))
    async def cmd_smmfind(e):
        """/smmfind telegram member  -> cheapest matching panel services"""
        if e.sender_id not in ADMIN_IDS: return
        words = e.pattern_match.group(1).lower().split()
        try:
            data = await panel_services()
        except Exception as ex:
            return await e.reply(f"{P_WARN} {html.escape(str(ex))}")
        m = [x for x in data if all(w in (str(x.get("name")) + " " + str(x.get("category"))).lower() for w in words)]
        m.sort(key=lambda x: float(x.get("rate", 0)))
        if not m: return await e.reply("No matching service.")
        out = "\n".join(f"<code>{x['service']}</code> · ₹{x['rate']}/1K · {x['min']}-{x['max']} · {html.escape(str(x['name']))[:70]}" for x in m[:25])
        await e.reply(out[:4000] + "\n\n<i>Connect: /setsmm &lt;local_id&gt; &lt;panel_id&gt; [sell_price]</i>")

    @bot.on(events.NewMessage(pattern=r"^/smm_status(?:@\w+)?(?:\s+(\d+))?$"))
    async def cmd_smm_status(e):
        order_id = e.pattern_match.group(1)
        if not order_id:
            return await e.reply(f"{P_WARN} Usage: <code>/smm_status ORDER_ID</code>")
        try:
            info = await refresh_order(order_id, e.sender_id)
        except Exception as ex:
            row = cur.execute("SELECT status FROM smm_orders WHERE fansmm_order_id=? AND user_id=?", (order_id, e.sender_id)).fetchone()
            if not row: return await e.reply(f"{P_WARN} Order not found.")
            return await e.reply(f"{P_WARN} Could not fetch live status. Last known: <b>{row[0]}</b>", buttons=status_buttons(order_id))
        if not info:
            return await e.reply(f"{P_WARN} Order not found.")
        await e.reply(status_text(info), buttons=status_buttons(order_id))

    @bot.on(events.CallbackQuery(pattern=rb"^smm_st\|(\w+)$"))
    async def cb_smm_status(e):
        order_id = e.pattern_match.group(1).decode()
        try:
            info = await refresh_order(order_id, e.sender_id)
        except Exception:
            return await e.answer("Could not fetch live status, try again in a minute.", alert=True)
        if not info:
            return await e.answer("Order not found.", alert=True)
        try: await e.answer(f"Status: {info['status']}" + (f" · ₹{info['refund']} refunded" if info.get("refund") else ""))
        except Exception: pass
        try: await e.edit(status_text(info), buttons=status_buttons(order_id))
        except MessageNotModifiedError: pass
        except Exception: await e.respond(status_text(info), buttons=status_buttons(order_id))

    try:
        asyncio.get_event_loop().create_task(auto_status_loop())
    except Exception as ex:
        logger.warning("auto status loop not started: %s", ex)
