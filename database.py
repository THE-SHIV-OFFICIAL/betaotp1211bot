import sqlite3
import os
from config import ADMIN_ID, ADMIN_IDS, SUPPORT_USERNAME
from premium_emojis import premium_flag_id

# Initialize DB
db_path = "otp_bot_final.db"
# Ensure we run from the old DB to not lose data, or just point to it.
# We'll use absolute path or same dir. We can symlink later if needed, but let's just use the current path
# Better yet, since we will run from Numbott_Telethon, let's use the DB from ../Numbott to share it, or copy it.
# Let's just point to it directly:
class _SyncConnection(sqlite3.Connection):
    """Every save is also pushed to MongoDB (see mongo_store.py)."""
    def commit(self):
        super().commit()
        try:
            import mongo_store
            mongo_store.mark_dirty()
        except Exception:
            pass

db = sqlite3.connect("otp_bot_final.db", check_same_thread=False, timeout=30, factory=_SyncConnection)
# Fast, concurrency-safe pragmas
db.execute("PRAGMA journal_mode=WAL;")
db.execute("PRAGMA synchronous=NORMAL;")
db.execute("PRAGMA cache_size=-64000;")
db.execute("PRAGMA temp_store=MEMORY;")
db.execute("PRAGMA mmap_size=268435456;")
db.execute("PRAGMA busy_timeout=30000;")
cur = db.cursor()

def setup_db():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        referred_by INTEGER,
        total_deposited INTEGER DEFAULT 0,
        joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        banned INTEGER DEFAULT 0,
        discount INTEGER DEFAULT 0,
        terms_accepted INTEGER DEFAULT 0,
        currency TEXT DEFAULT 'INR',
        language TEXT DEFAULT 'en'
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS stock (
        phone TEXT PRIMARY KEY,
        session_file TEXT,
        country_name TEXT,
        country_icon TEXT DEFAULT '🌍',
        account_year INTEGER,
        category TEXT DEFAULT 'Good',
        price INTEGER,
        available INTEGER DEFAULT 1,
        twofa TEXT DEFAULT 'None',
        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS auto_prices (
        country TEXT,
        year TEXT,
        price INTEGER,
        PRIMARY KEY (country, year)
    );
    CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        method_name TEXT,
        status TEXT, 
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS upi_orders (
        order_id TEXT PRIMARY KEY,
        user_id INTEGER,
        amount INTEGER,
        status TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        country TEXT,
        year INTEGER,
        price INTEGER,
        phone TEXT,
        otp TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS custom_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        caption TEXT,
        qr_file_id TEXT
    );
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        p_add_stock INTEGER DEFAULT 0,
        p_manage_stock INTEGER DEFAULT 0,
        p_stats INTEGER DEFAULT 0,
        p_bal INTEGER DEFAULT 0,
        p_settings INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS custom_countries (
        code TEXT PRIMARY KEY,
        name TEXT,
        flag TEXT
    );
    CREATE TABLE IF NOT EXISTS smm_services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        category TEXT,
        fansmm_service_id TEXT,
        min_qty INTEGER DEFAULT 10,
        max_qty INTEGER DEFAULT 100000,
        price_per_1000 INTEGER,
        description TEXT DEFAULT '',
        available INTEGER DEFAULT 1,
        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS smm_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        service_id INTEGER,
        service_name TEXT,
        link TEXT,
        quantity INTEGER,
        price INTEGER,
        fansmm_order_id TEXT,
        status TEXT DEFAULT 'pending',
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS repos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        description TEXT DEFAULT '',
        price INTEGER,
        zip_file TEXT,
        available INTEGER DEFAULT 1,
        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS repo_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        repo_id INTEGER,
        repo_name TEXT,
        price INTEGER,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    db.commit()

setup_db()

def _migrate():
    def add_col(table, col, ddl):
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info('{table}')").fetchall()]
        if col not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    add_col("stock", "cost", "cost REAL DEFAULT 0")
    add_col("smm_services", "cost_per_1000", "cost_per_1000 REAL DEFAULT 0")
    add_col("smm_services", "panel_type", "panel_type TEXT DEFAULT 'Default'")
    add_col("users", "currency", "currency TEXT DEFAULT 'INR'")
    add_col("users", "language", "language TEXT DEFAULT 'en'")
    add_col("smm_orders", "refunded", "refunded REAL DEFAULT 0")
    add_col("smm_orders", "remains", "remains INTEGER DEFAULT NULL")
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, kind TEXT, item TEXT,
        sell REAL, cost REAL, profit REAL,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS manual_stock (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT, details TEXT,
        price REAL, cost REAL DEFAULT 0,
        available INTEGER DEFAULT 1, sold_to INTEGER,
        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS sold_sessions (
        phone TEXT PRIMARY KEY,
        user_id INTEGER, session_file TEXT, country TEXT, year INTEGER,
        twofa TEXT, otp TEXT, start_time REAL, logout_at REAL,
        devices_cleared INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS number_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, platform TEXT, server INTEGER,
        activation_id TEXT, phone TEXT, otp TEXT,
        price REAL, cost REAL, status TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS notif_users (
        user_id INTEGER PRIMARY KEY,
        enabled INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS notif_seen (
        key TEXT PRIMARY KEY,
        present INTEGER DEFAULT 1,
        last_notified REAL DEFAULT 0
    );
    """)
    # Hero SMS number orders: change-number / cancel flow (see plugins/numflow.py)
    add_col("number_orders", "started", "started REAL")
    add_col("number_orders", "meta", "meta TEXT")
    add_col("number_orders", "changes", "changes INTEGER DEFAULT 0")
    db.commit()

_migrate()

import mongo_store
mongo_store.connect(db)

# ================= HELPER FUNCTIONS =================
def session_base(path):
    """Telethon appends '.session' itself; stored paths keep it, so strip it before opening."""
    path = str(path or "").strip()
    return path[:-8] if path.endswith(".session") else path

def remove_session_files(path):
    import os
    base = session_base(path)
    for ext in ('.session', '.session-wal', '.session-shm', '.session-journal'):
        try:
            if os.path.exists(base + ext): os.remove(base + ext)
        except OSError:
            pass

def is_bot_online():
    res = cur.execute("SELECT value FROM settings WHERE key='bot_status'").fetchone()
    return res[0] == 'on' if res else True

def is_admin(uid):
    if uid in ADMIN_IDS: return True
    row = cur.execute("SELECT user_id FROM admins WHERE user_id=?", (uid,)).fetchone()
    return bool(row)

def has_perm(uid, perm):
    if uid in ADMIN_IDS: return True
    if perm not in {'p_add_stock','p_manage_stock','p_stats','p_bal','p_settings'}: return False
    row = cur.execute(f"SELECT {perm} FROM admins WHERE user_id=?", (uid,)).fetchone()
    return bool(row and row[0] == 1)

def ensure_user(uid):
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
    db.commit()

def get_usdt_rate():
    res = cur.execute("SELECT value FROM settings WHERE key='usdt_rate'").fetchone()
    try: return float(res[0]) if res else 94.0
    except: return 94.0

def get_support_url():
    res = cur.execute("SELECT value FROM settings WHERE key='support_url'").fetchone()
    url = res[0] if res and res[0] else f"https://t.me/{SUPPORT_USERNAME}"
    if not url.startswith("http"): url = "https://" + url.replace("@", "t.me/")
    return url

def to_usd(inr):
    return round(inr / get_usdt_rate(), 2)

def is_user_banned(uid):
    res = cur.execute("SELECT banned FROM users WHERE user_id=?", (uid,)).fetchone()
    return res and res[0] == 1

def update_balance(uid, amount):
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    db.commit()

COUNTRY_CODES = {
    '1': ('USA/Canada', '🇺🇸'), '7': ('Russia', '🇷🇺'), '20': ('Egypt', '🇪🇬'),
    '27': ('South Africa', '🇿🇦'), '31': ('Netherlands', '🇳🇱'), '32': ('Belgium', '🇧🇪'),
    '33': ('France', '🇫🇷'), '34': ('Spain', '🇪🇸'), '39': ('Italy', '🇮🇹'), 
    '44': ('UK', '🇬🇧'), '46': ('Sweden', '🇸🇪'), '48': ('Poland', '🇵🇱'),
    '49': ('Germany', '🇩🇪'), '51': ('Peru', '🇵🇪'), '52': ('Mexico', '🇲🇽'),
    '54': ('Argentina', '🇦🇷'), '55': ('Brazil', '🇧🇷'), '56': ('Chile', '🇨🇱'),
    '57': ('Colombia', '🇨🇴'), '58': ('Venezuela', '🇻🇪'), '60': ('Malaysia', '🇲🇾'),
    '61': ('Australia', '🇦🇺'), '62': ('Indonesia', '🇮🇩'), '63': ('Philippines', '🇵🇭'), 
    '66': ('Thailand', '🇹🇭'), '84': ('Vietnam', '🇻🇳'), '86': ('China', '🇨🇳'), 
    '90': ('Turkey', '🇹🇷'), '91': ('India', '🇮🇳'), '92': ('Pakistan', '🇵🇰'), 
    '93': ('Afghanistan', '🇦🇫'), '94': ('Sri Lanka', '🇱🇰'), '95': ('Myanmar', '🇲🇲'),
    '98': ('Iran', '🇮🇷'), '212': ('Morocco', '🇲🇦'), '213': ('Algeria', '🇩🇿'),
    '234': ('Nigeria', '🇳🇬'), '254': ('Kenya', '🇰🇪'), '255': ('Tanzania', '🇹🇿'),
    '380': ('Ukraine', '🇺🇦'), '880': ('Bangladesh', '🇧🇩'), '964': ('Iraq', '🇮🇶'),
    '966': ('Saudi Arabia', '🇸🇦'), '971': ('UAE', '🇦🇪'), '998': ('Uzbekistan', '🇺🇿')
}

def get_plain_flag_by_country_name(name):
    for code, (c_name, c_flag) in COUNTRY_CODES.items():
        if c_name == name: return c_flag
    try:
        row = cur.execute("SELECT flag FROM custom_countries WHERE name=?", (name,)).fetchone()
        if row: return row[0]
    except: pass
    return "🌍"

def get_flag_by_country_name(name, premium=True):
    flag = get_plain_flag_by_country_name(name)
    emoji_id = premium_flag_id(flag)
    if premium and emoji_id:
        return f'<emoji id="{emoji_id}">{flag}</emoji>'
    return flag

def get_country_info(phone):
    phone = str(phone).replace(' ', '').replace('+', '')
    if not phone: return "Unknown", "🌍"
    
    try:
        customs = cur.execute("SELECT code, name, flag FROM custom_countries").fetchall()
        customs.sort(key=lambda x: len(x[0]), reverse=True)
        for code, name, flag in customs:
            if phone.startswith(code): return name, flag
    except: pass

    for length in (3, 2, 1):
        prefix = phone[:length]
        if prefix in COUNTRY_CODES: return COUNTRY_CODES[prefix]
    return "Unknown", "🌍"
