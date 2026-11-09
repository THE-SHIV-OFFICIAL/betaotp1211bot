#MADE_BY_SHIV

import os
import re
import html
import urllib.parse
import io
import time
import asyncio
import random
import aiohttp
from PIL import Image
from telethon import events, Button
from telethon.errors import MessageNotModifiedError
from database import ensure_user, cur, db, get_usdt_rate, update_balance, to_usd, is_admin
from config import PE_GIFT, PE_LIGHTNING, P_MONEY, P_CARD, P_UPI, P_CW, P_NO, P_YES, P_WARN, P_INR, P_USDT, P_KEY, PE_CHECK, P_ACC, P_ID, LOG_CHANNEL_ID, PAYMENT_LOG_CHANNELS, ADMIN_ID, CWALLET_QR, CWALLET_ID, UPI_ID, UPI_NAME, BINANCE_ID, BINANCE_QR, ADMIN_IDS, bot, logger
from utils.keyboards import style_btn
from utils.states import deposit_input, waiting_proof, admin_dep_state, custom_dep_amt, get_user_lock
from utils import paygate

def _pay(key, default):
    row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row and row[0] else default

async def deposit_menu(event):
    UPI_ID, BINANCE_ID, CWALLET_ID = _pay("upi_id", _U), _pay("binance_id", _B), _pay("cwallet_id", _C)
    btns = []
    if paygate.is_enabled():
        q = [50, 100, 200, 500, 1000, 2000]
        btns += [[style_btn(f"{P_INR}{a}", f"pgamt|{a}", "success", icon=5409271925014801629) for a in q[i:i+3]] for i in (0, 3)]
        btns.append([style_btn("✍️ 𝐂ᴜsᴛᴏᴍ 𝐀ᴍᴏᴜɴᴛ (𝐀ᴜᴛᴏ 𝐔𝐏𝐈)", "depm_UPI", "primary", icon=5409271925014801629)])
    elif UPI_ID: btns.append([style_btn("𝐀ᴜᴛᴏ 𝐔𝐏𝐈 (𝐈ɴsᴛᴀɴᴛ)" if paygate.is_enabled() else "𝐀ᴅᴅ 𝐅ᴜɴᴅs ʙʏ 𝐔𝐏𝐈", "depm_UPI", "success", icon=5409271925014801629)])
    if BINANCE_ID: btns.append([style_btn("𝐁ɪɴᴀɴᴄᴇ 𝐏ᴀʏ (𝐔𝐒𝐃𝐓)", "depm_Binance", "primary", icon=5440627033111557670)])
    if CWALLET_ID: btns.append([style_btn("𝐂ᴡᴀʟʟᴇᴛ (5% 𝐁𝐎𝐍𝐔𝐒)", "depm_Cwallet", "primary", icon=5440627033111557670)])
    
    customs = cur.execute("SELECT name FROM custom_payments").fetchall()
    for c in customs:
        btns.append([style_btn(f"{c[0]}", f"depm_{c[0]}", "primary", icon=5408832111773757273)])
    btns.append([style_btn("𝐁ᴀᴄᴋ", "menu_home", "danger", icon=6129812419028982717)])
    
    msg = f"<blockquote>{PE_GIFT} <b>𝐀ᴅᴅ 𝐅ᴜɴᴅs</b>\n\n𝐓ᴀᴘ ᴀɴ ᴀᴍᴏᴜɴᴛ → 𝐐𝐑 ᴀᴀʏᴇɢᴀ → 𝐏ᴀʏ ᴋᴀʀᴏ → 𝐁ᴀʟᴀɴᴄᴇ ᴀᴜᴛᴏ ᴀᴅᴅ ✅\n𝐘ᴀ ɴɪᴄʜᴇ sᴇ ᴅᴜsʀᴀ ᴍᴇᴛʜᴏᴅ ᴄʜᴜɴᴏ:</blockquote>"
    if isinstance(event, events.CallbackQuery.Event):
        try:
            return await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            return
        except Exception:
            try: await event.delete()
            except Exception: pass
    await event.respond(msg, buttons=btns)

async def manual_deposit_init(event, method):
    uid = event.sender_id
    deposit_input[uid] = {'step': 'wait_amt', 'method': method}
    await event.edit(f"{P_MONEY} <b>𝐄ɴᴛᴇʀ 𝐃ᴇᴘᴏsɪᴛ 𝐀ᴍᴏᴜɴᴛ (ɪɴ {P_INR}):</b>\n\n<i>𝐌ɪɴɪᴍᴜᴍ ᴅᴇᴘᴏsɪᴛ ɪs {P_INR}10. 𝐐𝐑 ᴇxᴘɪʀᴇs ɪɴ 10 ᴍɪɴᴜᴛᴇs.</i>", buttons=[[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", "cancel_action")]])

async def process_referral_bonus(user_id, amt):
    try:
        row = cur.execute("SELECT referred_by FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or not row[0]: return
        ref_id = row[0]
        
        pct_row = cur.execute("SELECT value FROM settings WHERE key='ref_percent'").fetchone()
        pct = int(pct_row[0]) if pct_row else 3
        
        bonus = int(amt * (pct / 100))
        if bonus <= 0: return
        
        async with get_user_lock(ref_id):
            update_balance(ref_id, bonus)
            db.commit()
            
        try: await bot.send_message(int(ref_id), f"{PE_GIFT} <b>Referral Bonus!</b>\nYour friend deposited {P_INR}{amt}. You received <b>{P_INR}{bonus}</b> ({pct}%) in your balance!")
        except: pass
    except Exception as e: logger.error(f"Ref bonus error: {e}")

def get_admin_custom_keypad(dep_id):
    return [
        [style_btn("1", f"dkp|{dep_id}|1", "primary", icon=5375125990118793401), style_btn("2", f"dkp|{dep_id}|2", "primary", icon=5409098988156629257), style_btn("3", f"dkp|{dep_id}|3", "primary", icon=6154249597532248059)],
        [style_btn("4", f"dkp|{dep_id}|4", "primary", icon=5796170975699544141), style_btn("5", f"dkp|{dep_id}|5", "primary", icon=5409320020058584473), style_btn("6", f"dkp|{dep_id}|6", "primary", icon=5409098988156629257)],
        [style_btn("7", f"dkp|{dep_id}|7", "primary", icon=6129779562529168023), style_btn("8", f"dkp|{dep_id}|8", "primary", icon=5355292788923593967), style_btn("9", f"dkp|{dep_id}|9", "primary", icon=5408832111773757273)],
        [style_btn("Del", f"dkp|{dep_id}|del", "danger", icon=6129732880529628243), style_btn("0", f"dkp|{dep_id}|0", "primary", icon=6154249597532248059), style_btn("Confirm", f"dkp|{dep_id}|conf", "success", icon=5409320020058584473)],
        [style_btn("𝐂ᴀɴᴄᴇʟ", f"dkp|{dep_id}|cancel", "danger", icon=6129888444245089008)]
    ]

# We will skip the automated UPI part in this script to save space if needed, 
# or I can port it directly. The user had a keypad logic for UPI amounts.
def get_keypad():
    return [
        [style_btn("1", b"kp_1", style_type="primary", icon=5408832111773757273), style_btn("2", b"kp_2", style_type="primary", icon=5408832111773757273), style_btn("3", b"kp_3", style_type="primary", icon=6129888444245089008)],
        [style_btn("4", b"kp_4", style_type="primary", icon=6064275556008989746), style_btn("5", b"kp_5", style_type="primary", icon=6129627894349045589), style_btn("6", b"kp_6", style_type="primary", icon=5409320020058584473)],
        [style_btn("7", b"kp_7", style_type="primary", icon=5375125990118793401), style_btn("8", b"kp_8", style_type="primary", icon=6129731974291527294), style_btn("9", b"kp_9", style_type="primary", icon=6170048080679801421)],
        [style_btn("Del", b"kp_del", style_type="danger", icon=6203982793379154737), style_btn("0", b"kp_0", style_type="primary", icon=5408832111773757273), style_btn("Confirm", b"kp_done", style_type="success", icon=6064310143380625195)],
        [style_btn("𝐂ᴀɴᴄᴇʟ", b"cancel_action", style_type="danger", icon=5796170975699544141)]
    ]

_U, _UN, _B, _BQ, _C = UPI_ID, UPI_NAME, BINANCE_ID, BINANCE_QR, CWALLET_ID

DEPOSIT_EXPIRY = 600  # 10 minutes

async def _user_line(uid):
    try:
        u = await bot.get_entity(int(uid))
        name = html.escape((u.first_name or "User") + (" " + u.last_name if getattr(u, "last_name", None) else ""))
        un = f" (@{u.username})" if getattr(u, "username", None) else ""
        return f"<a href='tg://user?id={uid}'>{name}</a>{un} · <code>{uid}</code>"
    except Exception:
        return f"<code>{uid}</code>"


async def log_payment_event(title, uid, amount, method="-", prev_bal=None, by=None, extra=""):
    """Detailed entry in the payment logger group."""
    from utils.logsend import payment_log
    lines = [f"<blockquote>{PE_CHECK} <b>{title}</b></blockquote>",
             f"{P_ACC} <b>User:</b> {await _user_line(uid)}",
             f"{P_MONEY} <b>Amount:</b> {P_INR}{amount}",
             f"{P_CARD} <b>Method:</b> {html.escape(str(method))}"]
    if prev_bal is not None:
        try: new_bal = round(float(prev_bal) + float(amount), 2)
        except Exception: new_bal = "-"
        lines.append(f"📉 <b>Old Balance:</b> {P_INR}{prev_bal} · 📈 <b>New Balance:</b> {P_INR}{new_bal}")
    if by: lines.append(f"👮 <b>Approved by:</b> <code>{by}</code>")
    if extra: lines.append(extra)
    lines.append(f"🕒 {time.strftime('%d %b %Y • %I:%M %p')}")
    await payment_log(bot, "\n".join(lines))

MIN_DEPOSIT = 10

async def _replace_qr_with_expired(bot, uid, msg_id, txt):
    """Delete the QR photo (a photo message can't be edited into text) and send
    the timeout notice with a Deposit Now button."""
    if msg_id:
        try: await bot.delete_messages(uid, msg_id)
        except Exception as ex: logger.warning("QR delete failed %s/%s: %s", uid, msg_id, ex)
    btns = [[style_btn("💳 𝐃ᴇᴘᴏsɪᴛ 𝐍ᴏᴡ", b"menu_recharge", "success", icon=5409320020058584473)]]
    try: await bot.send_message(uid, txt, buttons=btns)
    except Exception as ex: logger.warning("expiry notice failed %s: %s", uid, ex)


async def expire_deposit(bot, uid, oid):
    """After 10 min: kill the QR / payment request if no proof was sent."""
    await asyncio.sleep(DEPOSIT_EXPIRY)
    info = waiting_proof.get(uid)
    if not info or info.get('order_id') != oid:
        return
    waiting_proof.pop(uid, None)
    txt = (f"<blockquote>⌛ <b>𝐏ᴀʏᴍᴇɴᴛ 𝐒ᴇssɪᴏɴ 𝐄xᴘɪʀᴇᴅ</b>\n\n🧾 𝐎ʀᴅᴇʀ: <code>{oid}</code>\n{P_MONEY} 𝐀ᴍᴏᴜɴᴛ: {P_INR}{info['amount']}\n\n"
           f"⚠️ 𝐐𝐑 ᴅᴇʟᴇᴛᴇᴅ — ᴅᴏ ɴᴏᴛ ᴘᴀʏ ᴏɴ ɪᴛ ɴᴏᴡ.\n👇 𝐓ᴀᴘ <b>𝐃ᴇᴘᴏsɪᴛ 𝐍ᴏᴡ</b> ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ɴᴇᴡ ᴏɴᴇ.</blockquote>")
    await _replace_qr_with_expired(bot, uid, info.get('msg_id'), txt)

# ================= AUTO UPI (BETA payment gateway) =================
PAYGATE_POLL_SECONDS = 5

cur.execute("""CREATE TABLE IF NOT EXISTS gateway_orders (
    order_id TEXT PRIMARY KEY, user_id INTEGER, amount INTEGER, pay_amount REAL,
    status TEXT DEFAULT 'PENDING', msg_id INTEGER, created_at INTEGER)""")
for _col in ("buy_cb TEXT", "buy_label TEXT"):
    try: cur.execute(f"ALTER TABLE gateway_orders ADD COLUMN {_col}")
    except Exception: pass
db.commit()

async def credit_gateway_order(bot, oid):
    """Credit balance exactly once for a PAID gateway order."""
    row = cur.execute("SELECT user_id, amount, status, pay_amount FROM gateway_orders WHERE order_id=?", (oid,)).fetchone()
    if not row or row[2] == 'PAID': return
    uid, amt, _, pay_amt = row
    async with get_user_lock(uid):
        row = cur.execute("SELECT status FROM gateway_orders WHERE order_id=?", (oid,)).fetchone()
        if not row or row[0] == 'PAID': return
        ensure_user(uid)
        prev_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        prev_bal = prev_row[0] if prev_row else 0
        update_balance(uid, amt)
        cur.execute("UPDATE gateway_orders SET status='PAID' WHERE order_id=?", (oid,))
        cur.execute("INSERT INTO deposits (user_id, amount, method_name, status) VALUES (?,?,?,?)", (uid, amt, "AutoUPI", "approved"))
        cur.execute("UPDATE users SET total_deposited = total_deposited + ? WHERE user_id=?", (amt, uid))
        db.commit()
    await process_referral_bonus(uid, amt)
    extra_row = cur.execute("SELECT msg_id, buy_cb, buy_label FROM gateway_orders WHERE order_id=?", (oid,)).fetchone()
    qr_msg, buy_cb, buy_label = extra_row if extra_row else (None, None, None)
    txt = (f"<blockquote>{PE_CHECK} <b>𝐏ᴀʏᴍᴇɴᴛ 𝐕ᴇʀɪғɪᴇᴅ!</b>\n\n🧾 𝐎ʀᴅᴇʀ: <code>{oid}</code>\n"
           f"{P_MONEY} <b>𝐀ᴅᴅᴇᴅ:</b> ${to_usd(amt):.2f} ({P_INR}{amt})\n"
           f"📉 <b>𝐏ʀᴇᴠɪᴏᴜs:</b> ${to_usd(prev_bal):.2f} ({P_INR}{prev_bal})\n"
           f"📈 <b>𝐍ᴇᴡ 𝐁ᴀʟᴀɴᴄᴇ:</b> ${to_usd(prev_bal+amt):.2f} ({P_INR}{prev_bal+amt})</blockquote>")
    btns = None
    if buy_cb:
        txt += f"\n\n<blockquote>🛒 <b>𝐘ᴏᴜʀ ᴘᴜʀᴄʜᴀsᴇ ɪs ʀᴇᴀᴅʏ!</b>\n👇 𝐓ᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ɪᴛ ɴᴏᴡ.</blockquote>"
        btns = [[style_btn(f"🛒 {buy_label or 'Buy Now'}"[:60], buy_cb.encode(), "success", icon=5409320020058584473)]]
    # remove the QR message — payment is done
    if qr_msg:
        try: await bot.delete_messages(uid, qr_msg)
        except Exception: pass
    try: await bot.send_message(uid, txt, buttons=btns)
    except Exception: pass
    await log_payment_event("Auto UPI Money Added", uid, amt, "AutoUPI", prev_bal,
                            extra=f"🧾 <b>Order:</b> <code>{oid}</code> · paid {P_INR}{pay_amt}")

async def watch_gateway_order(bot, oid, deadline):
    """Poll the gateway until the order is PAID / EXPIRED / deadline."""
    while time.time() < deadline:
        await asyncio.sleep(PAYGATE_POLL_SECONDS)
        try: status, verified, _ = await paygate.get_status(oid)
        except Exception as ex:
            logger.warning(f"Gateway status error {oid}: {ex}"); continue
        if status == "PAID" and verified:
            return await credit_gateway_order(bot, oid)
        if status == "EXPIRED": break
    row = cur.execute("SELECT user_id, amount, status, msg_id FROM gateway_orders WHERE order_id=?", (oid,)).fetchone()
    if not row or row[2] != 'PENDING': return
    cur.execute("UPDATE gateway_orders SET status='EXPIRED' WHERE order_id=?", (oid,)); db.commit()
    txt = (f"<blockquote>⌛ <b>𝐏ᴀʏᴍᴇɴᴛ 𝐒ᴇssɪᴏɴ 𝐄xᴘɪʀᴇᴅ</b>\n\n🧾 𝐎ʀᴅᴇʀ: <code>{oid}</code>\n{P_MONEY} {P_INR}{row[1]}\n\n"
           f"⚠️ 𝐐𝐑 ᴅᴇʟᴇᴛᴇᴅ — ᴅᴏ ɴᴏᴛ ᴘᴀʏ ᴏɴ ɪᴛ ɴᴏᴡ.\n👇 𝐓ᴀᴘ <b>𝐃ᴇᴘᴏsɪᴛ 𝐍ᴏᴡ</b> ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ɴᴇᴡ ᴏɴᴇ.</blockquote>")
    await _replace_qr_with_expired(bot, row[0], row[3], txt)

async def start_gateway_deposit(bot, e, uid, amt, buy_cb=None, buy_label=None):
    try:
        order = await paygate.create_payment(amt, note=f"Deposit {uid}")
    except Exception as ex:
        logger.error(f"Gateway create failed: {ex}")
        return await bot.send_message(uid, f"{P_WARN} <b>𝐀ᴜᴛᴏ 𝐔𝐏𝐈 ɪs ᴅᴏᴡɴ ʀɪɢʜᴛ ɴᴏᴡ.</b> 𝐏ʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.")
    oid, pay_amt = order["orderId"], order.get("payAmount", amt)
    deadline = time.time() + DEPOSIT_EXPIRY
    exp_txt = time.strftime('%I:%M %p', time.gmtime(deadline + 19800))
    cur.execute("INSERT OR REPLACE INTO gateway_orders (order_id, user_id, amount, pay_amount, status, created_at, buy_cb, buy_label) VALUES (?,?,?,?,?,?,?,?)",
                (oid, uid, amt, pay_amt, 'PENDING', int(time.time()), buy_cb, buy_label))
    db.commit()
    msg = (f"<blockquote>{P_UPI} <b>𝐀ᴜᴛᴏ 𝐔𝐏𝐈 𝐏ᴀʏᴍᴇɴᴛ</b>\n\n🧾 <b>𝐎ʀᴅᴇʀ 𝐈𝐃:</b> <code>{oid}</code>\n"
           f"{P_MONEY} <b>𝐏ᴀʏ 𝐄xᴀᴄᴛʟʏ:</b> <code>{P_INR}{pay_amt}</code>\n"
           f"🎁 <b>𝐘ᴏᴜ ɢᴇᴛ:</b> {P_INR}{amt}\n"
           + (f"🛒 <b>𝐅ᴏʀ:</b> {html.escape(buy_label)}\n" if buy_label else "")
           + f"⏳ <b>𝐕ᴀʟɪᴅ ᴛɪʟʟ {exp_txt} IST</b></blockquote>\n"
           f"<blockquote>📲 𝐒ᴄᴀɴ ᴡɪᴛʜ ᴀɴʏ 𝐔𝐏𝐈 ᴀᴘᴘ ᴏʀ ᴛᴀᴘ <b>𝐏ᴀʏ 𝐍ᴏᴡ</b>.\n"
           + (f"🔗 <b>𝐋ɪᴠᴇ 𝐏ᴀʏ</b> = <a href=\"{html.escape(order['payUrl'], quote=True)}\">𝐂ʟɪᴄᴋ 𝐇ᴇʀᴇ</a>\n" if order.get("payUrl") else "")
           + f"⚠️ 𝐏ᴀʏ ᴛʜᴇ <b>ᴇxᴀᴄᴛ</b> ᴀᴍᴏᴜɴᴛ (ᴡɪᴛʜ ᴘᴀɪsᴇ).\n"
           f"✅ 𝐁ᴀʟᴀɴᴄᴇ ɪs ᴀᴅᴅᴇᴅ <b>ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ</b> — ɴᴏ sᴄʀᴇᴇɴsʜᴏᴛ ɴᴇᴇᴅᴇᴅ.</blockquote>")
    btns = [[Button.url("💳 𝐏ᴀʏ 𝐍ᴏᴡ", order["payUrl"])] if order.get("payUrl") else [],
            [Button.inline("✅ 𝐈 𝐇𝐀𝐕𝐄 𝐏𝐀𝐈𝐃", f"ihp|{oid}".encode())],
            [Button.inline("🔄 𝐂ʜᴇᴄᴋ 𝐒ᴛᴀᴛᴜs", f"pgchk|{oid}".encode())],
            [style_btn("🔙 𝐁ᴀᴄᴋ", b"pg_back", "danger", icon=6129812419028982717)]]
    btns = [b for b in btns if b]
    sent = None
    try:
        qr_source = order.get("qrImageUrl")
        if not qr_source:
            raise ValueError("Gateway response did not include qrImageUrl")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(qr_source) as response:
                response.raise_for_status()
                qr_bytes = await response.read()
        image = Image.open(io.BytesIO(qr_bytes)).convert("RGB")
        qr_photo = io.BytesIO(); qr_photo.name = "payment-qr.jpg"
        image.save(qr_photo, "JPEG", quality=95); qr_photo.seek(0)
        sent = await bot.send_file(uid, qr_photo, caption=msg, buttons=btns, force_document=False)
    except Exception:
        try:
            import qrcode
            image = qrcode.make(order["upiUri"]).convert("RGB")
            qf = io.BytesIO(); qf.name = "payment-qr.jpg"
            image.save(qf, "JPEG", quality=95); qf.seek(0)
            sent = await bot.send_file(uid, qf, caption=msg, buttons=btns, force_document=False)
        except Exception as ex:
            logger.error(f"QR send failed: {ex}")
            sent = await bot.send_message(uid, msg, buttons=btns)
    if sent:
        cur.execute("UPDATE gateway_orders SET msg_id=? WHERE order_id=?", (sent.id, oid)); db.commit()
    asyncio.create_task(watch_gateway_order(bot, oid, deadline))

def topup_needed(balance, price):
    """Rupees the user must pay to afford `price` (never below the minimum recharge)."""
    import math
    return max(MIN_DEPOSIT, int(math.ceil(float(price) - float(balance or 0))))


async def pay_for_item(e, price, label):
    """Low balance on a purchase: send an Auto UPI QR for the missing amount.
    After payment the QR is deleted and the verified message carries a button
    that repeats the same purchase (same callback data the user tapped)."""
    uid = e.sender_id
    row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = row[0] if row else 0
    if not paygate.is_enabled():
        return await e.answer(f"❌ Insufficient Balance! Need {P_INR}{price}, you have {P_INR}{bal}. Please recharge.", alert=True)
    need = topup_needed(bal, price)
    retry = getattr(e, "data", None)
    retry = retry.decode("utf-8", "ignore") if isinstance(retry, (bytes, bytearray)) else None
    try: await e.answer(f"💳 Low balance! Pay {P_INR}{need} — QR sent below 👇", alert=False)
    except Exception: pass
    await start_gateway_deposit(e.client, e, uid, need, buy_cb=retry, buy_label=label)


def resume_gateway_orders(bot):
    """After restart, keep watching orders that are still within the window."""
    now = time.time()
    for oid, created in cur.execute("SELECT order_id, created_at FROM gateway_orders WHERE status='PENDING'").fetchall():
        asyncio.get_event_loop().create_task(watch_gateway_order(bot, oid, max((created or 0) + DEPOSIT_EXPIRY, now + 30)))

def register_deposit(bot):
    try: resume_gateway_orders(bot)
    except Exception as ex: logger.warning(f"resume gateway orders: {ex}")

    @bot.on(events.CallbackQuery(pattern=b"^pg_back$"))
    async def cb_pg_back(e):
        # order keeps being watched in background: if user still pays, balance is added
        await e.answer()
        try: await e.delete()          # remove the QR photo
        except Exception: pass
        await deposit_menu(e)

    @bot.on(events.NewMessage(pattern=r"(?i)^/(recharge|deposit|addfund|addfunds)(?:@\w+)?(?:\s+(\d+))?$"))
    async def cmd_recharge(e):
        amt = e.pattern_match.group(2)
        if amt and paygate.is_enabled():
            amt = int(amt)
            if amt < 10:
                return await e.reply(f"{P_WARN} Minimum recharge is {P_INR}10.")
            deposit_input.pop(e.sender_id, None)
            return await start_gateway_deposit(bot, e, e.sender_id, amt)
        await deposit_menu(e)

    @bot.on(events.CallbackQuery(pattern=rb"^pgchk\|(.+)$"))
    async def cb_pg_check(e):
        oid = e.pattern_match.group(1).decode()
        row = cur.execute("SELECT user_id, status FROM gateway_orders WHERE order_id=?", (oid,)).fetchone()
        if not row or row[0] != e.sender_id: return await e.answer("Order not found.", alert=True)
        if row[1] == 'PAID': return await e.answer("✅ Already paid & credited.", alert=True)
        try: status, verified, _ = await paygate.get_status(oid)
        except Exception: return await e.answer("Gateway busy, try again.", alert=True)
        if status == "PAID" and verified:
            await credit_gateway_order(bot, oid); return await e.answer("✅ Payment verified!", alert=True)
        await e.answer("⏳ Payment not received yet." if status == "PENDING" else "⌛ Order expired.", alert=True)

    @bot.on(events.CallbackQuery(pattern=rb"^ihp\|(.+)$"))
    async def cb_i_have_paid(e):
        oid = e.pattern_match.group(1).decode()
        row = cur.execute("SELECT user_id, status FROM gateway_orders WHERE order_id=?", (oid,)).fetchone()
        if not row or row[0] != e.sender_id: return await e.answer("Order not found.", alert=True)
        if row[1] == "PAID": return await e.answer("✅ Payment already verified and credited.", alert=True)
        try: status, verified, _ = await paygate.get_status(oid)
        except Exception as ex:
            logger.warning("I HAVE PAID check failed for %s: %s", oid, ex)
            return await e.answer("Payment check is busy. Please try again.", alert=True)
        if status == "PAID" and verified:
            await credit_gateway_order(bot, oid)
            return await e.answer("✅ Payment verified! Balance credited.", alert=True)
        await e.answer("⏳ Payment is not verified yet. Wait a few seconds and tap again.", alert=True)
    @bot.on(events.NewMessage(pattern=r"^/(setupi|setupiname|setbinance|setbinanceqr|setcwallet)(?:\s+(.+))?$"))
    async def cmd_setpay(e):
        if not is_admin(e.sender_id): return
        keymap = {"setupi": "upi_id", "setupiname": "upi_name", "setbinance": "binance_id", "setbinanceqr": "binance_qr", "setcwallet": "cwallet_id"}
        cmd, val = e.pattern_match.group(1), (e.pattern_match.group(2) or "").strip()
        if not val: return await e.reply(f"Usage: <code>/{cmd} value</code>  (use <code>/{cmd} off</code> to disable)")
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (keymap[cmd], "" if val.lower() == "off" else val))
        db.commit()
        await e.reply(f"{PE_CHECK} <b>{keymap[cmd]}</b> updated: <code>{html.escape(val)}</code>")

    @bot.on(events.NewMessage(pattern=r"^/payinfo$"))
    async def cmd_payinfo(e):
        if not is_admin(e.sender_id): return
        await e.reply(f"<b>UPI:</b> <code>{_pay('upi_id', _U) or 'off'}</code> ({_pay('upi_name', _UN)})\n<b>Binance:</b> <code>{_pay('binance_id', _B) or 'off'}</code>\n<b>Cwallet:</b> <code>{_pay('cwallet_id', _C) or 'off'}</code>\n\nCommands: /setupi /setupiname /setbinance /setbinanceqr /setcwallet")

    @bot.on(events.NewMessage(pattern=r"(?i)^(𝐃ᴇᴘᴏsɪᴛ|💳 𝐃ᴇᴘᴏsɪᴛ|💳 Deposit)$"))
    async def msg_deposit(e):
        await deposit_menu(e)

    @bot.on(events.CallbackQuery(pattern=rb"^pgamt\|(\d+)$"))
    async def cb_pg_amount(e):
        amt = int(e.pattern_match.group(1).decode())
        await e.answer("⏳ QR bana raha hu...")
        deposit_input.pop(e.sender_id, None)
        await start_gateway_deposit(bot, e, e.sender_id, amt)

    @bot.on(events.NewMessage(pattern=r"^/setpaykey(?:\s+(\S+))?$"))
    async def cmd_setpaykey(e):
        if e.sender_id not in ADMIN_IDS: return
        val = (e.pattern_match.group(1) or "").strip()
        if not val: return await e.reply("Usage: <code>/setpaykey YOUR_GATEWAY_KEY</code>")
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('paygate_key', ?)", (val,)); db.commit()
        try:
            o = await paygate.create_payment(10, note="key test")
            await e.reply(f"{PE_CHECK} Gateway key saved & working (test order <code>{o['orderId']}</code>).")
        except Exception as ex:
            await e.reply(f"{P_WARN} Key saved but test failed: <code>{html.escape(str(ex))}</code>")

    @bot.on(events.CallbackQuery(pattern=r"^depm_(.+)$"))
    async def cb_manual_dep(e):
        method = e.pattern_match.group(1).decode()
        await manual_deposit_init(e, method)

    @bot.on(events.NewMessage(func=lambda e: e.sender_id in deposit_input and deposit_input[e.sender_id]['step'] == 'wait_amt'))
    async def msg_wait_amt(e):
        uid = e.sender_id
        text = e.text or ""
        try:
            amt = int(re.sub(r'[^\d]', '', text))
            if amt < MIN_DEPOSIT: return await e.reply(f"{P_WARN} <b>𝐌ɪɴɪᴍᴜᴍ ᴅᴇᴘᴏsɪᴛ ɪs {P_INR}{MIN_DEPOSIT}.</b> 𝐄ɴᴛᴇʀ ᴀɢᴀɪɴ:")
            if amt > 100000: return await e.reply(f"{P_WARN} 𝐌ᴀxɪᴍᴜᴍ {P_INR}100000 ᴘᴇʀ ᴅᴇᴘᴏsɪᴛ.")
            method = deposit_input[uid]['method']
            if method == "UPI" and paygate.is_enabled():
                deposit_input.pop(uid, None)
                return await start_gateway_deposit(bot, e, uid, amt)
            oid = f"BH{int(time.time())}{random.randint(10,99)}"
            expires = time.time() + DEPOSIT_EXPIRY
            waiting_proof[uid] = {'amount': amt, 'method': method, 'order_id': oid, 'expires': expires, 'msg_id': None}
            exp_txt = time.strftime('%I:%M %p', time.gmtime(expires + 19800))
            deposit_input.pop(uid)
            
            rate = get_usdt_rate()
            usdt_amt = round(amt / rate, 2)
            rate_text = f"<blockquote>{P_MONEY} <b>𝐀ᴍᴏᴜɴᴛ ᴛᴏ 𝐏ᴀʏ:</b> {P_INR}{amt} (~{P_USDT}{usdt_amt} USDT)\n💱 <i>𝐄xᴄʜᴀɴɢᴇ 𝐑ᴀᴛᴇ: {P_INR}{rate} = $1</i></blockquote>"
            
            UPI_ID, UPI_NAME, BINANCE_ID, BINANCE_QR, CWALLET_ID = _pay("upi_id", _U), _pay("upi_name", _UN), _pay("binance_id", _B), _pay("binance_qr", _BQ), _pay("cwallet_id", _C)
            if method == "Cwallet":
                msg = (f"<blockquote>{P_CARD} <b>𝐌ᴇᴛʜᴏᴅ:</b> {method}\n\n🚀 <b>𝐀ᴅᴅʀᴇss / 𝐈𝐃:</b>\n<code>{CWALLET_ID}</code></blockquote>\n"
                       f"{rate_text}\n"
                       f"<blockquote>👉 <b>𝐒ᴇɴᴅ 𝐏ʀᴏᴏғ:</b>\n𝐏ʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ 𝐓ʀᴀɴsᴀᴄᴛɪᴏɴ 𝐇ᴀsʜ (𝐋ɪɴᴋ) ᴏʀ ᴀ 𝐒ᴄʀᴇᴇɴsʜᴏᴛ ᴏғ ᴛʜᴇ ᴘᴀʏᴍᴇɴᴛ ɴᴏᴡ.</blockquote>")
                try: await bot.send_file(uid, CWALLET_QR, caption=msg, buttons=[[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", "cancel_action")]])
                except Exception: await bot.send_message(uid, msg + f"\n\n🔗 QR Link: {CWALLET_QR}", buttons=[[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", "cancel_action")]])
            elif method == "Binance":
                msg = (f"<blockquote>{P_CARD} <b>𝐌ᴇᴛʜᴏᴅ:</b> Binance Pay\n\n🆔 <b>𝐁ɪɴᴀɴᴄᴇ 𝐏ᴀʏ 𝐈𝐃:</b>\n<code>{BINANCE_ID}</code></blockquote>\n"
                       f"{rate_text}\n"
                       f"<blockquote>👉 <b>𝐒ᴇɴᴅ 𝐏ʀᴏᴏғ:</b>\n𝐒ᴇɴᴅ ᴀ 𝐒ᴄʀᴇᴇɴsʜᴏᴛ ᴏʀ 𝐎ʀᴅᴇʀ 𝐈𝐃 ᴏғ ᴛʜᴇ ᴘᴀʏᴍᴇɴᴛ ɴᴏᴡ.</blockquote>")
                cbtn = [[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", "cancel_action")]]
                if BINANCE_QR:
                    try: await bot.send_file(uid, BINANCE_QR, caption=msg, buttons=cbtn)
                    except Exception: await bot.send_message(uid, msg, buttons=cbtn)
                else: await bot.send_message(uid, msg, buttons=cbtn)
            elif method == "UPI":
                upi_url = f"upi://pay?pa={UPI_ID}&am={amt}.00&cu=INR&tn={oid}&tr={oid}" + (f"&pn={urllib.parse.quote(UPI_NAME)}" if UPI_NAME else "")
                msg = (f"<blockquote>{P_UPI} <b>𝐔𝐏𝐈 𝐏ᴀʏᴍᴇɴᴛ</b>\n\n🧾 <b>𝐎ʀᴅᴇʀ 𝐈𝐃:</b> <code>{oid}</code>\n🆔 <b>𝐔𝐏𝐈 𝐈𝐃:</b> <code>{UPI_ID}</code>\n"
                       f"{P_MONEY} <b>𝐀ᴍᴏᴜɴᴛ:</b> <code>{P_INR}{amt}</code> (ᴇxᴀᴄᴛ)\n⏳ <b>𝐐𝐑 ᴠᴀʟɪᴅ ғᴏʀ 10 ᴍɪɴᴜᴛᴇs</b> (ᴛɪʟʟ {exp_txt} IST)</blockquote>\n"
                       f"<blockquote>📲 𝐒ᴄᴀɴ ᴛʜᴇ 𝐐𝐑 ᴡɪᴛʜ ᴀɴʏ 𝐔𝐏𝐈 ᴀᴘᴘ (𝐆ᴘᴀʏ / 𝐏ʜᴏɴᴇ𝐏ᴇ / 𝐏ᴀʏᴛᴍ / 𝐅ᴀᴍ𝐏ᴀʏ). 𝐀ᴍᴏᴜɴᴛ ɪs ᴀᴜᴛᴏ-ғɪʟʟᴇᴅ.</blockquote>\n"
                       f"<blockquote>👉 <b>𝐒ᴇɴᴅ 𝐏ʀᴏᴏғ:</b>\n𝐀ғᴛᴇʀ ᴘᴀʏɪɴɢ, sᴇɴᴅ ᴀ ᴄʟᴇᴀʀ 𝐒ᴄʀᴇᴇɴsʜᴏᴛ ᴏʀ ᴛʜᴇ 12-ᴅɪɢɪᴛ 𝐔𝐓𝐑 ɴᴏ. ʜᴇʀᴇ.</blockquote>")
                try: 
                    import qrcode
                    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
                    qr.add_data(upi_url)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    
                    qr_file = io.BytesIO()
                    qr_file.name = "upi_qr.png"
                    img.save(qr_file, "PNG")
                    qr_file.seek(0)
                    
                    sent = await bot.send_file(uid, qr_file, caption=msg, buttons=[[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", "cancel_action")]])
                    waiting_proof[uid]['msg_id'] = sent.id
                except Exception as e: 
                    logger.error(f"Failed to send UPI QR: {e}")
                    await bot.send_message(uid, msg, buttons=[[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", "cancel_action")]])
            else:
                row = cur.execute("SELECT caption, qr_file_id FROM custom_payments WHERE name=?", (method,)).fetchone()
                if row:
                    cap = f"<blockquote>{row[0]}</blockquote>\n{rate_text}\n<blockquote>👇 <b>𝐀ғᴛᴇʀ ᴘᴀʏɪɴɢ, sᴇɴᴅ ᴀ ᴄʟᴇᴀʀ 𝐒ᴄʀᴇᴇɴsʜᴏᴛ ʜᴇʀᴇ:</b></blockquote>"
                    btns = [[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", "cancel_action")]]
                    if row[1] and os.path.exists(row[1]): 
                        try: await bot.send_file(e.chat_id, row[1], caption=cap, buttons=btns)
                        except: await e.reply(cap, buttons=btns)
                    else: await e.reply(cap, buttons=btns)
                else: await e.reply(f"{P_CARD} <b>{method} Deposit</b>{rate_text}\n\n👇 Send Screenshot here:", buttons=[[Button.inline("❌ 𝐂ᴀɴᴄᴇʟ", "cancel_action")]])
            asyncio.create_task(expire_deposit(bot, uid, oid))
        except ValueError: await e.respond(f"{P_NO} Please enter a valid number in {P_INR} (INR).")

    @bot.on(events.NewMessage(func=lambda e: e.sender_id in waiting_proof and (e.photo or (e.text and ("http" in e.text or re.fullmatch(r"\s*\d{12}\s*", e.text))))))
    async def msg_wait_proof(e):
        uid = e.sender_id
        info = waiting_proof.pop(uid)
        ensure_user(uid)
        if time.time() > info.get('expires', time.time() + 1):
            return await e.reply(f"⌛ <b>𝐓ʜɪs ᴘᴀʏᴍᴇɴᴛ sᴇssɪᴏɴ ʜᴀs ᴇxᴘɪʀᴇᴅ.</b> 𝐂ᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ ɪғ ʏᴏᴜ ᴀʟʀᴇᴀᴅʏ ᴘᴀɪᴅ.")
        final_amt = info['amount']
        if info['method'] == "Cwallet": final_amt = int(final_amt * 1.05)
        
        cur.execute("INSERT INTO deposits (user_id, amount, method_name, status) VALUES (?,?,?,?)", (uid, final_amt, info['method'], "pending"))
        db.commit()
        dep_id = cur.lastrowid
        await e.reply(f"{PE_GIFT} 𝐃ᴇᴘᴏsɪᴛ ʀᴇǫᴜᴇsᴛ sᴜʙᴍɪᴛᴛᴇᴅ! 𝐏ʟᴇᴀsᴇ ᴡᴀɪᴛ ғᴏʀ ᴀᴅᴍɪɴ ᴀᴘᴘʀᴏᴠᴀʟ.")
        cap = f"{PE_LIGHTNING} <b>𝐍ᴇᴡ 𝐃ᴇᴘᴏsɪᴛ 𝐑ᴇǫᴜᴇsᴛ</b>\n{P_ACC} 𝐔sᴇʀ: <code>{uid}</code>\n{P_MONEY} 𝐑ᴇǫᴜᴇsᴛ: <b>{P_INR}{info['amount']}</b>\n{P_CARD} 𝐌ᴇᴛʜᴏᴅ: {info['method']}\n{P_ID} 𝐑ᴇғ: <code>{dep_id}</code>\n🧾 𝐎ʀᴅᴇʀ: <code>{info.get('order_id', '-')}</code>"
        btns = [[style_btn(f"𝐀ᴄᴄᴇᴘᴛ (₹{final_amt})", f"dep_acc|{dep_id}|{uid}|{info['method']}|exact|{final_amt}", "success", icon=5409098988156629257), 
                 style_btn("𝐑ᴇᴊᴇᴄᴛ", f"dep_rej|{dep_id}|{uid}", "danger", icon=5409119256107297715)],
                [style_btn("𝐂ᴜsᴛᴏᴍ 𝐀ᴍᴏᴜɴᴛ", f"dep_acc|{dep_id}|{uid}|{info['method']}|custom|0", "primary", icon=5409098988156629257)]]
        
        sent = False
        for log_ch in PAYMENT_LOG_CHANNELS:
            try:
                if e.photo: await bot.send_message(log_ch, cap, file=e.media, buttons=btns)
                else: await bot.send_message(log_ch, cap + f"\n🔗 Proof / UTR: <code>{html.escape(e.text)}</code>", buttons=btns)
                sent = True
            except Exception:
                logger.exception("Could not send deposit request to log channel %s", log_ch)
        if not sent:
            # No log channel (or bot not admin there) -> send directly to owner/admins
            for adm in ADMIN_IDS:
                try:
                    if e.photo: await bot.send_message(adm, cap, file=e.media, buttons=btns)
                    else: await bot.send_message(adm, cap + f"\n🔗 Proof / UTR: <code>{html.escape(e.text)}</code>", buttons=btns)
                except Exception as admin_err: logger.error(f"Failed to send deposit to admin {adm}: {admin_err}")

    @bot.on(events.CallbackQuery(pattern=r"^dep_acc\|"))
    async def cb_dep_acc(e):
        if not is_admin(e.sender_id):
            return await e.answer("Admin access required.", alert=True)
        p = e.data.decode().split("|")
        dep_id, t_uid, method, a_type = p[1], int(p[2]), p[3], p[4]
        row = cur.execute("SELECT status FROM deposits WHERE id=?", (dep_id,)).fetchone()
        if not row or row[0] != 'pending': return await e.edit(f"{P_WARN} Already processed.")
        
        if a_type == "exact":
            amt = int(p[5]) 
            async with get_user_lock(t_uid):
                prev_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (t_uid,)).fetchone()
                prev_bal = prev_row[0] if prev_row else 0
                update_balance(t_uid, amt)
                
                cur.execute("UPDATE deposits SET status='approved', amount=? WHERE id=?", (amt, dep_id))
                cur.execute("UPDATE users SET total_deposited = total_deposited + ? WHERE user_id=?", (amt, t_uid))
                db.commit()
            
            await process_referral_bonus(t_uid, amt)
            
            user_msg = (f"<blockquote>{PE_CHECK} <b>Deposit Approved!</b>\n\n{P_MONEY} <b>Amount Added:</b> ${to_usd(amt):.2f} ({P_INR}{amt})\n"
                        f"📉 <b>𝐏ʀᴇᴠious 𝐁ᴀʟᴀɴᴄᴇ:</b> ${to_usd(prev_bal):.2f} ({P_INR}{prev_bal})\n📈 <b>New 𝐁ᴀʟᴀɴᴄᴇ:</b> ${to_usd(prev_bal+amt):.2f} ({P_INR}{prev_bal+amt})</blockquote>")
            await bot.send_message(int(t_uid), user_msg)
            await log_payment_event("Deposit Approved · Money Added", t_uid, amt, method, prev_bal, by=e.sender_id,
                                    extra=f"{P_ID} <b>Ref:</b> <code>{dep_id}</code>")
            try: await e.edit(f"{PE_CHECK} <b>INSTANT CREDITED {P_INR}{amt} TO {t_uid}</b>")
            except MessageNotModifiedError: pass
            
        elif a_type == "custom":
            custom_dep_amt[int(dep_id)] = "0"
            await e.edit(f"{P_KEY} <b>Enter 𝐂ᴜsᴛᴏᴍ 𝐀ᴍᴏᴜɴᴛ for User {t_uid}:</b>\n\n{P_MONEY} 0", buttons=get_admin_custom_keypad(int(dep_id)))
            
    @bot.on(events.CallbackQuery(pattern=r"^dep_rej\|"))
    async def cb_dep_rej(e):
        if not is_admin(e.sender_id):
            return await e.answer("Admin access required.", alert=True)
        uid = e.sender_id
        p = e.data.decode().split("|")
        dep_id, t_uid = p[1], int(p[2])
        row = cur.execute("SELECT status FROM deposits WHERE id=?", (dep_id,)).fetchone()
        if not row or row[0] != 'pending': return await e.edit(f"{P_WARN} Already processed.")
        admin_dep_state[uid] = {'target_uid': t_uid, 'dep_id': dep_id, 'step': 'wait_reason', 'msg_id': e.message_id, 'chat_id': e.chat_id}
        await bot.send_message(uid, f"{P_WARN} Reply to this message with the REASON for rejecting user <code>{t_uid}</code>:")
        try: await e.answer("Check your bot PMs to enter the reason.", alert=True)
        except: pass

    @bot.on(events.NewMessage(func=lambda e: e.sender_id in admin_dep_state and admin_dep_state[e.sender_id]['step'] == 'wait_reason'))
    async def msg_admin_rej_reason(e):
        if not is_admin(e.sender_id):
            return
        uid = e.sender_id
        st = admin_dep_state[uid]
        t_uid, dep_id, msg_id = st['target_uid'], st['dep_id'], st['msg_id']
        log_chat = st.get('chat_id') or (PAYMENT_LOG_CHANNELS[0] if PAYMENT_LOG_CHANNELS else LOG_CHANNEL_ID)
        cur.execute("UPDATE deposits SET status='rejected' WHERE id=?", (dep_id,))
        db.commit()
        
        try:
            await bot.edit_message(log_chat, msg_id, f"{P_NO} <b>REJECTED USER {t_uid}</b>\nReason: {html.escape(e.text)}")
            for log_ch in PAYMENT_LOG_CHANNELS:
                if log_ch != log_chat:
                    try: await bot.send_message(log_ch, f"{P_NO} <b>REJECTED USER {t_uid}</b>\nReason: {html.escape(e.text)}")
                    except: pass
        except: pass
        
        await bot.send_message(int(t_uid), f"{P_NO} <b>Deposit 𝐑ᴇᴊᴇᴄᴛed!</b>\n📋 Reason: {html.escape(e.text)}")
        await e.reply(f"{P_YES} 𝐑ᴇᴊᴇᴄᴛion reason sent.")
        admin_dep_state.pop(uid)

    @bot.on(events.CallbackQuery(pattern=r"^dkp\|"))
    async def cb_dkp(e):
        if not is_admin(e.sender_id):
            return await e.answer("Admin access required.", alert=True)
        uid = e.sender_id
        _, dep_id, action = e.data.decode().split("|")
        dep_id = int(dep_id)
        row = cur.execute("SELECT user_id, method_name, status, amount FROM deposits WHERE id=?", (dep_id,)).fetchone()
        if not row or row[2] != 'pending': return await e.edit(f"{P_WARN} Already processed.")
        t_uid, method, orig_amt = row[0], row[1], row[3]
        
        curr = custom_dep_amt.get(dep_id, "0")
        
        if action.isdigit():
            if curr == "0": curr = action
            else: curr += action
            if len(curr) > 7: curr = curr[:7]
        elif action == "del": curr = curr[:-1] or "0"
        elif action == "cancel":
            btns = [[style_btn(f"𝐀ᴄᴄᴇᴘᴛ (₹{orig_amt})", f"dep_acc|{dep_id}|{t_uid}|{method}|exact|{orig_amt}", "success", icon=6147460667281511517), 
                     style_btn("𝐑ᴇᴊᴇᴄᴛ", f"dep_rej|{dep_id}|{t_uid}", "danger", icon=6129888444245089008)],
                    [style_btn("𝐂ᴜsᴛᴏᴍ 𝐀ᴍᴏᴜɴᴛ", f"dep_acc|{dep_id}|{t_uid}|{method}|custom|0", "primary", icon=5796170975699544141)]]
            return await e.edit(f"{PE_LIGHTNING} <b>𝐍ᴇᴡ 𝐃ᴇᴘᴏsɪᴛ 𝐑ᴇǫᴜᴇsᴛ</b>\n{P_ACC} 𝐔sᴇʀ: <code>{t_uid}</code>\n{P_MONEY} 𝐑ᴇǫᴜᴇsᴛ: <b>{P_INR}{orig_amt}</b>\n{P_CARD} 𝐌ᴇᴛʜᴏᴅ: {method}\n{P_ID} 𝐑ᴇғ: <code>{dep_id}</code>", buttons=btns)
        elif action == "conf":
            amt = int(curr)
            if amt <= 0: return await e.answer("Amount must be > 0", alert=True)
            
            async with get_user_lock(t_uid):
                prev_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (t_uid,)).fetchone()
                prev_bal = prev_row[0] if prev_row else 0
                update_balance(t_uid, amt)
                cur.execute("UPDATE deposits SET status='approved', amount=? WHERE id=?", (amt, dep_id))
                cur.execute("UPDATE users SET total_deposited = total_deposited + ? WHERE user_id=?", (amt, t_uid))
                db.commit()
                
            await process_referral_bonus(t_uid, amt)
            await log_payment_event("Deposit Approved · Custom Amount Added", t_uid, amt, method, prev_bal, by=e.sender_id,
                                    extra=f"{P_ID} <b>Ref:</b> <code>{dep_id}</code> · requested {P_INR}{orig_amt}")
            await e.edit(f"{PE_CHECK} <b>APPROVED {P_INR}{amt} TO {t_uid} (𝐂ᴜsᴛᴏᴍ 𝐀ᴍᴏᴜɴᴛ)</b>")
            await bot.send_message(int(t_uid), f"{PE_CHECK} <b>Deposit Approved!</b>\n{P_MONEY} Amount Added: {P_INR}{amt}\n📉 Old: {P_INR}{prev_bal} | 📈 New: {P_INR}{prev_bal+amt}")
            return

        custom_dep_amt[dep_id] = curr
        await e.edit(f"{P_KEY} <b>Enter 𝐂ᴜsᴛᴏᴍ 𝐀ᴍᴏᴜɴᴛ for User {t_uid}:</b>\n\n{P_MONEY} {curr}", buttons=get_admin_custom_keypad(dep_id))
