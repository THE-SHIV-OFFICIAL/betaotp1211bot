import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("API_ID", "1"); os.environ.setdefault("API_HASH", "x")
from plugins import lztmarket as lz


class LztParsing(unittest.TestCase):
    def test_code_plain(self):
        self.assertEqual(lz._find_code({"code": "12345"}), "12345")

    def test_code_list_newest(self):
        self.assertEqual(lz._find_code({"codes": [{"code": "111", "date": 1}, {"code": "222", "date": 5}]}), "222")

    def test_no_code(self):
        self.assertIsNone(lz._find_code({"codes": []}))

    def test_login_info(self):
        self.assertEqual(lz.item_login_info({"loginData": {"login": "919999999999", "password": "pw"}}), ("+919999999999", "pw"))

    def test_country_key(self):
        self.assertEqual(lz.country_key({"telegram_country": "in"}), ("IN", "IN"))
        self.assertEqual(lz.country_key({}), ("XX", "Unknown"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
