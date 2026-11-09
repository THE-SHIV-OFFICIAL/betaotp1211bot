"""Hero SMS integration (https://hero-sms.com) — replaces Grizzly SMS.

Used for:
  WhatsApp Server 1  -> Physical SIM (GSM operator) numbers, top countries
  WhatsApp Server 2  -> cheapest risky countries (warning shown)
  Telegram Server 3  -> cheapest countries (warning shown, from Rs 25)
  Instagram / Facebook / Google -> Server 2 / 3

Admin commands:
  /hbalance                     Hero SMS account balance
  /hbuy <service> <country>     get a number manually (e.g. /hbuy wa 22)
  /hstatus <id>                 check SMS code
  /hcancel <id>                 cancel activation
  /hdone <id>                   finish activation
  /herosms                      website link
"""
import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from telethon import events, Button
from config import ADMIN_IDS, HERO_SMS_API_KEY, HERO_SMS_API_URL, HERO_SMS_WEB_URL, logger


def _call_sync(params):
    params = {"api_key": HERO_SMS_API_KEY, **params}
    url = f"{HERO_SMS_API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BetaBot)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode().strip()
    except urllib.error.HTTPError as ex:  # getNumberV2 returns 4xx with a JSON error body
        return ex.read().decode(errors="ignore").strip() or f"HTTP_{ex.code}"


async def hero_call(**params):
    return await asyncio.to_thread(_call_sync, params)


async def get_balance():
    res = await hero_call(action="getBalance")
    return res.split(":", 1)[1] if res.startswith("ACCESS_BALANCE") else res


async def get_number(service, country, max_price=None):
    """Returns dict {activationId, phoneNumber, activationCost, ...}; raises on failure."""
    params = {"action": "getNumberV2", "service": service, "country": country}
    if max_price:
        params["maxPrice"] = max_price
    res = await hero_call(**params)
    try:
        d = json.loads(res)
    except Exception:
        raise Exception(res)
    if not isinstance(d, dict) or "activationId" not in d:
        raise Exception((d or {}).get("title") if isinstance(d, dict) else res)
    return d


async def get_status(act_id):
    return await hero_call(action="getStatus", id=act_id)


async def set_status(act_id, status):
    return await hero_call(action="setStatus", id=act_id, status=status)


def register_herosms(bot):
    def is_admin(e):
        return e.sender_id in ADMIN_IDS

    @bot.on(events.NewMessage(pattern=r"^/herosms$"))
    async def _site(e):
        await e.respond("📲 <b>Hero SMS</b>\nVirtual numbers for OTP verification",
                        buttons=[Button.url("Open Hero SMS", HERO_SMS_WEB_URL)])

    @bot.on(events.NewMessage(pattern=r"^/hbalance$"))
    async def _bal(e):
        if not is_admin(e): return
        try: await e.respond(f"💰 Hero SMS balance: <b>${await get_balance()}</b>")
        except Exception as ex: await e.respond(f"❌ {ex}")

    @bot.on(events.NewMessage(pattern=r"^/hbuy (\S+) (\S+)$"))
    async def _buy(e):
        if not is_admin(e): return
        try:
            d = await get_number(e.pattern_match.group(1), e.pattern_match.group(2))
            await e.respond(f"📱 Number: <code>+{d['phoneNumber']}</code>\n🆔 ID: <code>{d['activationId']}</code>\nUse /hstatus {d['activationId']}")
        except Exception as ex: await e.respond(f"❌ {ex}")

    @bot.on(events.NewMessage(pattern=r"^/hstatus (\d+)$"))
    async def _st(e):
        if not is_admin(e): return
        res = await get_status(e.pattern_match.group(1))
        if res.startswith("STATUS_OK"):
            await e.respond(f"🔢 Code: <code>{res.split(':', 1)[1]}</code>")
        else:
            await e.respond(f"⏳ {res}")

    @bot.on(events.NewMessage(pattern=r"^/hcancel (\d+)$"))
    async def _cancel(e):
        if not is_admin(e): return
        await e.respond(f"🔴 {await set_status(e.pattern_match.group(1), 8)}")

    @bot.on(events.NewMessage(pattern=r"^/hdone (\d+)$"))
    async def _done(e):
        if not is_admin(e): return
        await e.respond(f"✅ {await set_status(e.pattern_match.group(1), 6)}")

    logger.info("Hero SMS handlers registered")
