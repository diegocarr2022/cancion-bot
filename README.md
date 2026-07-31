# Cancion Bot — piloto de canciones personalizadas 100% automatizado

Flujo: Telegram (recibe pedido) -> dLocal Go (crea el cobro y confirma el
pago via webhook) -> Claude API (escribe letra) -> Suno via AceDataCloud
(genera audio) -> Telegram (entrega el archivo). Todo automático, sin pasos
manuales en el camino feliz.

## Que necesitas antes de desplegar

1. **Bot de Telegram**: habla con [@BotFather](https://t.me/BotFather) en Telegram,
   crea un bot nuevo (`/newbot`), copia el token que te da.
2. **Tu chat_id de Telegram**: hablale a [@userinfobot](https://t.me/userinfobot),
   te va a decir tu ID numérico. Ese sos vos como admin.
3. **Cuenta de dLocal Go**: la que ya creaste. Para probar primero en modo
   sandbox, anda a dashboard-sbx.dlocalgo.com y saca tu API Key y Secret Key
   (sección de API Keys / credenciales). Cuando quieras cobrar de verdad,
   repites el proceso en dashboard.dlocalgo.com (modo "live").
4. **Token de AceDataCloud**: el que ya tenés (platform.acedata.cloud).
5. **API key de Anthropic**: en console.anthropic.com, crea una API key
   (distinta a tu cuenta de Claude.ai/Cowork - es de pago por uso).
6. **Cuenta de Render**: render.com, conecta tu repo de GitHub con este código.

## Pasos para desplegar

1. Sube esta carpeta a un repositorio de GitHub.
2. En Render: New -> Blueprint -> selecciona el repo (usa el `render.yaml`
   incluido).
3. Render te va a pedir que completes a mano estas variables:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_WEBHOOK_SECRET` (invéntate cualquier string largo y random)
   - `ADMIN_CHAT_ID`
   - `DLOCAL_API_KEY` y `DLOCAL_SECRET_KEY` (empieza con las de sandbox)
   - `ACEDATACLOUD_API_TOKEN`
   - `ANTHROPIC_API_KEY`
   - `BASE_URL` (la URL pública que Render te asigna, ej.
     `https://cancion-bot.onrender.com` - la sabrás después del primer
     deploy, así que puede que necesites desplegar una vez, copiar la URL,
     pegarla en esta variable, y volver a desplegar)
4. `DLOCAL_ENV` viene en `sandbox` por defecto - así podés probar todo el
   flujo con tarjetas de prueba antes de arriesgar dinero real. Cuando estés
   conforme, cambiás `DLOCAL_ENV` a `live` y reemplazás las API keys por las
   de tu cuenta live.
5. Al arrancar, el servicio registra el webhook de Telegram automáticamente.
6. Prueba mandándole `/start` a tu bot en Telegram.

## Cómo funciona el día a día

1. Un cliente le escribe a tu bot, responde las preguntas del pedido.
2. El bot crea un cobro específico para ese pedido en dLocal Go y le manda
   el link de pago (197 MXN).
3. El cliente paga. dLocal Go llama automáticamente a tu servidor
   (`/dlocal/webhook`) avisando que hubo un cambio de estado.
4. Tu servidor verifica la firma del aviso, confirma con dLocal Go que el
   estado es `PAID`, y dispara todo lo demás solo: Claude redacta la letra,
   Suno genera la canción, y se entrega por Telegram en cuanto está lista
   (se revisa el estado cada 20 segundos).
5. Vos solo recibís notificaciones de "pedido nuevo" - no necesitás tocar
   nada, salvo que algo falle.

### Respaldo manual

Si por algún motivo el webhook de dLocal Go no llega (problema de red,
timeout, etc.), podés confirmar el pago a mano: entrás a tu dashboard de
dLocal Go, verificás que el pago esté `PAID`, y le escribís a tu propio bot:
`/confirmar <chat_id>` (el chat_id te lo dio el bot cuando avisó del pedido
nuevo). Desde ahí sigue todo automático igual.

## Cosas importantes que revisar antes de cobrar dinero real

- **Probá primero en sandbox**: con `DLOCAL_ENV=sandbox` podés usar las
  tarjetas de prueba de la documentación de dLocal Go para validar el flujo
  completo (webhook, firma, generación de canción, entrega) sin arriesgar
  dinero real ni el tuyo ni el de un cliente.
- **Verificación de firma**: el webhook viene firmado con HMAC-SHA256
  (`app/dlocal_client.py:verify_signature`). No lo desactives - sin eso,
  cualquiera podría simular un aviso de "pago exitoso" falso.
- **AceDataCloud**: es un proveedor no oficial (revende acceso a Suno). Hay
  riesgo de que cambie su API o deje de funcionar sin aviso.
- **Plan de Render**: usa el plan Starter (de pago) definido en `render.yaml`,
  no el free tier - el free tier se "duerme" y los webhooks se pueden perder
  o llegar tarde.
- **Precio vs costos**: cada generación de Suno cuesta centavos de dólar, la
  API de Claude cuesta centavos por pedido, dLocal Go cobra su comisión por
  transacción, y Render son $7 USD/mes fijos.
- Este es un piloto para validar el modelo, no un sistema a prueba de fallos.
  Revisa los logs de Render seguido las primeras semanas.
