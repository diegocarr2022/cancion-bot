import asyncio, json, os, re, threading, http.server, sys
sys.path.insert(0, ".")
os.environ["ETSY_WORKER_URL"] = "http://127.0.0.1:9099"
os.environ["ETSY_REDEEM_KEY"] = "testkey"
if os.path.exists(os.environ["DB_PATH"]): os.remove(os.environ["DB_PATH"])

consumed = []
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        if self.headers.get("x-redeem-key") != "testkey": return self._send(401, {"ok": False, "error": "unauthorized"})
        o, act = body["order_number"], body["action"]
        table = {"111": (1, 0), "222": None, "333": "wrong", "444": (1, 1), "555": (1, 0), "888": (3, 0)}
        v = table.get(o)
        if v is None: return self._send(404, {"ok": False, "error": "not_found"})
        if v == "wrong": return self._send(403, {"ok": False, "error": "wrong_product"})
        credits, base_used = v
        sess = [c[1] for c in consumed if c[0] == o]
        used = max(base_used, len(sess))
        if act == "consume":
            if o == "555" and not consumed: pass
            if used >= credits and body["session_id"] not in sess:
                return self._send(409, {"ok": False, "error": "no_credits_left"})
            if body["session_id"] not in sess: consumed.append((o, body["session_id"]))
            used = max(base_used, len([c for c in consumed if c[0] == o]))
        self._send(200, {"ok": True, "credits": credits, "used": used, "remaining": credits - used})
    def _send(self, code, d):
        b = json.dumps(d).encode(); self.send_response(code); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 9099), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

from fastapi.testclient import TestClient
from app import main, db, web_conversation as wc
db.init_db()
c = TestClient(main.app)
ok = lambda name, cond: print(("PASS " if cond else "FAIL ") + name) or (cond or sys.exit(1))

r = c.get("/etsy"); ok("GET /etsy 200", r.status_code == 200); ok("noindex header", "noindex" in r.headers.get("x-robots-tag", ""))
ok("etsy page has gate", 'id="etsy-gate"' in r.text and "Enter your Etsy order number" in r.text)
ok("etsy page keeps demos", 'id="samples"' in r.text and "/static/hiphop.mp3" in r.text)
ok("etsy page: no stripe script / pixel", "js.stripe.com" not in r.text and "connect.facebook.net" not in r.text and "googletagmanager" not in r.text)
en = c.get("/cancion?lang=en").text
ok("regression: normal EN landing still has price + stripe", "launch price" in en and "js.stripe.com" in en)

ok("check bad body", c.post("/etsy/check", json={}).json()["ok"] is False)
j = c.post("/etsy/check", json={"order_number": "222"}).json(); ok("check not_found msg", not j["ok"] and "couldn't find" in j["error"])
j = c.post("/etsy/check", json={"order_number": "333"}).json(); ok("check wrong product msg", not j["ok"] and "personalized song" in j["error"])
j = c.post("/etsy/check", json={"order_number": "444"}).json(); ok("check used-up msg (no previous session)", not j["ok"] and "already been used" in j["error"])
j = c.post("/etsy/check", json={"order_number": "111"}).json(); ok("check ok", j["ok"] and j.get("remaining") == 1 and "resume_session_id" not in j)

r = c.post("/web/session", json={"etsy_order": "222", "lang": "en"}); ok("session rejects invalid order (403)", r.status_code == 403)
r = c.post("/web/session", json={"etsy_order": "111", "lang": "en"}); ok("session ok", r.status_code == 200)
sid = r.json()["session_id"]
o = db.get_web_order(sid); ok("order is etsy/en/US/unpaid", o["gateway"] == "etsy" and o["language"] == "en" and o["etsy_order_number"] == "111" and o["paid"] == 0 and o["landing_flow"] is None)

# chat: etsy prompt + only finalizar_letra tool, no pricing
seen = {}
async def fake_send_chat(messages, system=None, tools=None):
    seen["system"], seen["tools"] = system, tools
    return {"content": [{"type": "text", "text": "Hi! What's your name?"}]}
wc.send_chat = fake_send_chat
res = asyncio.run(wc.handle_web_chat(sid, ""))
ok("chat uses etsy prompt (no price/pay talk)", "NOTHING to pay" in seen["system"] and "FREE PREVIEW" not in seen["system"])
ok("chat tools = finalizar_letra only", [t["name"] for t in seen["tools"]] == ["finalizar_letra"])

# approve lyrics -> consume credit, suno starts, paid=1
started = []
async def fake_song(**kw): started.append(kw); return {"task_id": "T123"}
wc.generate_custom_song = fake_song
tool = {"title": "T", "style": "pop", "lyric": "[Verse 1]\nhi", "email": "a@b.com", "customer_name": "Ana"}
out = {}
msg = asyncio.run(wc._finalizar_letra(sid, db.get_web_order(sid), main.resolve_precio_orden("US","song",None), tool, out))
o = db.get_web_order(sid)
ok("approve: paid=1, step=generando, task saved", o["paid"] == 1 and o["step"] == "generando" and o["suno_task_id"] == "T123")
ok("approve: etsy_generando flag, no payment fields", out.get("etsy_generando") and not out.get("listo_para_pagar") and not o.get("stripe_client_secret"))
ok("approve: credit consumed for this session", ("111", sid) in consumed)
ok("delivery poll will pick it up", any(x["session_id"] == sid for x in db.find_unfinished_web_suno_tasks()))
ok("excluded from recovery/review emails", not any(x["session_id"] == sid for x in db.find_web_orders_pending_recovery_email(min_hours=0)))
j = c.post("/etsy/check", json={"order_number": "111"}).json(); ok("same order again -> resume that session", j["ok"] and j.get("resume_session_id") == sid)
st = c.get(f"/web/status?session_id={sid}").json(); ok("status shows generating & paid", st["step"] == "generando" and st["paid"])

# no credits left path: order 444 session
r = c.post("/web/session", json={"etsy_order": "111", "lang": "en"})  # second session on same order (credit used by first)
sid2 = r.json()["session_id"] if r.status_code == 200 else None
if sid2:
    db.update_web_order(sid2, etsy_order_number="444")   # simulate an already-used order
    out2 = {}; started.clear()
    msg2 = asyncio.run(wc._finalizar_letra(sid2, db.get_web_order(sid2), main.resolve_precio_orden("US","song",None), tool, out2))
    o2 = db.get_web_order(sid2)
    ok("no credits: not paid, no suno, tells bot to explain", o2["paid"] == 0 and not started and "ya se uso" in msg2 and not out2.get("etsy_generando"))
    ok("no credits: not in recovery-email list", not any(x["session_id"] == sid2 for x in db.find_web_orders_pending_recovery_email(min_hours=0)))
# pack de 3 canciones: orden 888 con 3 creditos -> sesiones nuevas hasta agotarlos, luego resume
sids3 = []
for i in range(3):
    j = c.post("/etsy/check", json={"order_number": "888"}).json()
    ok(f"pack song #{i+1}: check ok with {3-i} left, no resume", j["ok"] and j.get("remaining") == 3 - i and "resume_session_id" not in j)
    r = c.post("/web/session", json={"etsy_order": "888", "lang": "en"}); ok("  pack session created", r.status_code == 200)
    sid3 = r.json()["session_id"]; sids3.append(sid3)
    out3 = {}; asyncio.run(wc._finalizar_letra(sid3, db.get_web_order(sid3), main.resolve_precio_orden("US","song",None), tool, out3))
    ok("  pack approve ok", out3.get("etsy_generando") is True)
j = c.post("/etsy/check", json={"order_number": "888"}).json(); ok("pack exhausted -> resume to latest song", j["ok"] and j.get("resume_session_id") == sids3[-1])
ok("pack: 4th session refused", c.post("/web/session", json={"etsy_order": "888", "lang": "en"}).status_code == 403)
# rate limit
for _ in range(14): last = c.post("/etsy/check", json={"order_number": "111"})
ok("rate limit kicks in (429)", last.status_code == 429)
print("ALL TESTS PASSED")

# --- guard de idioma: letra en espanol -> NO guarda, NO gasta credito, NO genera ---
from app.lang_guard import looks_spanish
r = c.post("/web/session", json={"etsy_order": "555", "lang": "en"}); sidl = r.json()["session_id"]
started2 = []
async def fake_song2(**kw): started2.append(kw); return {"task_id": "T9"}
wc.generate_custom_song = fake_song2
n_before = len([x for x in consumed if x[0] == "555"])
spanish = {"title": "Diez", "style": "pop", "lyric": "[Verse 1]\nDiez años de viajes y café al amanecer\nCantando nuestra canción favorita\nTú eres la que yo quiero, por siempre\n[Chorus]\nDiez años y te elegiría otra vez\nPor cada amanecer, con todo mi corazón", "email": "a@b.com", "customer_name": "Ana"}
outl = {}; msgl = asyncio.run(wc._finalizar_letra(sidl, db.get_web_order(sidl), main.resolve_precio_orden("US","song",None), spanish, outl))
ol = db.get_web_order(sidl)
ok("spanish lyric: rejected before anything happens", "ESPANOL" in msgl and not started2 and ol["paid"] == 0 and not ol.get("final_lyric") and len([x for x in consumed if x[0] == "555"]) == n_before and not outl.get("etsy_generando"))
english = dict(spanish, lyric="[Verse 1]\nTen years of road trips and coffee at dawn,\nSinging our favorite song,\nYou are the one that I want, for always\n[Chorus]\nTen years and I'd choose you again,\nThrough every sunrise, with all of my heart")
outl2 = {}; asyncio.run(wc._finalizar_letra(sidl, db.get_web_order(sidl), main.resolve_precio_orden("US","song",None), english, outl2))
ok("english lyric after the rewrite: goes through (credit used, suno started)", outl2.get("etsy_generando") and started2 and db.get_web_order(sidl)["paid"] == 1)
print("LANG GUARD OK")
