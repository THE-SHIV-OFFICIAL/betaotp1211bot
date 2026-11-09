"""Auto-import every service from the SMM panel (CheapestSMMPanels).

* Every panel service is sorted into  "<Platform> • <Type>"  (e.g. Telegram • Reactions).
* Sell price = panel cost + profit %  (rounded UP, at least SMM_MIN_PROFIT ₹/1K profit).
* Runs on start-up and every SMM_SYNC_HOURS hours (default 6).
* Services with no panel ID are hidden, so buyers never see "service is being set up".

Admin commands
  /smmsync               re-import now
  /setmargin <percent>   change profit % for all auto-imported services (then re-syncs)
  /smmprices [platform]  cost · sell · profit table
"""
import asyncio
import html
import math
import os
import re

from telethon import events
from database import cur, db
from config import ADMIN_IDS, logger

# ─────────── classification ───────────
PLATFORM_WORDS = [
    ("Telegram", ("telegram", "tg", "t.me")),
    ("Instagram", ("instagram", "insta", "ig", "reel")),
    ("YouTube", ("youtube", "yt", "shorts")),
    ("Facebook", ("facebook", "fb")),
    ("WhatsApp", ("whatsapp", "wa channel")),
    ("TikTok", ("tiktok", "tik tok")),
    ("Twitter", ("twitter", "x.com", "tweet")),
    ("Threads", ("threads",)),
    ("Spotify", ("spotify",)),
]

# everything else on the panel goes to "Others • <name>"
OTHER_WORDS = [
    ("Website Traffic", ("website traffic", "google real visitors", "social signals", "google maps")),
    ("Snapchat", ("snapchat",)), ("LinkedIn", ("linkedin",)), ("Twitch", ("twitch",)),
    ("Kick", ("kick",)), ("Discord", ("discord",)), ("Reddit", ("reddit",)),
    ("Pinterest", ("pinterest",)), ("Audiomack", ("audiomack",)), ("SoundCloud", ("soundcloud",)),
    ("Podcast", ("podcast", "itunes")), ("Apple Music", ("apple music",)), ("Clubhouse", ("clubhouse",)),
    ("VK / OK.ru", ("vk.com", "ok.ru", "rutube", "yandex")), ("Quora", ("quora",)),
    ("Shopee", ("shopee",)), ("Likee / Kwai", ("likee", "kwai")), ("Vimeo", ("vimeo",)),
    ("Tumblr", ("tumblr",)), ("Line", ("line voom",)), ("Tidal", ("tidal",)),
]

# order matters – first match wins
TYPE_WORDS = [
    ("Reactions", ("reaction", "react", "emoji")),
    ("Votes", ("vote", "poll")),
    ("Bot Starts", ("bot start", "start bot", "bot users", "referral", "bot member")),
    ("Boosts", ("boost",)),
    ("Comments", ("comment", "reply", "replies")),
    ("Shares", ("share", "forward", "repost", "retweet")),
    ("Saves", ("save",)),
    ("Live", ("live stream", "livestream", "live view", "live viewer", "live ")),
    ("Watch Time", ("watch time", "watchtime", "watch hour")),
    ("Story Views", ("story",)),
    ("Views", ("view", "impression", "play", "stream")),
    ("Subscribers", ("subscriber",)),
    ("Members", ("member", "join")),
    ("Followers", ("follower", "follow")),
    ("Likes", ("like", "heart", "favorite")),
]

DEFAULT_MARGIN = float(os.getenv("SMM_PROFIT_PERCENT", "40"))
MIN_PROFIT = float(os.getenv("SMM_MIN_PROFIT", "2"))
RATE_MULTIPLIER = float(os.getenv("SMM_RATE_MULTIPLIER", "1"))  # set e.g. 88 if panel shows USD
SYNC_HOURS = float(os.getenv("SMM_SYNC_HOURS", "6"))


def _has(text, words):
    return any(re.search(r"(?<![a-z])" + re.escape(w), text) for w in words)


def classify(name: str, category: str = ""):
    """Return (platform, type) or (None, None)."""
    cat_l = f" {html.unescape(category)} ".lower()
    name_l = f" {html.unescape(name)} ".lower()
    text = cat_l + name_l
    if "🔻" in category or "🔻" in name:          # panel section headers
        return None, None
    for o, words in OTHER_WORDS:                   # non-main platforms first (by category)
        if _has(cat_l, words):
            return "Others", o
    plat = None
    for p, words in PLATFORM_WORDS:
        if _has(cat_l, words):
            plat = p
            break
    if not plat:
        for p, words in PLATFORM_WORDS:
            if _has(name_l, words):
                plat = p
                break
    if not plat:
        if any(w in text for w in ("bot", "premium member", "online member", "referral")):
            plat = "Telegram"
        else:
            for o, words in OTHER_WORDS:
                if _has(text, words):
                    return "Others", o
            return "Others", "Other Services"
    typ = "Other"
    for src in (name_l, cat_l):                    # the service NAME decides first
        for t, words in TYPE_WORDS:
            if _has(src, words):
                typ = t
                break
        if typ != "Other":
            break
    if plat == "YouTube" and typ == "Members":
        typ = "Subscribers"
    if plat == "Telegram" and typ in ("Subscribers", "Followers"):
        typ = "Members"
    if plat == "Instagram" and typ == "Subscribers":
        typ = "Followers"
    if plat == "Telegram" and "star" in text and typ == "Other":
        typ = "Premium & Stars"
    return plat, typ


def normalize_category(category: str, name: str) -> str:
    """'Telegram' + 'Positive reactions'  ->  'Telegram • Reactions'."""
    category = (category or "").strip()
    if "•" in category:
        return category
    plat, typ = classify(name, category)
    if not plat:
        return category or "Other"
    return f"{plat} • {typ}"




# cost per 1K (₹) up to  ->  profit %
PRICE_TIERS = [(10, 100), (50, 60), (200, 40), (1000, 30), (10**12, 20)]


def tier_margin(cost: float) -> float:
    for limit, pct in PRICE_TIERS:
        if cost <= limit:
            return pct
    return 20


def sell_price(cost: float, margin: float | None = None) -> int:
    if margin is None:
        r = cur.execute("SELECT value FROM settings WHERE key='smm_margin'").fetchone()
        margin = float(r[0]) if r and r[0] not in (None, "", "auto") else tier_margin(cost)
    p = cost * (1 + margin / 100)
    p = max(p, cost + MIN_PROFIT)
    return max(1, math.ceil(p))


def _clean_name(n: str) -> str:
    n = html.unescape(str(n or "")).strip()
    n = re.sub(r"\s+", " ", n)
    return html.escape(n[:120])


def ensure_columns():
    cols = [r[1] for r in cur.execute("PRAGMA table_info(smm_services)").fetchall()]
    if "auto_synced" not in cols:
        cur.execute("ALTER TABLE smm_services ADD COLUMN auto_synced INTEGER DEFAULT 0")
    if "panel_type" not in cols:
        cur.execute("ALTER TABLE smm_services ADD COLUMN panel_type TEXT DEFAULT 'Default'")
    if "cost_per_1000" not in cols:
        cur.execute("ALTER TABLE smm_services ADD COLUMN cost_per_1000 REAL DEFAULT 0")
    db.commit()


def fix_existing_rows():
    """Repair services added by hand with a plain category (e.g. 'Telegram')."""
    ensure_columns()
    rows = cur.execute("SELECT id, name, category FROM smm_services").fetchall()
    for sid, name, cat in rows:
        new_cat = normalize_category(cat, name)
        new_name = re.sub(r"(?i)postitive", "Positive", name or "")
        if new_cat != cat or new_name != name:
            cur.execute("UPDATE smm_services SET category=?, name=? WHERE id=?", (new_cat, new_name, sid))
    # hide placeholders that have no panel ID – they can never be ordered
    cur.execute("UPDATE smm_services SET available=0 WHERE trim(coalesce(fansmm_service_id,''))=''")
    db.commit()


async def sync_panel(margin: float | None = None, force=True):
    """Import / update every panel service. Returns stats dict."""
    from plugins.smm import panel_services
    ensure_columns()
    data = await panel_services(force=force)
    if not isinstance(data, list) or not data:
        raise Exception("Panel returned no services (check SMM_API_KEY)")
    seen, added, updated, skipped = set(), 0, 0, 0
    for x in data:
        try:
            pid = str(x.get("service", "")).strip()
            if not pid:
                continue
            name = _clean_name(x.get("name"))
            plat, typ = classify(name, str(x.get("category", "")))
            if not plat:
                skipped += 1
                continue
            cost = round(float(x.get("rate", 0)) * RATE_MULTIPLIER, 4)
            mn = int(float(x.get("min", 10) or 10))
            mx = int(float(x.get("max", 100000) or 100000))
            if cost <= 0 or mx < mn:
                skipped += 1
                continue
            seen.add(pid)
            ptype = str(x.get("type") or "Default")
            cat = f"{plat} • {typ}"
            price = sell_price(cost, margin)
            desc = html.escape(f"{html.unescape(str(x.get('category', '')))}"[:150]) or name
            row = cur.execute("SELECT id, auto_synced, price_per_1000 FROM smm_services WHERE fansmm_service_id=?", (pid,)).fetchone()
            if row:
                sid, auto, old_price = row
                if auto == 2:          # deleted by admin -> never bring back
                    continue
                if auto:               # 3 = hidden by admin: update numbers, stay hidden
                    cur.execute("UPDATE smm_services SET name=?, category=?, min_qty=?, max_qty=?, price_per_1000=?, cost_per_1000=?, available=? WHERE id=?",
                                (name, cat, mn, mx, price, cost, 0 if auto == 3 else 1, sid))
                else:  # manual service: keep admin price, but never sell at a loss
                    new_price = old_price if (old_price or 0) > cost else price
                    cur.execute("UPDATE smm_services SET category=?, min_qty=?, max_qty=?, price_per_1000=?, cost_per_1000=? WHERE id=?",
                                (normalize_category(cat, name), mn, mx, new_price, cost, sid))
                cur.execute("UPDATE smm_services SET panel_type=? WHERE id=?", (ptype, sid))
                updated += 1
            else:
                cur.execute("INSERT INTO smm_services (name, category, fansmm_service_id, min_qty, max_qty, price_per_1000, description, available, cost_per_1000, auto_synced) VALUES (?,?,?,?,?,?,?,1,?,1)",
                            (name, cat, pid, mn, mx, price, desc, cost))
                cur.execute("UPDATE smm_services SET panel_type=? WHERE fansmm_service_id=?", (ptype, pid))
                added += 1
        except Exception as ex:
            skipped += 1
            logger.warning(f"smm sync skip {x}: {ex}")
    # services removed from the panel -> hide
    removed = 0
    for sid, pid in cur.execute("SELECT id, fansmm_service_id FROM smm_services WHERE auto_synced=1 AND available=1").fetchall():
        if str(pid) not in seen:
            cur.execute("UPDATE smm_services SET available=0 WHERE id=?", (sid,))
            removed += 1
    cur.execute("UPDATE smm_services SET available=0 WHERE trim(coalesce(fansmm_service_id,''))=''")
    db.commit()
    return {"added": added, "updated": updated, "skipped": skipped, "removed": removed,
            "margin": margin if margin is not None else "auto (tiers)"}


async def _loop():
    await asyncio.sleep(5)
    while True:
        try:
            r = await sync_panel()
            logger.info(f"SMM sync OK: {r}")
        except Exception as ex:
            logger.warning(f"SMM sync failed: {ex}")
        await asyncio.sleep(max(0.5, SYNC_HOURS) * 3600)


def register_smm_sync(bot):
    fix_existing_rows()
    try:
        asyncio.get_event_loop().create_task(_loop())
    except Exception as ex:
        logger.warning(f"SMM sync loop not started: {ex}")

    @bot.on(events.NewMessage(pattern=r"^/smmsync$"))
    async def _sync(e):
        if e.sender_id not in ADMIN_IDS: return
        m = await e.reply("⏳ Importing all panel services…")
        try:
            r = await sync_panel()
            await m.edit(f"✅ <b>SMM sync done</b>\n➕ Added: {r['added']}\n🔄 Updated: {r['updated']}\n"
                         f"🙈 Hidden (removed from panel): {r['removed']}\n⏭ Skipped: {r['skipped']}\n"
                         f"👑 Profit margin: {r['margin']}")
        except Exception as ex:
            await m.edit(f"⚠️ Sync failed: {html.escape(str(ex))}")

    @bot.on(events.NewMessage(pattern=r"^/setmargin (auto|\d+(?:\.\d+)?)$"))
    async def _margin_cmd(e):
        if e.sender_id not in ADMIN_IDS: return
        raw = e.pattern_match.group(1)
        val = None if raw == "auto" else float(raw)
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('smm_margin', ?)", (raw,))
        db.commit()
        n = 0
        for sid, cost in cur.execute("SELECT id, cost_per_1000 FROM smm_services WHERE auto_synced=1 AND cost_per_1000>0").fetchall():
            cur.execute("UPDATE smm_services SET price_per_1000=? WHERE id=?", (sell_price(cost, val), sid)); n += 1
        db.commit()
        await e.reply(f"✅ Profit margin set to <b>{'auto tiers' if val is None else str(val) + '%'}</b> · {n} prices updated.")

    @bot.on(events.NewMessage(pattern=r"^/smmprices(?: (\w+))?$"))
    async def _prices(e):
        if e.sender_id not in ADMIN_IDS: return
        plat = e.pattern_match.group(1)
        q = "SELECT id, category, name, cost_per_1000, price_per_1000 FROM smm_services WHERE available=1"
        args = ()
        if plat:
            q += " AND lower(category) LIKE ?"; args = (plat.lower() + "%",)
        rows = cur.execute(q + " ORDER BY category, price_per_1000", args).fetchall()
        if not rows: return await e.reply("No services.")
        out, last = "", None
        for sid, cat, n, c, p in rows:
            if cat != last:
                out += f"\n<b>{cat}</b>\n"; last = cat
            out += f"<code>{sid}</code> {n[:40]} · 🧾₹{round(c or 0, 2)} → 💵₹{p} · 👑₹{round(p - (c or 0), 2)}\n"
        for i in range(0, len(out), 3800):
            await e.respond(out[i:i + 3800])
