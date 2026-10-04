import os, sys, base64
sys.path.insert(0, ".")
for k in ("ETSY_WORKER_URL", "ETSY_REDEEM_KEY"): os.environ.pop(k, None)
if os.path.exists(os.environ["DB_PATH"]): os.remove(os.environ["DB_PATH"])
from fastapi.testclient import TestClient
from app import main, db
db.init_db()
c = TestClient(main.app)
ok = lambda n, cond: print(("PASS " if cond else "FAIL ") + n) or (cond or sys.exit(1))
# pedido normal y pedido de Etsy (creados directo en la BD, sin tocar Etsy)
db.create_web_order("normalsess0001", source="x", country="US", currency="USD", client_ip="1.1.1.1", client_user_agent="t", language="en", tier="song", landing_flow="v1")
db.create_web_order("etsysess000001", source="etsy", country="US", currency="USD", client_ip="1.1.1.1", client_user_agent="t",
                    language="en", tier="song", landing_flow=None, gateway="etsy", etsy_order_number="4567890123")
db.create_web_order("etsytest000001", source="etsy-test", country="US", currency="USD", client_ip="1.1.1.1", client_user_agent="t",
                    language="en", tier="song", landing_flow=None, gateway="etsy", etsy_order_number="720514")
auth = {"Authorization": "Basic " + base64.b64encode(b"admin:" + os.environ["ADMIN_PANEL_PASSWORD"].encode()).decode()}
r = c.get("/admin", headers=auth); ok("/admin 200", r.status_code == 200)
t = r.text
ok("Etsy session shows 'Etsy #<order>' in the channel column", "Etsy #4567890123" in t)
ok("test order is marked (prueba)", "Etsy #720514 (prueba)" in t)
ok("normal session keeps its old channel label", "EN · " in t and "Etsy #" in t)
ok("Etsy stats card present, test orders excluded (1 real order)", "Sesiones Etsy (1 pedidos)" in t)
r = c.get("/admin/orden/web/etsysess000001", headers=auth); ok("detail 200", r.status_code == 200)
ok("detail shows order number", "Pedido Etsy #4567890123" in r.text and "Número de pedido de Etsy" in r.text)
r = c.get("/admin/orden/web/normalsess0001", headers=auth); ok("normal detail unchanged", r.status_code == 200 and "Pedido web" in r.text and "Etsy #" not in r.text)
r = c.get("/admin/charlas-abandonadas", headers=auth); ok("abandoned chats JSON carries the order number",
    r.status_code == 200 and any(s.get("etsy_order_number") == "4567890123" for s in r.json()["sesiones"]))
print("ADMIN OK")
