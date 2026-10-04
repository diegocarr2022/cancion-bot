import asyncio, os, sys
sys.path.insert(0, ".")
os.environ["ETSY_TEST_ORDERS"] = "720514"
for k in ("ETSY_WORKER_URL", "ETSY_REDEEM_KEY"): os.environ.pop(k, None)   # sin Worker: solo el pedido de prueba debe pasar
if os.path.exists(os.environ["DB_PATH"]): os.remove(os.environ["DB_PATH"])
from fastapi.testclient import TestClient
from app import main, db, web_conversation as wc
db.init_db()
c = TestClient(main.app)
ok = lambda n, cond: print(("PASS " if cond else "FAIL ") + n) or (cond or sys.exit(1))
ok("/etsy available with only a test order configured", c.get("/etsy").status_code == 200)
j = c.post("/etsy/check", json={"order_number": "720514"}).json(); ok("test order passes check", j["ok"] is True)
j = c.post("/etsy/check", json={"order_number": "720515"}).json(); ok("other number rejected (worker not configured)", j["ok"] is False)

async def fake_song(**kw): return {"task_id": "TT"}
wc.generate_custom_song = fake_song
tool = {"title": "T", "style": "pop", "lyric": "[Verse 1]\nhi", "email": "a@b.com", "customer_name": "Ana"}
sids = []
for i in range(3):   # varios escenarios con el MISMO numero de prueba
    r = c.post("/web/session", json={"etsy_order": "720514", "lang": "en"}); ok(f"test session #{i+1} created", r.status_code == 200)
    sid = r.json()["session_id"]; sids.append(sid)
    o = db.get_web_order(sid); ok("  marked etsy-test", o["source"] == "etsy-test" and o["gateway"] == "etsy")
    out = {}; asyncio.run(wc._finalizar_letra(sid, o, main.resolve_precio_orden("US", "song", None), tool, out))
    o = db.get_web_order(sid); ok("  approve -> generating, paid", out.get("etsy_generando") and o["paid"] == 1 and o["step"] == "generando")
    j = c.post("/etsy/check", json={"order_number": "720514"}).json(); ok("  check still passes, no resume redirect (reusable)", j["ok"] and "resume_session_id" not in j)
ok("3 distinct sessions", len(set(sids)) == 3)
print("TEST ORDER OK")
