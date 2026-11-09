# V6 delivery follow-up — verified 6 October 2026

## Changes
- Sends a separate thank-you message with existing premium emoji IDs after successful session OTP, TGLion OTP, Grizzly OTP, manual ready-account, and bot-repository ZIP delivery.
- Visit Again invokes the same handler as /start. It keeps the delivered message intact and preserves the existing ban, maintenance, and terms checks.
- Successful thank-you sends are recorded in SQLite (and synchronized through the existing database commit integration) by buyer + order key. Refreshes and restarts do not repeat recorded notes.
- A failed thank-you send is logged and does not undo a completed purchase. A later delivery action can retry it.
- Existing stock claim, balance rules, active account sessions, and payment integration are unchanged.

## Offline verification
- 17 existing regression checks passed: all module imports, SQLite WAL/NORMAL mode, table setup, payment creation/status/authentication, 200 polls sharing one HTTP session, payment errors/session cleanup, 10 simultaneous buyers competing for 3 stock, insufficient balance, and dead-session refund.
- 13 new delivery tests passed: concurrent duplicate prevention; persisted deduplication after module reload; separate orders/buyers; safe send failure/retry; start callback/menu/state reset; ban/terms guards; repository success/failure ordering and refund; manual delivery; TGLion waiting/refresh; Grizzly success/cancellation; automatic session OTP ordering.
- All Python source files passed syntax parsing.
- Regression tests now use assertions and fail with a nonzero exit status.

## Run the checks
Run these commands from the extracted source folder. Use fresh disposable directories, NOT the production DATA_DIR. The regression script deletes test users and stock.

```sh
DATA_DIR=/tmp/betaotp-test-regression python3 tests/regression_checks.py
DATA_DIR=/tmp/betaotp-test-delivery python3 tests/test_delivery.py
```

## Not verified live
No real Telegram bot/user credentials or payment-provider credentials were used. Actual Telegram rendering of custom/premium emojis, real OTP arrival, button interaction in Telegram, and real payments require a live smoke test. Existing Telegram account/bot eligibility determines custom emoji rendering.

Keep the deployment's existing MONGO_URI and persistent DATA_DIR configured. A process crash between Telegram accepting a message and recording it can still cause a duplicate on retry; Telegram and SQLite cannot share one atomic transaction.
