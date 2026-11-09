"""Offline tests: number flow (tip / change / cancel / 2 min lock), Change TG No,
new-country notifications, panel balance alerts, admin Remove Acc, main menu.
Run from the source root in a disposable DATA_DIR (see AGENTS.md)."""
import asyncio
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.update(API_ID="1", API_HASH="x", BOT_TOKEN="1:x", ADMIN_ID="1", OWNER_ID="1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database as d
from utils import states
from plugins import social, numflow, notify, admin_actions


def labels(rows):
    return [b["text"] for row in rows for b in row]


def datas(rows):
    return [b["data"] if isinstance(b["data"], bytes) else str(b["data"]).encode()
            for row in rows for b in row if b.get("data")]


class NumFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        states.user_locks.clear()
        numflow._unlocked.clear(); numflow._pollers.clear(); numflow._locks.clear()
        for t in ("number_orders", "delivery_thanks"):
            try: d.cur.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.uid = 5551
        d.ensure_user(self.uid)
        d.cur.execute("UPDATE users SET balance=1000, terms_accepted=1 WHERE user_id=?", (self.uid,)); d.db.commit()
        self.bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=42)),
                                   edit_message=AsyncMock(), send_file=AsyncMock())
        self.ev = SimpleNamespace(sender_id=self.uid, message_id=77, edit=AsyncMock(), answer=AsyncMock(), respond=AsyncMock())
        self.rows = [("22", "India", "IN", 0.2, 10, 0)]

    def bal(self):
        return d.cur.execute("SELECT balance FROM users WHERE user_id=?", (self.uid,)).fetchone()[0]

    def order(self, oid=None):
        q = "SELECT id FROM number_orders ORDER BY id DESC LIMIT 1"
        oid = oid or d.cur.execute(q).fetchone()[0]
        return numflow.load(oid)

    async def _place(self, code="wa", server=2, status="STATUS_WAIT_CODE", number="911"):
        """Buy a number and stop polling right after the screen is shown."""
        with patch.object(social, "gz_rows", new=AsyncMock(return_value=self.rows)), \
             patch("plugins.herosms.get_number", new=AsyncMock(return_value={"activationId": "A1", "phoneNumber": number, "activationCost": 0.2})), \
             patch.object(numflow, "run_poll", new=AsyncMock()):
            await social.buy_number(self.bot, self.ev, code, server, "22")
        return self.order()

    # ---- screen ----
    async def test_screen_has_vpn_tip_copy_change_cancel_locked(self):
        o = await self._place()
        text = self.ev.edit.await_args.args[0]
        btns = self.ev.edit.await_args.kwargs["buttons"]
        self.assertIn("Use VPN while logging in for the first time", text)
        self.assertIn("+911", text)
        self.assertEqual(len(btns), 2)
        self.assertEqual(len(btns[0]), 2)          # [Copy No] [Change No]
        self.assertIn("Copy No", btns[0][0]["text"])
        self.assertIn("Change No", btns[0][1]["text"])
        self.assertIn("Cancel", btns[1][0]["text"])  # Cancel below
        self.assertIn("⏳", btns[0][1]["text"])      # locked for 2 min
        self.assertEqual(o["meta"]["msg_id"], 77)
        self.assertLess(self.bal(), 1000)

    # ---- 2 minute timer ----
    async def test_change_and_cancel_locked_for_two_minutes(self):
        o = await self._place()
        with patch("plugins.herosms.set_status", new=AsyncMock()) as ss:
            await numflow.on_change(self.bot, self.ev, o["id"])
            await numflow.on_cancel(self.bot, self.ev, o["id"])
        ss.assert_not_awaited()
        self.assertEqual(self.ev.answer.await_count, 2)
        self.assertIn("2 minutes", self.ev.answer.await_args.args[0])
        self.assertEqual(self.order(o["id"])["status"], "waiting")

    def _age(self, oid, seconds=130):
        d.cur.execute("UPDATE number_orders SET started=? WHERE id=?", (time.time() - seconds, oid)); d.db.commit()

    async def test_cancel_after_timer_refunds(self):
        o = await self._place(); price = o["price"]
        self._age(o["id"])
        with patch("plugins.herosms.set_status", new=AsyncMock(return_value="ACCESS_CANCEL")) as ss:
            await numflow.on_cancel(self.bot, self.ev, o["id"])
            ss.assert_awaited_once_with("A1", 8)
            await numflow.on_cancel(self.bot, self.ev, o["id"])   # double tap: no second refund
        self.assertEqual(self.order(o["id"])["status"], "cancelled")
        self.assertEqual(self.bal(), 1000)
        self.assertEqual(self.ev.answer.await_args.args[0], "This order is already finished.")

    async def test_provider_early_cancel_denied_keeps_order(self):
        o = await self._place(); self._age(o["id"])
        with patch("plugins.herosms.set_status", new=AsyncMock(return_value="EARLY_CANCEL_DENIED")):
            await numflow.on_cancel(self.bot, self.ev, o["id"])
        self.assertEqual(self.order(o["id"])["status"], "waiting")
        self.assertLess(self.bal(), 1000)

    async def test_change_number_gives_new_number_without_extra_charge(self):
        o = await self._place(); self._age(o["id"]); paid_bal = self.bal()
        new = {"activationId": "B2", "phoneNumber": "922", "activationCost": 0.2}
        with patch("plugins.herosms.set_status", new=AsyncMock(return_value="ACCESS_CANCEL")), \
             patch("plugins.herosms.get_number", new=AsyncMock(return_value=new)) as gn, \
             patch.object(numflow, "run_poll", new=AsyncMock()):
            await numflow.on_change(self.bot, self.ev, o["id"])
        gn.assert_awaited_once()
        self.assertEqual(gn.await_args.args[:2], ("wa", "22"))
        n = self.order(o["id"])
        self.assertEqual((n["activation_id"], n["phone"], n["changes"], n["status"]), ("B2", "922", 1, "waiting"))
        self.assertEqual(self.bal(), paid_bal)                      # no extra charge
        text = self.ev.edit.await_args.args[0]
        self.assertIn("+922", text); self.assertIn("changed 1x", text)
        self.assertLess(time.time() - n["started"], 5)              # timer restarted
        self.assertIn("⏳", self.ev.edit.await_args.kwargs["buttons"][0][1]["text"])

    async def test_change_number_without_stock_refunds(self):
        o = await self._place(); self._age(o["id"])
        with patch("plugins.herosms.set_status", new=AsyncMock(return_value="ACCESS_CANCEL")), \
             patch("plugins.herosms.get_number", new=AsyncMock(side_effect=Exception("NO_NUMBERS"))):
            await numflow.on_change(self.bot, self.ev, o["id"])
        self.assertEqual(self.order(o["id"])["status"], "cancelled")
        self.assertEqual(self.bal(), 1000)

    async def test_other_users_cannot_touch_the_order(self):
        o = await self._place(); self._age(o["id"])
        stranger = SimpleNamespace(sender_id=999, answer=AsyncMock(), edit=AsyncMock(), message_id=1)
        with patch("plugins.herosms.set_status", new=AsyncMock()) as ss:
            await numflow.on_cancel(self.bot, stranger, o["id"])
        ss.assert_not_awaited()
        self.assertEqual(self.order(o["id"])["status"], "waiting")

    # ---- polling ----
    async def test_buttons_unlock_after_two_minutes(self):
        o = await self._place(); self._age(o["id"])
        with patch("plugins.herosms.get_status", new=AsyncMock(side_effect=["STATUS_WAIT_CODE", "STATUS_OK:5566"])), \
             patch("plugins.herosms.set_status", new=AsyncMock()), patch("plugins.profit.notify_profit", new=AsyncMock()), \
             patch("plugins.salelog.post_sale", new=AsyncMock()), patch.object(asyncio, "sleep", new=AsyncMock()):
            await numflow.run_poll(self.bot, o["id"])
        unlocked = [c for c in self.bot.edit_message.await_args_list if "Change No" in " ".join(labels(c.kwargs.get("buttons") or []))]
        self.assertTrue(unlocked)
        self.assertNotIn("⏳", labels(unlocked[0].kwargs["buttons"])[1])
        self.assertIn("🔓", unlocked[0].args[2])

    async def test_otp_message_has_copy_code_and_back(self):
        o = await self._place()
        with patch("plugins.herosms.get_status", new=AsyncMock(return_value="STATUS_OK:5566")), \
             patch("plugins.herosms.set_status", new=AsyncMock()), patch("plugins.profit.notify_profit", new=AsyncMock()), \
             patch("plugins.salelog.post_sale", new=AsyncMock()), patch.object(asyncio, "sleep", new=AsyncMock()):
            await numflow.run_poll(self.bot, o["id"])
        otp_call = self.bot.send_message.await_args_list[0]
        self.assertIn("5566", otp_call.args[1])
        rows = otp_call.kwargs["buttons"]
        self.assertTrue(any("Copy Code" in l for l in labels(rows)))
        self.assertTrue(any("Copy No" in l for l in labels(rows)))
        self.assertTrue(any("Back" in l for l in labels(rows)))
        self.assertEqual(self.order(o["id"])["status"], "done")
        self.assertEqual(rows[-1][0]["data"], b"num_p|wa")

    async def test_no_otp_auto_refund(self):
        o = await self._place()
        d.cur.execute("UPDATE number_orders SET started=? WHERE id=?", (time.time() - 700, o["id"])); d.db.commit()
        with patch("plugins.herosms.get_status", new=AsyncMock(return_value="STATUS_WAIT_CODE")), \
             patch("plugins.herosms.set_status", new=AsyncMock()), patch.object(asyncio, "sleep", new=AsyncMock()):
            await numflow.run_poll(self.bot, o["id"])
        self.assertEqual(self.order(o["id"])["status"], "cancelled")
        self.assertEqual(self.bal(), 1000)

    # ---- Telegram Server 3: Change TG No ----
    async def test_change_tg_no_uses_hero_telegram_numbers(self):
        o = await self._place(code="tc", server=3, number="9199")
        self.assertEqual((o["platform"], o["server"]), ("tc", 3))
        text = self.ev.edit.await_args.args[0]
        self.assertIn("Change Number", text)
        self.assertIn("VPN", text)
        self.assertIn("+9199", text)
        # price uses the dedicated 'tc' profit rule and keeps a profit
        sell, cost, _ = social.gz_offer("tc", 3, 0.2)
        self.assertGreaterEqual(sell - cost, 10)

    async def test_change_tg_no_service_is_telegram_and_otp_screen_back_goes_to_server3(self):
        with patch.object(social, "gz_rows", new=AsyncMock(return_value=self.rows)), \
             patch("plugins.herosms.get_number", new=AsyncMock(return_value={"activationId": "T1", "phoneNumber": "9100", "activationCost": 0.2})) as gn, \
             patch.object(numflow, "run_poll", new=AsyncMock()):
            await social.buy_number(self.bot, self.ev, "tc", 3, "22")
        self.assertEqual(gn.await_args.args[0], "tg")
        o = self.order()
        with patch("plugins.herosms.get_status", new=AsyncMock(return_value="STATUS_OK:1234")), \
             patch("plugins.herosms.set_status", new=AsyncMock()), patch("plugins.profit.notify_profit", new=AsyncMock()), \
             patch("plugins.salelog.post_sale", new=AsyncMock()), patch.object(asyncio, "sleep", new=AsyncMock()):
            await numflow.run_poll(self.bot, o["id"])
        rows = self.bot.send_message.await_args_list[0].kwargs["buttons"]
        self.assertIn("Login Code", self.bot.send_message.await_args_list[0].args[1])
        self.assertTrue(rows[-1][0]["data"].startswith(b"num_"))

    async def test_resume_waiting_orders_after_restart(self):
        o = await self._place()
        with patch.object(numflow, "run_poll", new=AsyncMock()) as rp:
            await numflow.resume_waiting(self.bot)
            await asyncio.sleep(0)
        rp.assert_called_once_with(self.bot, o["id"])


class NotifyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for t in ("notif_seen", "notif_users"):
            d.cur.execute(f"DELETE FROM {t}")
        d.cur.execute("DELETE FROM settings WHERE key LIKE 'notif_seeded_%'")
        d.db.commit()

    def snap(self, *names, stock=3):
        return {f"tg|1|{n}": notify._item("Telegram", "✈️", 1, n, "🇲🇷", stock, 109.5, f"bc|single|{n}") for n in names}

    def test_first_scan_is_silent_then_new_country_is_announced(self):
        self.assertEqual(notify.diff_source("tg|1", self.snap("India")), [])
        self.assertEqual(notify.diff_source("tg|1", self.snap("India")), [])
        new = notify.diff_source("tg|1", self.snap("India", "Mauritania"))
        self.assertEqual([i["country"] for i in new], ["Mauritania"])
        self.assertEqual(notify.diff_source("tg|1", self.snap("India", "Mauritania")), [])

    def test_back_in_stock_needs_cooldown(self):
        notify.diff_source("tg|1", self.snap("India"))
        notify.diff_source("tg|1", self.snap("India", "Peru"))
        notify.diff_source("tg|1", self.snap("India"))                                  # Peru sold out
        self.assertEqual(notify.diff_source("tg|1", self.snap("India", "Peru")), [])    # back right away -> no spam
        notify.diff_source("tg|1", self.snap("India"))
        later = time.time() + notify.COOLDOWN + 5
        self.assertEqual([i["country"] for i in notify.diff_source("tg|1", self.snap("India", "Peru"), now=later)], ["Peru"])

    def test_sources_are_independent(self):
        notify.diff_source("tg|1", self.snap("India"))
        wa = {"wa|1|22": notify._item("WhatsApp", "💬", 1, "India", "🇮🇳", 5, 90, "gz_c|wa|1|22")}
        self.assertEqual(notify.diff_source("wa|1", wa), [])    # first scan of WhatsApp S1 stays silent as well

    def test_alert_text_matches_screenshot_and_has_service(self):
        it = notify._item("Telegram", "✈️", 1, "Mauritania", "🇲🇷", 3, 109.5, "bc|single|Mauritania")
        t = notify.alert_text(it)
        for part in ("New Country Added!", "Country:", "Mauritania", "3 accounts", "₹109.5", "Service:", "Telegram", "Grab it before it runs out!"):
            self.assertIn(part, t)
        rows = notify.alert_buttons(it["cb"], True)
        self.assertEqual(rows[0][0]["data"], b"bc|single|Mauritania")
        self.assertIn("Buy Now", rows[0][0]["text"])
        self.assertIn("Turn Off Notifications", rows[1][0]["text"])
        self.assertIn("Turn On Notifications", notify.alert_buttons(it["cb"], False)[1][0]["text"])

    def test_long_callback_falls_back_to_server_list(self):
        it = notify._item("WhatsApp", "💬", 2, "x" * 80, "🏳", 1, 5, "bc|single|" + "x" * 80)
        self.assertEqual(it["cb"], b"num_p|wa")

    async def test_preferences_and_recipients(self):
        for uid in (801, 802, 803):
            d.ensure_user(uid)
            d.cur.execute("UPDATE users SET terms_accepted=1 WHERE user_id=?", (uid,))
        d.db.commit()
        self.assertIn(801, notify.recipients())
        self.assertFalse(notify.toggle_pref(801))
        self.assertNotIn(801, notify.recipients())
        self.assertTrue(notify.toggle_pref(801))
        d.cur.execute("UPDATE users SET banned=1 WHERE user_id=802"); d.db.commit()
        self.assertNotIn(802, notify.recipients())
        d.cur.execute("UPDATE users SET banned=0 WHERE user_id=802"); d.db.commit()

    async def test_broadcast_only_reaches_subscribers(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        it = notify._item("Telegram", "✈️", 1, "Peru", "🇵🇪", 2, 80, "bc|single|Peru")
        with patch.object(asyncio, "sleep", new=AsyncMock()):
            n = await notify.broadcast(bot, it, users=[1, 2, 3])
        self.assertEqual(n, 3)
        self.assertEqual(bot.send_message.await_count, 3)


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_low_balance_alert_goes_to_owner_with_cooldown(self):
        from utils import panels
        panels._last_alert.clear()
        rows = [{"label": "Hero SMS", "ok": True, "inr": 20.0, "raw": "$0.21", "error": "", "low": True},
                {"label": "LZT Market", "ok": True, "inr": 900.0, "raw": "$9.57", "error": "", "low": False}]
        bot = SimpleNamespace(send_message=AsyncMock())
        await panels.check_and_alert(bot, rows)
        self.assertEqual(bot.send_message.await_count, 1)
        self.assertEqual(bot.send_message.await_args.args[0], 1)           # OWNER_ID
        self.assertIn("Hero SMS", bot.send_message.await_args.args[1])
        await panels.check_and_alert(bot, rows)                              # cooldown -> no repeat
        self.assertEqual(bot.send_message.await_count, 1)
        await panels.check_and_alert(bot, rows, force=True)                  # /health forces it
        self.assertEqual(bot.send_message.await_count, 2)

    async def test_threshold_and_conversion(self):
        from utils import panels
        with patch.object(panels, "_configured", return_value=[("Hero SMS", AsyncMock(return_value=(0.3, "usd"))),
                                                               ("SMM panel", AsyncMock(return_value=(49.0, "INR"))),
                                                               ("TG-Lion", AsyncMock(return_value=(5.0, "usd"))),
                                                               ("Broken", AsyncMock(side_effect=RuntimeError("down")))]):
            rows = await panels.fetch_balances()
        by = {r["label"]: r for r in rows}
        self.assertTrue(by["Hero SMS"]["low"])        # 0.3 USD ~ ₹28 < ₹50
        self.assertTrue(by["SMM panel"]["low"])       # ₹49 < ₹50
        self.assertFalse(by["TG-Lion"]["low"])
        self.assertFalse(by["Broken"]["ok"])
        txt = panels.format_balances(rows)
        self.assertIn("LOW", txt); self.assertIn("balance unavailable", txt)

    async def test_health_report_has_panel_section(self):
        from utils import health
        rep = {"ok": False, "bot": {"ok": True, "verdict": "OK", "loop_lag_ms": 1, "uptime": "1m", "memory_mb": 1, "telegram": "connected", "tg_ms": 1},
               "apis": [], "db": {"ok": True, "local": {"ok": True, "integrity": "ok", "counts": {}},
                                  "mongo": {"status": "x", "latency_ms": 1, "sync": "n/a", "last_sync": None, "failures": 0, "mismatch": {}}},
               "config": {"ok": True, "required": [], "optional": []},
               "panels": [{"label": "Hero SMS", "ok": True, "inr": 20.0, "raw": "$0.21", "error": "", "low": True}]}
        out = health.format_report(rep)
        self.assertIn("Panel balances", out); self.assertIn("Hero SMS", out); self.assertIn("LOW", out)


class AdminRemoveAccTests(unittest.TestCase):
    def test_remove_only_unsold_account_and_session_file(self):
        d.cur.execute("DELETE FROM stock")
        sess = Path(os.getcwd()) / "sessions" / "919000.session"
        sess.parent.mkdir(exist_ok=True); sess.write_text("x")
        d.cur.execute("INSERT INTO stock (phone, session_file, country_name, account_year, price, available) VALUES ('919000', ?, 'India', 2022, 50, 1)", (str(sess),))
        d.cur.execute("INSERT INTO stock (phone, session_file, country_name, account_year, price, available) VALUES ('919001', 'x', 'India', 2022, 50, 0)")
        d.db.commit()
        self.assertEqual(admin_actions._drop_stock_account("919000"), "India")
        self.assertFalse(sess.exists())
        self.assertIsNone(admin_actions._drop_stock_account("919001"))     # sold -> untouched
        self.assertIsNone(admin_actions._drop_stock_account("000"))
        self.assertEqual(d.cur.execute("SELECT COUNT(*) FROM stock").fetchone()[0], 1)

    def test_country_screen_has_remove_acc_button(self):
        d.cur.execute("DELETE FROM stock")
        d.cur.execute("INSERT INTO stock (phone, session_file, country_name, account_year, price, available) VALUES ('919002', 'x', 'India', 2022, 50, 1)")
        d.db.commit()
        ev = SimpleNamespace(edit=AsyncMock())
        asyncio.run(admin_actions.send_manage_stock_country(ev, "India"))
        self.assertIn("🗑 Remove Acc", labels(ev.edit.await_args.kwargs["buttons"]))
        ev2 = SimpleNamespace(edit=AsyncMock())
        asyncio.run(admin_actions.send_remove_acc_list(ev2, "India", 1))
        b = ev2.edit.await_args.kwargs["buttons"]
        self.assertIn(b"adm_msdel|919002", datas(b))
        self.assertTrue(any("Remove ALL" in l for l in labels(b)))


class MenuTests(unittest.TestCase):
    def test_main_menu_matches_reference_without_removed_buttons(self):
        from utils.keyboards import get_main_inline_menu
        rows = get_main_inline_menu()
        flat = labels(rows)
        for want in ("Buy tg Acc", "Buy Wp Acc", "All apps acc", "Social media services", "Support", "Recharge", "My Profile", "Bot Guide", "More"):
            self.assertIn(want, flat)
        for gone in ("Free Temp Mail", "Spin & Win", "API Keys"):
            self.assertNotIn(gone, " ".join(flat))
        self.assertEqual(rows[0][0].get("data"), b"menu_buy")
        guide = [b for r in rows for b in r if b["text"] == "Bot Guide"][0]
        more = [b for r in rows for b in r if b["text"] == "More"][0]
        self.assertEqual(guide["style"], "success")
        self.assertEqual(more["style"], "danger")
        self.assertIn(b"menu_numbers", datas(rows))
        self.assertIn(b"menu_smm", datas(rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
