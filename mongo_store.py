"""MongoDB storage for the whole bot.

MongoDB is the permanent home of ALL data (users, balances, orders, stock,
settings, sold-account session files). A local fast copy is kept for speed;
on every save (db.commit) the changes are pushed to MongoDB within ~1 second,
and on start-up everything is loaded back from MongoDB. So a redeploy, crash
or a wiped server never loses users or money.

Set MONGO_URI (MongoDB Atlas free cluster works) and optionally MONGO_DB.
"""
import hashlib
import json
import logging
import os
import threading
import time

log = logging.getLogger("mongo")

MONGO_URI = os.getenv("MONGO_URI", "").strip()
MONGO_DB = os.getenv("MONGO_DB", "betabot").strip() or "betabot"
SESSIONS_DIR = "sessions"

_client = None
_mdb = None
_conn = None
_hash = {}          # (table, _id) -> hash
_dirty = threading.Event()
_lock = threading.Lock()
enabled = False
# Sync status (read by the admin /health command)
stats = {"last_sync": 0.0, "last_error": "", "last_error_at": 0.0, "failures": 0, "syncs": 0}


def pending_changes() -> bool:
    return _dirty.is_set()


def _tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]


def _pk_cols(conn, table):
    info = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    pks = [c[1] for c in sorted(info, key=lambda c: c[5]) if c[5] > 0]
    return pks, [c[1] for c in info]


def _doc_id(row, pks):
    if pks:
        return "|".join(str(row[k]) for k in pks)
    return f"rowid:{row['__rowid']}"


def connect(conn):
    """Call once after tables are created. Restores data from MongoDB."""
    global _client, _mdb, _conn, enabled
    _conn = conn
    if not MONGO_URI:
        log.warning("MONGO_URI not set — data is only stored locally (NOT safe on redeploy)")
        return
    from pymongo import MongoClient
    _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=15000, retryWrites=True)
    _client.admin.command("ping")
    _mdb = _client[MONGO_DB]
    enabled = True
    _restore()
    _restore_sessions()
    threading.Thread(target=_loop, daemon=True, name="mongo-sync").start()
    log.info("MongoDB connected (%s) — all data is saved there", MONGO_DB)


def _restore():
    with _lock:
        for table in _tables(_conn):
            pks, cols = _pk_cols(_conn, table)
            docs = list(_mdb[table].find({}))
            local = _conn.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0]
            if docs:
                # MongoDB is the source of truth -> replace local copy
                _conn.execute(f"DELETE FROM '{table}'")
                for d in docs:
                    row = {c: d.get(c) for c in cols if c in d}
                    if not row:
                        continue
                    q = f"INSERT OR REPLACE INTO '{table}' ({','.join(row)}) VALUES ({','.join('?' * len(row))})"
                    _conn.execute(q, list(row.values()))
                log.info("Restored %s rows into %s", len(docs), table)
            elif local:
                log.info("First run: uploading %s local rows of %s to MongoDB", local, table)
        sqlite_commit(_conn)
    _sync_once()


def sqlite_commit(conn):
    import sqlite3
    sqlite3.Connection.commit(conn)


def mark_dirty():
    if enabled:
        _dirty.set()


def _sync_once():
    from pymongo import ReplaceOne, DeleteOne
    with _lock:
        for table in _tables(_conn):
            pks, cols = _pk_cols(_conn, table)
            cur = _conn.execute(f"SELECT rowid AS __rowid, * FROM '{table}'")
            names = [d[0] for d in cur.description]
            seen, ops = set(), []
            for r in cur.fetchall():
                row = dict(zip(names, r))
                _id = _doc_id(row, pks)
                seen.add(_id)
                doc = {k: v for k, v in row.items() if k != "__rowid"}
                h = hashlib.md5(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()
                if _hash.get((table, _id)) != h:
                    doc["_id"] = _id
                    ops.append(ReplaceOne({"_id": _id}, doc, upsert=True))
                    _hash[(table, _id)] = h
            for (t, _id) in [k for k in _hash if k[0] == table and k[1] not in seen]:
                ops.append(DeleteOne({"_id": _id}))
                _hash.pop((t, _id), None)
            if ops:
                _mdb[table].bulk_write(ops, ordered=False)
        stats["last_sync"] = time.time()
        stats["syncs"] += 1


def _restore_sessions():
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    n = 0
    for d in _mdb["_files"].find({}):
        path = d["_id"]
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as f:
                f.write(d["data"])
            n += 1
    if n:
        log.info("Restored %s session files from MongoDB", n)


_file_mtimes = {}


def _sync_sessions():
    if not os.path.isdir(SESSIONS_DIR):
        return
    present = set()
    for root, _, files in os.walk(SESSIONS_DIR):
        for fn in files:
            if not fn.endswith(".session"):
                continue
            p = os.path.join(root, fn)
            present.add(p)
            m = os.path.getmtime(p)
            if _file_mtimes.get(p) != m:
                with open(p, "rb") as f:
                    data = f.read()
                if len(data) < 15_000_000:
                    _mdb["_files"].replace_one({"_id": p}, {"_id": p, "data": data}, upsert=True)
                _file_mtimes[p] = m
    for p in [p for p in _file_mtimes if p not in present]:
        _mdb["_files"].delete_one({"_id": p})
        _file_mtimes.pop(p, None)


def _loop():
    last_files = 0
    while True:
        _dirty.wait(timeout=30)
        _dirty.clear()
        try:
            time.sleep(0.5)  # group quick writes together
            _sync_once()
            if time.time() - last_files > 30:
                _sync_sessions()
                last_files = time.time()
        except Exception as ex:
            log.error("MongoDB sync failed, will retry: %s", ex)
            stats["failures"] += 1
            stats["last_error"] = type(ex).__name__
            stats["last_error_at"] = time.time()
            time.sleep(3)
            _dirty.set()


def flush():
    """Force an immediate save (used on shutdown)."""
    if enabled:
        try:
            _sync_once()
            _sync_sessions()
        except Exception as ex:
            log.error("MongoDB flush failed: %s", ex)
