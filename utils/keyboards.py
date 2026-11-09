from telethon import Button
from config import TERMS_URL, JOIN_URLS
from database import is_admin, get_support_url

# We use bg_primary (blue), bg_success (green), bg_danger (red)
# For icon, we pass the custom emoji ID (int)

from config import SUPPORT_USERNAME
from premium_emojis import premium_service_id
SUPPORT_URL = f"https://t.me/{SUPPORT_USERNAME}"


def style_btn(text, data, style_type=None, icon=None):
    return Button.inline(text, data, style=style_type, icon=icon)

def copy_btn(text, copy_text, style_type=None, icon=None, fallback_data=None):
    """Native Telegram copy button; falls back to a normal callback on older clients/libraries."""
    try:
        from telethon.tl import types
        return types.KeyboardInlineButton(text, types.InlineButtonTypeCopy(copy_text=str(copy_text)[:256]),
                                          style=Button._get_style(style_type, icon))
    except Exception:
        return Button.inline(text, fallback_data or b"noop", style=style_type, icon=icon)

def style_url(text, url, style_type=None, icon=None):
    return Button.url(text, url, style=style_type, icon=icon)


def get_terms_buttons():
    buttons = []
    if TERMS_URL and TERMS_URL.startswith("http"):
        buttons.append([Button.url("📜 Read Terms & Conditions", TERMS_URL)])
    buttons.append([
        style_btn("𝐀ᴄᴄᴇᴘᴛ", b"tc_accept", style_type='success', icon=5409380965644514142),
        style_btn("𝐑ᴇᴊᴇᴄᴛ", b"tc_reject", style_type='danger', icon=5354889508674360491)
    ])
    return buttons

def get_join_buttons():
    from config import JOIN_LABELS
    buttons = [[style_url(JOIN_LABELS[i] if i < len(JOIN_LABELS) else f"📢 Join {i+1}", link, "primary")] for i, link in enumerate(JOIN_URLS) if link]
    buttons.append([style_btn("✅ 𝐉ᴏɪɴᴇᴅ — 𝐕ᴇʀɪғʏ", b"verify_join", style_type='success', icon=6129627894349045589)])
    return buttons

def get_persistent_menu(uid):
    """Bottom reply keyboard (same layout as the reference screenshot)."""
    from database import is_admin
    buttons = [
        [Button.text("𝐏ʀᴏғɪʟᴇ", resize=True, style="primary", icon=6203982793379154737), Button.text("𝐌ʏ 𝐎ʀᴅᴇʀs", resize=True, style="primary", icon=5409098988156629257)],
        [Button.text("𝐁ᴀʟᴀɴᴄᴇ", resize=True, style="success", icon=5409320020058584473), Button.text("𝐒ᴛᴏᴄᴋ", resize=True, style="primary", icon=6129627894349045589)],
        [Button.text("𝐑ᴇғᴇʀ", resize=True, style="success", icon=5440627033111557670), Button.text("𝐒ᴜᴘᴘᴏʀᴛ", resize=True, style="primary", icon=6129732880529628243)],
        [Button.text("𝐒ᴛᴀʀᴛ", resize=True, style="success", icon=6129399728506412489)],
    ]
    if is_admin(uid):
        buttons.append([Button.text("𝐀ᴅᴍɪɴ 𝐏ᴀɴᴇʟ", resize=True, style="danger", icon=5409166771330494453)])
    return buttons

def get_main_inline_menu():
    """Inline menu: dark (default) buttons, green Bot Guide, red More."""
    return [
        [style_btn("Buy telegram Acc", b"menu_buy", "primary", premium_service_id("✈️", 6264777724741556322)),
         style_btn("Buy Whatsapp Acc", b"menu_whatsapp", "primary", premium_service_id("💬", 5206384258431599552))],
        [style_btn("All apps sms", b"menu_numbers", None, premium_service_id("📲", 6100636573043268040)),
         style_btn("Social media services", b"menu_smm", None, premium_service_id("🚀", 6129639980387015660))],
        [style_btn("Recharge", b"menu_recharge", "primary", premium_service_id("💲", 5206391796099204564)),
         style_btn("My Profile", b"menu_account", "primary", premium_service_id("👑", 6129739490484294910))],
        [style_url("Support", get_support_url(), None, 6129732880529628243),
         style_btn("Settings", b"menu_settings", None, premium_service_id("🛠", 5213214428958306222))],
        [style_btn("Bot Guide", b"menu_guide", "success", premium_service_id("📲", 5900192223160438756))],
        [style_btn("More", b"menu_more", "danger", premium_service_id("⬅️", 5215361191051798408))],
    ]

def get_more_menu():
    return [
        [style_btn("💻 Buy Repo", b"menu_store", "primary", icon=5409098988156629257)],
        [style_btn("📦 My Orders", b"menu_orders"), style_btn("💰 Balance", b"menu_balance")],
        [style_btn("📊 Stock", b"menu_stock"), style_btn("🎁 Refer & Earn", b"menu_refer", "success")],
        [style_url("📢 Updates", "https://t.me/BETABOT_HUB", "primary"),
         style_url("🛒 Proofs", "https://t.me/Beta_account_store", "primary")],
        [style_btn("📜 Terms & Conditions", b"menu_terms", icon=5408995930416362034)],
        [style_btn("⬅️ Back", b"menu_home", "danger")],
    ]

def get_support_buttons():
    buttons = [
        [Button.url("📩 Contact Support", SUPPORT_URL)],
    ]
    if TERMS_URL and TERMS_URL.startswith("http"):
        buttons.append([Button.url("📜 Terms & Conditions", TERMS_URL)])
    if JOIN_URLS:
        buttons.append([Button.url("📢 Channel", JOIN_URLS[0])])
    return buttons

def get_keypad():
    return [
        [style_btn("1", b"kp_1", style_type="primary", icon=6064275556008989746), style_btn("2", b"kp_2", style_type="primary", icon=5409337058193847247), style_btn("3", b"kp_3", style_type="primary", icon=5355292788923593967)],
        [style_btn("4", b"kp_4", style_type="primary", icon=5409320020058584473), style_btn("5", b"kp_5", style_type="primary", icon=6064310143380625195), style_btn("6", b"kp_6", style_type="primary", icon=6129399728506412489)],
        [style_btn("7", b"kp_7", style_type="primary", icon=6129779562529168023), style_btn("8", b"kp_8", style_type="primary", icon=6154249597532248059), style_btn("9", b"kp_9", style_type="primary", icon=6129812419028982717)],
        [style_btn("Del", b"kp_del", style_type="danger", icon=6129731974291527294), style_btn("0", b"kp_0", style_type="primary", icon=6203982793379154737), style_btn("Confirm", b"kp_done", style_type="success", icon=6129399728506412489)],
        [style_btn("𝐂ᴀɴᴄᴇʟ", b"cancel_action", style_type="danger", icon=6064310143380625195)]
    ]
