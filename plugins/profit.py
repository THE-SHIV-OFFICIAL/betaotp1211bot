"""Profit tracking: every sale stores selling price, cost and profit.

Admin commands
  /profit                 today / 7 days / 30 days / all-time report
  /profit 50              last 50 sales with profit of each
"""
import html
from telethon import events
from database import cur, db
from config import ADMIN_IDS, SERVICE_LOG_CHANNELS, PE_CROWN, PE_CHECK, P_INR, bot, logger


def record_sale(user_id, kind, item, sell, cost):
    sell = round(float(sell or 0), 2)
    cost = round(float(cost or 0), 2)
    profit = round(sell - cost, 2)
    cur.execute("INSERT INTO sales (user_id, kind, item, sell, cost, profit) VALUES (?,?,?,?,?,?)",
                (user_id, kind, item, sell, cost, profit))
    db.commit()
    return profit


async def notify_profit(user_id, kind, item, sell, cost):
    """Record the sale and DM every admin a short profit message."""
    profit = record_sale(user_id, kind, item, sell, cost)
    today = cur.execute("SELECT COALESCE(SUM(profit),0) FROM sales WHERE date(date)=date('now')").fetchone()[0]
    msg = (f"<blockquote>{PE_CHECK} <b>𝐍ᴇᴡ 𝐒ᴀʟᴇ · {html.escape(kind)}</b>\n"
           f"🛍 {html.escape(str(item))}\n👤 <a href='tg://user?id={user_id}'>Buyer</a>\n👤 <code>{user_id}</code>\n"
           f"💵 𝐒ᴏʟᴅ: {P_INR}{sell} · 🧾 𝐂ᴏsᴛ: {P_INR}{round(float(cost or 0), 2)}\n"
           f"{PE_CROWN} <b>𝐏ʀᴏғɪᴛ: {P_INR}{profit}</b>\n📈 𝐓ᴏᴅᴀʏ: {P_INR}{round(today, 2)}</blockquote>")
    from utils.logsend import send_log
    import time as _t
    msg += f"\n🕒 {_t.strftime('%d %b %Y • %I:%M %p')}"
    await send_log(bot, SERVICE_LOG_CHANNELS, msg)   # service log channel: every sale
    await send_log(bot, list(ADMIN_IDS), msg)
    return profit


def _sum(where):
    r = cur.execute(f"SELECT COUNT(*), COALESCE(SUM(sell),0), COALESCE(SUM(cost),0), COALESCE(SUM(profit),0) FROM sales {where}").fetchone()
    return r


def register_profit(bot):
    @bot.on(events.NewMessage(pattern=r"^/profit(?: (\d+))?$"))
    async def _profit(e):
        if e.sender_id not in ADMIN_IDS:
            return
        n = e.pattern_match.group(1)
        if n:
            rows = cur.execute("SELECT kind, item, sell, cost, profit, date FROM sales ORDER BY id DESC LIMIT ?", (min(int(n), 100),)).fetchall()
            if not rows:
                return await e.respond("No sales yet.")
            out = f"<blockquote>{PE_CROWN} <b>𝐋ᴀsᴛ {len(rows)} 𝐒ᴀʟᴇs</b></blockquote>\n"
            for k, it, s, c, p, d in rows:
                out += f"• {html.escape(k)} · {html.escape(str(it))[:40]}\n   {P_INR}{s} − {P_INR}{c} = <b>{P_INR}{p}</b> · {str(d)[:16]}\n"
            return await e.respond(out[:4000])
        lines = []
        for label, where in [("𝐓ᴏᴅᴀʏ", "WHERE date(date)=date('now')"),
                             ("7 𝐃ᴀʏs", "WHERE date >= datetime('now','-7 days')"),
                             ("30 𝐃ᴀʏs", "WHERE date >= datetime('now','-30 days')"),
                             ("𝐀ʟʟ 𝐓ɪᴍᴇ", "")]:
            c, s, co, p = _sum(where)
            lines.append(f"<b>{label}</b>: {c} sales · {P_INR}{round(s,2)} sold · {P_INR}{round(co,2)} cost · <b>{P_INR}{round(p,2)} profit</b>")
        kinds = cur.execute("SELECT kind, COUNT(*), COALESCE(SUM(profit),0) FROM sales WHERE date >= datetime('now','-30 days') GROUP BY kind ORDER BY 3 DESC").fetchall()
        by = "\n".join(f"• {html.escape(k)}: {c} · {P_INR}{round(p,2)}" for k, c, p in kinds) or "—"
        await e.respond(f"<blockquote>{PE_CROWN} <b>𝐏ʀᴏғɪᴛ 𝐑ᴇᴘᴏʀᴛ</b></blockquote>\n<blockquote>" + "\n".join(lines) +
                        f"</blockquote>\n<blockquote><b>𝐁ʏ 𝐒ᴇʀᴠɪᴄᴇ (30 ᴅᴀʏs)</b>\n{by}</blockquote>\n"
                        f"<i>/profit 20 = last 20 sales</i>")

    logger.info("Profit tracking registered")
