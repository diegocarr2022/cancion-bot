# Canciones vendidas en Etsy: qué se hizo, por qué y cómo operarlo

> **Para quién es:** el siguiente chat de Claude Code (o persona) que continúe en este proyecto. Escrito el **2026-10-03/04**,
> al cerrar la integración. Todo lo descrito como "desplegado" **está en producción y verificado** (incluida una compra real de
> Diego en Etsy desde otra cuenta: el pedido se identificó y el flujo funcionó de punta a punta).
>
> **Cómo usarlo:** lee el §0 y el §1 (5 minutos) para entender qué es esto y por qué. El resto es referencia: busca por sección.
> Si algo de aquí contradice lo que Diego te pida hoy, hazle caso a Diego, pero **pregunta antes de deshacer una decisión de este
> documento** (casi todas tienen un motivo y a veces un incidente detrás; ver §17).

## Índice

0. Resumen en una página
1. Contexto de negocio y decisiones (con alternativas descartadas)
2. Mapa de sistemas: qué vive dónde, accesos y cuidados
3. Productos, precios, créditos e IDs
4. El flujo completo, paso a paso
5. Referencia de endpoints (cancion-bot, Worker, servicio de medios)
6. Datos: columnas de `web_orders` y claves de KV
7. Código: guía archivo por archivo
8. Seguridad y antiabuso
9. Reglas de Etsy y de contenido (qué se puede y no prometer)
10. Solo inglés: prompt + guardia
11. PDF de la letra en vinil
12. "Misma letra, otro estilo" (variaciones)
13. La tienda de Etsy: listings, fotos, video, secciones, FAQs, políticas, anuncios
14. Runbooks (cómo hacer cada tarea de operación)
15. Pruebas
16. Troubleshooting: mensaje → causa → arreglo
17. Historia, incidentes y lecciones
18. Pendientes y mejoras propuestas
19. Cómo trabaja Diego (preferencias)

---

## 0. Resumen en una página

- **Qué:** las canciones personalizadas de tunecraft.studio (este repo, FastAPI en Render) ahora se venden también en Etsy
  (tienda **VibeCraftDigitalShop**, precios en MXN). Dos listings: **1 canción (MX$299)** y **pack de 3 (MX$599)**.
- **Cómo funciona para el comprador:** compra en Etsy → Etsy le entrega un **PDF** con un link a `https://tunecraft.studio/etsy` →
  mete su **número de pedido de Etsy** → chatea ~3 min con el bot → aprueba la letra → en ~2 min tiene la canción (**2 tomas**) y un
  **PDF de la letra en vinil** → si compró el pack, puede pedir **la misma letra en otro estilo**.
- **Diferencia clave con el flujo normal:** el pago ya ocurrió en Etsy. Donde el flujo normal **cobra (al aprobar la letra)**, el de
  Etsy **gasta un crédito** y arranca Suno. No hay Stripe, ni preview gratis, ni precios visibles en `/etsy`.
- **Tres sistemas:** (1) este repo en Render, (2) un **Cloudflare Worker** que valida el pedido contra la API de Etsy y lleva los
  créditos (carpeta aparte: `/Users/minds/Photo_Stocker/etsy_delivery/worker/`), (3) el **droplet de medios** (ya existía) al que se le
  agregó la generación del PDF en vinil con Chromium.
- **Solo en inglés** (el listing lo promete): prompt sin excepción + guardia determinista que rechaza letras en español (aplica a
  todo el sitio EN, no solo Etsy).
- **Estado de las variables de Render:** `ETSY_WORKER_URL`, `ETSY_REDEEM_KEY`, `ETSY_SONG_PRODUCT` puestas; `ETSY_TEST_ORDERS`
  **vacía** (se quitó el 2026-10-04 porque era una puerta trasera de canciones gratis).
- **Publicidad:** Etsy Ads activo a **US$1/día solo para el pack** (MX$599). Revisar a los 5-7 días.
- **Hecho (2026-10-04, commit 9636a65):** el chat ya va en pasos cortos de 1-2 preguntas relacionadas (ver §18.1). Probado en producción de punta a punta hasta la letra.
- **Pruebas:** `bash tests/etsy/run_all.sh` (7 archivos, ~110 verificaciones, todas locales). Pasaban todas al cierre.

---

## 1. Contexto de negocio y decisiones

### 1.1 Quién es Diego y qué quiere
Diego Carranza, ingeniero de software, opera **solo** varios negocios automatizados. En Etsy tiene "VibeCraftDigitalShop" (wall art
digital imprimible hecho con IA en estilos de arcilla, fieltro, crochet, origami; hasta 40×60 in) y quiso sumar su servicio de canciones
personalizadas. Prefiere **soluciones pragmáticas y honestas**: rechazó textos de marketing que describían cosas que no existen (§9).

### 1.2 Por qué la canción se vende como "PDF con un link" y no como un formulario de Etsy
El valor del producto es el **chat que pregunta lo que falta** para que la letra salga buena (un formulario de Etsy no puede repreguntar:
la calidad bajaría, o habría que pedirle al cliente que "amplíe" la información, y eso toma tiempo). Además, la competencia en Etsy
entrega en **24 a 72 horas**; esto en **~5 minutos** (3 de chat + 2 de generación), con la letra aprobada antes de producir.
Por eso el listing es un **artículo digital instantáneo** cuyo archivo es un PDF con el link `/etsy`.

### 1.3 Decisiones tomadas y alternativas descartadas

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| Validar el pedido con un **Worker de Cloudflare** que habla con la API de Etsy (`/api/redeem`) | Que tunecraft hable directo con Etsy | El Worker ya existía para entregar el wall art (valida número de pedido → link de descarga) y **ya tiene las credenciales y el OAuth**; centralizar evita duplicar secretos. Este repo solo conoce una llave compartida |
| `/etsy` = la landing EN **renderizada en modo Etsy en el servidor**, sustituyendo todo lo que habla de dinero | Duplicar la landing; o esconder precios con CSS/JS | Duplicar = 2000+ líneas a mantener doble. Esconder con CSS es frágil (un descuido muestra un precio, y Etsy **prohíbe ofrecer comprar fuera de su plataforma**). Así el precio nunca llega al navegador y se hereda marca, demos y chat |
| Falla **cerrado**: si la plantilla cambia o se cuela una palabra de dinero, `/etsy` responde 503 | Mostrar la página igual | Un precio visible en `/etsy` es una violación de políticas |
| Gastar el crédito **al aprobar la letra** | Al validar el número de pedido | El cliente puede chatear, cerrar y volver sin perder su canción; el crédito solo se gasta cuando se compromete la generación |
| En variaciones: **Suno primero, crédito después** | Crédito primero (como en la canción nueva) | Si Suno falla, el cliente no pierde un crédito. En la canción nueva el orden es el contrario porque `consume` es idempotente por sesión y el reintento es en la **misma** sesión |
| PDF en vinil generado en el **droplet** | Generarlo en Render | Chromium no cabe/funciona bien en Render Starter (512 MB, sin librerías del sistema). El droplet ya hacía preview/video y tiene 4 GB |
| Respaldo al PDF sencillo si el servicio de medios falla | Fallar con error | Nadie se queda sin PDF |
| Prompt de Etsy **derivado** de la plantilla EN (reemplazos que fallan fuerte si la plantilla cambia) | Un prompt propio copiado | Copia = diverge. Derivado + falla fuerte = si alguien edita el prompt EN, se entera |
| Precios **299 / 599 sin descuento ficticio** | "Precio original" tachado inflado | Etsy y las leyes de consumo exigen que el precio tachado sea real. Diego investigó y decidió 299/599 |
| Anunciar **solo el pack** en Etsy Ads | Anunciar todo | Con US$1/día el presupuesto no alcanza para 26 listings; el pack deja más ganancia neta por venta (~MX$500) para pagar clics |
| Sin reseñas propias | Reseñar desde otra cuenta | Es reseña falsa (política de Etsy + FTC). Diego estuvo de acuerdo |

---

## 2. Mapa de sistemas: qué vive dónde

```
 Comprador (Etsy)
    │ compra listing 4587652826 (1) o 4587653912 (3)
    ▼
 Etsy ──entrega──> PDF "your_song_instructions.pdf" (link clicable a tunecraft.studio/etsy)
    │
    ▼
 tunecraft.studio/etsy   ← Render, servicio "cancion-bot" (ESTE REPO)
    │  POST /etsy/check {order_number}            (validación)
    │  POST /web/session {etsy_order}              (crea la sesión)
    │  POST /web/chat                              (chat con Claude vía AceDataCloud)
    │  _finalizar_letra_etsy → consume crédito → Suno (AceDataCloud) → 2 tomas
    │  /web/lyrics-pdf/{id}?size=…  → PDF vinil
    │  POST /web/variation                         (misma letra, otro estilo)
    ├──────────► Worker Cloudflare "photo-stocker-etsy-delivery"
    │             POST /api/redeem (header x-redeem-key)  ── OAuth ──► API de Etsy v3 (receipts)
    │             KV PRODUCTS: "tunecraft-song" = mapa listing→créditos, "redeem:*" = sesiones que gastaron créditos
    └──────────► Droplet de medios (DigitalOcean) media.tunecraft.studio
                  POST /vinyl-pdf (Bearer MEDIA_API_TOKEN) → Chromium → 4 PDF
```

| Pieza | Dónde | Código fuente local | Despliegue |
|---|---|---|---|
| **cancion-bot** | Render, servicio `srv-d9mdqnm417fc73b7dj00` (workspace `tea-d9l6qvijnfac73abofb0`), URL `https://cancion-bot.onrender.com` = `tunecraft.studio`; autodeploy de `main` | este repo (`/Users/minds/Documents/Canciones personalizadas/cancion-bot`), GitHub `diegocarr2022/cancion-bot` | `git push origin main` |
| **Worker de Etsy** | Cloudflare, `https://photo-stocker-etsy-delivery.craft-studio.workers.dev`; R2 `photo-stocker-etsy`; KV `PRODUCTS` y `RATE` | `/Users/minds/Photo_Stocker/etsy_delivery/worker/index.js` (+ `i18n.js`, `wrangler.toml`) | `cd` ahí y `npx wrangler deploy` (Node 22: `PATH=/opt/homebrew/opt/node@22/bin:$PATH`) |
| **Servicio de medios** | Droplet DigitalOcean `167.172.221.235` (Ubuntu 22.04, 2 vCPU/4 GB), systemd `tunecraft-media`, `/opt/tunecraft-media`, nginx → `media.tunecraft.studio` (puerto 8901, detrás de Cloudflare) | `/Users/minds/Documents/Canciones personalizadas/tunecraft-media-services/service/` (idéntico al del droplet) | `scp` + `systemctl restart tunecraft-media` |
| **Contenido de Etsy** (fotos, video, textos, scripts) | Etsy | `/Users/minds/Photo_Stocker/etsy_delivery/songs/` y `.../scripts/` | scripts que hablan con el Worker |

**Accesos:**
- Render: conexión MCP de Render (workspace único "My Workspace"). Variables de entorno editables con `update_environment_variables`
  (modo fusionar; para "borrar" una variable se pone valor vacío).
- Droplet: `ssh -i ~/.ssh/advisor2 root@167.172.221.235` (llave que Diego ya tiene; **el droplet también aloja otros proyectos de
  Diego** (My Voice en `/opt/myvoice`, un app.advisor.com.mx apagado con contenedores docker detenidos): **no toques nada fuera de
  `/opt/tunecraft-media`**).
- Etsy: sesión de Chrome de Diego (extensión "Claude in Chrome"); la API de Etsy v3 solo a través del Worker.
- Cloudflare: `wrangler` ya autenticado en la máquina de Diego.

**Cuidados con secretos (importante):**
- Hay secretos vivos en `tunecraft-media-services/deploy/server.env` (tokens del servicio de medios y de AceDataCloud): **no lo imprimas**.
- `etsy_delivery/secrets/` guarda `admin_token.txt` (protege los endpoints admin del Worker), `redeem_key.txt` (la llave de `/api/redeem`) y
  `etsy_refresh_token.json`. **Nunca los pegues en el chat ni en commits.** El sistema de seguridad de Claude Code **bloquea** leer
  esos archivos para pasarlos a otro sitio; si hay que ponerlos en Render, Diego los copia con `pbcopy < archivo` y los pega él.

---

## 3. Productos, precios, créditos e IDs

| | Listing 1 canción | Listing pack de 3 |
|---|---|---|
| ID de Etsy | `4587652826` | `4587653912` |
| Precio (MXN) | **299** | **599** |
| Precio visto por compradores de México | MX$346.84 (Etsy suma 16 % de IVA al comprador mexicano) | MX$694.84 |
| Créditos | **1** | **3** |
| Categoría Etsy | Digital Music (digital) | ídem |
| Sección de la tienda | Personalized Song Gifts | ídem |
| Etsy Ads | no | **sí (US$1/día)** |

- **Un crédito = una canción**: una canción nueva (chat nuevo) **o** la misma letra en otro estilo (§12). Cada una entrega **2 tomas**.
- Mapa de créditos (Worker, KV `PRODUCTS`, clave `tunecraft-song`):
  `{"name":"Personalized Song","credits":{"4587652826":1,"4587653912":3}}`. Créditos de un pedido =
  Σ (`quantity` de cada transacción × `credits[listing_id]`). **Un listing nuevo de canciones hay que agregarlo ahí.**
- Otros IDs relevantes de la tienda: sample XL de calidad `4586917731` (MX$4); wall art: ver sección 13.5.
- Precio de lista del sitio normal (tunecraft.studio) es otro (USD, ver `config.py`); **Etsy se vende más barato a propósito** (es un
  canal de descubrimiento, con comisiones de Etsy).

---

## 4. El flujo completo, paso a paso

**A. Compra.** El cliente compra en Etsy. Etsy le muestra la descarga digital: el PDF `your_song_instructions.pdf` (hay uno para
la canción y otro para el pack; el del pack aclara "3 canciones, cada una puede ser nueva o la misma letra en otro estilo").

**B. Entrada.** El PDF tiene el link clicable `https://tunecraft.studio/etsy`. La página muestra "Enter your Etsy order number".
(Si abre `/etsy?session_id=...` salta la puerta y retoma esa sesión.)

**C. Validación** (`POST /etsy/check`): el navegador manda solo dígitos. El servidor llama `etsy_client.check()` → Worker
`POST /api/redeem {action:"check"}` → el Worker pide el *receipt* a Etsy y verifica: existe, `is_paid != false`, y alguna transacción
es de un listing del mapa de créditos. Responde `{ok, credits, used, remaining}`. En `/etsy/check`:
- `remaining > 0` → `{ok:true, remaining}` y el navegador crea una sesión nueva;
- `remaining == 0` y existe una sesión pagada de ese pedido → `{ok:true, resume_session_id}` (redirige a su última canción);
- si no → error (mensajes en §16).

**D. Sesión** (`POST /web/session {etsy_order}`): el servidor **revalida** (no confía en el navegador) y crea el pedido web con
`gateway="etsy"`, `source="etsy"`, `language="en"`, `country="US"`, `landing_flow=None` (flujo v1: **2 tomas**, sin video upsell).

**E. Chat** (`POST /web/chat`): igual que el flujo EN, pero con el prompt de Etsy (§10) y solo la herramienta `finalizar_letra`
(no `find_previous_order`, que podría regenerar un link de pago de Stripe). Pide: para quién, ocasión, estilo, voz, anécdotas,
nombre/apodo para firmar y correo.

**F. Aprobación** (`finalizar_letra` → `_finalizar_letra_etsy` en `web_conversation.py`):
1. Guardia de idioma (§10): letra en español → se rechaza y el bot la reescribe.
2. Se guarda título/estilo/letra/voz, correo, nombre, `final_recipient`, `final_from`.
3. **`consume`** el crédito (idempotente por `session_id`). Si ya no hay → mensaje al bot para explicarlo con amabilidad.
4. `generate_custom_song` (Suno vía AceDataCloud) → `task_id`; `paid=1`, `step="generando"`.
5. La respuesta incluye `etsy_generando=true` → el navegador oculta el chat y muestra "Recording the full song…".

**G. Entrega.** `poll_web_suno_tasks_loop` (cada `POLL_INTERVAL_SECONDS`, 60 s en render.yaml) consulta Suno; el flujo v1 espera
**ambas tomas**; marca `delivered=1`, `step="entregado"`, guarda `audio_urls` y manda el correo (Mailgun) con links de descarga y el
link del PDF de letra. La pantalla muestra las 2 tomas, botones de compartir, "Download printable lyrics (PDF)" y otros tamaños.
Los correos de **recuperación de carrito** y de **reseña de Trustpilot** excluyen `gateway='etsy'`.

**H. PDF de letra** (`GET /web/lyrics-pdf/{session}?size=8x10`): vinil vía droplet con caché; respaldo al PDF sencillo (§11).

**I. Otra versión** (solo si quedan créditos): bloque "Create another version" → `POST /web/variation` (§12).

**J. Volver más tarde.** Mismo número de pedido en `/etsy`: si quedan créditos abre sesión nueva; si no, lo lleva a su última canción.

---

## 5. Referencia de endpoints

### 5.1 cancion-bot (este repo, `app/main.py`)

| Ruta | Qué hace | Notas |
|---|---|---|
| `GET /etsy` | HTML de la landing en modo Etsy | 503 si `_etsy_disponible()` es falso; `X-Robots-Tag: noindex, nofollow` |
| `POST /etsy/check` `{order_number}` | Valida el pedido (ver §4.C) | Respuestas siempre JSON, `Cache-Control: no-store`. Rate limit en memoria 12/10 min/IP (429) |
| `GET /etsy/credits?session_id=` | ¿Se puede ofrecer "otra versión" y cuántos créditos quedan? | `{eligible, remaining, styles:[{key,label}]}`; elegible solo si la sesión es de Etsy, ya entregada y quedan créditos |
| `POST /web/variation` `{session_id, style_key | style_text, gender?}` | Crea una versión nueva con la misma letra | §12. 403 si el padre no está listo; 409 si no quedan créditos; 502 si Suno falla; 429 por rate limit |
| `POST /web/session` | Crea sesión; acepta `etsy_order` | Con `etsy_order` revalida con el Worker; 403/503 si no pasa |
| `POST /web/chat`, `GET /web/status` | Chat y estado (compartidos con el flujo normal) | `/web/chat` devuelve `etsy_generando` en sesiones de Etsy |
| `GET /web/lyrics-pdf/{session}?size=` | PDF de la letra | `size` ∈ `8x10, 11x14, A4, 12x12`; otro valor → 8x10 |
| `GET /terms`, `/privacy`, `/terminos`, `/privacidad` | Páginas legales | Actualizadas (§9.3) |

Mensajes que ve el comprador (`_ETSY_ERRORS` en `main.py`): `not_found`, `not_paid`, `wrong_product`, `no_credits_left`, `unknown_product`,
`unavailable`/`etsy_error` (ver §16).

### 5.2 Worker de Cloudflare (`etsy_delivery/worker/index.js`)

Autenticación: `x-redeem-key` (solo `/api/redeem`) o `x-admin-token` (endpoints `/api/admin/*`). Ningún endpoint **devuelve** tokens ni
credenciales. (Un endpoint que devolvía el token de Etsy fue **bloqueado por el sistema de seguridad** y no se desplegó; no vuelvas a
intentarlo: se usan proxies de acciones concretas.)

| Endpoint | Para qué |
|---|---|
| `GET /`, `POST /api/validate`, `GET /dl` | Flujo del **wall art**: número de pedido → link de descarga firmado de R2 (48 h) |
| `POST /api/redeem` `{action:"check"|"consume", order_number, session_id?, product}` | **El que usa este repo.** `check` valida y dice créditos; `consume` gasta uno (idempotente por `session_id`; 409 `no_credits_left` si no hay). Estado en KV `redeem:<product>:<order>` = `{sessions:[…]}` |
| `POST /api/admin/link`, `/extend`, `/upload-url` | Links de `/dl`, prórrogas de links viejos, URL prefirmada para subir zips a R2 |
| `POST /api/admin/etsy-video` (multipart `listing_id, name, video`) | Sube un video a un listing |
| `POST /api/admin/etsy-videos`, `/etsy-video-delete` | Lista / borra videos |
| `POST /api/admin/etsy-images`, `/etsy-image` (multipart `listing_id, image, rank`), `/etsy-image-delete` | Lista / sube / borra fotos |
| `POST /api/admin/etsy-sections` `{action:"list"|"create"|"listings"|"assign"}` | Secciones y asignación de listings (`create` **falla**: al token le falta el scope `shops_w`; las secciones se crearon a mano en la UI) |

La API de Etsy: app "vibecraftapp" (Personal Access, sin sandbox), header `x-api-key: keystring:sharedsecret`, scopes
`transactions_r listings_r listings_w listings_d`. El refresh token (90 días) **rota** en cada uso; el último vive en KV
(`etsy:refresh`) y gana sobre el secreto `ETSY_REFRESH_TOKEN`; el access token se cachea 3300 s (`etsy:access`).
Límites de tasa: `/api/validate` 20 intentos/h/IP (KV `RATE`, claves `rl:<ip>`).

### 5.3 Servicio de medios (droplet)

`POST /vinyl-pdf` (Bearer `MEDIA_API_TOKEN`) con `{title, lyrics, recipient?, sender?, dedication?, sizes?}` →
`{files:{ "8x10": url, "11x14": url, "A4": url, "12x12": url }, font_pt, warnings}`. Los PDF quedan en
`/opt/tunecraft-media/workdir/vinyl/<job>/lyrics-<size>.pdf` y se sirven públicos (UUID no adivinable) en
`https://media.tunecraft.studio/files/vinyl/<job>/…`. Entradas saneadas: quita emojis/CJK (las fuentes son subset latino), tope 6000
caracteres de letra, 120 de título. Sin token: 401.

---

## 6. Datos

### 6.1 Columnas nuevas de `web_orders` (migraciones `ALTER TABLE` en `db.py`)

| Columna | Qué guarda |
|---|---|
| `gateway` | `"etsy"` para pedidos de Etsy (ya existía para dlocal/stripe) |
| `etsy_order_number` | Número de pedido de Etsy con el que se canjeó |
| `final_recipient` | Para quién es la canción (etiqueta "A song for X") |
| `final_from` | Cómo quiere firmar (apodo / primer nombre) |
| `vinyl_pdfs` | Caché JSON `{"h": hash(título\|letra\|destinatario\|firma), "files": {tamaño: url}}` |
| `parent_session_id` | En una variación, la sesión de la que se copió la letra |

`source` vale `"etsy"` (o `"etsy-test"` para pedidos de prueba) → útil para excluir/ver estas sesiones en el panel de admin.
`db.find_etsy_session_for_order(n)` = sesión pagada más reciente de ese pedido. Las consultas de correos de recuperación y de reseña
llevan `AND COALESCE(gateway,'') != 'etsy'`.

### 6.2 Claves de KV del Worker

`PRODUCTS`: claves de producto del wall art (`<slug>` → `{name, listing_id, r2_key, tier}`), **`tunecraft-song`** (mapa de créditos),
`redeem:tunecraft-song:<pedido>` (sesiones que gastaron créditos), `etsy:access`, `etsy:refresh`, `ext:*` (prórrogas de links).
`RATE`: `rl:<ip>`.

---

## 7. Código: guía archivo por archivo (este repo)

| Archivo | Contenido clave |
|---|---|
| `app/etsy_client.py` | `check(order)`, `consume(order, session_id)`, `is_test_order()`. Nunca lanzan: devuelven `{"ok":False,"error":…}` (`unavailable` si el Worker no responde). Los pedidos de `ETSY_TEST_ORDERS` devuelven créditos ilimitados sin llamar al Worker |
| `app/landing_etsy.py` | `build_etsy_landing()` toma `LANDING_HTML_EN` y: quita JSON-LD, pixel de Meta, Google Ads, Stripe.js; reemplaza el bloque de precio por el campo de pedido; reescribe textos con "pay/price/launch…"; vacía las cajas de preview/pago (el JS las necesita presentes); quita el bloque de reseña de Trustpilot; inyecta el JS de la puerta del pedido, de "otra versión" (`ofrecerVariacion`) y el arranque. Al final verifica con `_FORBIDDEN_VISIBLE` el texto visible y los `<meta>`. Resultado en `ETSY_LANDING_HTML` (o `None` + `ETSY_LANDING_ERROR`) |
| `app/lang_guard.py` | `looks_spanish(texto)`: cuenta palabras funcionales exclusivamente españolas vs inglesas (ignora `[Verse 1]`); `es>=6 and es>en` → español |
| `app/claude_client.py` | `_ETSY_PROMPT_REPLACEMENTS` + `_build_etsy_web_prompt()` (lanza `ValueError` si la plantilla EN cambió) + `etsy_prompt_ok()`; `WEB_CONTENT_TOOLS_ETSY` (solo `finalizar_letra`); campos `recipient` y `from_name` en la herramienta EN; pregunta de firma en el prompt |
| `app/web_conversation.py` | `_finalizar_letra`: guardia de idioma, guarda recipient/from; rama `gateway=="etsy"` → `_finalizar_letra_etsy` (consume → Suno → paid). `handle_web_chat` usa prompt y herramientas de Etsy |
| `app/main.py` | `_etsy_disponible()`, `_etsy_rate_limited()`, `_ETSY_ERRORS`, rutas de §5.1, `ETSY_STYLE_PRESETS`, `_vinyl_pdf_bytes()` y `/web/lyrics-pdf`, arranque que loguea el estado de `/etsy` |
| `app/media_client.py` | `generar_vinyl_pdfs()`, `descargar_pdf()` |
| `app/db.py` | migraciones y `find_etsy_session_for_order` |
| `app/config.py` | `ETSY_WORKER_URL`, `ETSY_REDEEM_KEY`, `ETSY_SONG_PRODUCT`, `ETSY_TEST_ORDERS`, `ETSY_ENABLED` |
| `app/landing.py` | Solo se añadió en `mostrarDescarga` el enlace principal "Download printable lyrics (PDF)" + "Other print sizes" |
| `app/legal.py` | Aviso de privacidad EN/ES reescrito; términos EN con pagos Stripe + pedidos de Etsy |
| `tests/etsy/` | Pruebas (ver §15) |

`ETSY_ENABLED = (URL y KEY) o ETSY_TEST_ORDERS`. Sin eso `/etsy` da 503 y **el sitio normal no cambia**.

---

## 8. Seguridad y antiabuso

- **Número de pedido = credencial.** Quien lo conozca puede usar los créditos. Por eso: créditos de un solo uso por canción (idempotentes por
  sesión), rate limit en `/etsy/check` y `/web/variation`, y el aviso en el PDF "no compartas tu número de pedido".
- **Verificación en el servidor:** `/web/session` revalida el pedido aunque el navegador ya lo haya validado.
- **La llave `ETSY_REDEEM_KEY`** solo viaja de Render al Worker (HTTPS, header). El Worker nunca devuelve tokens de Etsy.
- **Pedido de prueba (`ETSY_TEST_ORDERS=720514`)** existió para probar sin comprar; da créditos ilimitados gratis. **Quitado** de Render;
  si hay que volver a probar, ponerlo temporalmente y volver a quitarlo. Las sesiones de prueba se marcan `source="etsy-test"`.
- Sin pixel/Stripe/Google en `/etsy`; sin precios. `/etsy` es `noindex`.
- Los PDF del droplet son públicos por URL con UUID (no listados); no contienen datos personales aparte de la letra y los nombres.

---

## 9. Reglas de Etsy y de contenido

### 9.1 Qué no se puede poner en fotos, video ni descripciones
- **Ninguna URL ni nombre de sitio externo** (Etsy prohíbe sacar al comprador de su plataforma). El link `tunecraft.studio/etsy` va **solo en
  el PDF de entrega** (llega después de pagar). La marca "Tunecraft" tampoco sale en las fotos/video/descripción del listing.
  (El video original del anuncio terminaba con una tarjeta con la URL: se recortó.)
- **Declarar la IA:** "How it's made → With an AI generator" en los dos listings, y el texto lo dice.
- **No prometer lo que no hay:** nada de "RAW", "TIFF", "170 MP", "óleo/impasto", "radio-ready", "the fastest on Etsy", "flawless". Diego
  rechazó un texto de "laboratorio" que mezclaba ideas futuras con lo actual. **TIFF "Museum Edition" y wall art a pedido son ideas futuras**
  de Diego (aparcadas); no se anuncian hasta que existan.
- **Solo inglés**, dicho en portada, descripción, FAQ y PDF.
- **Reseñas:** solo de compradores reales. El vendedor no puede reseñar su tienda desde otra cuenta; tampoco ofrecer incentivos.

### 9.2 Portadas (aprendido por prueba y error)
Etsy recorta las miniaturas (búsqueda, tienda, móvil) **desde el centro** a cuadrado, vertical (4:5) y horizontal (4:3). Una portada con
contenido a los lados se corta (le pasó a la primera de canciones). La actual es **cuadrada 3000×3000** con una **zona segura de 2400×2250
centrada**; el fondo y la decoración (ondas de audio) llenan el resto. Debe decir literalmente "personalized" (si no, nadie entiende que es
una canción personalizada). Se puede comprobar con "Adjust thumbnails" en el editor de Etsy (muestra Square, Portrait, Landscape).

### 9.3 Legal
- Privacidad EN/ES reescrita (Stripe/dLocal en lugar de PayPal, número de pedido de Etsy, Meta Pixel y Google disclosed y **no** usados
  en `/etsy`, correos de seguimiento, proveedores, tratamiento en otros países, GDPR/CCPA/ARCO). El propio archivo dice que **no es asesoría
  legal**: conviene revisión de un abogado antes de escalar (LFPDPPP/GDPR).
- En la tienda de Etsy: política de privacidad propia publicada; cancelaciones "no se aceptan"; devoluciones: la política preestablecida
  de Etsy para digitales ("no returns or exchanges, contact the seller") aplica a los 26 listings.

---

## 10. Solo inglés: prompt + guardia

**Problema real:** un latino en EE.UU. ponía un nombre en español (o pedía un estilo latino) y el modelo escribía la letra en español. Diego no
puede vender así en EE.UU. Pasaba "a veces", por lo que **un prompt no basta**.

1. **Prompt de Etsy sin excepción.** La plantilla EN normal dice "siempre inglés… a menos que el cliente pida explícitamente español". En
   la variante de Etsy ese "a menos que" se reemplaza por "solo inglés, sin excepciones: si pide otro idioma, explícale con amabilidad y
   ofrece escribirla en inglés". Los nombres propios/apodos en español se conservan dentro de la letra en inglés.
2. **Guardia determinista** `lang_guard.looks_spanish(letra)` en `_finalizar_letra` para **todas** las sesiones `language=="en"`
   (sitio de EE.UU. **y** Etsy): si la letra está en español **no se guarda, no se gasta crédito, no se llama a Suno**; el bot recibe la orden
   de reescribirla en inglés y pedir aprobación otra vez. Heurística de palabras funcionales (sin dependencias ni llamadas extra). Las letras en
   inglés con "mi amor", "Nena", "Dale, mami" pasan; una letra mayormente en español se rechaza.
3. **Límites conocidos:** solo revisa la letra (no el texto del chat); no es perfecta con letras muy cortas.
4. Las sesiones en español (Telegram y landing ES) **no** se tocaron.

---

## 11. PDF de la letra en vinil

Diego aportó `vibecraft-vinyl-pdf.zip` (módulo `vinyl_pdf.py` + README = especificación). Dibuja la letra en espiral sobre un vinil crema con
etiqueta terracota (título, dedicatoria, firma manuscrita, "A SONG FOR X"), título y "A song for X · with love, Y" debajo; PDF vectorial de una
página, fuentes incrustadas, 4 tamaños (8×10, 11×14, A4, 12×12). **No se rediseña** sin que Diego lo pida (colores, fuentes, proporciones).

- **Dónde corre:** en el droplet de medios (`service/vinyl.py`, `service/vinyl_pdf.py`, `service/fonts/`). Playwright 1.63 + Chromium
  instalados en el venv del servicio. Un solo hilo con un Chromium compartido (`--no-sandbox`, se relanza y reintenta una vez si muere).
  ~3.4 s los 4 tamaños en frío, ~0.4 s después. Respaldo previo del servicio: `/opt/tunecraft-media/service.bak-2026-10-03`.
- **Aquí:** `/web/lyrics-pdf/{id}?size=` genera los 4 tamaños de una vez, guarda las URLs en `web_orders.vinyl_pdfs` (caché por hash de título,
  letra, destinatario y firma → cambia la letra, se regenera), descarga el PDF pedido y lo sirve inline con nombre `<titulo>-lyrics-<size>.pdf`.
  **Cualquier fallo → PDF sencillo de `pdf_client.py`.**
- **Datos:** título, letra, `final_recipient`, firma = `final_from` o **primer nombre** de `customer_name` (mucha gente da su nombre completo pero
  prefiere un apodo en una dedicatoria). Sin dedicatoria, la etiqueta queda solo con el título. Para el listing de Etsy se usó este mismo
  diseño como foto del producto (`etsy_delivery/songs/assets/vinyl_sample_8x10.png`, hecho con `make_vinyl_sample.py`).
- **Verificado en producción:** una canción real con "Carlos Eduardo Ramirez Soto, dime Lolo, para Ana" salió firmada **"A SONG FOR ANA · WITH LOVE, LOLO"**.

---

## 12. "Misma letra, otro estilo" (variaciones)

Motivo: Diego preguntó "¿y si un cliente quiere la misma letra en 3 estilos?"; con el pack de 3 solo había 3 chats independientes (la letra
se reescribe distinta cada vez). Ahora el crédito puede usarse para esto.

- **UI** (solo `/etsy`, en la pantalla de entrega): si `GET /etsy/credits` dice `eligible`, aparece "Want these same lyrics in another style? Your order
  still includes N more songs…", una lista de estilos y "Create another version". Tras el clic redirige a `/etsy?session_id=<hija>`.
- **Estilos** (`ETSY_STYLE_PRESETS`): Pop, Acoustic ballad, Country, Pop/Rock, Hip-Hop/R&B, Latin (**cantada en inglés**), Big Band; o `style_text`
  libre (≤160 caracteres, sin caracteres de control). Cada preset es una descripción musical para Suno.
- **Lógica** (`POST /web/variation`): padre debe ser Etsy, entregado y con letra; `check` créditos; crea sesión hija (`parent_session_id`) copiando título,
  letra, correo, nombre, destinatario, firma y voz; **Suno primero y `consume` después**; `paid=1/step="generando"`; entrega con el poll habitual (2 tomas).
  Dedupe 60 s por (padre, estilo) para doble clic. Si el crédito se agota justo entre el `check` y el `consume` (carrera), la hija queda sin pagar y nunca se
  entrega (cuesta centavos de Suno).
- **Verificado en producción** con el pedido de prueba: variación "acoustic" → entregó 2 tomas con el mismo título.

---

## 13. La tienda de Etsy

### 13.1 Listings de canciones (fuente de verdad del texto: `etsy_delivery/songs/texts.py`)
- **1 canción:** título "Custom Song in 5 Minutes | Personalized Last-Minute Gift | Your Story Turned Into a Song (English Only)"; 13 tags
  (personalized song, custom song gift, song from your story, custom lyrics, birthday song, anniversary gift, love song gift, last minute gift,
  instant song gift, wedding song gift, gift for her, gift for him, mp3 song gift); cantidad 999.
- **Pack:** "3 Custom Songs in Minutes | Personalized Song Pack | Last-Minute Gift Set (English Only)"; mismos tags salvo `3 song pack`
  y `song bundle`; descripción añade la opción de otro estilo.
- **Fotos (10):** portada cuadrada (la del pack con **tres discos**), cómo funciona, chat, aprobar letra, resultado (vinil enmarcado en una sala), vinil
  como póster imprimible, 6 sonidos, qué incluye, ocasiones, "100 % English". Generadas por código con la identidad de marca de Tunecraft (tinta
  `#16110d`, papel `#efe4cc`, ámbar `#e8a23a`, Fraunces Black): `etsy_delivery/songs/build_song_listing.py` → `songs/out/`.
- **Video (13 s, cuadrado, con la canción real de muestra de fondo):** pensado para entenderse **sin sonido** (portada → paso 1 chat → paso 2 aprobar letra → paso 3
  disco), con franja de ondas ámbar que reaccionan al audio: `songs/build_song_video.py`. (Un primer video era la pareja del anuncio; Diego notó que
  "puede ser de cualquier cosa" sin audio, así que se rehízo.)
- **PDF de entrega:** `your_song_instructions.pdf` (y `…_pack3`) con link **clicable** (reportlab), pasos, términos de uso y "solo inglés". Se sube como el
  archivo digital del listing.

### 13.2 Secciones, destacados y contenido de la tienda
- **Secciones (6):** Christmas Nursery Trios (12), Halloween Nursery Trios (3), Capybara Wall Art (8), Autumn & Woodland (0, para trios que faltan),
  Try the Quality (1), Personalized Song Gifts (2). Las creó Diego/yo **a mano en la UI** porque el token no tiene `shops_w`; la asignación se hace por API
  (`scripts/organize_sections.py [--apply]`, por reglas de título/ID).
- **Destacados (4):** canción de 1, trío clay de Navidad (reindeer/polar bear/cabin), sample XL, set de 3 capibaras.
- **Tagline:** "XL printable wall art & custom songs, instant delivery". **Anuncio** y **About** (honesto: ingeniero, hecho con IA, 300 DPI JPG, solo inglés para
  canciones; sin TIFF/RAW/170 MP). **10 FAQs** ("Wall art: …" / "Songs: …"; Etsy limita a 10 y respuestas de 750 caracteres; la de "otro estilo" se integró en
  "Songs: Can I change the lyrics?"). **Mensaje a compradores digitales** corto y neutro (es global para todos los digitales).

### 13.3 Etsy Ads
Activo desde 2026-10-03/04 a **US$1/día** (monto personalizado; el panel sugiere $5). Etsy enciende todos los listings por defecto: se apagaron los 26 y se
dejó **solo el pack**. Etsy recomienda no tocar ≥30 días; revisar clics/CPC/pedidos a los 5-7 días. **Regla de equilibrio:** CPC máximo =
ganancia neta por venta (~MX$500 en el pack) × tasa de conversión (1 % → ~$0.26; 2 % → ~$0.52, según tipo de cambio ~19 MXN/USD y comisiones ~13-15 %).
No hay palabras clave que elegir: Etsy usa título, tags y categoría. Después de unos días se ven las búsquedas reales en las estadísticas. "Offsite Ads" no se tocó.
En la tabla de Etsy Ads el filtro por defecto "Advertised" **oculta** los listings sin anuncio: usar el filtro de Sección para encontrar uno.

### 13.4 Costos y precios (cifras que Diego dio / se calcularon)
Costo por canción (Claude + Suno) **< MX$2**. Comisión de Etsy ~13-15 % + US$0.20 por listing publicado/renovado. Precios: 299 / 599. Benchmark de la competencia
(barrido del 2026-10-03, ~45 listings por búsqueda, en MXN con IVA): mediana ≈ MX$430-490, percentil 25 ≈ MX$300; casi todos prometen "24 hour delivery"; casi
nadie promete minutos.

### 13.5 Tienda de wall art (contexto, otro proyecto)
24 listings de wall art (trios de Navidad en 4 estilos, 3 de Halloween clay, 8 de capibaras, sample XL) hechos con el pipeline de `Photo_Stocker` (generación, ampliación
con Real-ESRGAN, kits de fotos, video, zip a R2 y entrega por número de pedido con el mismo Worker). Los trios de **felt otoño** y **crochet** esperan
sus impresiones XL en la cola.

### 13.6 Scripts útiles (`/Users/minds/Photo_Stocker/etsy_delivery/`)
Todos se corren con `venv/bin/python` desde `/Users/minds/Photo_Stocker` y hablan con el Worker (que usa las credenciales de Etsy):
- `scripts/replace_images.py <listing_id> <carpeta>`: reemplaza todas las fotos (sube las nuevas y luego borra las viejas).
- `scripts/upload_video.py <listing_id> <mp4>`: sube un video (hay que borrar el viejo con `/api/admin/etsy-video-delete`).
- `scripts/organize_sections.py [--apply]`, `scripts/register_product.py`, `scripts/upload_zip.py`, `scripts/publish_package.py` (wall art).
- `songs/build_song_listing.py` (fotos y PDFs), `songs/build_song_video.py` (video), `songs/texts.py` (textos y tags).

---

## 14. Runbooks

**Agregar un listing nuevo de canciones** (p. ej. variantes por ocasión: cumpleaños, aniversario…)
1. Crear el listing en Etsy (Digital Music, digital, IA declarada, PDF de entrega con el link `/etsy`).
2. **Agregar su ID al KV `tunecraft-song` del Worker**: `cd /Users/minds/Photo_Stocker/etsy_delivery/worker && npx wrangler kv key get --binding PRODUCTS --remote tunecraft-song`,
   editar el JSON y `… kv key put --binding PRODUCTS --remote tunecraft-song '<json>'`. Sin esto, el comprador ve "doesn't include a personalized song".
3. Asignarlo a la sección y, si va con anuncio, encenderlo en Etsy Ads.

**Cambiar el precio o los créditos:** el precio es solo de Etsy (editor del listing). Los créditos por listing son del KV (paso 2 de arriba).

**Poner/quitar el pedido de prueba:** Render → servicio → variable `ETSY_TEST_ORDERS=<número>` (solo dígitos, varios con coma) / valor vacío para quitarla. Con ella,
`/etsy` funciona sin consultar a Etsy y con créditos ilimitados (cada canción cuesta Claude + Suno reales).

**Rotar la llave de `/api/redeem`:** generar una nueva (`openssl rand -base64 32 | tr -d '\n='`), `npx wrangler secret put REDEEM_KEY` en la carpeta del Worker y poner el mismo
valor en `ETSY_REDEEM_KEY` de Render. Diego la copia con `pbcopy` (Claude no puede leer el archivo de secretos para pegarlo).

**Cambiar fotos o video de un listing:** regenerar con los scripts de `songs/`, `replace_images.py` y `upload_video.py` (+ borrar el video viejo). Recordar la zona segura central (§9.2).

**Desplegar:**
- *cancion-bot:* `git push origin main` (Render redespliega en ~2-3 min; durante el despliegue `/etsy` puede dar 404/502 unos segundos).
- *Worker:* backup (`cp index.js index.js.bak-YYYY-MM-DD`), `node --check index.js`, `npx wrangler deploy`, y **probar `/`, `/dl`, `/api/redeem`, `/api/validate`** (el
  Worker sirve también el wall art; una vez un reemplazo mal hecho truncó el archivo y rompió `/dl`: §17).
- *Droplet:* backup (`cp -a service service.bak-FECHA`), `scp` de los archivos, `systemctl restart tunecraft-media` (arranca en ~10 s; **no reiniciar con un render de video en curso**:
  `jobs.sqlite3` muestra `processing`), y probar `/health` y el endpoint nuevo desde el propio droplet leyendo el token del `.env` **dentro** del comando (no imprimirlo).

**Rollback:** cancion-bot → `git revert` + push (o redeploy del commit anterior desde Render). Worker → `npx wrangler rollback <version-id>` (ver `wrangler deployments list`). Droplet → copiar de
`service.bak-2026-10-03`.

**Revisar la campaña:** Etsy → Marketing → Etsy Ads (clics, CPC, pedidos) y Stats → búsquedas. Aplicar la regla de equilibrio de §13.3.

---

## 15. Pruebas

`bash tests/etsy/run_all.sh` desde la raíz del repo (primera vez crea `/tmp/cb-test-venv` con `requirements.txt`). Son **100 % locales**: claves falsas, un Worker de Etsy
**simulado** en `localhost:9097-9099`, y Suno/Claude/Mailgun/medios simulados; no tocan producción ni gastan nada.

| Archivo | Qué cubre |
|---|---|
| `test_etsy.py` | `/etsy` sin dinero ni Stripe ni pixel, mensajes de error de `/etsy/check`, sesión, prompt/herramientas de Etsy, canje al aprobar (crédito, Suno, `paid`), reanudar sesión, **pack de 3** (créditos 3→0, reanuda al agotarse), rate limit, y la **guardia de idioma** en una sesión de Etsy |
| `test_variation.py` | `/etsy/credits` y `/web/variation`: orden Suno→crédito, dedupe de doble clic, fallo de Suno sin gastar crédito, agotado (409), pedido de 1 crédito, pedido de prueba ilimitado, sesión no-Etsy (403), estilo libre saneado |
| `test_vinyl.py` | PDF vinil con caché, regeneración al cambiar la letra, tamaños, **respaldo** cuando el servicio de medios cae, 404, `recipient`/`from_name` guardados, firma = primer nombre |
| `test_lang.py` | `looks_spanish` con letras reales (español, reggaetón, inglés con "mi amor", mezcla) |
| `test_lang_normal.py` | La guardia también protege el flujo EN normal (preview) y **no** toca el ES |
| `test_testorder.py` | Pedido de prueba: pasa sin Worker, ilimitado, reutilizable, otros números se rechazan |
| `test_regression.py` | Sin variables de Etsy: `/etsy` 503, el sitio normal (`/`, `/cancion`, legales, `/web/session`) idéntico |

**Prueba real en producción** (con el pedido de prueba, ya quitado): `POST /web/session` + `/web/chat` + `/web/status` + `/web/lyrics-pdf` + `/web/variation`; script de ejemplo en los
registros de trabajo (consulta Suno y cuesta centavos). Más la **compra real de Diego**: el pedido se identificó y todo funcionó. El **pack** no se probó con un pedido real de varios créditos
(la lógica está probada con simulación y es la misma que para 1).

---

## 16. Troubleshooting: mensaje → causa → arreglo

| Lo que ve el comprador / el síntoma | Causa probable | Qué hacer |
|---|---|---|
| "We couldn't find that order…" | Número mal copiado, o Etsy aún no sincroniza el pedido (espera 1 min), o el pedido es de otra tienda | Pedir el número exacto de *Purchases and reviews*; probar de nuevo |
| "That order isn't marked as paid yet…" | El receipt aún no está pagado en Etsy | Esperar |
| "That order doesn't include a personalized song…" | El pedido es de wall art, **o el listing no está en el mapa `tunecraft-song` del KV** | Si es un listing nuevo, agregarlo al KV (§14) |
| "This order's song has already been used…" | Créditos agotados y sin sesión pagada que reanudar | Revisar `web_orders` por `etsy_order_number`; es un error solo si el cliente no recibió canción |
| "We couldn't verify your order right now" | El Worker no responde, la llave `ETSY_REDEEM_KEY` no coincide (el Worker responde 401), Etsy API caída, o el refresh token expiró | Ver logs de Render (`[etsy]`, "No se pudo hablar con el Worker de Etsy"); probar `POST <worker>/api/redeem` con la llave; si el token de Etsy venció, repetir `etsy_oauth_setup.py` + `set_worker_secrets.py` (Diego, con login) |
| "Too many attempts…" (429) | Rate limit de 12 intentos/10 min/IP | Esperar; en memoria, un redeploy lo reinicia |
| `/etsy` responde 503 | Faltan `ETSY_*` en Render, o `ETSY_LANDING_ERROR` (la plantilla EN cambió / palabra de dinero), o `etsy_prompt_ok()` es falso | Ver el log de arranque `[etsy] /etsy NO disponible: landing=… prompt_ok=…`; arreglar la sustitución o los reemplazos del prompt |
| El bloque "Create another version" no aparece | No quedan créditos, la sesión no es de Etsy o no está entregada, o el navegador está haciendo cola con los audios de muestra | `GET /etsy/credits?session_id=…`; en producción detrás de Cloudflare no debería tardar |
| El PDF sale "sencillo" (no vinil) | El servicio de medios falló (se usa el respaldo) | Logs "PDF vinil no disponible"; en el droplet: `systemctl status tunecraft-media`, `journalctl -u tunecraft-media -n 50`, probar `/vinyl-pdf` local |
| El bot rechaza la letra con "ESPAÑOL" | Guardia de idioma (funciona como se diseñó) | El bot la reescribe; si hay falsos positivos, afinar `lang_guard` |
| Video/fotos no suben a Etsy desde el navegador | La subida de video por el editor es **inestable** del lado de Etsy | Usar `upload_video.py` (por API es fiable) |
| El anuncio no gasta ni muestra impresiones | Normal con US$1/día y un listing nuevo sin reseñas | Esperar 5-7 días; no tocar la campaña antes de 30 |

---

## 17. Historia, incidentes y lecciones

- **El Worker truncado (2026-10-02):** un reemplazo con script de Python truncó `index.js` y se desplegó; `/dl` dejó de funcionar. Se hizo `wrangler rollback`, se reconstruyeron las funciones
  y se redespleó probando todos los endpoints. **Lección:** hacer backup, `node --check` y probar los endpoints existentes **antes** de desplegar.
- **Endpoint que devolvía credenciales (bloqueado):** se intentó un `/api/admin/etsy-token` que entregara el access token y el Shared secret a un script local. El sistema de seguridad lo
  bloqueó (con razón). Alternativa adoptada: **proxies de acciones concretas** (subir video, fotos, secciones) que usan las credenciales dentro del Worker.
- **Lectura de la llave bloqueada:** al intentar leer `redeem_key.txt` para pegarla en Render, el sistema lo bloqueó; Diego la copió él con `pbcopy`. No eludir ese bloqueo.
- **`server.env` impreso por accidente:** al listar `tunecraft-media-services/deploy/` se mostraron tokens; no se usaron ni copiaron. Diego fue informado.
- **Portada con contenido lateral:** se vio cortada en la miniatura; se rehízo cuadrada y centrada (§9.2).
- **Prompt "bloque de preguntas":** al añadir la pregunta de firma y mantener la frase "puedes combinar preguntas", el bot preguntó casi todo en un solo mensaje; Diego quiere pasos cortos de 1-2 preguntas, como conversación (ver §18.1).
- **Mensaje de error del chat en español en la landing EN** (preexistente, sin tocar): "Tuve un problema procesando tu mensaje…".
- **Etsy publicó los listings sin diálogo de la tarifa de US$0.20** (no quedan créditos gratis); la tarifa se cobra igual.
- **Etsy FAQs:** límite de 10. Las secciones no se pueden crear por API sin `shops_w`.

---

## 18. Pendientes y mejoras propuestas

### 18.1 (RESUELTO 2026-10-04, commit 9636a65) Ritmo del chat: que se sienta como conversación
**Estado:** aplicado el punto 1 de la plantilla EN (aplica al sitio EN y a Etsy). Prueba real en producción (7 turnos): quién+ocasión → estilo → voz → anécdota → firma → correo → letra; sin bloques. Detalle: si el cliente no ha dado su nombre, el bot lo vuelve a pedir pegado a la siguiente pregunta (es el paso de nombre de la plantilla). Lo de abajo es el contexto original.

**Feedback de Diego (2026-10-04, con captura de pantalla del chat en vivo):** tras el nombre, el bot "me aventó todo lo que necesitaba escribir de un trancazo": quién/ocasión, estilo, voz, anécdotas, apodo
de firma y correo, todo en un solo mensaje. Antes de Etsy iba **por partes**: (1) para quién es y cuál es la ocasión, (2) qué estilo, (3) voz masculina o femenina, (4) un comentario sobre lo que dijo y luego
"ahora platícame una anécdota / lo que más te gusta de ella / una broma interna", **dejando espacio para escribir**, (5) más preguntas **solo si hacía falta**, (6) el correo al final para el respaldo. "Se sentía
menos requisito."

**Aclaración importante de Diego:** **no** significa "una sola pregunta por mensaje". El primer paso, por ejemplo, **son 2 preguntas** ("¿para quién es esta canción y cuál es la ocasión?"). Lo que busca es
**que se sienta más como una conversación**: pasos cortos, de 1 o 2 preguntas **relacionadas**, comentando lo que el cliente va diciendo, en lugar de un bloque largo de requisitos. Dijo **"por ahora déjala así,
vamos a aprobar con la publicidad"**: se arranca con anuncios primero y esto se corrige después.

**Causa probable:** el punto 1 de la plantilla EN (`_WEB_CONTENT_SYSTEM_PROMPT_TEMPLATE_EN`, "1. Ask naturally…") dice "You can combine questions and follow the natural rhythm, no need to ask one thing at a time",
y el párrafo que agregué sobre firma/destinatario sumó preguntas al mismo bloque.

**Propuesta** (reemplazar ese punto 1; aplica al sitio EN normal **y** a Etsy porque la variante de Etsy deriva de la misma plantilla; **no** tocar los fragmentos que usa `_ETSY_PROMPT_REPLACEMENTS`, y correr
`tests/etsy/run_all.sh`):
> Make it feel like a conversation, not a form: ask in SHORT STEPS of one or two closely related questions per message, never a long list. In order, skipping anything the customer already told you:
> a) who the song is for and what the occasion is (these two together); b) react warmly in one short sentence, then ask the musical style they'd love; c) male or female singer; d) with a short comment on what they've shared,
> invite a story, what they love most about that person, or an inside joke, and leave them room to write (if their answer is thin, ask 1-2 follow-ups, one at a time); e) how they'd like to sign the printable lyrics (first name or nickname);
> f) last, their email for the backup copy, with the short reassurance.
**Cuidado:** después de cambiarlo, probar una charla real de 3 a 6 turnos y verificar tono y ritmo (que no sea ni un bloque ni demasiado lento: cada mensaje extra es fricción).

### 18.2 Otros
1. **Revisar la campaña** a los 5-7 días (CPC real vs regla de equilibrio). Si funciona, considerar también anunciar el listing de 1 canción.
2. **Primera venta real del pack** = primera prueba con un pedido real de varios créditos: vigilar los logs `[etsy]` y que `remaining` cuente 3→2→1→0.
3. **Variantes por ocasión** (cumpleaños, aniversario, esposa/esposo, mamá, boda, San Valentín): listings extra con títulos/tags distintos que apuntan al mismo producto (más cobertura de búsqueda,
   costo marginal casi cero). Cada uno: agregar su ID al KV (§14).
4. **Trios de felt otoño y crochet** (listos para hacer kit cuando termine la cola XL; la sección "Autumn & Woodland" espera).
5. **Aviso de privacidad:** revisión legal antes de escalar publicidad.
6. **Idea futura de Diego (aparcada):** edición "Museum" con TIFF sin pérdida y wall art a pedido (estilos pincel/espátula son muy buscados en Etsy); recomendación: probar demanda con una edición "Museum" de arte existente (US$39-69)
   antes de construir el flujo a pedido. No prometer TIFF/RAW/170 MP hasta que exista.
7. **Mensaje de error en español** en la landing EN (ver §17).
8. Si Diego quiere crear secciones por API: reautorizar la app de Etsy con el scope `shops_w`.

---

## 19. Cómo trabaja Diego (para no frustrarlo)

- Español en la conversación; los textos para clientes y Etsy, en **inglés**. Honestidad ante todo: prefiere un "esto no se puede" claro a una promesa vaga.
- Le gusta ver **los entregables** (te pide "pásame la portada para verla"): mándale archivos y capturas antes de publicar cuando sea algo visual o público.
- Decide rápido y delega, pero **confirmó cada paso que gasta dinero o es público** (publicar, anuncios, cambios en producción): confirma antes de esas acciones salvo que ya lo haya aprobado.
- Valora que el chat se **sienta como conversación** (pasos cortos que comentan lo que dice el cliente), no como formulario ni como un bloque de requisitos.
- Detesta el desperdicio visual y el texto que no comunica ("no dice nada"): piensa siempre en cómo se ve en miniatura y sin sonido.
- No quiere reseñas falsas ni promesas que el sistema no cumple.
- Memoria del proyecto (en el entorno de Claude de Photo_Stocker): `~/.claude/projects/-Users-minds-Photo-Stocker/memory/project_etsy_tunecraft_songs.md` tiene el diario detallado de esta integración.

## 19. Panel de admin: identificación por número de pedido (2026-10-04)
Las sesiones que llegan por `/etsy` ya no aparecen como "Web / EN · etsy" en `/admin`: se muestran como **🛍️ Etsy #<número de pedido>** (con "(prueba)" para los pedidos de prueba y "· variación" si son "misma letra, otro estilo"):
- tabla de sesiones web (columna Canal) y "Últimas entregas";
- página de detalle (`/admin/orden/web/<session>`): título "Pedido Etsy #…", número de pedido y enlace a la sesión original si es una variación;
- tarjeta "🛍️ Sesiones Etsy (N pedidos · M entregadas)" (excluye pedidos de prueba);
- `/admin/charlas-abandonadas` devuelve `etsy_order_number` en cada sesión.
Código: `_etiqueta_canal_web()` en `main.py`, `get_etsy_web_stats()` y `get_recent_deliveries()` en `db.py`. Prueba: `tests/etsy/test_admin.py`.
Nota: solo se registra una sesión cuando el cliente valida su número de pedido y empieza; las visitas a `/etsy` que no validan un pedido no dejan registro.

