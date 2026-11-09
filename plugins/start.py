import os
import time
from telethon import events, types
from telethon.errors import MessageNotModifiedError
from database import cur, db, ensure_user, is_user_banned, is_bot_online, is_admin
from utils.keyboards import get_persistent_menu, get_terms_buttons, get_join_buttons
from utils.helpers import check_channel_joined
from config import PE_FLOWER, PE_LOCATION, P_OFF, PE_HEART, PE_GIFT, P_GIFT, P_GLOBE, P_INR, LOG_CHANNEL_ID, bot
from utils.states import session_buy_state, deposit_input

BANNER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "image.jpg")

async def send_main_menu(bot, event, uid):
    from utils.keyboards import get_main_inline_menu
    from database import to_usd
    me = await bot.get_me()
    bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = bal_row[0] if bal_row else 0
    name = "User"
    try:
        u = await bot.get_entity(uid)
        name = (u.first_name or "User").replace("<", "").replace(">", "")
    except Exception:
        pass
    msg = (f"<blockquote>{PE_HEART} <b>𝐇ᴇʟʟᴏ {name}, 𝐖ᴇʟᴄᴏᴍᴇ ᴛᴏ 𝐁ᴇᴛᴀ 𝐀ᴄᴄᴏᴜɴᴛ 𝐒ᴛᴏʀᴇ</b></blockquote>\n\n"
           f"🚀 <b>𝐄ɴᴊᴏʏ ғᴀsᴛ & sᴀғᴇ ᴀᴄᴄᴏᴜɴᴛ ʙᴜʏɪɴɢ ᴇxᴘᴇʀɪᴇɴᴄᴇ!</b>\n"
           f"━━━━━━━━━━━━━━━━━━\n"
           f"• <b>𝐘ᴏᴜʀ 𝐈𝐃:</b> <code>{uid}</code>\n"
           f"• <b>𝐘ᴏᴜʀ 𝐁ᴀʟᴀɴᴄᴇ:</b> {P_INR}{bal} | ${to_usd(bal):.2f}\n\n"
           f"<blockquote>{PE_GIFT} 𝐓ᴇʟᴇɢʀᴀᴍ 𝐀ᴄᴄᴏᴜɴᴛs • 𝐁ᴏᴛ 𝐑ᴇᴘᴏs • 𝐒𝐌𝐌 𝐒ᴇʀᴠɪᴄᴇs</blockquote>")
    # 1) bottom keyboard  2) banner with inline menu
    try:
        await bot.send_message(uid, f"{PE_FLOWER} <b>𝐌ᴀɪɴ 𝐌ᴇɴᴜ ʟᴏᴀᴅᴇᴅ</b>", buttons=get_persistent_menu(uid))
    except Exception:
        pass
    try:
        await bot.send_file(uid, BANNER, caption=msg, buttons=get_main_inline_menu())
    except Exception:
        await bot.send_message(uid, msg, buttons=get_main_inline_menu())

def register_start(bot):
    @bot.on(events.CallbackQuery(pattern=rb"^visit_again$"))
    @bot.on(events.NewMessage(pattern=r"(?i)^(𝐒ᴛᴀʀᴛ|/start|🏠 𝐒ᴛᴀʀᴛ)"))
    async def handle_start(e):
        try:
            if isinstance(e, events.CallbackQuery.Event):
                await e.answer()
            uid = e.sender_id
            if not uid: return
            
            # Check old vs new user
            u_row = cur.execute("SELECT balance, total_deposited, referred_by FROM users WHERE user_id=?", (uid,)).fetchone()
            is_new = u_row is None
            
            # Check Referral parameter from /start ref_12345
            referrer_id = None
            text = getattr(e, 'text', '') or ''
            if len(text.split()) > 1:
                start_param = text.split()[1]
                if start_param.startswith("ref_"):
                    ref = start_param.replace("ref_", "")
                    if ref.isdigit() and int(ref) != uid:
                        referrer_id = int(ref)

            # Ensure user exists in database
            ensure_user(uid)

            # Save referral for new user
            if is_new and referrer_id:
                cur.execute("UPDATE users SET referred_by=? WHERE user_id=? AND referred_by IS NULL", (referrer_id, uid))
                db.commit()

            # --- START LOGGER (New / Old User + Referral Info) ---
            if LOG_CHANNEL_ID:
                try:
                    u = await e.get_sender()
                    first_name = (getattr(u, 'first_name', None) or "User").replace("<", "").replace(">", "")
                    username = f"@{u.username}" if getattr(u, 'username', None) else "None"
                    
                    # Current IST Date & Time
                    now_ist = time.strftime("%d %b %Y • %I:%M:%S %p IST", time.gmtime(time.time() + 19800))
                    
                    if is_new:
                        tot_row = cur.execute("SELECT COUNT(*) FROM users").fetchone()
                        total_users = (tot_row[0] if tot_row else 0)
                        
                        # Referrer details fetch
                        ref_text = "Direct (No Referral)"
                        if referrer_id:
                            try:
                                ru = await bot.get_entity(referrer_id)
                                r_name = (getattr(ru, 'first_name', None) or "User").replace("<", "").replace(">", "")
                                ref_text = f"<a href='tg://user?id={referrer_id}'>{r_name}</a> (<code>{referrer_id}</code>)"
                            except Exception:
                                ref_text = f"<code>{referrer_id}</code>"
                        
                        log_msg = (
                            f"🆕 <b>#New_User Started Bot</b>\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"👤 <b>Name:</b> <a href='tg://user?id={uid}'>{first_name}</a>\n"
                            f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
                            f"🏷 <b>Username:</b> {username}\n"
                            f"🔗 <b>Referred By:</b> {ref_text}\n"
                            f"📅 <b>Date & Time:</b> <code>{now_ist}</code>\n"
                            f"📊 <b>Total Users:</b> <code>{total_users}</code>"
                        )
                        
                        # Referrer ko bhi notify kar do
                        if referrer_id:
                            try:
                                await bot.send_message(
                                    referrer_id,
                                    f"🎉 <b>New Referral Joined!</b>\n\n"
                                    f"👤 <b>User:</b> {first_name}\n"
                                    f"🆔 <b>ID:</b> <code>{uid}</code>"
                                )
                            except Exception:
                                pass
                    else:
                        bal = u_row[0] if u_row else 0
                        total_dep = u_row[1] if u_row else 0
                        old_ref = u_row[2] if (u_row and len(u_row) > 2) else None
                        ref_info = f"<code>{old_ref}</code>" if old_ref else "Direct"
                        
                        log_msg = (
                            f"🔄 <b>#Old_User Started Bot</b>\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"👤 <b>Name:</b> <a href='tg://user?id={uid}'>{first_name}</a>\n"
                            f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
                            f"🏷 <b>Username:</b> {username}\n"
                            f"💰 <b>Balance:</b> {P_INR}{bal}\n"
                            f"💳 <b>Total Deposited:</b> {P_INR}{total_dep}\n"
                            f"🔗 <b>Invited By:</b> {ref_info}\n"
                            f"📅 <b>Date & Time:</b> <code>{now_ist}</code>"
                        )
                    
                    await bot.send_message(LOG_CHANNEL_ID, log_msg, link_preview=False)
                except Exception as log_err:
                    print(f"Start Logger Error: {log_err}")
            # ----------------------------------------------------

            if is_user_banned(uid): return

            if not is_bot_online() and not is_admin(uid):
                return await e.respond(f"{P_OFF} <b>Bot is currently under maintenance.</b> Please try again later.")
            
            session_buy_state.pop(uid, None)
            deposit_input.pop(uid, None)

            row = cur.execute("SELECT terms_accepted FROM users WHERE user_id=?", (uid,)).fetchone()
            terms_acc = row[0] if row else 0
            if not terms_acc:
                from plugins.social import TERMS_TEXT
                msg = TERMS_TEXT
                return await e.respond(msg, buttons=get_terms_buttons())

            await send_main_menu(bot, e, uid)
        except Exception as ex: 
            print(f"Start Error: {ex}")
