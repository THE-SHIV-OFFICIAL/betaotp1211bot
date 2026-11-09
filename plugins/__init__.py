from plugins.start import register_start
from plugins.profile import register_profile
from plugins.deposit import register_deposit
from plugins.buy import register_buy
from plugins.repos import register_repos
from plugins.smm import register_smm
from plugins.social import register_social
from plugins.profit import register_profit
from plugins.herosms import register_herosms
from plugins.numflow import register_numflow
from plugins.notify import register_notify
from plugins.tglion import register_tglion
from plugins.admin import register_admin
from plugins.admin_actions import register_admin_actions
from plugins.callbacks import register_callbacks

def _keep_banner_only_on_start():
    """Menus opened from the /start banner used to keep the banner photo on every
    screen. If a callback edits a photo message with text only, delete the photo
    message and send a clean text message instead."""
    from telethon import events
    orig = events.CallbackQuery.Event.edit
    if getattr(orig, "_banner_patch", False):
        return

    async def edit(self, *args, **kwargs):
        if "file" not in kwargs:
            try:
                m = await self.get_message()
            except Exception:
                m = None
            if m is not None and getattr(m, "photo", None):
                text = args[0] if args else kwargs.get("text", kwargs.get("message", ""))
                send_kw = {k: kwargs[k] for k in ("buttons", "parse_mode", "link_preview") if k in kwargs}
                new = await self.client.send_message(self.chat_id, text, **send_kw)
                try: await m.delete()
                except Exception: pass
                return new
        return await orig(self, *args, **kwargs)

    edit._banner_patch = True
    events.CallbackQuery.Event.edit = edit


def register_all_handlers(bot):
    _keep_banner_only_on_start()
    register_start(bot)
    register_profile(bot)
    register_deposit(bot)
    register_buy(bot)
    register_repos(bot)
    register_smm(bot)
    register_social(bot)
    register_profit(bot)
    register_herosms(bot)
    register_numflow(bot)
    register_tglion(bot)
    register_admin(bot)
    register_admin_actions(bot)
    register_callbacks(bot)
    register_notify(bot)
    try:
        from utils.panels import start_monitor
        start_monitor(bot)   # owner alert when a supplier panel balance drops below ₹50
    except Exception as ex:
        print(f"panel monitor not started: {ex}")
