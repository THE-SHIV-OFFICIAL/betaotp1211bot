"""Public 'Buy Logger' — posts a professional purchase proof to the store channel."""
import time
from telethon import Button
from config import bot, logger, SALE_LOG_CHANNEL, PE_CHECK, SUPPORT_USERNAME

_ME = {"u": None}


async def _bot_username():
    if not _ME["u"]:
        me = await bot.get_me()
        _ME["u"] = me.username or ""
    return _ME["u"]


async def post_sale(title, body):
    if not SALE_LOG_CHANNEL:
        return
    uname = await _bot_username()
    ts = time.strftime("%d %b %Y • %I:%M %p")
    msg = (f"<blockquote><b>{PE_CHECK} {title}</b></blockquote>\n\n"
           f"{body}\n\n"
           f"🕒 <i>{ts}</i>\n"
           f"• <a href='https://t.me/{uname}'>@{uname}</a> || "
           f"<a href='https://t.me/BETABOT_HUB'>@BETABOT_HUB</a> || "
           f"<a href='https://t.me/{SUPPORT_USERNAME}'>@{SUPPORT_USERNAME}</a>")
    buttons = [[Button.url("• Buy Now •", f"https://t.me/{uname}?start=store", style="success", icon=5440627033111557670)]] if uname else None
    from utils.logsend import send_log
    await send_log(bot, [SALE_LOG_CHANNEL], msg, buttons=buttons)
