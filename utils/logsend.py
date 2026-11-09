"""Reliable log posting: retries without premium emoji, never raises."""
import re
from config import logger

_TG_EMOJI = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', re.S)


def plain(text):
    return _TG_EMOJI.sub(r"\1", text or "")


async def send_log(bot, chats, text, **kw):
    """Send `text` to every chat in `chats`. Returns number of successful sends."""
    ok = 0
    for ch in [c for c in dict.fromkeys(chats or []) if c]:
        try:
            await bot.send_message(ch, text, link_preview=False, **kw)
            ok += 1
            continue
        except Exception as ex:
            first = ex
        try:  # premium emoji / file issues -> retry as plain text
            kw2 = {k: v for k, v in kw.items() if k != "file"}
            await bot.send_message(ch, plain(text), link_preview=False, **kw2)
            ok += 1
        except Exception as ex:
            logger.warning("Log send to %s failed: %s / %s (is the bot admin there?)", ch, first, ex)
    return ok


async def payment_log(bot, text, **kw):
    from config import PAYMENT_LOG_CHANNELS, ADMIN_IDS
    if not await send_log(bot, PAYMENT_LOG_CHANNELS, text, **kw):
        await send_log(bot, list(ADMIN_IDS), text, **kw)
