"""Readable delivery / drop / refill info for an SMM service.

Panels put this info in the service name (e.g. "Members [Non Drop] [30 Days Refill]
[0-1 Hr Start] [10K/Day]"). We read the name + description + panel flags and turn
them into clear lines for the user.
"""
import re


def _text(*parts):
    return " ".join(str(p or "") for p in parts).lower()


def drop_info(name, desc=""):
    t = _text(name, desc)
    if re.search(r"non[\s\-]?drop|no[\s\-]?drop|0%\s*drop|zero\s*drop|lifetime|permanent", t):
        return "✅ <b>𝐍ᴏɴ-𝐃ʀᴏᴘ</b> — ᴘᴇʀᴍᴀɴᴇɴᴛ, ᴡɪʟʟ ɴᴏᴛ ᴅʀᴏᴘ"
    m = re.search(r"(?:drop|drops)\s*(?:rate)?\s*[:\-]?\s*(\d+\s*(?:-|to)?\s*\d*)\s*%", t) or \
        re.search(r"(\d+\s*(?:-|to)?\s*\d*)\s*%\s*drop", t)
    if m:
        return f"⚠️ <b>𝐃ʀᴏᴘ:</b> ~{m.group(1).replace(' ', '')}% ᴍᴀʏ ᴅʀᴏᴘ ᴏᴠᴇʀ ᴛɪᴍᴇ"
    if re.search(r"low[\s\-]?drop|less\s*drop|stable", t):
        return "🟢 <b>𝐋ᴏᴡ 𝐃ʀᴏᴘ</b> — ᴠᴇʀʏ sᴍᴀʟʟ ᴅʀᴏᴘ ᴘᴏssɪʙʟᴇ"
    if re.search(r"high[\s\-]?drop|may\s*drop|drop\s*possible", t):
        return "🔴 <b>𝐇ɪɢʜ 𝐃ʀᴏᴘ</b> — ᴄᴀɴ ᴅʀᴏᴘ, ɴᴏ ɢᴜᴀʀᴀɴᴛᴇᴇ"
    if re.search(r"view|reaction|vote|share|bot\s*start|watch|live|story", t):
        return "✅ <b>𝐍ᴏ 𝐃ʀᴏᴘ</b> — ᴠɪᴇᴡs/ʀᴇᴀᴄᴛɪᴏɴs sᴛᴀʏ ᴘᴇʀᴍᴀɴᴇɴᴛ"
    return "⚠️ <b>𝐃ʀᴏᴘ ᴘᴏssɪʙʟᴇ</b> — ɴᴏ ɴᴏɴ-ᴅʀᴏᴘ ɢᴜᴀʀᴀɴᴛᴇᴇ"


def refill_info(name, desc="", panel_refill=None):
    t = _text(name, desc)
    m = re.search(r"(\d+)\s*(?:days?|d)\s*(?:auto\s*)?refill", t) or re.search(r"refill\s*[:\-]?\s*(\d+)\s*(?:days?|d)\b", t) \
        or re.search(r"\br(\d+)\b", t)
    if re.search(r"lifetime\s*refill|refill\s*lifetime|\br365\b", t):
        return "♻️ <b>𝐑ᴇғɪʟʟ:</b> ʟɪғᴇᴛɪᴍᴇ"
    if m:
        return f"♻️ <b>𝐑ᴇғɪʟʟ:</b> {m.group(1)} ᴅᴀʏs"
    if re.search(r"no\s*refill|without\s*refill|\br0\b", t) or panel_refill is False:
        return "🚫 <b>𝐑ᴇғɪʟʟ:</b> ɴᴏ ʀᴇғɪʟʟ"
    if panel_refill is True or "refill" in t:
        return "♻️ <b>𝐑ᴇғɪʟʟ:</b> ᴀᴠᴀɪʟᴀʙʟᴇ"
    return "🚫 <b>𝐑ᴇғɪʟʟ:</b> ɴᴏ ʀᴇғɪʟʟ"


def start_info(name, desc=""):
    t = _text(name, desc)
    if re.search(r"instant|0\s*-\s*5\s*min|0\s*min", t):
        return "⚡ <b>𝐒ᴛᴀʀᴛ:</b> ɪɴsᴛᴀɴᴛ (0-5 ᴍɪɴ)"
    m = re.search(r"(?:start|starts|start\s*time)\s*[:\-]?\s*(\d+\s*-?\s*\d*)\s*(min|mins|minutes|hr|hrs|hour|hours|h)\b", t) \
        or re.search(r"(\d+\s*-\s*\d+)\s*(min|mins|minutes|hr|hrs|hour|hours|h)\s*start", t) \
        or re.search(r"(\d+\s*-\s*\d+)\s*(min|mins|minutes|hr|hrs|hour|hours|h)\b", t)
    if m:
        unit = "ᴍɪɴ" if m.group(2).startswith("m") else "ʜᴏᴜʀs"
        return f"⏱ <b>𝐒ᴛᴀʀᴛ:</b> {m.group(1).replace(' ', '')} {unit}"
    return "⏱ <b>𝐒ᴛᴀʀᴛ:</b> 0-1 ʜᴏᴜʀ (ᴜsᴜᴀʟʟʏ ғᴀsᴛᴇʀ)"


def speed_info(name, desc=""):
    t = _text(name, desc)
    m = re.search(r"(\d+(?:\.\d+)?\s*k?)\s*(?:/|per\s*)\s*(day|d|hour|hr|h)\b", t)
    if m:
        per = "ᴅᴀʏ" if m.group(2).startswith("d") else "ʜᴏᴜʀ"
        return f"🚀 <b>𝐒ᴘᴇᴇᴅ:</b> {m.group(1).replace(' ', '').upper()} / {per}"
    return None


def service_info_lines(name, desc="", panel=None):
    panel = panel or {}
    refill = panel.get("refill")
    if isinstance(refill, str):
        refill = refill.strip().lower() in ("1", "true", "yes")
    lines = [start_info(name, desc)]
    sp = speed_info(name, desc)
    if sp: lines.append(sp)
    lines.append(drop_info(name, desc))
    lines.append(refill_info(name, desc, refill if refill is not None else None))
    cancel = panel.get("cancel")
    if cancel in (True, 1, "1", "true"):
        lines.append("↩️ <b>𝐂ᴀɴᴄᴇʟ:</b> ᴀᴠᴀɪʟᴀʙʟᴇ")
    return lines
