#MADE_BY_SHIV

import os
from telethon import events, Button
from telethon.errors import MessageNotModifiedError
from database import cur, db, get_support_url, to_usd, get_flag_by_country_name
from config import P_NO, P_MONEY, P_INR, P_GIFT, P_USERS, PE_LOCATION, PE_GIFT, PE_CROWN
from utils.states import session_buy_state, deposit_input, active_orders, waiting_proof
from plugins.start import send_main_menu
from utils.helpers import check_channel_joined
from utils.keyboards import style_btn
from database import is_admin

def register_callbacks(bot):
    @bot.on(events.CallbackQuery(pattern=b"^tc_accept$"))
    async def cb_tc_accept(e):
        uid = e.sender_id
        cur.execute("UPDATE users SET terms_accepted=1 WHERE user_id=?", (uid,))
        db.commit()
        await e.answer("✅ Terms Accepted!", alert=True)
        await e.delete()
        await send_main_menu(bot, e, uid)

    @bot.on(events.CallbackQuery(pattern=b"^tc_reject$"))
    async def cb_tc_reject(e):
        try: await e.edit(f"{P_NO} You cannot use the bot without accepting the terms.")
        except MessageNotModifiedError: pass

    @bot.on(events.CallbackQuery(pattern=b"^cancel_action$"))
    async def cb_cancel_action(e):
        uid = e.sender_id
        in_deposit = uid in deposit_input or uid in waiting_proof
        in_buy = uid in session_buy_state
        deposit_input.pop(uid, None)
        session_buy_state.pop(uid, None)
        waiting_proof.pop(uid, None)
        await e.answer("Cancelled", alert=False)
        try: await e.delete()
        except Exception: pass
        # go back (menus fall back to a fresh message because the old one is removed) one step instead of just removing everything
        try:
            if in_deposit:
                from plugins.deposit import deposit_menu
                return await deposit_menu(e)
            if in_buy:
                from plugins.social import show_servers
                return await show_servers(e, "tg")
            from plugins.social import show_numbers
            return await show_numbers(e)
        except Exception:
            pass

    @bot.on(events.CallbackQuery(pattern=b"^verify_join$"))
    async def cb_verify_join(e):
        from utils.helpers import get_unjoined_channels, build_join_buttons, join_message
        uid = e.sender_id
        unjoined = await get_unjoined_channels(bot, uid)
        if unjoined:
            await e.answer(f"❌ {len(unjoined)} channel/group not joined yet!", alert=True)
            try: await e.edit(join_message(len(unjoined)), buttons=build_join_buttons(unjoined))
            except MessageNotModifiedError: pass
            return
        await e.answer("✅ Verified! You can buy now.", alert=True)
        try: await e.delete()
        except Exception: pass
        await send_main_menu(bot, e, uid)

    # ── Inline main menu ──
    @bot.on(events.CallbackQuery(pattern=b"^menu_(buy|whatsapp|numbers|recharge|account|smm|store|guide|settings|more|home|orders|balance|stock|refer)$"))
    async def cb_main_menu(e):
        from utils.keyboards import get_more_menu, get_main_inline_menu
        from utils.helpers import require_join
        act = e.pattern_match.group(1).decode()
        uid = e.sender_id
        await e.answer()
        if act == "buy":
            if not await require_join(bot, e): return
            from plugins.social import show_servers
            return await show_servers(e, "tg", back_to="menu_home")
        if act == "whatsapp":
            if not await require_join(bot, e): return
            from plugins.social import show_servers
            return await show_servers(e, "wa", back_to="menu_home")
        if act == "numbers":
            if not await require_join(bot, e): return
            from plugins.social import show_numbers
            return await show_numbers(e)
        if act == "recharge":
            from plugins.deposit import deposit_menu
            return await deposit_menu(e)
        if act == "account":
            from plugins.profile import profile_handler
            return await profile_handler(bot, e)
        if act == "smm":
            if not await require_join(bot, e): return
            from plugins.social import show_social_hub
            return await show_social_hub(e)
        if act == "store":
            if not await require_join(bot, e): return
            from plugins.repos import show_repos
            return await show_repos(e)
        if act == "guide":
            msg = ("<blockquote>📲 <b>𝐁𝐨𝐭 𝐆𝐮𝐢𝐝𝐞</b></blockquote>\n\n"
                   "<blockquote>1. Choose an account, OTP, or social service.\n"
                   "2. Recharge and pay the exact amount shown.\n"
                   "3. Tap <b>I HAVE PAID</b> after payment.\n"
                   "4. Keep the order screen open until delivery.</blockquote>")
            return await e.edit(msg, buttons=[[style_btn("Back", b"menu_home", "danger")]])
        if act == "settings":
            return await show_settings(e)
        if act == "more":
            try: return await e.edit(buttons=get_more_menu())
            except MessageNotModifiedError: return
        if act == "home":
            try: return await e.edit(buttons=get_main_inline_menu())
            except MessageNotModifiedError: return
        extra = [[style_btn("💳 𝐑ᴇᴄʜᴀʀɢᴇ 𝐍ᴏᴡ", b"menu_recharge", "success", icon=5409320020058584473)]] if act == "balance" else None
        await bot.send_message(uid, await _quick_text(act, uid), buttons=extra)

    async def show_settings(e):
        row = cur.execute("SELECT currency, language FROM users WHERE user_id=?", (e.sender_id,)).fetchone() or ("INR", "en")
        currency, language = row
        names = {"en": "🇬🇧 English", "hinglish": "🇮🇳 Hinglish", "hi": "🇮🇳 हिन्दी", "ru": "🇷🇺 Русский", "zh": "🇨🇳 中文", "ar": "🇸🇦 العربية"}
        mark = "● "
        btns = [
            [style_btn((mark if currency == "INR" else "") + "₹ INR", b"set_cur|INR", "success" if currency == "INR" else None),
             style_btn((mark if currency == "USD" else "") + "$ USD", b"set_cur|USD", "success" if currency == "USD" else None)],
        ]
        langs = list(names.items())
        for i in range(0, len(langs), 2):
            btns.append([style_btn((mark if language == code else "") + label, f"set_lang|{code}", "success" if language == code else None) for code, label in langs[i:i+2]])
        from plugins.notify import is_enabled as _nt_on
        _on = _nt_on(e.sender_id)
        btns.append([style_btn(f"🔔 New Country Alerts: {'ON' if _on else 'OFF'}", b"nt_set", "success" if _on else None)])
        btns.append([style_btn("Back", b"menu_home", "danger")])
        msg = (f"<blockquote><b>Settings</b>\n━━━━━━━━━━━━━━━━\n💱 Currency: {currency}\n🌐 Language: {names.get(language, names['en'])}</blockquote>\n\n"
               "<i>Your preference is saved. Checkout continues to show the gateway's payable currency.</i>")
        try: await e.edit(msg, buttons=btns)
        except MessageNotModifiedError: pass

    @bot.on(events.CallbackQuery(pattern=b"^nt_set$"))
    async def cb_nt_set(e):
        from plugins.notify import toggle_pref
        on = toggle_pref(e.sender_id)
        await e.answer("🔔 New country alerts ON" if on else "🔕 New country alerts OFF")
        await show_settings(e)

    @bot.on(events.CallbackQuery(pattern=rb"^set_cur\|(INR|USD)$"))
    async def cb_set_currency(e):
        cur.execute("UPDATE users SET currency=? WHERE user_id=?", (e.pattern_match.group(1).decode(), e.sender_id)); db.commit()
        await show_settings(e)

    @bot.on(events.CallbackQuery(pattern=rb"^set_lang\|(en|hinglish|hi|ru|zh|ar)$"))
    async def cb_set_language(e):
        cur.execute("UPDATE users SET language=? WHERE user_id=?", (e.pattern_match.group(1).decode(), e.sender_id)); db.commit()
        await show_settings(e)

    async def _quick_text(act, uid):
        if act == "balance":
            bal = (cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone() or [0])[0]
            return f"<blockquote>{PE_CROWN} <b>𝐘ᴏᴜʀ 𝐁ᴀʟᴀɴᴄᴇ:</b> <code>{P_INR}{bal}</code> | <code>${to_usd(bal):.2f}</code></blockquote>"
        if act == "orders":
            rows = cur.execute("SELECT phone, country, price, date FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
            if not rows: return f"<blockquote>{PE_GIFT} <b>𝐍ᴏ ᴏʀᴅᴇʀs ʏᴇᴛ.</b></blockquote>"
            return f"<blockquote>{PE_GIFT} <b>𝐌ʏ 𝐎ʀᴅᴇʀs</b></blockquote>\n" + "".join(
                f"<blockquote>{get_flag_by_country_name(cn)} {cn} | <code>{ph}</code>\n{P_MONEY} {P_INR}{pr} | 📅 {str(dt)[:10]}</blockquote>\n" for ph, cn, pr, dt in rows)
        if act == "stock":
            rows = cur.execute("SELECT country_name, COUNT(*) FROM stock WHERE available=1 GROUP BY country_name ORDER BY country_name").fetchall()
            if not rows: return f"<blockquote>{PE_LOCATION} 𝐍ᴏ sᴛᴏᴄᴋ ʀɪɢʜᴛ ɴᴏᴡ.</blockquote>"
            return f"<blockquote>{PE_LOCATION} <b>𝐀ᴠᴀɪʟᴀʙʟᴇ 𝐒ᴛᴏᴄᴋ</b></blockquote>\n" + "".join(
                f"<blockquote>{get_flag_by_country_name(cn)} <b>{cn}</b> — {c}</blockquote>\n" for cn, c in rows)
        me = await bot.get_me()
        pct_row = cur.execute("SELECT value FROM settings WHERE key='ref_percent'").fetchone()
        pct = pct_row[0] if pct_row else 3
        return (f"<blockquote>{P_GIFT} <b>𝐑ᴇғᴇʀ & 𝐄ᴀʀɴ {pct}%</b></blockquote>\n"
                f"<blockquote>🔗 <code>https://t.me/{me.username}?start=ref_{uid}</code></blockquote>")

    # ── Keyboard Button Handlers ──

    @bot.on(events.NewMessage(pattern=r"(?i)^(𝐌ʏ 𝐎ʀᴅᴇʀs|📦 𝐌ʏ 𝐎ʀᴅᴇʀs|📦 My Orders)$"))
    async def msg_my_orders(e):
        uid = e.sender_id
        rows = cur.execute("SELECT phone, country, price, date FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
        if not rows:
            return await e.respond(f"<blockquote>{PE_GIFT} <b>𝐌ʏ 𝐎ʀᴅᴇʀs</b></blockquote>\n\n<blockquote>𝐍ᴏ ᴏʀᴅᴇʀs ʏᴇᴛ. 𝐁ᴜʏ ʏᴏᴜʀ ғɪʀsᴛ ᴀᴄᴄᴏᴜɴᴛ!</blockquote>")
        msg = f"<blockquote>{PE_GIFT} <b>𝐌ʏ 𝐎ʀᴅᴇʀs</b> (𝐋ᴀsᴛ 10)</blockquote>\n\n"
        for ph, cn, pr, dt in rows:
            flag = get_flag_by_country_name(cn)
            msg += f"<blockquote>{flag} {cn} | <code>{ph}</code>\n{P_MONEY} {P_INR}{pr} | 📅 {dt[:10]}</blockquote>\n"
        await e.respond(msg)

    @bot.on(events.NewMessage(pattern=r"(?i)^(𝐁ᴀʟᴀɴᴄᴇ|💰 𝐁ᴀʟᴀɴᴄᴇ|💰 Balance)$"))
    async def msg_balance(e):
        uid = e.sender_id
        row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        bal = row[0] if row else 0
        msg = (f"<blockquote>{PE_CROWN} <b>𝐘ᴏᴜʀ 𝐁ᴀʟᴀɴᴄᴇ</b></blockquote>\n\n"
               f"<blockquote>{P_MONEY} <b>𝐁ᴀʟᴀɴᴄᴇ:</b> <code>{P_INR}{bal}</code>\n"
               f"💲 <b>𝐔𝐒𝐃:</b> <code>${to_usd(bal):.2f}</code></blockquote>")
        await e.respond(msg, buttons=[[style_btn("💳 𝐑ᴇᴄʜᴀʀɢᴇ 𝐍ᴏᴡ", b"menu_recharge", "success", icon=5409320020058584473)]])

    @bot.on(events.NewMessage(pattern=r"(?i)^(𝐒ᴛᴏᴄᴋ|📊 𝐒ᴛᴏᴄᴋ|📊 Stock)$"))
    async def msg_stock(e):
        rows = cur.execute("SELECT country_name, COUNT(*) FROM stock WHERE available=1 GROUP BY country_name ORDER BY country_name").fetchall()
        if not rows:
            return await e.respond(f"<blockquote>{PE_LOCATION} <b>𝐒ᴛᴏᴄᴋ</b></blockquote>\n\n<blockquote>𝐍ᴏ sᴛᴏᴄᴋ ᴀᴠᴀɪʟᴀʙʟᴇ ʀɪɢʜᴛ ɴᴏᴡ.</blockquote>")
        total = sum(c for _, c in rows)
        msg = f"<blockquote>{PE_LOCATION} <b>𝐀ᴠᴀɪʟᴀʙʟᴇ 𝐒ᴛᴏᴄᴋ</b> ({total} ᴛᴏᴛᴀʟ)</blockquote>\n\n"
        for cn, cnt in rows:
            flag = get_flag_by_country_name(cn)
            msg += f"<blockquote>{flag} <b>{cn}</b> — {cnt} ᴀᴄᴄᴏᴜɴᴛs</blockquote>\n"
        await e.respond(msg)

    @bot.on(events.NewMessage(pattern=r"(?i)^(𝐑ᴇғᴇʀ|🎁 𝐑ᴇғᴇʀ|🎁 Refer)$"))
    async def msg_refer(e):
        uid = e.sender_id
        me = await bot.get_me()
        bot_username = me.username or ""
        ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"
        ref_count = cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()[0]
        pct_row = cur.execute("SELECT value FROM settings WHERE key='ref_percent'").fetchone()
        pct = pct_row[0] if pct_row else 3
        msg = (f"<blockquote>{P_GIFT} <b>𝐑ᴇғᴇʀ & 𝐄ᴀʀɴ</b></blockquote>\n\n"
               f"<blockquote>{P_USERS} <b>𝐘ᴏᴜʀ 𝐑ᴇғᴇʀʀᴀʟs:</b> {ref_count}\n"
               f"💲 <b>𝐁ᴏɴᴜs:</b> {pct}% ᴏғ ᴇᴠᴇʀʏ ᴅᴇᴘᴏsɪᴛ</blockquote>\n\n"
               f"<blockquote>🔗 <b>𝐘ᴏᴜʀ 𝐋ɪɴᴋ:</b>\n<code>{ref_link}</code></blockquote>\n\n"
               f"<blockquote><i>𝐒ʜᴀʀᴇ ᴛʜɪs ʟɪɴᴋ ᴡɪᴛʜ ғʀɪᴇɴᴅs. 𝐖ʜᴇɴ ᴛʜᴇʏ ᴅᴇᴘᴏsɪᴛ, ʏᴏᴜ ᴇᴀʀɴ {pct}%!</i></blockquote>")
        await e.respond(msg)

    @bot.on(events.NewMessage(pattern=r"(?i)^(𝐒ᴜᴘᴘᴏʀᴛ|📩 𝐒ᴜᴘᴘᴏʀᴛ|📩 Support)$"))
    async def msg_support(e):
        url = get_support_url()
        msg = f"<blockquote>📩 <b>𝐒ᴜᴘᴘᴏʀᴛ</b></blockquote>\n\n<blockquote>𝐅ᴏʀ ᴀɴʏ ɪssᴜᴇs ᴏʀ ǫᴜᴇsᴛɪᴏɴs, ᴄᴏɴᴛᴀᴄᴛ ᴏᴜʀ sᴜᴘᴘᴏʀᴛ:</blockquote>"
        btns = [[Button.url("📩 𝐂ᴏɴᴛᴀᴄᴛ 𝐒ᴜᴘᴘᴏʀᴛ", url)]]
        await e.respond(msg, buttons=btns)
