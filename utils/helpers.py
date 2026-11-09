#MADE_BY_SHIV

from telethon import Button, events
from telethon.errors import UserNotParticipantError, ChatAdminRequiredError, MessageNotModifiedError
from telethon.tl.functions.channels import GetParticipantRequest
from config import CHECK_CHANNELS, JOIN_URLS, JOIN_LABELS, logger


async def check_channel_joined(bot, uid, is_admin_func):
    """/start is open for everyone. Force-join is enforced at purchase time (see require_join)."""
    return True


def _label(i):
    return JOIN_LABELS[i] if i < len(JOIN_LABELS) else f"📢 Join Channel {i + 1}"


async def get_unjoined_channels(bot, uid):
    """Returns list of (url, index, label) for chats the user has NOT joined."""
    unjoined = []
    for i, ch in enumerate(CHECK_CHANNELS):
        ch = str(ch).strip()
        url = JOIN_URLS[i] if i < len(JOIN_URLS) else f"https://t.me/{ch.lstrip('@')}"
        try:
            ch_id = int(ch) if ch.lstrip('-').isdigit() else ch
            entity = await bot.get_entity(ch_id)
            await bot(GetParticipantRequest(channel=entity, participant=uid))
        except UserNotParticipantError:
            unjoined.append((url, i + 1, _label(i)))
        except ChatAdminRequiredError:
            # Bot is not admin there -> cannot verify. Don't lock users out, just log it.
            logger.error(f"[FORCE-JOIN] Make the bot ADMIN in {ch} to verify members.")
        except Exception as e:
            logger.error(f"[FORCE-JOIN] Check error for {ch} (uid={uid}): {type(e).__name__}: {e}")
    return unjoined


def build_join_buttons(unjoined):
    from utils.keyboards import style_btn, style_url
    rows = [[style_url(label, url, "primary")] for url, _idx, label in unjoined]
    rows.append([style_btn("✅ 𝐉ᴏɪɴᴇᴅ — 𝐕ᴇʀɪғʏ", b"verify_join", "success", icon=6129627894349045589)])
    return rows


def join_message(remaining):
    return ("<blockquote>🔒 <b>𝐉ᴏɪɴ ʀᴇǫᴜɪʀᴇᴅ ʙᴇғᴏʀᴇ ᴘᴜʀᴄʜᴀsᴇ</b></blockquote>\n"
            "<blockquote>𝐓ᴏ ʙᴜʏ ᴀɴʏᴛʜɪɴɢ ғʀᴏᴍ ᴛʜɪs ʙᴏᴛ, ᴘʟᴇᴀsᴇ ᴊᴏɪɴ ᴀʟʟ ᴏғғɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟs & ɢʀᴏᴜᴘ ʙᴇʟᴏᴡ.\n\n"
            f"📌 <b>{remaining}</b> ʀᴇᴍᴀɪɴɪɴɢ — ᴊᴏɪɴ ᴛʜᴇᴍ, ᴛʜᴇɴ ᴛᴀᴘ <b>𝐕ᴇʀɪғʏ</b>.</blockquote>")


async def require_join(bot, event):
    """Return True if the user may buy. Otherwise shows the join + verify prompt and returns False."""
    from database import is_admin
    uid = event.sender_id
    if is_admin(uid):
        return True
    unjoined = await get_unjoined_channels(bot, uid)
    if not unjoined:
        return True
    msg, btns = join_message(len(unjoined)), build_join_buttons(unjoined)
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.answer("🔒 Join our channels & group first!", alert=True)
        except Exception:
            pass
        try:
            await event.edit(msg, buttons=btns)
        except MessageNotModifiedError:
            pass
        except Exception:
            await bot.send_message(uid, msg, buttons=btns)
    else:
        await event.respond(msg, buttons=btns)
    return False
