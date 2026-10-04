#!/bin/bash
# Pruebas de la integracion de Etsy (y regresion del sitio normal). Corren 100% locales: claves falsas, Worker de Etsy
# simulado en localhost (puertos 9097-9099), Suno/Claude/Mailgun/media simulados. NO tocan produccion ni gastan nada.
#
# Uso, desde la raiz del repo:   bash tests/etsy/run_all.sh
# (crea un venv en /tmp/cb-test-venv la primera vez; otro: VENV=/ruta bash tests/etsy/run_all.sh)
cd "$(dirname "$0")/../.." || exit 1
VENV=${VENV:-/tmp/cb-test-venv}
if [ ! -x "$VENV/bin/python" ]; then python3 -m venv "$VENV" && "$VENV/bin/pip" install -q -r requirements.txt || exit 1; fi
export TELEGRAM_BOT_TOKEN=test ACEDATACLOUD_API_TOKEN=test DLOCAL_API_KEY=test DLOCAL_SECRET_KEY=test ADMIN_CHAT_ID=1 \
       ADMIN_PANEL_PASSWORD=test BASE_URL=http://localhost:8000 DB_PATH=/tmp/cb-test.db MEDIA_DIR=/tmp/cb-media
unset ETSY_WORKER_URL ETSY_REDEEM_KEY ETSY_TEST_ORDERS            # cada prueba fija las suyas
fail=0
for t in test_lang test_etsy test_variation test_vinyl test_lang_normal test_testorder test_regression test_admin; do
  echo "=== $t"
  out=$("$VENV/bin/python" "tests/etsy/$t.py" 2>&1); code=$?
  echo "$out" | grep -E "^(PASS|FAIL)|OK$|ALL TESTS PASSED" | sed 's/^/   /'
  if [ $code -ne 0 ] || echo "$out" | grep -q "^FAIL"; then echo "   >>> $t FALLO"; echo "$out" | tail -15; fail=1; fi
done
[ $fail -eq 0 ] && echo "TODAS LAS PRUEBAS PASARON" || { echo "HAY PRUEBAS FALLIDAS"; exit 1; }
