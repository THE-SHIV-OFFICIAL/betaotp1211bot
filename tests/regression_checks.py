import os,sys,asyncio,importlib,types,time
os.environ.update(API_ID="1",API_HASH="x",BOT_TOKEN="1:x",ADMIN_ID="1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def ok(name, condition):
    assert condition, name
    print("PASS " + name)
# 1 import all modules
bad=[]
for m in ["config","database","utils.paygate","utils.helpers","utils.keyboards","utils.states"]+["plugins."+f[:-3] for f in os.listdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins")) if f.endswith(".py") and f!="__init__.py"]:
    try: importlib.import_module(m)
    except Exception as e: bad.append(f"{m}: {e!r}")
ok("all modules import "+str(bad),not bad)
import database as d
d.setup_db()
ok("WAL mode",d.db.execute("PRAGMA journal_mode").fetchone()[0]=="wal")
ok("synchronous NORMAL",d.db.execute("PRAGMA synchronous").fetchone()[0]==1)
ok("tables created",{"users","stock","settings"}<=set(r[0] for r in d.db.execute("select name from sqlite_master")))
# 2 paygate against local fake server
from aiohttp import web
from utils import paygate as p
os.environ["PAYGATE_API_KEY"]="k"
calls=[]
async def create(r): calls.append(r.headers.get("Authorization")); return web.json_response({"success":True,"order":{"orderId":"O1","payAmount":100}})
async def status(r): return web.json_response({"verified":True,"order":{"status":"paid"}})
async def bad_(r): return web.json_response({"success":False,"error":"nope"})
async def run_pg():
    app=web.Application();app.router.add_post("/api/v1/payments/create",create);app.router.add_get("/api/v1/payments/{id}",status)
    rn=web.AppRunner(app);await rn.setup();s=web.TCPSite(rn,"127.0.0.1",8799);await s.start()
    p.PAYGATE_URL="http://127.0.0.1:8799"
    o=await p.create_payment(100,"n");ok("create_payment returns order",o["orderId"]=="O1")
    ok("auth header sent",calls[0]=="Bearer k")
    st=await p.get_status("O1");ok("get_status PAID+verified",st[0]=="PAID" and st[1])
    sess=p.get_http_session()
    for _ in range(200): await p.get_status("O1")
    ok("200 polls reuse 1 session",sess is p.get_http_session())
    ok("open sockets small",len(sess.connector._conns.get(next(iter(sess.connector._conns)),[]))<=5 if sess.connector._conns else True)
    app2=web.Application();app2.router.add_post("/api/v1/payments/create",bad_);r2=web.AppRunner(app2);await r2.setup();await web.TCPSite(r2,"127.0.0.1",8798).start()
    p.PAYGATE_URL="http://127.0.0.1:8798"
    try: await p.create_payment(1);ok("error raises PayGateError",False)
    except p.PayGateError: ok("error raises PayGateError",True)
    await p.close_http_session();ok("session closes",sess.closed)
    ns=p.get_http_session();ok("new session after close",not ns.closed and ns is not sess);await p.close_http_session()
    await rn.cleanup();await r2.cleanup()
asyncio.run(run_pg())
# 3 real process_purchase under load (Telegram client mocked)
import plugins.buy as b
cur,db=d.cur,d.db
cur.execute("DELETE FROM stock");cur.execute("DELETE FROM users")
cols=[r[1] for r in cur.execute("PRAGMA table_info(stock)")]
for i in range(3):
    cur.execute("INSERT INTO stock(phone,country_name,account_year,price,session_file,twofa,available) VALUES(?,?,?,?,?,?,1)",(f"+9100{i}","India",2020,50,f"s{i}",""))
for u in range(1,11): cur.execute("INSERT INTO users(user_id,balance) VALUES(?,100)",(u,))
db.commit()
class FC:
    def __init__(s,*a,**k):pass
    async def connect(s):pass
    async def is_user_authorized(s):return True
    async def disconnect(s):pass
    def is_connected(s):return True
    def add_event_handler(s,*a,**k):pass
    def __getattr__(s,n):
        async def f(*a,**k):return None
        return f
b.TelegramClient=FC
class Ev:
    def __init__(s,u):s.sender_id=u;s.alerts=[];s.message_id=5
    async def answer(s,t="",alert=False):s.alerts.append(t)
    async def edit(s,*a,**k):pass
    async def respond(s,*a,**k):return types.SimpleNamespace(id=1)
async def buyall():
    evs=[Ev(u) for u in range(1,11)]
    res=await asyncio.gather(*[b.process_purchase(e,"India","2020","50") for e in evs],return_exceptions=True)
    return evs,res
evs,res=asyncio.run(buyall())
errs=[r for r in res if isinstance(r,Exception)]
ok("no crash during 10 parallel buys "+str(errs[:2]),not errs)
sold=cur.execute("SELECT COUNT(*) FROM stock WHERE available=0").fetchone()[0]
paid=cur.execute("SELECT COUNT(*) FROM users WHERE balance=50").fetchone()[0]
full=cur.execute("SELECT COUNT(*) FROM users WHERE balance=100").fetchone()[0]
ok(f"3 numbers sold, 3 users charged, 7 refunded/untouched ({sold},{paid},{full})",sold==3 and paid==3 and full==7)
ok("out-of-stock users told",sum(1 for e in evs if any("stock" in a.lower() or "sold" in a.lower() for a in e.alerts))==7)
cur.execute("INSERT INTO stock(phone,country_name,account_year,price,session_file,twofa,available) VALUES('+9199','India',2020,50,'sx','',1)")
cur.execute("INSERT INTO users(user_id,balance) VALUES(99,10)");db.commit()
e=Ev(99);asyncio.run(b.process_purchase(e,"India","2020","50"))
ok("low balance blocked, number kept",any("Balance" in a for a in e.alerts) and cur.execute("select available from stock where phone='+9199'").fetchone()[0]==1 and cur.execute("select balance from users where user_id=99").fetchone()[0]==10)
class BadC(FC):
    async def is_user_authorized(s):return False
b.TelegramClient=BadC;cur.execute("UPDATE users SET balance=100 WHERE user_id=99");db.commit()
e=Ev(99);asyncio.run(b.process_purchase(e,"India","2020","50"))
ok("dead session -> money refunded + number back",cur.execute("select balance from users where user_id=99").fetchone()[0]==100 and cur.execute("select available from stock where phone='+9199'").fetchone()[0]==1)
# 4 DB speed
t=time.time()
for i in range(3000): cur.execute("UPDATE users SET balance=balance+0 WHERE user_id=1");db.commit()
print(f"INFO 3000 saves in {time.time()-t:.2f}s")
