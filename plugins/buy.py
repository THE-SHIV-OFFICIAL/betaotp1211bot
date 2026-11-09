import os
import asyncio
import time
import zipfile
import re
import html
from telethon import events, Button, TelegramClient, types
from telethon.errors import MessageNotModifiedError
from database import cur, db, get_flag_by_country_name, get_plain_flag_by_country_name, session_base, remove_session_files
from premium_emojis import premium_flag_id
from config import PE_LOCATION, PE_GIFT, PE_LIGHTNING, PE_CHECK, P_MONEY, P_PKG, P_CARD, P_WARN, P_NO, P_YES, P_INR, P_TIME, P_FLAG, P_OTP, P_2FA, P_PHONE, LOG_CHANNELS, AUTO_CANCEL_SECONDS, OTP_REGEX, bot, logger, API_ID, API_HASH
from utils.keyboards import style_btn, copy_btn
from utils.delivery import send_delivery_thanks
from utils.helpers import require_join
from utils.states import active_orders, session_buy_state, get_user_lock
from utils.s1cat import S1_CATS, split_mode, cat_sql, cat_label, cat_counts, migrate_categories, cat_icon, cat_text

migrate_categories(cur, db)

# The bot's session for a sold account stays alive until the buyer manually
# terminates it with the "Terminate Bot Session" button (no auto-logout).

async def show_countries(event, mode, page):
    limit = 12
    offset = (page - 1) * limit
    _base, cat = split_mode(mode)
    w, a = cat_sql(cat)
    rows = cur.execute("SELECT country_name, COUNT(*) FROM stock WHERE available=1" + w + " GROUP BY country_name", a).fetchall()
    total = len(rows)
    countries = rows[offset:offset+limit]
    
    if not countries and cat:
        msg = f"<blockquote>{P_WARN} <b>{cat_text(cat)}</b>\n\nNo account in this category right now. Please check another category.</blockquote>"
        btns = [[style_btn("⬅️ Back", b"s1_cats", "danger", icon=6129812419028982717)]]
        if isinstance(event, events.CallbackQuery.Event):
            try: return await event.edit(msg, buttons=btns)
            except MessageNotModifiedError: return
        return await event.respond(msg, buttons=btns)

    if not countries:
        # No session stock uploaded -> send user to Telegram servers (ready accounts + Hero SMS OTP numbers)
        try:
            from plugins.social import show_servers
            return await show_servers(event, "tg", back_to="menu_home")
        except Exception as ex:
            logger.warning(f"tg servers fallback failed: {ex}")
            return await event.respond(f"{P_WARN} 𝐍ᴏ sᴛᴏᴄᴋ ᴀᴠᴀɪʟᴀʙʟᴇ ᴀᴛ ᴛʜᴇ ᴍᴏᴍᴇɴᴛ. 𝐏ʟᴇᴀsᴇ ᴄʜᴇᴄᴋ ʙᴀᴄᴋ ʟᴀᴛᴇʀ!")

    btns = []
    for c_name, count in countries:
        flag = get_plain_flag_by_country_name(c_name)
        btns.append(style_btn(f"{c_name} ({count})", f"bc|{mode}|{c_name}", "primary", icon=premium_flag_id(flag)))
        
    f_btns = [btns[i:i+2] for i in range(0, len(btns), 2)]
    
    nav = []
    if page > 1: nav.append(style_btn("𝐏ʀᴇᴠ", f"pg_c|{mode}|{page-1}", "primary", icon=6129627894349045589))
    if offset + limit < total: nav.append(style_btn("𝐍ᴇxᴛ", f"pg_c|{mode}|{page+1}", "primary", icon=6129732880529628243))
    if nav: f_btns.append(nav)
    f_btns.append([style_btn("🔍 𝐒ᴇᴀʀᴄʜ 𝐂ᴏᴜɴᴛʀʏ", f"s1_search|{mode}", "success", icon=6203982793379154737)])
    if cat:
        f_btns.append([style_btn("⬅️ Back to Categories", b"s1_cats", "danger", icon=6129812419028982717)])
    else:
        f_btns.append([style_btn("⬅️ Back to Menu", b"menu_home", "danger", icon=6129812419028982717)])
    
    head = f"<blockquote><b>{cat_text(cat)}</b></blockquote>\n" if cat else ""
    msg = head + f"<blockquote>{PE_LOCATION} <b>𝐒ᴇʟᴇᴄᴛ ᴀ 𝐂ᴏᴜɴᴛʀʏ:</b> (𝐏ᴀɢᴇ {page})</blockquote>"
    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=f_btns)
        except MessageNotModifiedError: pass
    else: await event.respond(msg, buttons=f_btns)

s1_search_state = {}


async def show_s1_categories(event):
    """Server 1 · first step: choose account type (3 buttons)."""
    counts = cat_counts(cur)
    btns = [[style_btn(f"{S1_CATS[k][0]} ({counts[k]})", f"s1_cat|{k}".encode(), S1_CATS[k][1], icon=cat_icon(k))] for k in S1_CATS]
    manual = cur.execute("SELECT COUNT(*) FROM manual_stock WHERE platform='tg' AND available=1").fetchone()[0]
    if manual:
        btns.append([style_btn(f"⭐ Ready Account ({manual})", b"s1_manual", "success", icon=5408995930416362034)])
    btns.append([style_btn("⬅️ Back", b"num_p|tg", "danger", icon=6129812419028982717)])
    guide = "\n".join(f"{cat_text(k)}: {v[2]}" for k, v in S1_CATS.items())
    msg = (f"<blockquote>⭐ <b>Server 1 · Ready Account</b></blockquote>\n\n"
           f"<blockquote>{PE_LIGHTNING} Choose account type:\n\n{guide}</blockquote>")
    if isinstance(event, events.CallbackQuery.Event):
        try: await event.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass
    else: await event.respond(msg, buttons=btns)


def _s1_match(c_name, q):
    from database import COUNTRY_CODES
    q = q.strip().lower().lstrip("+")
    if len(q) >= 2 and q in c_name.lower(): return True
    dials = [d for d, (n, _f) in COUNTRY_CODES.items() if n == c_name]
    if q.isdigit() and q in dials: return True
    if len(q) == 2 and q.isalpha():
        try:
            import phonenumbers
            return any(phonenumbers.region_code_for_country_code(int(d)).lower() == q for d in dials)
        except Exception:
            return False
    return False


async def s1_search(event, mode, query):
    w, a = cat_sql(split_mode(mode)[1])
    rows = cur.execute("SELECT country_name, COUNT(*) FROM stock WHERE available=1" + w + " GROUP BY country_name", a).fetchall()
    res = [(c, n) for c, n in rows if _s1_match(c, query)][:40]
    btns = [style_btn(f"{c} ({n})", f"bc|{mode}|{c}", "primary", icon=premium_flag_id(get_plain_flag_by_country_name(c))) for c, n in res]
    f_btns = [btns[i:i+2] for i in range(0, len(btns), 2)]
    f_btns.append([style_btn("🔍 𝐒ᴇᴀʀᴄʜ 𝐀ɢᴀɪɴ", f"s1_search|{mode}", "success", icon=6203982793379154737)])
    f_btns.append([style_btn("𝐁ᴀᴄᴋ", f"pg_c|{mode}|1", "danger", icon=6129812419028982717)])
    head = f"<blockquote>🔍 <b>𝐑ᴇsᴜʟᴛs ғᴏʀ:</b> <code>{html.escape(query)}</code> ({len(res)})</blockquote>"
    if not res: head += "\n\n<blockquote>𝐍ᴏ ᴄᴏᴜɴᴛʀʏ ғᴏᴜɴᴅ. 𝐓ʀʏ ɴᴀᴍᴇ (India), ᴄᴏᴅᴇ (IN) ᴏʀ ᴅɪᴀʟ (+91).</blockquote>"
    await event.respond(head, buttons=f_btns)


async def show_years(event, mode, country):
    cat = split_mode(mode)[1]
    w, a = cat_sql(cat)
    years = cur.execute("SELECT account_year, COUNT(*), price FROM stock WHERE country_name=? AND available=1" + w + " GROUP BY account_year, price", (country,) + a).fetchall()
    if not years: return await event.edit(f"{P_WARN} 𝐍ᴏ sᴛᴏᴄᴋ ʟᴇғᴛ ғᴏʀ {country}.")
    
    flag = get_flag_by_country_name(country)
    btns = []
    for y, count, price in years:
        btns.append([style_btn(f"{y} - {P_INR}{price} ({count} left)", f"by|{mode}|{country}|{y}|{price}", "primary", icon=5408995930416362034)])
    btns.append([style_btn("𝐁ᴀᴄᴋ", f"pg_c|{mode}|1", "danger", icon=6129812419028982717)])
    head = f"<blockquote><b>{cat_text(cat)}</b></blockquote>\n" if cat else ""
    await event.edit(head + f"<blockquote>{flag} <b>𝐒ᴇʟᴇᴄᴛ 𝐘ᴇᴀʀ & 𝐏ʀɪᴄᴇ ғᴏʀ {country}:</b></blockquote>", buttons=btns)

async def confirm_purchase(event, country, year, price, cat=None):
    ctxt = f"🏷 Type: {cat_text(cat)}\n" if cat else ""
    msg = f"<blockquote>{PE_GIFT} <b>𝐂ᴏɴғɪʀᴍ 𝐏ᴜʀᴄʜᴀsᴇ</b>\n\n{ctxt}{P_FLAG} 𝐂ᴏᴜɴᴛʀʏ: {country}\n📆 𝐘ᴇᴀʀ: {year}\n{P_MONEY} 𝐏ʀɪᴄᴇ: {P_INR}{price}\n\n𝐀ʀᴇ ʏᴏᴜ sᴜʀᴇ?</blockquote>"
    btns = [
        [style_btn("𝐂ᴏɴғɪʀᴍ 𝐁ᴜʏ", f"buy_cf|{country}|{year}|{price}" + (f"|{cat}" if cat else ""), "success", icon=5409320020058584473)],
        [style_btn("𝐂ᴀɴᴄᴇʟ", "cancel_action", "danger", icon=6129888444245089008)]
    ]
    await event.edit(msg, buttons=btns)

async def process_purchase(event, country, year, price_str, cat=None):
    uid, price = event.sender_id, int(price_str)

    async with get_user_lock(uid):
        w, a = cat_sql(cat)
        row = cur.execute("SELECT phone, session_file, twofa FROM stock WHERE country_name=? AND account_year=? AND price=? AND available=1" + w + " LIMIT 1", (country, int(year), price) + a).fetchone()
        if not row: return await event.answer("❌ Out of stock!", alert=True)

        phone, sess, twofa_pass = row
        if not cat:
            _cr = cur.execute("SELECT category FROM stock WHERE phone=?", (phone,)).fetchone()
            cat = _cr[0] if _cr else None
        sess = session_base(sess)

        disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
        discount = disc_row[0] if disc_row else 0
        final_price = price if discount == 0 else int(price * (100 - discount) / 100)

        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (final_price, uid, final_price))
        if cur.rowcount == 0:
            from plugins.deposit import pay_for_item
            return await pay_for_item(event, final_price, f"Buy Telegram Acc · {country} ₹{final_price}")

        cur.execute("UPDATE stock SET available=0 WHERE phone=? AND available=1", (phone,))
        if cur.rowcount == 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_price, uid))
            db.commit()
            return await event.answer("❌ This account was just sold. Balance returned.", alert=True)
        db.commit()

    await event.edit(f"{PE_LIGHTNING} <b>𝐏ʀᴏᴄᴇssɪɴɢ ʏᴏᴜʀ ᴏʀᴅᴇʀ...</b>\n𝐏ʟᴇᴀsᴇ ᴡᴀɪᴛ ᴡʜɪʟᴇ ᴡᴇ ɪɴɪᴛɪᴀʟɪᴢᴇ ᴛʜᴇ sᴇssɪᴏɴ.")

    client = TelegramClient(sess, API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise Exception("Session expired or not authorized")
    except Exception as e:
        logger.error(f"Client init error ({phone}): {e}")
        try: await client.disconnect()
        except Exception: pass
        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_price, uid))
            cur.execute("UPDATE stock SET available=1 WHERE phone=?", (phone,))
            db.commit()
        return await event.edit(f"{P_NO} <b>Error initializing account.</b> Money refunded.")

    c_icon = get_flag_by_country_name(country)
    actual_year = int(year)
    msg = (f"<blockquote expandable>{PE_LIGHTNING} <b>𝐎ʀᴅᴇʀ 𝐀ᴄᴛɪᴠᴇ!</b>\n\n"
           f"{P_PHONE} <b>𝐏ʜᴏɴᴇ:</b> <code>{phone}</code>\n"
           f"{P_FLAG} <b>𝐂ᴏᴜɴᴛʀʏ:</b> {c_icon} {country}\n\n"
           f"🔻 <b>𝐈ɴsᴛʀᴜᴄᴛɪᴏɴs:</b>\n"
           f"1. 𝐎ᴘᴇɴ 𝐓ᴇʟᴇɢʀᴀᴍ & 𝐀ᴅᴅ 𝐀ᴄᴄᴏᴜɴᴛ\n"
           f"2. 𝐄ɴᴛᴇʀ ᴛʜᴇ ɴᴜᴍʙᴇʀ ᴀʙᴏᴠᴇ.\n"
           f"3. ⏳ <b>𝐏ʟᴇᴀsᴇ ᴡᴀɪᴛ!</b> 𝐓ʜᴇ ʙᴏᴛ ɪs ᴀᴄᴛɪᴠᴇʟʏ ʟɪsᴛᴇɴɪɴɢ ғᴏʀ ʏᴏᴜʀ 𝐎𝐓𝐏 ᴀɴᴅ ᴡɪʟʟ sᴇɴᴅ ɪᴛ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴏɴᴄᴇ 𝐓ᴇʟᴇɢʀᴀᴍ ᴅᴇʟɪᴠᴇʀs ɪᴛ.\n\n"
           f"<i>𝐍ᴏᴛᴇ: 𝐈ғ ɴᴏ 𝐎𝐓𝐏 ɪs ʀᴇᴄᴇɪᴠᴇᴅ ᴡɪᴛʜɪɴ 10 ᴍɪɴᴜᴛᴇs, ᴛʜᴇ ʙᴏᴛ ᴡɪʟʟ ᴀᴜᴛᴏ-ᴄᴀɴᴄᴇʟ ᴀɴᴅ ʀᴇғᴜɴᴅ ʏᴏᴜʀ ʙᴀʟᴀɴᴄᴇ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ.</i>")

    pre_btns = [[style_btn("🔢 𝐆ᴇᴛ 𝐎𝐓𝐏", f"get_otp_again|{phone}", "primary", icon=6129627894349045589),
                 copy_btn("📋 𝐂ᴏᴘʏ 𝐍ᴜᴍʙᴇʀ", phone, "success", icon=5409320020058584473)]]
    sent_msg = await event.edit(msg, buttons=pre_btns)

    active_orders[phone] = {
        'uid': uid, 'client': client, 'sess': sess, 'start_time': time.time(),
        'paid': False, 'price': final_price, 'country': country, 'year': actual_year,
        'c_icon': c_icon, 'twofa': twofa_pass, 'cat': cat, 'msg_id': getattr(sent_msg, 'id', None) or getattr(event, 'message_id', None), 'otp': None
    }
    asyncio.create_task(auto_otp_task(phone))

async def send_purchase_log(order, phone):
    """Public purchase proof for the store channel (no OTP / 2FA / session ever leaked)."""
    from plugins.salelog import post_sale
    p = str(phone).replace(" ", "")
    if not p.startswith("+"): p = "+" + p
    masked = p[:6] + "•" * max(4, len(p) - 6)
    flag = order.get('c_icon') or get_flag_by_country_name(order['country'])
    cat = order.get('cat')
    if not cat:
        _r = cur.execute("SELECT category FROM stock WHERE phone=?", (str(phone).lstrip("+"),)).fetchone()
        cat = _r[0] if _r else None
    body = (f"➖ <b>Server:</b> Server 1 · Ready Account ⭐\n"
            f"➖ <b>Account Type:</b> {cat_text(cat)}\n"
            f"➖ <b>Country:</b> {html.escape(str(order['country']))} {flag}\n"
            f"➖ <b>Application:</b> Telegram ✈️\n"
            f"➖ <b>Account Year:</b> {order.get('year', '—')} 📆\n\n"
            f"➕ <b>Number:</b> <code>{masked}</code> 📞\n"
            f"➕ <b>Code:</b> <tg-spoiler>●●●●●</tg-spoiler> 💬\n"
            f"➕ <b>Password:</b> <tg-spoiler>●●●●●●</tg-spoiler> 🔐\n"
            f"➕ <b>Price:</b> {P_INR}{order['price']} 💰")
    await post_sale(f"New Server 1 · {cat_label(cat)} Sold — {P_INR}{order['price']}", body)

# ======================= OTP DELIVERY =======================

async def fetch_latest_otp(order):
    """Reads the newest Telegram login code for this order (None when nothing new)."""
    client = order['client']
    try:
        peer = await client.get_input_entity(777000)
    except Exception:
        peer = types.InputPeerUser(user_id=777000, access_hash=0)
    msgs = await client.get_messages(peer, limit=5)
    for m in msgs:
        if m.date.timestamp() > order['start_time'] - 10:
            if m.message and re.search(OTP_REGEX, m.message) and "Login detected" not in m.message:
                return re.search(OTP_REGEX, m.message).group()
    return None

def otp_buttons(phone, order):
    """Buttons shown after the OTP arrives: get again / copy / logout old devices / buy again."""
    code = order.get('otp') or ""
    rows = [[style_btn("🔄 𝐆ᴇᴛ 𝐎𝐓𝐏 𝐀ɢᴀɪɴ", f"get_otp_again|{phone}", "primary", icon=6129627894349045589)]]
    if code:
        rows[0].append(copy_btn("📋 𝐂ᴏᴘʏ 𝐎𝐓𝐏", code, "success", icon=5409320020058584473,
                                fallback_data=f"show_otp|{phone}"))
    if order.get('twofa') and order['twofa'] != "None":
        rows.append([copy_btn("🔐 𝐂ᴏᴘʏ 𝟐𝐅𝐀 𝐏ᴀssᴡᴏʀᴅ", order['twofa'], "primary", icon=5408995930416362034,
                              fallback_data=f"show_2fa|{phone}")])
    rows.append([style_btn("🚪 𝐋ᴏɢᴏᴜᴛ 𝐎ᴛʜᴇʀ 𝐃ᴇᴠɪᴄᴇs", f"logout_bot|{phone}", "danger", icon=6129888444245089008)])
    rows.append([style_btn("🗑 𝐓ᴇʀᴍɪɴᴀᴛᴇ 𝐁ᴏᴛ 𝐒ᴇssɪᴏɴ", f"term_sess|{phone}", "danger", icon=6129888444245089008)])
    rows.append([style_btn("🛒 𝐁ᴜʏ 𝐀ɢᴀɪɴ", "buy_again", "success", icon=5409380965644514142)])
    return rows

def otp_text(phone, order):
    code = order.get('otp')
    twofa_text = (f"{P_2FA} <b>2FA:</b> <code>{order['twofa']}</code>"
                  if order.get('twofa') and order['twofa'] != "None"
                  else "🔓 <b>2FA:</b> <code>Disabled (No Password)</code>")
    return (f"<blockquote>{PE_CHECK} <b>𝐋ᴀᴛᴇsᴛ 𝐎𝐓𝐏 𝐅ᴇᴛᴄʜᴇᴅ!</b>\n\n"
            f"{P_PHONE} <b>𝐏ʜᴏɴᴇ:</b> <code>{phone}</code>\n"
            f"{P_FLAG} <b>𝐂ᴏᴜɴᴛʀʏ:</b> {order['c_icon']} {order['country']}\n"
            f"{P_OTP} <b>𝐎𝐓𝐏:</b> <code>{code}</code>\n"
            f"{twofa_text}</blockquote>\n\n"
            f"<blockquote>🛡 <b>𝐒𝐄𝐂𝐔𝐑𝐈𝐓𝐘 𝐍𝐎𝐓𝐈𝐂𝐄</b>\n\n"
            f"<b>📁 The account's SESSION FILE has been sent to you along with the number. It stays valid until YOU manually terminate it.</b>\n"
            f"<b>Tap \"🚪 𝐋ᴏɢᴏᴜᴛ 𝐎ᴛʜᴇʀ 𝐃ᴇᴠɪᴄᴇs\" to terminate all OLD sessions of this account — only your new login and the bot will stay.</b>\n"
            f"<b>The bot's own session is NEVER auto-logged out. Once YOU have logged in, tap \"🗑 𝐓ᴇʀᴍɪɴᴀᴛᴇ 𝐁ᴏᴛ 𝐒ᴇssɪᴏɴ\" to end the bot's login — until you log in, it will NOT be terminated.</b></blockquote>")

async def send_session_file(uid, phone, order):
    """Sends the account's .session file to the buyer so they can log in anywhere.
    The session stays valid until the buyer manually terminates it."""
    sess_file = session_base(order['sess']) + ".session"
    if not os.path.exists(sess_file):
        logger.warning(f"session file missing for {phone}: {sess_file}")
        return
    try:
        await bot.send_file(
            uid, sess_file,
            caption=(f"<blockquote>📁 <b>𝐒𝐄𝐒𝐒𝐈𝐎𝐍 𝐅𝐈𝐋𝐄</b>\n\n"
                     f"{P_PHONE} <b>𝐍ᴜᴍʙᴇʀ:</b> <code>{phone}</code>\n"
                     f"{P_FLAG} <b>𝐂ᴏᴜɴᴛʀʏ:</b> {order['c_icon']} {order['country']}\n\n"
                     f"<b>This session stays active until YOU manually terminate it. "
                     f"Keep this file private — anyone with it can access the account.</b></blockquote>"),
            parse_mode="html")
    except Exception as ex:
        logger.error(f"session file send failed for {phone}: {ex}")

async def finalize_order(phone, order, code):
    """Records the sale once, schedules the 24h bot-session logout, and returns the OTP view."""
    uid = order['uid']
    order['otp'] = code
    if not order['paid']:
        order['paid'] = True
        cost = 0
        async with get_user_lock(uid):
            cur.execute("INSERT INTO orders (user_id, country, year, price, phone, otp) VALUES (?,?,?,?,?,?)",
                        (uid, order['country'], order['year'], order['price'], phone, code))
            _c = cur.execute("SELECT cost FROM stock WHERE phone=?", (phone,)).fetchone()
            cost = (_c[0] if _c else 0) or 0
            cur.execute("DELETE FROM stock WHERE phone=?", (phone,))
            cur.execute("""INSERT OR REPLACE INTO sold_sessions
                           (phone, user_id, session_file, country, year, twofa, otp, start_time, logout_at, devices_cleared)
                           VALUES (?,?,?,?,?,?,?,?,?,0)""",
                        (phone, uid, order['sess'], order['country'], order['year'], order['twofa'], code,
                         order['start_time'], None))
            db.commit()
        await send_purchase_log(order, phone)
        try:
            from plugins.profit import notify_profit
            await notify_profit(uid, "Server 1 · Telegram", f"{order['country']} {order['year']} +{phone}", order['price'], cost)
        except Exception as ex:
            logger.warning(f"profit log failed for {phone}: {ex}")
        await send_session_file(uid, phone, order)
    else:
        cur.execute("UPDATE sold_sessions SET otp=? WHERE phone=?", (code, phone))
        db.commit()
    return otp_text(phone, order), otp_buttons(phone, order)

async def logout_old_devices(phone, order):
    """Terminates every OLD login of the account, keeping the buyer's new device and the bot session."""
    from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
    client = order['client']
    killed, kept, skipped = 0, 0, 0
    auths = await client(GetAuthorizationsRequest())
    for a in auths.authorizations:
        if getattr(a, 'current', False) or a.hash == 0:
            kept += 1          # the bot's own session, needed until the 24h auto-logout
            continue
        created = getattr(a, 'date_created', None)
        if created and created.timestamp() >= order['start_time'] - 60:
            kept += 1          # the buyer's brand new login
            continue
        try:
            await client(ResetAuthorizationRequest(hash=a.hash))
            killed += 1
        except Exception as ex:
            skipped += 1
            logger.warning(f"Could not reset auth for {phone}: {ex}")
        await asyncio.sleep(0.3)
    return killed, kept, skipped

async def schedule_bot_logout(phone, logout_at):
    """After 24h the bot's own session is removed so only the buyer stays logged in."""
    delay = max(0, logout_at - time.time())
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    await run_bot_logout(phone)

async def run_bot_logout(phone):
    row = cur.execute("SELECT user_id, session_file FROM sold_sessions WHERE phone=?", (phone,)).fetchone()
    order = active_orders.pop(phone, None)
    sess = session_base(order['sess'] if order else (row[1] if row else ""))
    uid = order['uid'] if order else (row[0] if row else None)
    client = order['client'] if order else None
    try:
        if client is None and sess:
            client = TelegramClient(sess, API_ID, API_HASH)
            await client.connect()
        if client:
            try:
                if await client.is_user_authorized():
                    await client.log_out()
            except Exception as ex:
                logger.warning(f"bot log_out failed for {phone}: {ex}")
            try: await client.disconnect()
            except Exception: pass
    except Exception as ex:
        logger.warning(f"bot logout error for {phone}: {ex}")
    remove_session_files(sess)
    cur.execute("DELETE FROM sold_sessions WHERE phone=?", (phone,))
    db.commit()
    if uid:
        try:
            await bot.send_message(uid, f"{P_YES} <b>𝐁ᴏᴛ ʟᴏɢɪɴ ʀᴇᴍᴏᴠᴇᴅ</b>\n\n{P_PHONE} <code>{phone}</code> — ᴛʜᴇ 24-ʜᴏᴜʀ ᴡɪɴᴅᴏᴡ ᴇɴᴅᴇᴅ, sᴏ ᴛʜᴇ ʙᴏᴛ's ᴏᴡɴ sᴇssɪᴏɴ ʜᴀs ʙᴇᴇɴ ʟᴏɢɢᴇᴅ ᴏᴜᴛ. 𝐘ᴏᴜʀ ᴅᴇᴠɪᴄᴇ sᴛᴀʏs ʟᴏɢɢᴇᴅ ɪɴ.")
        except Exception:
            pass

async def restore_order(phone):
    """Rebuilds a paid order from the database after a restart so the buttons keep working."""
    row = cur.execute("SELECT user_id, session_file, country, year, twofa, otp, start_time, logout_at FROM sold_sessions WHERE phone=?", (phone,)).fetchone()
    if not row: return None
    uid, sess, country, year, twofa, otp, start_time, logout_at = row
    client = TelegramClient(session_base(sess), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return None
    except Exception as ex:
        logger.warning(f"restore_order failed for {phone}: {ex}")
        return None
    order = {'uid': uid, 'client': client, 'sess': session_base(sess), 'start_time': start_time or time.time(),
             'paid': True, 'price': 0, 'country': country, 'year': year,
             'c_icon': get_flag_by_country_name(country), 'twofa': twofa, 'msg_id': None,
             'otp': otp, 'logout_at': logout_at}
    active_orders[phone] = order
    return order

async def resume_sold_sessions():
    """Sold sessions now stay alive until the buyer manually terminates them,
    so there is nothing to schedule after a restart. Kept as a safe no-op."""
    return

async def auto_otp_task(phone):
    if phone not in active_orders: return

    order = active_orders[phone]
    start_time = order['start_time']
    uid = order['uid']
    msg_id = order['msg_id']

    while time.time() - start_time < AUTO_CANCEL_SECONDS:
        if phone not in active_orders: return
        try:
            code = await fetch_latest_otp(order)
            if code:
                text, btns = await finalize_order(phone, order, code)
                try: await bot.edit_message(uid, msg_id, text, buttons=btns)
                except MessageNotModifiedError: pass
                await send_delivery_thanks(bot, uid, f"session:{phone}:{order['start_time']}")
                return
        except Exception as ex:
            logger.error(f"OTP fetch error for {phone}: {ex}")
        await asyncio.sleep(6)

    if phone in active_orders and not active_orders[phone]['paid']:
        order = active_orders.pop(phone)
        try: await order['client'].disconnect()
        except Exception: pass

        async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (order['price'], uid))
            cur.execute("UPDATE stock SET available=1 WHERE phone=?", (phone,))
            db.commit()

        try: await bot.edit_message(uid, msg_id, f"{P_TIME} <b>𝐎ʀᴅᴇʀ 𝐄xᴘɪʀᴇᴅ!</b>\n𝐓ʜᴇ 10-ᴍɪɴᴜᴛᴇ ʟɪᴍɪᴛ ғᴏʀ <code>{phone}</code> ʀᴀɴ ᴏᴜᴛ. 𝐘ᴏᴜʀ ᴍᴏɴᴇʏ ({P_INR}{order['price']}) ʜᴀs ʙᴇᴇɴ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ʀᴇғᴜɴᴅᴇᴅ.")
        except Exception: pass

def register_buy(bot):
    try:
        asyncio.ensure_future(resume_sold_sessions())
    except Exception as ex:
        logger.warning(f"could not resume 24h logouts: {ex}")

    @bot.on(events.NewMessage(pattern=r"(?i)^(𝐁ᴜʏ 𝐀ᴄᴄᴏᴜɴᴛ|🛒 𝐁ᴜʏ 𝐀ᴄᴄᴏᴜɴᴛ|🛒 Buy Account|📁 Buy Sessions)$"))
    async def msg_buy(e):
        if not await require_join(bot, e): return
        mode = 'bulk' if e.text == '📁 Buy Sessions' else 'single'
        await show_countries(e, mode, 1)

    @bot.on(events.CallbackQuery(pattern=r"^bc\|(.+)\|(.+)$"))
    async def cb_bc(e):
        if not await require_join(bot, e): return
        p = e.pattern_match
        await show_years(e, p.group(1).decode(), p.group(2).decode())

    @bot.on(events.CallbackQuery(pattern=r"^s1_search\|(.+)$"))
    async def cb_s1_search(e):
        s1_search_state[e.sender_id] = e.pattern_match.group(1).decode()
        await e.answer()
        await e.respond("<blockquote>🔍 <b>𝐒ᴇᴀʀᴄʜ 𝐂ᴏᴜɴᴛʀʏ</b></blockquote>\n\n"
                        "<blockquote>𝐒ᴇɴᴅ ᴄᴏᴜɴᴛʀʏ <b>ɴᴀᴍᴇ</b> (India), <b>2-ʟᴇᴛᴛᴇʀ ᴄᴏᴅᴇ</b> (IN) ᴏʀ <b>ᴅɪᴀʟ ᴄᴏᴅᴇ</b> (+91).</blockquote>")

    @bot.on(events.NewMessage(func=lambda e: e.is_private and e.sender_id in s1_search_state and not (e.text or "").startswith("/")))
    async def msg_s1_search(e):
        mode = s1_search_state.pop(e.sender_id, "single")
        await s1_search(e, mode, e.text or "")

    @bot.on(events.CallbackQuery(pattern=r"^pg_c\|(.+)\|(\d+)$"))
    async def cb_pg_c(e):
        p = e.pattern_match
        await show_countries(e, p.group(1).decode(), int(p.group(2).decode()))

    @bot.on(events.CallbackQuery(pattern=r"^by\|(.+)\|(.+)\|(\d+)\|(\d+)$"))
    async def cb_by_single(e):
        if not await require_join(bot, e): return
        p = e.pattern_match
        await confirm_purchase(e, p.group(2).decode(), p.group(3).decode(), p.group(4).decode(), split_mode(p.group(1).decode())[1])

    @bot.on(events.CallbackQuery(pattern=r"^buy_cf\|(.+?)\|(\d+)\|(\d+)(?:\|(fake|old|good))?$"))
    async def cb_buy_cf(e):
        if not await require_join(bot, e): return
        p = e.pattern_match
        cat = p.group(4).decode() if p.group(4) else None
        await process_purchase(e, p.group(1).decode(), p.group(2).decode(), p.group(3).decode(), cat)

    @bot.on(events.CallbackQuery(pattern=rb"^s1_cats$"))
    async def cb_s1_cats(e):
        if not await require_join(bot, e): return
        await show_s1_categories(e)

    @bot.on(events.CallbackQuery(pattern=rb"^s1_cat\|(fake|old|good)$"))
    async def cb_s1_cat(e):
        if not await require_join(bot, e): return
        await show_countries(e, "single:" + e.pattern_match.group(1).decode(), 1)

    @bot.on(events.CallbackQuery(pattern=rb"^buy_again$"))
    async def cb_buy_again(e):
        if not await require_join(bot, e): return
        await e.answer()
        await show_countries(e, 'single', 1)

    @bot.on(events.CallbackQuery(pattern=r"^show_otp\|(.+)$"))
    async def cb_show_otp(e):
        phone = e.pattern_match.group(1).decode()
        order = active_orders.get(phone)
        code = order.get('otp') if order else None
        if not code:
            row = cur.execute("SELECT otp FROM sold_sessions WHERE phone=?", (phone,)).fetchone()
            code = row[0] if row else None
        await e.answer(f"OTP: {code}" if code else "⚠️ No OTP yet.", alert=True)

    @bot.on(events.CallbackQuery(pattern=r"^show_2fa\|(.+)$"))
    async def cb_show_2fa(e):
        phone = e.pattern_match.group(1).decode()
        order = active_orders.get(phone)
        pwd = order.get('twofa') if order else None
        if not pwd:
            row = cur.execute("SELECT twofa FROM sold_sessions WHERE phone=?", (phone,)).fetchone()
            pwd = row[0] if row else None
        await e.answer(f"2FA: {pwd}" if pwd and pwd != "None" else "🔓 No 2FA password.", alert=True)

    @bot.on(events.CallbackQuery(pattern=r"^get_otp_again\|(.+)$"))
    async def cb_get_otp_again(e):
        phone = e.pattern_match.group(1).decode()
        order = active_orders.get(phone) or await restore_order(phone)
        if not order: return await e.answer("⚠️ Session expired.", alert=True)
        if e.sender_id != order['uid']: return await e.answer("⚠️ This is not your order.", alert=True)
        if order.get('msg_id') is None: order['msg_id'] = e.message_id
        await e.answer("🔄 Fetching latest OTP...")
        try:
            code = await fetch_latest_otp(order)
            if not code:
                return await e.answer("⚠️ No new OTP found yet. Try again in a few seconds.", alert=True)
            text, btns = await finalize_order(phone, order, code)
            try: await bot.edit_message(order['uid'], order['msg_id'], text, buttons=btns)
            except MessageNotModifiedError: pass
            await send_delivery_thanks(bot, order['uid'], f"session:{phone}:{order['start_time']}")
        except Exception as ex:
            logger.error(f"Manual OTP fetch error for {phone}: {ex}")
            await e.answer("❌ Error fetching OTP. Please try again.", alert=True)

    @bot.on(events.CallbackQuery(pattern=r"^logout_bot\|(.+)$"))
    async def cb_logout_bot(e):
        phone = e.pattern_match.group(1).decode()
        order = active_orders.get(phone) or await restore_order(phone)
        if not order:
            return await e.answer("⚠️ This order is no longer active.", alert=True)
        if order.get('msg_id') is None: order['msg_id'] = e.message_id
        if e.sender_id != order['uid']:
            return await e.answer("⚠️ This is not your order.", alert=True)
        if not order.get('paid'):
            return await e.answer("⚠️ Please log in and get your OTP first.", alert=True)
        await e.answer("🚪 Removing old logins...")
        try:
            killed, kept, skipped = await logout_old_devices(phone, order)
        except Exception as ex:
            logger.error(f"logout_old_devices failed for {phone}: {ex}")
            return await e.answer("❌ Could not remove old devices. Try again in a minute.", alert=True)
        note = (f"<blockquote>{P_YES} <b>𝐎ʟᴅ 𝐋ᴏɢɪɴs 𝐑ᴇᴍᴏᴠᴇᴅ</b>\n\n"
                f"{P_PHONE} <code>{phone}</code>\n"
                f"🚪 𝐑ᴇᴍᴏᴠᴇᴅ: <b>{killed}</b>\n"
                f"{P_YES} 𝐊ᴇᴘᴛ (ʏᴏᴜʀ ᴅᴇᴠɪᴄᴇ + ʙᴏᴛ): <b>{kept}</b>\n"
                + (f"{P_WARN} 𝐓ᴏᴏ ɴᴇᴡ ᴛᴏ ʀᴇᴍᴏᴠᴇ: <b>{skipped}</b>\n" if skipped else "")
                + f"\n{P_TIME} 𝐓ʜᴇ ʙᴏᴛ's sᴇssɪᴏɴ sᴛᴀʏs ᴀᴄᴛɪᴠᴇ ᴜɴᴛɪʟ ʏᴏᴜ ᴛᴀᴘ \"🗑 𝐓ᴇʀᴍɪɴᴀᴛᴇ 𝐁ᴏᴛ 𝐒ᴇssɪᴏɴ\".</blockquote>")
        try:
            await bot.edit_message(order['uid'], order['msg_id'], otp_text(phone, order) + "\n" + note,
                                   buttons=otp_buttons(phone, order))
        except MessageNotModifiedError:
            pass
        except Exception as ex:
            logger.warning(f"logout notice edit failed: {ex}")

    @bot.on(events.CallbackQuery(pattern=r"^term_sess\|(.+)$"))
    async def cb_term_sess(e):
        phone = e.pattern_match.group(1).decode()
        order = active_orders.get(phone) or await restore_order(phone)
        if not order:
            return await e.answer("⚠️ This order is no longer active.", alert=True)
        if e.sender_id != order['uid']:
            return await e.answer("⚠️ This is not your order.", alert=True)
        if not order.get('paid'):
            return await e.answer("⚠️ Please log in and get your OTP first.", alert=True)
        # Only terminate the bot session if the buyer has actually logged in.
        try:
            from telethon.tl.functions.account import GetAuthorizationsRequest
            auths = await order['client'](GetAuthorizationsRequest())
            buyer_logged_in = any(
                (not getattr(a, 'current', False)) and a.hash != 0
                and getattr(a, 'date_created', None)
                and a.date_created.timestamp() >= order['start_time'] - 60
                for a in auths.authorizations)
        except Exception as ex:
            logger.warning(f"login check failed for {phone}: {ex}")
            return await e.answer("❌ Could not verify your login. Try again in a minute.", alert=True)
        if not buyer_logged_in:
            return await e.answer("⚠️ You haven't logged in to the account yet. Log in first — the bot session will NOT be terminated until you do.", alert=True)
        await e.answer("🗑 Terminating the bot session...")
        try:
            await run_bot_logout(phone)
        except Exception as ex:
            logger.error(f"manual bot-session terminate failed for {phone}: {ex}")
            return await e.answer("❌ Could not terminate the bot session. Try again in a minute.", alert=True)
        try:
            await bot.send_message(order['uid'],
                f"<blockquote>{P_YES} <b>𝐁ᴏᴛ 𝐒ᴇssɪᴏɴ 𝐓ᴇʀᴍɪɴᴀᴛᴇᴅ</b>\n\n"
                f"{P_PHONE} <code>{phone}</code>\n"
                f"<b>The bot's login for this account has been logged out and its session file deleted. "
                f"Your own session stays active until you terminate it yourself.</b></blockquote>")
        except Exception as ex:
            logger.warning(f"terminate notice failed for {phone}: {ex}")
