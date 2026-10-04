import asyncio, os, sys
sys.path.insert(0, ".")
for k in ("ETSY_WORKER_URL","ETSY_REDEEM_KEY"): os.environ.pop(k, None)
if os.path.exists(os.environ["DB_PATH"]): os.remove(os.environ["DB_PATH"])
from fastapi.testclient import TestClient
from app import main, db, media_client, web_conversation as wc
db.init_db(); c = TestClient(main.app)
ok = lambda n, cond: print(("PASS " if cond else "FAIL ") + n) or (cond or sys.exit(1))
sid = c.post("/web/session", json={"lang": "en"}).json()["session_id"]
db.update_web_order(sid, final_title="Ten Years of You", final_lyric="[Verse 1]\nTen years of road trips\n[Chorus]\nI'd choose you again", customer_name="Carlos Eduardo Ramirez Soto", final_recipient="Ana")
calls = {"gen": 0, "dl": []}
async def fake_gen(title, lyrics, recipient="", sender="", dedication="", sizes=None):
    calls["gen"] += 1; calls["args"] = (title, recipient, sender, sizes)
    return {z: f"https://media.example/files/vinyl/abc/lyrics-{z}.pdf" for z in sizes}
async def fake_dl(url): calls["dl"].append(url); return b"%PDF-VINYL-" + url.encode()
media_client.generar_vinyl_pdfs = fake_gen; media_client.descargar_pdf = fake_dl
r = c.get(f"/web/lyrics-pdf/{sid}")
ok("vinyl pdf served (default 8x10)", r.status_code == 200 and r.content.startswith(b"%PDF-VINYL-") and r.content.endswith(b"lyrics-8x10.pdf"))
ok("filename has size", "ten-years-of-you-lyrics-8x10.pdf" in r.headers["content-disposition"])
ok("sender = first name of a full customer name; recipient + 4 sizes", calls["args"] == ("Ten Years of You", "Ana", "Carlos", ["8x10", "11x14", "A4", "12x12"]))
db.update_web_order(sid, final_from="Lolo")
r = c.get(f"/web/lyrics-pdf/{sid}?size=11x14"); ok("explicit from_name (nickname) wins and regenerates", calls["args"][2] == "Lolo" and calls["gen"] == 2)
calls["gen"] = 1
r = c.get(f"/web/lyrics-pdf/{sid}?size=A4"); ok("other size served from cache (no 2nd generation)", r.content.endswith(b"lyrics-A4.pdf") and calls["gen"] == 1)
r = c.get(f"/web/lyrics-pdf/{sid}?size=99x99"); ok("invalid size falls back to 8x10", r.content.endswith(b"lyrics-8x10.pdf"))
db.update_web_order(sid, final_lyric="[Verse 1]\nNew lyric after edit\n[Chorus]\nchanged")
r = c.get(f"/web/lyrics-pdf/{sid}"); ok("changed lyric invalidates cache", calls["gen"] == 2)
async def boom(*a, **k): raise RuntimeError("media service down")
media_client.generar_vinyl_pdfs = boom
sid2 = c.post("/web/session", json={"lang": "en"}).json()["session_id"]
db.update_web_order(sid2, final_title="Fallback Song", final_lyric="[Verse 1]\nHello there\n[Chorus]\nGoodbye")
r = c.get(f"/web/lyrics-pdf/{sid2}"); ok("service down -> old simple PDF still delivered", r.status_code == 200 and r.content[:4] == b"%PDF" and not r.content.startswith(b"%PDF-VINYL"))
ok("fallback filename", "fallback-song-lyrics.pdf" in r.headers["content-disposition"])
ok("404 without lyrics", c.get("/web/lyrics-pdf/doesnotexist").status_code == 404)
# recipient stored from tool call
sid3 = c.post("/web/session", json={"lang": "en"}).json()["session_id"]
async def fake_song(**kw): return {"task_id": "T"}
wc.generate_custom_song = fake_song
tool = {"title": "T", "style": "pop", "lyric": "[Verse 1]\nTen years of road trips and coffee at dawn,\nYou are the one that I want\n[Chorus]\nI will choose you again, with all of my heart", "email": "a@b.com", "customer_name": "Carlos Eduardo Ramirez", "recipient": "Ana", "from_name": "Lolo"}
asyncio.run(wc._finalizar_letra(sid3, db.get_web_order(sid3), main.resolve_precio_orden("US","song",None), tool, {}))
ok("recipient + from_name saved from finalizar_letra", db.get_web_order(sid3)["final_recipient"] == "Ana" and db.get_web_order(sid3)["final_from"] == "Lolo")
html = c.get("/cancion?lang=en").text
ok("landing offers other print sizes", "Other print sizes" in html and "?size=" in html)
print("VINYL OK")
