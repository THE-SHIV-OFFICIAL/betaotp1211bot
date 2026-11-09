# New features (this update)

## 1. Number flow — WhatsApp S1/S2 + All apps (Hero SMS)
After a number is bought the user sees the number, **💡 Tip: Use VPN while logging in for the first time**, and
`[📋 Copy No] [🔄 Change No]` / `[❌ Cancel]`.
* **Change No / Cancel are locked for 2 minutes** (Hero SMS does not allow an earlier cancel). Tapping early shows the time left; the buttons unlock automatically.
* **Change No** → old number cancelled, new number of the same country, no extra charge, timer restarts.
* **Cancel** → full price back to the balance.
* OTP arrives → `[📋 Copy No] [📋 Copy Code]` + `[⬅️ Back]`.
* No OTP in 10 min → auto refund. Orders still waiting during a restart are resumed.
* VPN tip is also shown on the All apps / server-selection screens.

## 2. Telegram → Server 3 → 🔄 Change TG No (Hero SMS)
Button on the Server 3 screen. Pick a country → pay → number + `Copy No`, then the code with `Copy Code` + `Back`.
Price = max(cost × markup, cost + min profit). Default ×1.5 / ₹10 min profit.
* change live: `/setprofit tc 3 <markup> [min_profit]`, `/setminprice tc 3 <inr>`
* defaults via env: `NUM_MARKUP_TC_S3`; see all margins with `/numprices`

## 3. "New Country Added!" notification
Telegram (S1/S2/S3) and WhatsApp (S1/S2): when a new country appears every subscribed user gets
Country · Stock · Price · Service + `Buy Now` + `Turn On/Off Notifications`.
Users: `/notify` or Settings → New Country Alerts. Admin: `/testnotify`.
Env: `NOTIFY_ENABLED`, `NOTIFY_DEFAULT` (1 = on for everybody, 0 = opt-in), `NOTIFY_INTERVAL`, `NOTIFY_COOLDOWN`, `NOTIFY_MAX_PER_SCAN`.

## 4. /health — panel balances + low balance alert
`/health` now lists Hero SMS, TG-Lion, LZT Market and SMM panel balance (in ₹). Any panel under **₹50** → the owner gets a DM
(also checked in the background every 10 min, repeated at most every 6 h).
Env: `LOW_BALANCE_INR`, `PANEL_CHECK_INTERVAL`, `LOW_BALANCE_REPEAT`, `LZT_BALANCE_CURRENCY` (usd|rub|inr), `LZT_RUB_INR`, `TGLION_BALANCE_CURRENCY`.

## 5. Menu style
Main menu matches the reference screenshot (dark buttons, green **Bot Guide**, red **More**).
Free Temp Mail / Spin & Win / API Keys are not in the menu.

## 6. Admin → Manage Stock → country → 🗑 Remove Acc
List of unsold accounts (phone · year · price) → tap to remove (with confirmation), or **Remove ALL** for the country.
Session files are deleted too. Sold accounts are never touched.

Tests: `tests/test_new_features.py` (run in a disposable DATA_DIR, like the other tests).
