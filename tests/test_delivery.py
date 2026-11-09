"""Offline behavior tests. Run from source root in a disposable DATA_DIR."""
import asyncio
import os
from pathlib import Path
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.update(API_ID="1", API_HASH="x", BOT_TOKEN="1:x", ADMIN_ID="1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database as d
from utils import delivery, states
from plugins import start, repos, social, buy
from telethon import events


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        states.user_locks.clear()
        states.active_orders.clear()
        self.bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=42)),
                                   send_file=AsyncMock(), edit_message=AsyncMock())
        self.uid = 9876
        d.cur.execute("CREATE TABLE IF NOT EXISTS delivery_thanks (user_id INTEGER NOT NULL, delivery_key TEXT NOT NULL, message_id INTEGER, PRIMARY KEY(user_id, delivery_key))")
        for table in ('delivery_thanks', 'number_orders', 'manual_stock', 'repo_orders', 'repos'):
            d.cur.execute(f"DELETE FROM {table}")
        d.ensure_user(self.uid)
        d.cur.execute("UPDATE users SET balance=1000, terms_accepted=1 WHERE user_id=?", (self.uid,))
        d.db.commit()
        self.event = SimpleNamespace(sender_id=self.uid, message_id=123,
                                     edit=AsyncMock(), answer=AsyncMock(), respond=AsyncMock())

    async def test_one_note_per_order_even_with_parallel_refreshes(self):
        results = await asyncio.gather(*[delivery.send_delivery_thanks(self.bot, self.uid, 'number:1') for _ in range(8)])
        self.assertEqual(results.count(True), 1)
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertEqual(d.cur.execute("SELECT message_id FROM delivery_thanks").fetchone()[0], 42)

    async def test_deduplication_survives_module_reload(self):
        await delivery.send_delivery_thanks(self.bot, self.uid, 'number:1')
        import importlib
        importlib.reload(delivery)
        self.assertFalse(await delivery.send_delivery_thanks(self.bot, self.uid, 'number:1'))
        self.assertEqual(self.bot.send_message.await_count, 1)

    async def test_new_orders_and_different_buyers_get_their_own_note(self):
        for uid, key in [(self.uid, 'repo:1'), (self.uid, 'repo:2'), (self.uid + 1, 'repo:1')]:
            self.assertTrue(await delivery.send_delivery_thanks(self.bot, uid, key))
        self.assertEqual(self.bot.send_message.await_count, 3)

    async def test_failed_note_does_not_crash_or_mark_sent_and_can_retry(self):
        self.bot.send_message.side_effect = RuntimeError('Simulated Telegram failure')
        self.assertFalse(await delivery.send_delivery_thanks(self.bot, self.uid, 'manual:1'))
        self.assertEqual(d.cur.execute("SELECT COUNT(*) FROM delivery_thanks").fetchone()[0], 0)
        self.bot.send_message.side_effect = None
        self.assertTrue(await delivery.send_delivery_thanks(self.bot, self.uid, 'manual:1'))

    async def test_visit_again_runs_same_start_handler_and_preserves_delivered_message(self):
        callbacks = []
        def on(builder):
            def capture(handler):
                if isinstance(builder, events.CallbackQuery):
                    callbacks.append((builder, handler))
                return handler
            return capture
        fake_bot = SimpleNamespace(on=on)
        start.register_start(fake_bot)
        self.assertEqual(len(callbacks), 1)
        builder, handler = callbacks[0]
        self.assertIsNotNone(builder.match(b'visit_again'))
        self.assertIsNone(builder.match(b'menu_home'))
        event = Mock(spec=events.CallbackQuery.Event)
        event.sender_id = self.uid
        event.text = ''
        event.answer = AsyncMock()
        event.respond = AsyncMock()
        event.edit = AsyncMock()
        states.session_buy_state[self.uid] = 'old input'
        states.deposit_input[self.uid] = 'old input'
        with patch.object(start, 'send_main_menu', new=AsyncMock()) as menu:
            await handler(event)
            menu.assert_awaited_once_with(fake_bot, event, self.uid)
        event.answer.assert_awaited_once()
        event.edit.assert_not_awaited()
        self.assertNotIn(self.uid, states.session_buy_state)
        self.assertNotIn(self.uid, states.deposit_input)

    async def test_visit_again_keeps_start_ban_and_terms_guards(self):
        handlers = []
        def on(builder):
            def capture(handler):
                if isinstance(builder, events.CallbackQuery): handlers.append(handler)
                return handler
            return capture
        fake_bot = SimpleNamespace(on=on)
        start.register_start(fake_bot)
        event = Mock(spec=events.CallbackQuery.Event)
        event.sender_id = self.uid
        event.text = ''
        event.answer = AsyncMock()
        event.respond = AsyncMock()
        with patch.object(start, 'send_main_menu', new=AsyncMock()) as menu:
            with patch.object(start, 'is_user_banned', return_value=True):
                await handlers[0](event)
            menu.assert_not_awaited()
            d.cur.execute("UPDATE users SET terms_accepted=0 WHERE user_id=?", (self.uid,)); d.db.commit()
            await handlers[0](event)
            menu.assert_not_awaited()
            event.respond.assert_awaited_once()

    async def test_repo_note_follows_successful_file_delivery(self):
        asset = str(Path(__file__).resolve())
        d.cur.execute("INSERT INTO repos(name,price,zip_file,available) VALUES('test',50,?,1)", (asset,))
        rid = d.cur.lastrowid; d.db.commit()
        sequence = []
        self.bot.send_file.side_effect = lambda *a, **k: sequence.append('file')
        self.bot.send_message.side_effect = lambda *a, **k: sequence.append('thanks')
        with patch.object(repos, 'bot', self.bot), patch('plugins.salelog.post_sale', new=AsyncMock()):
            await repos.process_repo_purchase(self.event, rid)
        self.assertEqual(sequence, ['file', 'thanks'])
        self.assertEqual(d.cur.execute("SELECT balance FROM users WHERE user_id=?", (self.uid,)).fetchone()[0], 950)

    async def test_failed_repo_delivery_has_no_thanks_and_refunds(self):
        d.cur.execute("INSERT INTO repos(name,price,zip_file,available) VALUES('test',50,?,1)", (str(Path(__file__).resolve()),))
        rid = d.cur.lastrowid; d.db.commit()
        self.bot.send_file.side_effect = RuntimeError('delivery failed')
        with patch.object(repos, 'bot', self.bot):
            await repos.process_repo_purchase(self.event, rid)
        self.bot.send_message.assert_not_awaited()
        self.assertEqual(d.cur.execute("SELECT balance FROM users WHERE user_id=?", (self.uid,)).fetchone()[0], 1000)

    async def test_manual_account_thanks_after_delivery_and_not_again_when_sold(self):
        d.cur.execute("INSERT INTO manual_stock(platform,details,price,cost,available) VALUES('wa','test',50,20,1)")
        sid = d.cur.lastrowid; d.db.commit()
        sequence = []
        self.event.edit.side_effect = lambda *a, **k: sequence.append('delivery')
        self.bot.send_message.side_effect = lambda *a, **k: sequence.append('thanks')
        with patch('plugins.profit.notify_profit', new=AsyncMock()):
            await social.buy_manual(self.bot, self.event, sid)
            await social.buy_manual(self.bot, self.event, sid)
        self.assertEqual(sequence, ['delivery', 'thanks'])

    async def test_tglion_waiting_and_repeated_get_again(self):
        d.cur.execute("INSERT INTO number_orders(user_id,platform,server,activation_id,phone,price,cost,status) VALUES(?,'tg',2,'+911','911',50,20,'waiting')", (self.uid,))
        d.db.commit()
        with patch('plugins.tglion.tl_code', new=AsyncMock(return_value={})), patch('config.bot', self.bot):
            await social.tl_get_code(self.event, '+911')
        self.bot.send_message.assert_not_awaited()
        with patch('plugins.tglion.tl_code', new=AsyncMock(return_value={'code':'12345'})), patch('config.bot', self.bot):
            await social.tl_get_code(self.event, '+911')
            await social.tl_get_code(self.event, '+911')
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertEqual(self.event.edit.await_count, 2)

    async def test_herosms_note_only_after_otp_delivery(self):
        with patch.object(social, 'gz_rows', new=AsyncMock(return_value=[('22','India','IN',0.2,10,0)])), patch('plugins.salelog.post_sale', new=AsyncMock()), \
             patch('plugins.herosms.get_number', new=AsyncMock(return_value={'activationId':'test1','phoneNumber':'911'})), \
             patch('plugins.herosms.get_status', new=AsyncMock(return_value='STATUS_OK:12345')), \
             patch('plugins.herosms.set_status', new=AsyncMock()), \
             patch('plugins.profit.notify_profit', new=AsyncMock()), \
             patch.object(social.asyncio, 'sleep', new=AsyncMock()):
            await social.buy_number(self.bot, self.event, 'wa', 2)
        self.assertEqual(self.bot.send_message.await_count, 2)
        self.assertEqual(d.cur.execute("SELECT COUNT(*) FROM delivery_thanks").fetchone()[0], 1)

    async def test_herosms_cancel_does_not_send_thanks(self):
        with patch.object(social, 'gz_rows', new=AsyncMock(return_value=[('22','India','IN',0.2,10,0)])), patch('plugins.salelog.post_sale', new=AsyncMock()), \
             patch('plugins.herosms.get_number', new=AsyncMock(return_value={'activationId':'test2','phoneNumber':'912'})), \
             patch('plugins.herosms.get_status', new=AsyncMock(return_value='STATUS_CANCEL')), \
             patch('plugins.herosms.set_status', new=AsyncMock()), \
             patch.object(social.asyncio, 'sleep', new=AsyncMock()):
            await social.buy_number(self.bot, self.event, 'wa', 2)
        self.assertEqual(d.cur.execute("SELECT COUNT(*) FROM delivery_thanks").fetchone()[0], 0)
        self.assertEqual(d.cur.execute("SELECT balance FROM users WHERE user_id=?", (self.uid,)).fetchone()[0], 1000)

    async def test_auto_session_note_after_otp_edit(self):
        order = {'uid':self.uid, 'msg_id':123, 'start_time':time.time(), 'paid':True}
        states.active_orders['911'] = order
        sequence = []
        self.bot.edit_message.side_effect = lambda *a, **k: sequence.append('otp')
        self.bot.send_message.side_effect = lambda *a, **k: sequence.append('thanks')
        with patch.object(buy, 'bot', self.bot), \
             patch.object(buy, 'fetch_latest_otp', new=AsyncMock(return_value='12345')), \
             patch.object(buy, 'finalize_order', new=AsyncMock(return_value=('otp', []))):
            await buy.auto_otp_task('911')
        self.assertEqual(sequence, ['otp', 'thanks'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
