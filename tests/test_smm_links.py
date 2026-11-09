import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.smm_links import link_rule, check_link, normalize_tg

def test_rules():
    assert link_rule("Telegram mix positive Reaction + Views", "Telegram • Reactions") == "tg_post"
    assert link_rule("Channel Members", "Telegram • Members") == "tg_channel"
    assert link_rule("Auto TG Mix Positive Reactions [New / Old Post]", "Telegram • Reactions") == "tg_auto"
    assert link_rule("YouTube Subscribers Max 100K", "YouTube • Subscribers") == "yt_channel"
    assert link_rule("Instagram Likes", "Instagram • Likes") == "ig_post"

def test_checks():
    assert check_link("tg_post", "https://t.me/sukoon_s")[1]
    assert check_link("tg_post", "t.me/betabot_hub/6617")[0] == "https://t.me/betabot_hub/6617"
    assert check_link("tg_channel", "https://t.me/betabot_hub/6617")[0] == "https://t.me/betabot_hub"
    assert check_link("yt_channel", "https://t.me/maaambey")[1]
    assert check_link("yt_channel", "https://youtube.com/@abc")[1] is None
    assert check_link("yt_video", "https://youtu.be/xyz")[1] is None
    assert normalize_tg("x https://t.me/c/123/45")[2] == "45"

if __name__ == "__main__":
    test_rules(); test_checks(); print("tests OK")
