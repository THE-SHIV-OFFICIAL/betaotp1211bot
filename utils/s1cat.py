"""Server 1 (Telegram session stock) account categories.

Every account in the `stock` table has a `category`:
  fake -> FAKE/SCAM TAG accounts
  old  -> OLD ACCOUNT
  good -> GOOD QUALITY ACC
Buyers pick a category first on Server 1; the admin picks one while adding stock.
"""

# key: (button label, button style, short description)
S1_CATS = {
    "fake": ("FAKE/SCAM TAG", "danger", "Accounts with Fake / Scam tag — cheapest, buy at your own risk."),
    "old": ("OLD ACCOUNT", "primary", "Old aged Telegram accounts."),
    "good": ("GOOD QUALITY ACC", "success", "Clean, good quality Telegram accounts."),
}
# premium (custom) emoji id for each category
S1_ICONS = {"fake": 5845903973977951702, "old": 6161474570042740187, "good": 6100469558944994144}
_FALLBACK = {"fake": "🚫", "old": "🗓", "good": "✅"}


def cat_icon(cat):
    return S1_ICONS.get(cat, S1_ICONS["good"])


def cat_emoji(cat):
    """Premium emoji for message text."""
    cat = cat if cat in S1_ICONS else "good"
    return f'<tg-emoji emoji-id="{S1_ICONS[cat]}">{_FALLBACK[cat]}</tg-emoji>'


def cat_text(cat):
    """Premium emoji + label, for message text."""
    return f"{cat_emoji(cat)} {cat_label(cat)}"
S1_CAT_KEYS = tuple(S1_CATS)


def cat_label(cat):
    return S1_CATS.get(cat, S1_CATS["good"])[0]


def split_mode(mode):
    """'single:fake' -> ('single', 'fake'); 'single' -> ('single', None)."""
    mode = mode or "single"
    if ":" in mode:
        base, cat = mode.split(":", 1)
        return base, (cat if cat in S1_CATS else None)
    return mode, None


def cat_sql(cat):
    """Extra WHERE clause + args to filter stock by category."""
    return (" AND category=?", (cat,)) if cat else ("", ())


def migrate_categories(cur, db):
    """Old rows were saved as 'Good' -> normalise into the 3 keys."""
    try:
        cur.execute("UPDATE stock SET category='good' WHERE category IS NULL OR category NOT IN ('fake','old','good')")
        db.commit()
    except Exception:
        pass


def cat_counts(cur):
    rows = cur.execute("SELECT category, COUNT(*) FROM stock WHERE available=1 GROUP BY category").fetchall()
    out = {k: 0 for k in S1_CATS}
    for c, n in rows:
        if c in out:
            out[c] = n
    return out
