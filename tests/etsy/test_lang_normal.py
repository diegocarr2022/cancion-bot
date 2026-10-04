import asyncio, os, sys
sys.path.insert(0, ".")
for k in ("ETSY_WORKER_URL","ETSY_REDEEM_KEY"): os.environ.pop(k, None)
if os.path.exists(os.environ["DB_PATH"]): os.remove(os.environ["DB_PATH"])
from fastapi.testclient import TestClient
from app import main, db, web_conversation as wc
db.init_db(); c = TestClient(main.app)
ok = lambda n, cond: print(("PASS " if cond else "FAIL ") + n) or (cond or sys.exit(1))
sid = c.post("/web/session", json={"lang": "en"}).json()["session_id"]
started = []
async def fake_song(**kw): started.append(kw); return {"task_id": "P1"}
wc.generate_custom_song = fake_song
tool = {"title": "T", "style": "pop", "lyric": "[Verse 1]\nDiez años de viajes y café al amanecer\nTú eres la que yo quiero, por siempre\nCantando nuestra canción con todo el corazón\n[Chorus]\nY te elegiría otra vez, por cada amanecer, para siempre", "email": "a@b.com", "customer_name": "Ana"}
precio = main.resolve_precio_orden("US", "song", None); out = {}
msg = asyncio.run(wc._finalizar_letra(sid, db.get_web_order(sid), precio, tool, out))
o = db.get_web_order(sid)
ok("normal EN flow: Spanish lyric rejected (no suno, no preview)", "ESPANOL" in msg and not started and o["step"] == "charlando" and not out.get("generando_preview"))
tool["lyric"] = "[Verse 1]\nTen years of road trips and coffee at dawn,\nSinging our favorite song,\nYou are the one that I want, for always\n[Chorus]\nTen years and I'd choose you again,\nThrough every sunrise, with all of my heart"
out = {}; asyncio.run(wc._finalizar_letra(sid, db.get_web_order(sid), precio, tool, out))
ok("normal EN flow: English lyric goes to preview as before", out.get("generando_preview") and started and db.get_web_order(sid)["step"] == "generando_preview")
# ES flow untouched
sid_es = c.post("/web/session", json={"lang": "es"}).json()["session_id"]
tool_es = dict(tool, lyric="[Verso 1]\nDiez años de viajes y café al amanecer\nTú eres la que yo quiero, por siempre\n[Coro]\nY te elegiría otra vez, por cada amanecer, para siempre")
async def fake_pay(*a, **k): return {"redirect_url": "http://x"}
wc.crear_link_pago = fake_pay
out = {}; msg = asyncio.run(wc._finalizar_letra(sid_es, db.get_web_order(sid_es), main.resolve_precio_orden("MX", "song", None), tool_es, out))
ok("ES flow untouched: Spanish lyric accepted", "ESPANOL" not in msg and db.get_web_order(sid_es).get("final_lyric"))
print("NORMAL FLOW OK")
