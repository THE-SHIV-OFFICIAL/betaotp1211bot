import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("API_ID", "1"); os.environ.setdefault("API_HASH", "x")
from plugins.tglion import tl_price_from_inr
from utils.svcinfo import drop_info, refill_info


class Server2Prices(unittest.TestCase):
    def test_panel_30_sells_39(self):
        self.assertEqual(tl_price_from_inr(30), 39)

    def test_panel_33_sells_44(self):
        self.assertEqual(tl_price_from_inr(33), 44)

    def test_costly_accounts_earn_more_profit(self):
        self.assertGreater(tl_price_from_inr(200) - 200, tl_price_from_inr(30) - 30)


class TopUp(unittest.TestCase):
    def test_empty_balance_pays_full_price(self):
        from plugins.deposit import topup_needed
        self.assertEqual(topup_needed(0, 39), 39)

    def test_partial_balance_pays_difference_min_10(self):
        from plugins.deposit import topup_needed
        self.assertEqual(topup_needed(30, 39), 10)
        self.assertEqual(topup_needed(5, 44), 39)


class ServiceInfo(unittest.TestCase):
    def test_non_drop(self):
        self.assertIn("Non", drop_info("Members [Non Drop]").replace("𝐍ᴏɴ", "Non"))

    def test_refill_days(self):
        self.assertIn("30", refill_info("Followers [30 Days Refill]"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
