"""Full health-check tests. Run: python tests/test_health.py"""
import asyncio, os, sys, time
SECRETS = dict(API_ID="12345", API_HASH="HASHSECRET999", BOT_TOKEN="1:TOKENSECRET999", ADMIN_ID="1",
               PAYGATE_API_KEY="PAYKEYSECRET999", PAYGATE_URL="http://127.0.0.1:1",
               HERO_SMS_API_URL="http://127.0.0.1:1/g", SMM_API_URL="http://127.0.0.1:1/s",
               TGLION_API_URL="http://127.0.0.1:1/t")
MONGO = "mongodb://user:MONGOPASS999@127.0.0.1:1/db"
os.environ.update(SECRETS)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database; database.setup_db()
os.environ["MONGO_URI"] = MONGO
import mongo_store; mongo_store.MONGO_URI = MONGO
from utils import health, paygate

def ok(n, c):
    assert c, n; print("PASS", n)

ALL_SECRETS = ["HASHSECRET999", "TOKENSECRET999", "MONGOPASS999", "PAYKEYSECRET999", "GOODKEY", "user:"]

# --- helpers / stability rating
ok("safe_host strips creds/path", health.safe_host(MONGO) == "mongodb://127.0.0.1:1")
ok("stable", health.rate_stability([100, 120, 110])["verdict"] == "STABLE")
ok("unstable", health.rate_stability([100, None, 110])["verdict"] == "UNSTABLE")
ok("down", health.rate_stability([None, None, None])["verdict"] == "DOWN")
ok("slow", health.rate_stability([2000, 2100, 1900])["verdict"] == "SLOW")

# --- config
ok("config all required set", health.check_config()["ok"])
os.environ.pop("BOT_TOKEN"); ok("missing BOT_TOKEN detected", not health.check_config()["ok"])
os.environ["BOT_TOKEN"] = SECRETS["BOT_TOKEN"]

# --- bot smoothness
async def lag_test():
    smooth = await health.check_bot()
    async def blocker():
        await asyncio.sleep(0.01); time.sleep(0.5)  # simulates blocking code
    t = asyncio.create_task(blocker()); laggy = await health.check_bot(); await t
    return smooth, laggy
smooth, laggy = asyncio.run(lag_test())
ok(f"idle bot smooth ({smooth['loop_lag_ms']} ms)", smooth["ok"] and smooth["verdict"] == "SMOOTH")
ok(f"blocked bot laggy ({laggy['loop_lag_ms']} ms)", not laggy["ok"] and laggy["verdict"] == "LAGGY")
class FakeTG:
    def is_connected(s): return True
    async def get_me(s): return object()
ok("telegram connected", asyncio.run(health.check_bot(FakeTG()))["telegram"] == "connected")
class DeadTG:
    def is_connected(s): return False
ok("telegram disconnected -> not ok", not asyncio.run(health.check_bot(DeadTG()))["ok"])

# --- everything down
r = asyncio.run(health.run_health_check())
ok("payment DOWN detected", r["apis"][0]["verdict"] == "DOWN" and not r["apis"][0]["ok"])
ok("mongo unreachable detected", not r["db"]["mongo"]["ok"])
ok("local DB integrity ok", r["db"]["local"]["integrity"] == "ok" and "users" in r["db"]["local"]["counts"])
ok("overall ATTENTION", not r["ok"])
txt = health.format_report(r) + repr(r)
ok("no secret leaks (down)", not any(s in txt for s in ALL_SECRETS))

# --- fake APIs: stable paygate, flaky herosms
from aiohttp import web
flaky = {"n": 0}
async def g(req):
    flaky["n"] += 1
    return web.Response(status=503 if flaky["n"] % 2 else 200)
async def apis():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="ok"))
    app.router.add_get("/g", g)
    app.router.add_get("/api/v1/payments/{id}", lambda r: web.json_response(
        {}, status=404 if r.headers.get("Authorization") == "Bearer GOODKEY" else 401))
    run = web.AppRunner(app); await run.setup(); await web.TCPSite(run, "127.0.0.1", 18765).start()
    paygate.PAYGATE_URL = "http://127.0.0.1:18765"
    os.environ["HERO_SMS_API_URL"] = "http://127.0.0.1:18765/g"; os.environ["HERO_SMS_API_KEY"] = "x"
    bad = await health.check_apis()
    os.environ["PAYGATE_API_KEY"] = "GOODKEY"
    good = await health.check_apis()
    await run.cleanup(); return bad, good
bad, good = asyncio.run(apis())
ok("bad pay key -> rejected", bad[0]["auth"] == "rejected" and not bad[0]["ok"])
ok("pay STABLE + accepted", good[0]["verdict"] == "STABLE" and good[0]["auth"] == "accepted" and good[0]["ok"])
ok("flaky herosms -> UNSTABLE", good[1]["verdict"] == "UNSTABLE" and not good[1]["ok"])
ok("unset SMM shown as not configured", "SMM panel: not configured" in health.format_report(
    {"ok": False, "bot": smooth, "apis": good, "db": r["db"], "config": health.check_config()}))

# --- fake MongoDB: in sync vs out of sync
class Coll:
    def __init__(s, n): s.n = n
    def count_documents(s, q): return s.n
class FakeMongo:
    def __init__(s, counts): s.counts = counts
    class admin:
        @staticmethod
        def command(c): return {"ok": 1}
    def __getitem__(s, name):
        counts = s.counts
        class DB:
            def __getitem__(_, t): return Coll(counts.get(t, 0))
        return DB()
local = health._local_db_sync()["counts"]
mongo_store._client = FakeMongo(dict(local)); mongo_store.enabled = True
mongo_store.stats.update(last_sync=time.time() - 5, last_error="", last_error_at=0)
d = asyncio.run(health.check_database())
ok("DB UP TO DATE", d["ok"] and d["mongo"]["sync"] == "UP TO DATE")
mongo_store._client = FakeMongo({**local, "users": local["users"] + 7})
d = asyncio.run(health.check_database())
ok("DB mismatch detected", not d["ok"] and "users" in d["mongo"]["mismatch"])
mongo_store._client = FakeMongo(dict(local))
mongo_store.stats.update(last_error="AutoReconnect", last_error_at=time.time(), failures=2)
d = asyncio.run(health.check_database())
ok("DB sync FAILING detected", not d["ok"] and d["mongo"]["sync"] == "FAILING")
txt = health.format_report({"ok": False, "bot": smooth, "apis": good, "db": d, "config": health.check_config()})
ok("no secret leaks (full report)", not any(s in txt for s in ALL_SECRETS))
print("\n--- SAMPLE REPORT ---\n" + txt)
print("\nALL HEALTH TESTS PASSED")
