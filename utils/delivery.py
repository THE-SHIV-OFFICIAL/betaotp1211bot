"""One post-delivery thank-you per order; Telegram failures never undo a sale."""
from config import PE_CHECK, PE_CROWN, PE_HEART, PE_FLOWER, logger
from database import cur, db
from utils.keyboards import style_btn
from utils.states import get_user_lock


async def send_delivery_thanks(bot, uid, delivery_key):
    """Call only after the buyer's delivery message/file succeeds.

    Persist successful sends so Get Again and bot restarts do not repeat notes.
    Failed sends are logged and may be retried on the next delivery action.
    """
    try:
        async with get_user_lock(uid):
            cur.execute("""CREATE TABLE IF NOT EXISTS delivery_thanks (
                user_id INTEGER NOT NULL,
                delivery_key TEXT NOT NULL,
                message_id INTEGER,
                PRIMARY KEY (user_id, delivery_key)
            )""")
            db.commit()
            if cur.execute("SELECT 1 FROM delivery_thanks WHERE user_id=? AND delivery_key=?",
                           (uid, str(delivery_key))).fetchone():
                return False
            text = (
                f"<blockquote>{PE_CHECK} <b>Order Delivered Successfully!</b></blockquote>\n\n"
                f"{PE_CROWN} <b>Thank you for choosing Beta Account Store!</b>\n\n"
                f"{PE_HEART} Your trust means a lot to us. It was a pleasure serving you!\n\n"
                f"{PE_FLOWER} We'd love to welcome you back. Visit again whenever you need us.\n\n"
                "<b>With love, Team Beta Account Store</b>"
            )
            sent = await bot.send_message(
                uid, text, parse_mode="html", link_preview=False,
                buttons=[[style_btn("Visit Again", b"visit_again", "success", icon=6129399728506412489)]],
            )
            cur.execute("INSERT INTO delivery_thanks (user_id, delivery_key, message_id) VALUES (?,?,?)",
                        (uid, str(delivery_key), getattr(sent, "id", None)))
            db.commit()
            return True
    except Exception as ex:
        logger.warning("Delivery thank-you could not be sent for user %s: %s", uid, ex)
        return False
