<div align="center">

# ⚡ NUMBOTT TELETHON ⚡

<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=24&pause=1000&color=00F0FF&center=true&vCenter=true&width=500&lines=Advanced+Telegram+Account+Shop+Bot;Modular+%2B+Asynchronous+%2B+Telethon;Custom+UI+%2B+Dynamic+Must-Join" alt="Typing SVG" />
</p>

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Telethon](https://img.shields.io/badge/Telethon-Async-success?style=for-the-badge&logo=telegram&logoColor=white)](https://github.com/LonamiWebs/Telethon)
[![SQLite](https://img.shields.io/badge/Database-SQLite-orange?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-red?style=for-the-badge)](LICENSE)

</div>

---

## 🌟 Key Features

* 🚀 **Modular Architecture:** Cleanly organized plugins (`buy`, `deposit`, `profile`, `admin`, `callbacks`, `start`).
* 🎨 **Dynamic Keyboard & Modern UI:** Sleek styling with custom emojis, colors, and responsive inline/reply keyboards.
* 🔐 **Smart Must-Join Verification:** Auto-detects remaining channels and dynamically updates UI as users join.
* 💳 **Multi-Payment Gateways:** Supports automatic/manual Crypto (CWallet) and Indian UPI Payment options.
* 📦 **Automatic Stock & OTP System:** Complete session buying flow with built-in OTP retrieval and account state handling.
* 📋 **Live Price Lists:** `/plist` shows current Telegram and WhatsApp country prices by server; Telegram bulk-account requests link to the owner.
* 📊 **Multi-Log Channel Support:** Instant deposit alerts and administrative auditing sent across designated log channels.
* ⚡ **Anti-Bypass Referral Engine:** Secure referral tracking to guarantee bonuses apply strictly to unique, verified users.

---

## 🛠️ Environment Configuration (`.env`)

Create a `.env` file in the root directory and add the following keys:

```env
API_ID=your_api_id_here
API_HASH=your_api_hash_here
BOT_TOKEN=your_bot_token_here
ADMIN_ID=your_admin_id_here

# Logging Channels
LOG_CHANNEL_ID=your_log_channel_id_here
LOG_CHANNEL_ID_2=your_log_channel_id_2_here

# Must Join Verification Setup
CHECK_CHANNELS=your_check_channels_here
JOIN_URLS=your_join_urls_here

# Payment Credentials
CWALLET_ID=your_cwallet_id_here
UPI_ID=your_upi_id_here
PAYGATE_API_KEY=your_payment_gateway_key_here
```

Keep payment keys in your host's environment/secrets settings; do not commit them to source files.

---

## 🚀 Quick Start & Installation

### 1. Clone the Repository
```bash
git clone [https://github.com/ragini19854-prog/nobita-account-bot]
cd Numbott
```

### 2. Setup Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Bot
```bash
python main.py
```

---

## 💻 Tech Stack

- **Core Engine:** [Python 3.10+](https://www.python.org/)
- **Telegram Framework:** [Telethon (MTProto API Client)](https://github.com/LonamiWebs/Telethon)
- **Database:** SQLite3
- **Process Manager:** `tmux` / Background Daemon execution

---

## 👤 Developer & Credits

<div align="center">

Developed with ❤️ by **[𝐃𝐞𝐦𝐨𝐧](https://t.me/Demon_x_coder_aura)**

</div>

## SMM auto-import (new)
- Bot imports ALL panel services automatically on start + every 6 hours.
- Sell price = panel cost + 40% profit (min ₹1/1K profit). Change: `/setmargin 50`
- `/smmsync` re-import now · `/smmprices telegram` cost/sell/profit list
- Env (optional): SMM_PROFIT_PERCENT, SMM_MIN_PROFIT, SMM_SYNC_HOURS, SMM_RATE_MULTIPLIER (set ~88 if panel rates are USD)
