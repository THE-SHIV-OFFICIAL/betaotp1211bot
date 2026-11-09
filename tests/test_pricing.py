import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("API_ID", "1"); os.environ.setdefault("API_HASH", "x")
from plugins import social


class PricingRules(unittest.TestCase):
    def test_telegram_server3_is_lzt_not_hero(self):
        self.assertEqual(social.HERO_SERVERS["tg"], ())
        self.assertNotIn(("tg", 3), social.RISKY)

    def test_telegram_server3_has_profit(self):
        sell, cost, _ = social.gz_offer("tg", 3, 1.0)
        self.assertGreaterEqual(sell - cost, 10)

    def test_whatsapp_server2_cheaper_than_server1(self):
        self.assertLess(social.gz_offer("wa", 2, 0.5)[0], social.gz_offer("wa", 1, 0.5)[0])

    def test_risky_servers_have_warning(self):
        self.assertIn(("wa", 2), social.RISKY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
