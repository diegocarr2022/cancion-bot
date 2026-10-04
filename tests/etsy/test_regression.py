import os, sys
sys.path.insert(0, ".")
for k in ("ETSY_WORKER_URL","ETSY_REDEEM_KEY"): os.environ.pop(k, None)   # sin variables de Etsy: el sitio debe ser identico
if os.path.exists(os.environ["DB_PATH"]): os.remove(os.environ["DB_PATH"])
from fastapi.testclient import TestClient
from app import main, db
db.init_db()
c = TestClient(main.app)
ok = lambda n, cond: print(("PASS " if cond else "FAIL ") + n) or (cond or sys.exit(1))
ok("/etsy is 503 when ETSY_* vars are not set", c.get("/etsy").status_code == 503)
ok("/etsy/check is 503 when disabled", c.post("/etsy/check", json={"order_number": "1"}).status_code == 503)
for path in ("/", "/cancion", "/cancion?lang=en", "/terms", "/privacy", "/terminos", "/healthz"):
    ok(f"GET {path} 200", c.get(path, follow_redirects=True).status_code == 200)
r = c.post("/web/session", json={"lang": "en", "source": "test"}); ok("normal EN session still created", r.status_code == 200)
o = db.get_web_order(r.json()["session_id"]); ok("normal order is NOT etsy", o["gateway"] in (None, "") and o["etsy_order_number"] is None)
r = c.post("/web/session", json={"etsy_order": "123"}); ok("etsy_order ignored-safely: 503 when disabled", r.status_code == 503)
print("REGRESSION OK")
