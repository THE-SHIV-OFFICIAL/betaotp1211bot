"""TG-Lion (https://www.tg-lion.net) — Telegram accounts for Server 2.

Flow: user picks a country -> bot buys a number -> user enters the number in
Telegram -> taps "Get Code" -> bot fetches login code (+ 2FA password).

Admin: /tlbal  (TG-Lion balance)
"""
import asyncio
import json
import math
import os
import time
import urllib.parse
import urllib.request
from config import OWNER_ID, ADMIN_IDS, logger

TGLION_URL = os.getenv("TGLION_API_URL", "https://tg-lion.net/")


def _creds():
    key = os.getenv("TGLION_API_KEY", "")
    uid = os.getenv("TGLION_USER_ID", "").strip() or str(OWNER_ID)
    if not key:
        raise Exception("TGLION_API_KEY not configured")
    return key, uid


def _call_sync(params):
    key, uid = _creds()
    q = urllib.parse.urlencode({**params, "apiKey": key, "YourID": uid})
    req = urllib.request.Request(f"{TGLION_URL}?{q}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


async def tl_call(**params):
    return await asyncio.to_thread(_call_sync, params)


_cache = {"t": 0, "data": {}}


async def tl_countries():
    """{code: {name, qty, price(usd)}} — cached 3 min."""
    if time.time() - _cache["t"] < 180 and _cache["data"]:
        return _cache["data"]
    r = await tl_call(action="available_countries")
    data = {k: v for k, v in (r.get("countries") or {}).items() if int(v.get("qty") or 0) > 0}
    _cache.update(t=time.time(), data=data)
    return data


# (max panel cost in INR, markup). Cheap accounts get a small margin so the
# price stays attractive; costly accounts carry more profit.
# e.g. panel ₹30 -> ₹39, panel ₹33 -> ₹44
TL_TIERS = ((30, 1.30), (60, 1.33), (120, 1.38), (250, 1.42), (float("inf"), 1.45))
TL_MIN_PROFIT = 5


def tl_markup(cost_inr):
    for limit, mk in TL_TIERS:
        if cost_inr <= limit:
            return mk
    return TL_TIERS[-1][1]


def tl_price_from_inr(cost_inr):
    cost_inr = float(cost_inr)
    return int(max(math.ceil(round(cost_inr * tl_markup(cost_inr), 4)), math.ceil(cost_inr) + TL_MIN_PROFIT))


def tl_sell_price(usd):
    """(sell_inr, cost_inr) using the bot's USDT rate and tiered markup."""
    from database import get_usdt_rate
    cost = round(float(usd) * get_usdt_rate(), 2)
    return tl_price_from_inr(cost), cost


async def tl_buy(country_code):
    r = await tl_call(action="getNumber", country_code=country_code.lower())
    if r.get("status") != "ok":
        raise Exception(r.get("message") or str(r))
    return r  # {Number, price, name, new_balance}


async def tl_code(number):
    r = await tl_call(action="getCode", number=number)
    if r.get("status") != "ok":
        return None
    return r  # {code, pass}


def register_tglion(bot):
    from telethon import events

    @bot.on(events.NewMessage(pattern=r"^/tlbal$"))
    async def _bal(e):
        if e.sender_id not in ADMIN_IDS: return
        try:
            r = await tl_call(action="get_balance")
            await e.reply(f"🦁 TG-Lion balance: <b>{r.get('balance')}</b>")
        except Exception as ex:
            await e.reply(f"⚠️ {ex}")

    logger.info("TG-Lion registered")
