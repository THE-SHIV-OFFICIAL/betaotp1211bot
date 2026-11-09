"""Which link each SMM service needs + validation.

Wrong link = panel cancels the order (e.g. YouTube Subscribers with a t.me link,
or Telegram Reactions with a channel link instead of a POST link).
Every service is mapped to one rule below; the user is shown an exact example and
the bot refuses links that do not match before any money is taken.
"""
import re

TG_RE = re.compile(r"(?i)(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/(s/)?(c/\d+|\+[\w-]+|joinchat/[\w-]+|[a-z0-9_]{3,})(?:/(\d+))?(?:/(\d+))?(\?start=\S+)?")

PLATFORM_DOMAINS = {
    "Telegram": ("t.me", "telegram.me", "telegram.dog"),
    "YouTube": ("youtube.com", "youtu.be"),
    "Instagram": ("instagram.com", "instagr.am"),
    "Facebook": ("facebook.com", "fb.com", "fb.watch"),
    "TikTok": ("tiktok.com",),
    "Twitter": ("twitter.com", "x.com"),
    "Threads": ("threads.net", "threads.com"),
    "Spotify": ("spotify.com",),
    "WhatsApp": ("whatsapp.com", "wa.me"),
}

# rule -> (title, examples, help)
RULES = {
    "tg_post": ("Telegram POST link", ["https://t.me/yourchannel/123"],
                "Post kholo → ⋮ → <b>Copy Post Link</b>. Ya post ko seedha <b>forward</b> kar do. Channel <b>public</b> hona chahiye."),
    "tg_channel": ("Telegram CHANNEL / GROUP link", ["https://t.me/yourchannel", "@yourchannel"],
                   "Post link (…/123) mat bhejo, sirf channel/group ka link. Channel <b>public</b> hona chahiye."),
    "tg_auto": ("Telegram CHANNEL link (auto service)", ["https://t.me/yourchannel"],
                "Auto service naye/purane posts par khud lagti hai – sirf <b>public channel</b> ka link bhejo."),
    "tg_bot": ("Telegram BOT link", ["https://t.me/yourbot", "https://t.me/yourbot?start=ref123"],
               "Bot ka username link ya referral link bhejo."),
    "yt_video": ("YouTube VIDEO / SHORTS link",
                 ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ", "https://youtube.com/shorts/abc123"],
                 "Video kholo → Share → Copy link."),
    "yt_channel": ("YouTube CHANNEL link", ["https://www.youtube.com/@yourchannel", "https://www.youtube.com/channel/UCxxxx"],
                   "Subscribers ke liye CHANNEL link chahiye, video ya Telegram link nahi."),
    "yt_live": ("YouTube LIVE stream link", ["https://www.youtube.com/watch?v=xxxx", "https://youtube.com/live/xxxx"],
                "Live chal raha hona chahiye jab order karo."),
    "ig_profile": ("Instagram PROFILE link", ["https://www.instagram.com/yourusername"], "Account <b>public</b> hona chahiye."),
    "ig_post": ("Instagram POST / REEL link", ["https://www.instagram.com/p/Cxxxxxx/", "https://www.instagram.com/reel/Cxxxxxx/"],
                "Post/Reel → ⋯ → Copy link. Account <b>public</b> hona chahiye."),
    "ig_story": ("Instagram PROFILE link (story)", ["https://www.instagram.com/yourusername"], "Story abhi live honi chahiye."),
    "fb_page": ("Facebook PAGE / PROFILE link", ["https://www.facebook.com/yourpage"], "Page public hona chahiye."),
    "fb_post": ("Facebook POST / VIDEO link", ["https://www.facebook.com/yourpage/posts/123", "https://fb.watch/xxxx"], "Post public honi chahiye."),
    "tt_profile": ("TikTok PROFILE link", ["https://www.tiktok.com/@yourusername"], "Account public hona chahiye."),
    "tt_video": ("TikTok VIDEO link", ["https://www.tiktok.com/@user/video/1234567890"], "Video → Share → Copy link."),
    "tw_profile": ("X / Twitter PROFILE link", ["https://x.com/yourusername"], ""),
    "tw_post": ("X / Twitter POST link", ["https://x.com/user/status/1234567890"], ""),
    "wa_channel": ("WhatsApp CHANNEL link", ["https://whatsapp.com/channel/0029Vaxxxx"], ""),
    "sp_link": ("Spotify TRACK / ARTIST / PLAYLIST link", ["https://open.spotify.com/track/xxxx"], ""),
    "url": ("Link (URL)", ["https://example.com/your-page"], "Jis page/profile/post par service chahiye uska poora link."),
}


def platform_of(cat, name=""):
    if cat and "•" in cat:
        return cat.split("•", 1)[0].strip()
    t = f" {name} {cat} ".lower()
    for p in PLATFORM_DOMAINS:
        if p.lower() in t:
            return p
    return "Others"


def link_rule(name, cat=""):
    """Map a service to the RULES key it needs."""
    plat = platform_of(cat, name)
    typ = cat.split("•", 1)[1].strip().lower() if "•" in (cat or "") else ""
    t = f" {name} {cat} ".lower()
    has = lambda *w: any(x in t for x in w)
    if plat == "Telegram":
        if has("bot start", "start bot", "referral", "bot user") or typ == "bot starts":
            return "tg_bot"
        if has("auto", "future post", "new post", "subscription"):
            return "tg_auto"
        if (typ in ("members", "boosts", "premium & stars") or has("member", "subscriber", "boost", "join")) \
                and not has("reaction", "view", "vote", "poll", "comment", "share"):
            return "tg_channel"
        return "tg_post"
    if plat == "YouTube":
        if has("live"):
            return "yt_live"
        if typ == "subscribers" or has("subscriber", "member"):
            return "yt_channel"
        return "yt_video"
    if plat == "Instagram":
        if typ == "story views" or has("story"):
            return "ig_story"
        if typ == "followers" or has("follower"):
            return "ig_profile"
        return "ig_post"
    if plat == "Facebook":
        return "fb_page" if has("follower", "page like", "friend") else "fb_post"
    if plat == "TikTok":
        return "tt_profile" if has("follower") else "tt_video"
    if plat == "Twitter":
        return "tw_profile" if has("follower") else "tw_post"
    if plat == "WhatsApp":
        return "wa_channel"
    if plat == "Spotify":
        return "sp_link"
    return "url"


def link_prompt(rule):
    title, ex, help_ = RULES.get(rule, RULES["url"])
    exs = "\n".join(f"✅ <code>{e}</code>" for e in ex)
    return (f"🔗 <b>Step 1:</b> Send your <b>{title}</b>\n\n<b>Example:</b>\n{exs}"
            + (f"\n\n💡 {help_}" if help_ else ""))


def normalize_tg(text):
    """(url, username, post_id, start) for the first Telegram link, or None."""
    if not text:
        return None
    m = TG_RE.search(text)
    if m:
        chan = m.group(2)
        post = m.group(4) or m.group(3)
        url = f"https://t.me/{chan}" + (f"/{post}" if post else "")
        private = chan.lower().startswith(("c/", "+", "joinchat"))
        return url, (None if private else chan), post, (m.group(5) or "")
    m = re.search(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_]{3,31})\b", text)
    if m:
        return f"https://t.me/{m.group(1)}", m.group(1), None, ""
    return None


def _wrong(rule, why):
    return None, f"{why}\n\n<blockquote>{link_prompt(rule)}</blockquote>"


def check_link(rule, link):
    """Return (fixed_link, error_html_or_None)."""
    link = (link or "").strip()
    is_tg = bool(TG_RE.search(link)) or link.startswith("@")
    if rule.startswith("tg_"):
        tg = normalize_tg(link)
        if not tg:
            return _wrong(rule, "❌ Yeh Telegram link nahi hai.")
        url, user, post, start = tg
        if rule == "tg_post":
            if not post:
                return _wrong(rule, "❌ Yeh service <b>POST link</b> maangti hai, aapne <b>channel link</b> bheja.\n(Isi wajah se panel order CANCEL karta hai.)")
            if not user:
                return _wrong(rule, "❌ Private channel (t.me/c/…) ka post nahi chalega. Channel <b>public</b> karo.")
            return url, None
        if rule in ("tg_channel", "tg_auto"):
            if post:
                url = url.rsplit("/", 1)[0]
            if not user and rule == "tg_auto":
                return _wrong(rule, "❌ Auto service ke liye <b>public channel</b> link chahiye.")
            return url, None
        if rule == "tg_bot":
            if not user or not user.lower().endswith("bot"):
                return _wrong(rule, "❌ Yeh bot link nahi lag raha (username 'bot' par khatam hona chahiye).")
            return f"https://t.me/{user}{start}", None
    plat = {"yt": "YouTube", "ig": "Instagram", "fb": "Facebook", "tt": "TikTok",
            "tw": "Twitter", "wa": "WhatsApp", "sp": "Spotify"}.get(rule.split("_")[0])
    if plat:
        if is_tg:
            return _wrong(rule, f"❌ Aapne <b>Telegram link</b> bheja, yeh <b>{plat}</b> service hai.\n(Isi wajah se panel order CANCEL karta hai.)")
        l = link.lower()
        if not any(d in l for d in PLATFORM_DOMAINS[plat]):
            return _wrong(rule, f"❌ Yeh {plat} link nahi hai.")
        vid = ("watch?v=" in l or "youtu.be/" in l or "/shorts/" in l or "/live/" in l)
        if rule == "yt_channel" and vid:
            return _wrong(rule, "❌ Subscribers ke liye <b>CHANNEL</b> link chahiye, video link nahi.")
        if rule in ("yt_video", "yt_live") and not vid:
            return _wrong(rule, "❌ Yeh service <b>VIDEO</b> link maangti hai, channel link nahi.")
        if rule == "ig_post" and not any(x in l for x in ("/p/", "/reel/", "/reels/", "/tv/")):
            return _wrong(rule, "❌ Yeh service <b>POST/REEL</b> link maangti hai, profile link nahi.")
        if rule in ("ig_profile", "ig_story") and any(x in l for x in ("/p/", "/reel/", "/tv/")):
            return _wrong(rule, "❌ Yeh service <b>PROFILE</b> link maangti hai, post link nahi.")
        if rule == "tt_video" and not any(x in l for x in ("/video/", "vm.tiktok", "vt.tiktok")):
            return _wrong(rule, "❌ Yeh service <b>VIDEO</b> link maangti hai.")
        if rule == "tw_post" and "/status/" not in l:
            return _wrong(rule, "❌ Yeh service <b>POST</b> link (…/status/…) maangti hai.")
        return (link if l.startswith("http") else "https://" + link), None
    if not re.match(r"(?i)^(https?://)?[\w-]+(\.[\w-]+)+", link):
        return _wrong(rule, "❌ Valid link bhejo.")
    return (link if link.lower().startswith("http") else "https://" + link), None


def username_from_link(link):
    tg = normalize_tg(link or "")
    return tg[1] if tg and tg[1] else ""


def link_guide_text():
    out = ["<b>🔗 Kaunsi service me kaunsa link dena hai</b>"]
    groups = [
        ("Telegram", [("Reactions / Views / Votes / Comments / Shares", "tg_post"),
                      ("Members / Subscribers / Boosts", "tg_channel"),
                      ("Auto Reactions / Auto Views (New/Old post)", "tg_auto"),
                      ("Bot Starts / Referrals", "tg_bot")]),
        ("YouTube", [("Views / Likes / Comments / Watch time", "yt_video"),
                     ("Subscribers", "yt_channel"), ("Live viewers", "yt_live")]),
        ("Instagram", [("Followers", "ig_profile"), ("Likes / Views / Comments / Saves", "ig_post"),
                       ("Story views", "ig_story")]),
        ("Others", [("Facebook post", "fb_post"), ("TikTok video", "tt_video"), ("X post", "tw_post"),
                    ("Website / other", "url")]),
    ]
    for plat, items in groups:
        out.append(f"\n<b>{plat}</b>")
        for label, rule in items:
            out.append(f"• {label} → <code>{RULES[rule][1][0]}</code>")
    out.append("\n⚠️ Galat link = panel order <b>CANCEL</b> kar deta hai (paisa wapas balance me aata hai).")
    return "\n".join(out)
