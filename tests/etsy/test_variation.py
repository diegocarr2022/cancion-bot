import asyncio, json, os, sys, threading, http.server
sys.path.insert(0, ".")
os.environ["ETSY_WORKER_URL"] = "http://127.0.0.1:9097"; os.environ["ETSY_REDEEM_KEY"] = "testkey"; os.environ["ETSY_TEST_ORDERS"] = "720514"
if os.path.exists(os.environ["DB_PATH"]): os.remove(os.environ["DB_PATH"])
consumed = []
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["content-length"]))); o, act = b["order_number"], b["action"]
        credits = {"888": 3, "999": 1}.get(o)
        if credits is None: return self._send(404, {"ok": False, "error": "not_found"})
        sess = [c[1] for c in consumed if c[0] == o]
        if act == "consume":
            if b["session_id"] not in sess:
                if len(sess) >= credits: return self._send(409, {"ok": False, "error": "no_credits_left"})
                consumed.append((o, b["session_id"])); sess.append(b["session_id"])
        self._send(200, {"ok": True, "credits": credits, "used": len(sess), "remaining": credits - len(sess)})
    def _send(self, code, d):
        x = json.dumps(d).encode(); self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(x))); self.end_headers(); self.wfile.write(x)
threading.Thread(target=http.server.ThreadingHTTPServer(("127.0.0.1", 9097), H).serve_forever, daemon=True).start()
from fastapi.testclient import TestClient
from app import main, db, web_conversation as wc
db.init_db(); c = TestClient(main.app)
ok = lambda n, cond: print(("PASS " if cond else "FAIL ") + n) or (cond or sys.exit(1))
started = []; fail = {"on": False}
async def fake_song(**kw):
    if fail["on"]: raise RuntimeError("suno down")
    started.append(kw); return {"task_id": f"T{len(started)}"}
wc.generate_custom_song = fake_song; main.generate_custom_song = fake_song
LYR = "[Verse 1]\nTen years of road trips and coffee at dawn,\nYou are the one that I want, for always\n[Chorus]\nI will choose you again, with all of my heart"
tool = {"title": "Ten Years", "style": "soft pop", "lyric": LYR, "email": "a@b.com", "customer_name": "Carlos Ramirez", "recipient": "Ana", "from_name": "Lolo", "vocal_gender": "f"}
def make_parent(order):
    sid = c.post("/web/session", json={"etsy_order": order, "lang": "en"}).json()["session_id"]
    asyncio.run(wc._finalizar_letra(sid, db.get_web_order(sid), main.resolve_precio_orden("US","song",None), tool, {}))
    return sid
p = make_parent("888")
ok("parent consumed credit #1", len([x for x in consumed if x[0] == "888"]) == 1)
ok("not eligible until delivered", c.get(f"/etsy/credits?session_id={p}").json()["eligible"] is False)
r = c.post("/web/variation", json={"session_id": p, "style_key": "pop"}); ok("variation refused before delivery (403)", r.status_code == 403)
db.update_web_order(p, delivered=1, step="entregado", audio_urls=json.dumps(["u1", "u2"]))
cr = c.get(f"/etsy/credits?session_id={p}").json(); ok("eligible with 2 left + style list", cr["eligible"] and cr["remaining"] == 2 and len(cr["styles"]) >= 6)
r = c.post("/web/variation", json={"session_id": p}); ok("no style -> 400", r.status_code == 400)
n0 = len(started)
r = c.post("/web/variation", json={"session_id": p, "style_key": "country"}); ok("variation #1 ok", r.status_code == 200)
k1 = r.json()["session_id"]; o1 = db.get_web_order(k1)
ok("child: same lyric, new style, paid, generating, linked", o1["final_lyric"] == LYR and "country" in o1["final_style"].lower() and o1["paid"] == 1 and o1["step"] == "generando" and o1["suno_task_id"] and o1["parent_session_id"] == p)
ok("child keeps title/email/recipient/from/gender", o1["final_title"] == "Ten Years" and o1["email"] == "a@b.com" and o1["final_recipient"] == "Ana" and o1["final_from"] == "Lolo" and o1["final_gender"] == "f")
ok("suno got the SAME lyric with the NEW style", started[-1]["lyric"] == LYR and "country" in started[-1]["style"].lower() and len(started) == n0 + 1)
ok("credit #2 consumed for the child", ("888", k1) in consumed and len([x for x in consumed if x[0] == "888"]) == 2)
r = c.post("/web/variation", json={"session_id": p, "style_key": "country"}); ok("double click returns same child, no extra credit/Suno", r.json()["session_id"] == k1 and len([x for x in consumed if x[0] == "888"]) == 2 and len(started) == n0 + 1)
ok("child will be delivered by the usual poll (paid, task, undelivered)", any(x["session_id"] == k1 for x in db.find_unfinished_web_suno_tasks()))
ok("child excluded from recovery/review emails", not any(x["session_id"] == k1 for x in db.find_web_orders_pending_recovery_email(min_hours=0)))
fail["on"] = True
r = c.post("/web/variation", json={"session_id": p, "style_key": "rock"}); ok("Suno failure -> 502 and NO credit spent", r.status_code == 502 and len([x for x in consumed if x[0] == "888"]) == 2)
fail["on"] = False
r = c.post("/web/variation", json={"session_id": p, "style_text": "Dreamy lo-fi, soft piano   \n\x00 slow"}); ok("free-text style accepted + sanitized", r.status_code == 200 and "\x00" not in started[-1]["style"])
ok("credits exhausted (3/3)", len([x for x in consumed if x[0] == "888"]) == 3)
ok("not eligible when exhausted", c.get(f"/etsy/credits?session_id={p}").json()["eligible"] is False)
nst = len(started); r = c.post("/web/variation", json={"session_id": p, "style_key": "bigband"}); ok("4th variation refused (409), no Suno call", r.status_code == 409 and len(started) == nst)
single = make_parent("999"); db.update_web_order(single, delivered=1)
ok("single-credit order: not eligible after its only song", c.get(f"/etsy/credits?session_id={single}").json()["eligible"] is False)
t = make_parent("720514"); db.update_web_order(t, delivered=1)
for i, key in enumerate(("pop", "rock", "latin", "acoustic")):
    r = c.post("/web/variation", json={"session_id": t, "style_key": key}); ok(f"test order unlimited variation #{i+1}", r.status_code == 200)
normal = c.post("/web/session", json={"lang": "en"}).json()["session_id"]; db.update_web_order(normal, delivered=1, final_lyric=LYR)
ok("non-Etsy session cannot use it (403)", c.post("/web/variation", json={"session_id": normal, "style_key": "pop"}).status_code == 403)
html = c.get("/etsy").text; ok("landing offers variation UI, still no money words", "ofrecerVariacion" in html and "Create another version" in html)
print("VARIATION OK")
