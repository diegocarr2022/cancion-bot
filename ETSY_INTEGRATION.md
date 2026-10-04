# Canciones vendidas en Etsy: qué se hizo y por qué

> Documento de traspaso para quien continúe en este proyecto (otro chat de Claude Code). Escrito el 2026-10-03 al terminar
> la integración. Lo que dice aquí **está desplegado y verificado en producción**, salvo lo marcado como pendiente.
> Diego no pide "otra cosa" que lo que está aquí: si algo contradice este documento, pregunta antes de cambiarlo.

## 1. Contexto y decisión de negocio

Diego tiene una tienda de Etsy, **VibeCraftDigitalShop** (precios en MXN; vende wall art digital y ahora canciones). Quiso vender
también el servicio de **canciones personalizadas de tunecraft.studio** (este repo) dentro de Etsy.

Ventaja competitiva: la competencia en Etsy entrega en **24 a 72 horas**; aquí es **unos 5 minutos** (≈3 de chat + ≈2 de generación),
con la letra aprobada por el cliente antes de producir. El chat que pregunta lo que falta es el diferencial (un formulario de Etsy no lo
hace), así que **el listing de Etsy NO recoge los datos de la canción**: es un producto digital cuyo PDF de entrega lleva un link a
`https://tunecraft.studio/etsy`, donde el comprador mete su **número de pedido de Etsy** y chatea igual que cualquier cliente.

Diferencia clave con el flujo normal: el pago ya ocurrió en Etsy. Donde el flujo normal **cobra (al aprobar la letra)**, el flujo de Etsy
**gasta un crédito** de ese pedido y arranca Suno. No hay Stripe, ni preview gratis, ni precios visibles.

Productos (IDs de listing de Etsy):

| Producto | Listing | Precio (MXN) | Créditos |
|---|---|---|---|
| 1 canción | `4587652826` | 299 | 1 |
| Pack de 3 canciones | `4587653912` | 599 | 3 |

Un **crédito = una canción**: o una canción nueva (chat nuevo) o "la misma letra en otro estilo" (ver §6).

## 2. Arquitectura (3 piezas)

```
Comprador en Etsy ──compra──> Etsy ──PDF con link──> tunecraft.studio/etsy  (Render, este repo)
                                                          │  número de pedido
                                                          ▼
                                      Cloudflare Worker "photo-stocker-etsy-delivery"
                                      POST /api/redeem  (check | consume)   KV PRODUCTS
                                                          │  receipt (OAuth, API de Etsy v3)
                                                          ▼
                                                        Etsy
cancion-bot ──Suno/AceDataCloud──> canción (2 tomas)
cancion-bot ──POST /vinyl-pdf──> droplet de medios (Chromium) ──> PDF de la letra en vinil (4 tamaños)
```

1. **cancion-bot (Render, este repo)**: la landing `/etsy`, el chat, el canje de créditos al aprobar, la entrega, las variaciones.
2. **Worker de Cloudflare** (repo/carpeta aparte: `/Users/minds/Photo_Stocker/etsy_delivery/worker/`): valida el pedido contra Etsy y lleva
   la cuenta de créditos en KV. Es el único que habla con la API de Etsy y guarda sus credenciales. Este repo **solo** le habla a
   `/api/redeem`.
3. **Servicio de medios (droplet DigitalOcean `167.172.221.235`, `/opt/tunecraft-media`, systemd `tunecraft-media`)**: ya existía (preview y
   video). Se le agregó `POST /vinyl-pdf`. Código fuente local: `/Users/minds/Documents/Canciones personalizadas/tunecraft-media-services/service/`.

## 3. Variables de entorno (Render, servicio `cancion-bot`)

| Variable | Valor / para qué |
|---|---|
| `ETSY_WORKER_URL` | `https://photo-stocker-etsy-delivery.craft-studio.workers.dev` |
| `ETSY_REDEEM_KEY` | llave compartida con el Worker (secreto `REDEEM_KEY` del Worker). **Nunca** en el repo ni en chats |
| `ETSY_SONG_PRODUCT` | `tunecraft-song` (clave en el KV `PRODUCTS` del Worker con el mapa de créditos) |
| `ETSY_TEST_ORDERS` | `720514` (pedido de prueba, ver §8). **Conviene quitarla antes de hacer publicidad** |

Sin `ETSY_WORKER_URL`+`ETSY_REDEEM_KEY` (y sin `ETSY_TEST_ORDERS`) `/etsy` responde 503 y el resto del sitio no cambia.

El Worker guarda en KV `PRODUCTS` la clave `tunecraft-song` = `{"name":"Personalized Song","credits":{"4587652826":1,"4587653912":3}}`.
Para un listing nuevo de canciones hay que **agregar su ID ahí** (`wrangler kv key put --binding PRODUCTS --remote tunecraft-song '<json>'`).

## 4. Qué cambió en este repo (commits en `main`)

| Archivo | Qué |
|---|---|
| `app/etsy_client.py` (nuevo) | Cliente del Worker: `check()` y `consume()` (idempotente por sesión). Pedidos de prueba sin llamar al Worker |
| `app/landing_etsy.py` (nuevo) | La landing `/etsy` = la landing EN renderizada en modo Etsy (ver §5) |
| `app/lang_guard.py` (nuevo) | Guardia de idioma de la letra (ver §7) |
| `app/main.py` | `/etsy`, `/etsy/check`, `/etsy/credits`, `POST /web/variation`, `/web/session` acepta `etsy_order`, `/web/lyrics-pdf` con vinil |
| `app/web_conversation.py` | `_finalizar_letra_etsy`, guardia de idioma, guarda `recipient`/`from_name`, tools y prompt de Etsy |
| `app/claude_client.py` | Prompt de Etsy (variante de la plantilla EN), `WEB_CONTENT_TOOLS_ETSY`, pregunta por apodo/destinatario |
| `app/media_client.py` | `generar_vinyl_pdfs`, `descargar_pdf` |
| `app/db.py` | Columnas `gateway`, `etsy_order_number`, `final_recipient`, `final_from`, `vinyl_pdfs`, `parent_session_id`; exclusión de pedidos de Etsy en correos de recuperación/reseña; `find_etsy_session_for_order` |
| `app/config.py` | Variables `ETSY_*` |
| `app/legal.py` | Aviso de privacidad (EN y ES) y términos EN actualizados |

## 5. La landing `/etsy` (decisión de diseño importante)

Diego quería **mantener la identidad de marca y los demos de estilos** de la landing, pero **sin precios** (Etsy prohíbe ofrecer comprar
fuera de su plataforma; la página no debe cobrar ni mostrar precios). Se descartó duplicar la landing (2000+ líneas a mantener doble) y
descartó "esconder precios con CSS" (frágil). Lo que se hizo:

- `landing_etsy.build_etsy_landing()` toma `LANDING_HTML_EN` ya existente y **sustituye en el servidor** cada pedazo que habla de dinero
  (precio, contador de oferta, cajas de preview y de pago, Stripe.js, pixel de Meta, Google Ads, JSON-LD, FAQ de costo...). El precio
  **nunca llega al navegador**. Entra un campo "Enter your Etsy order number" que desbloquea el chat; el chat y los demos son los mismos.
- **Falla cerrado:** si la plantilla EN cambia y una sustitución ya no encaja, o si en el texto visible queda una palabra de dinero
  (`$`, price, stripe, checkout, pay, preview, launch price...), `ETSY_LANDING_HTML` queda en `None` y `/etsy` responde **503**
  (el motivo está en `ETSY_LANDING_ERROR` y se loguea al arrancar). **Si editas `landing.py` (EN), corre la prueba de `/etsy`.**
- El prompt de Etsy se arma igual: `claude_client._build_etsy_web_prompt()` reemplaza fragmentos de la plantilla EN y **lanza `ValueError`
  si la plantilla cambió**; `etsy_prompt_ok()` desactiva `/etsy` en ese caso. Si cambias esos fragmentos en la plantilla EN, actualiza
  `_ETSY_PROMPT_REPLACEMENTS`.
- La sesión de Etsy se crea con `gateway="etsy"`, `source="etsy"` (o `"etsy-test"`), `language="en"`, sin pixel/Stripe/preview.
- El bot de Etsy **no tiene** la herramienta `find_previous_order` (podría regenerar un link de pago de Stripe). Recuperar sesión =
  volver a `/etsy` con el mismo número de pedido (`/etsy/check` devuelve `resume_session_id` cuando ya no quedan créditos).

## 6. Flujo completo y créditos

1. `POST /etsy/check {order_number}` → Worker `check` (valida contra el receipt de Etsy: existe, está pagado, trae un listing de
   `tunecraft-song`) → `{ok, remaining}`. Rate limit en memoria: 12 intentos / 10 min / IP.
2. `POST /web/session {etsy_order}` revalida en el servidor y crea la sesión (`gateway="etsy"`).
3. Chat normal. Al **aprobar la letra** → `_finalizar_letra_etsy`: **primero `consume` el crédito** (idempotente por `session_id`) y luego
   Suno; `paid=1`, `step="generando"`. `poll_web_suno_tasks_loop` entrega las **2 tomas** como siempre.
4. **Pack de 3:** `remaining>0` → `/etsy/check` abre sesión nueva (otra canción). Con `remaining==0` reanuda la última sesión.
5. **"Misma letra, otro estilo"** (`GET /etsy/credits`, `POST /web/variation`): en la pantalla de entrega, si quedan créditos, el cliente
   elige uno de 7 estilos (`ETSY_STYLE_PRESETS` en `main.py`) o escribe uno (≤160 caracteres). Se crea una sesión hija con la letra ya
   aprobada (`parent_session_id`), **Suno primero y el crédito después** (si Suno falla no se gasta crédito), dedupe de doble clic 60 s,
   2 tomas. Las "dos versiones" son dos tomas del **mismo** estilo; la variación es el mecanismo para otro estilo.
6. Entrega: pantalla + correo (Mailgun) con links y PDF de la letra. Los correos de recuperación de carrito y de reseña de Trustpilot
   **excluyen** `gateway='etsy'`.

## 7. Solo inglés (requisito de negocio, el listing lo promete)

Un latino en EE.UU. que ponía un nombre en español hacía que el modelo escribiera la letra en español. Diego no puede vender así en EE.UU.:

1. El prompt de Etsy **no tiene** la excepción "si pide español, lo escribe en español" que sí tiene la plantilla EN normal.
2. `lang_guard.looks_spanish(lyric)` revisa la letra aprobada **antes** de gastar crédito o generar (aplica a **todas** las sesiones
   `language=="en"`: sitio de EE.UU. y Etsy). Si está en español: no se guarda, no se gasta crédito, y el bot recibe la orden de reescribirla
   en inglés y pedir aprobación otra vez. Heurística de palabras funcionales (español vs inglés): las letras en inglés con apodos o frases
   sueltas en español ("mi amor", "Nena") pasan. Ver `lang_guard.py` y su docstring.

## 8. Pedido de prueba

`ETSY_TEST_ORDERS=720514` deja pasar `/etsy` sin consultar a Etsy, con créditos ilimitados y reutilizables (las sesiones se marcan
`source="etsy-test"`). Cada canción de prueba cuesta Claude+Suno de verdad (centavos). **Es una puerta trasera de canciones gratis para
quien sepa el número**: quitar la variable de Render cuando terminen las pruebas / antes de campañas.

## 9. PDF de la letra en vinil (diseño de VibeCraft)

Diego aportó `vibecraft-vinyl-pdf.zip` (README = especificación; **no rediseñar** composición, colores ni fuentes sin que él lo pida).
Dibuja la letra en espiral sobre un disco de vinil con el título y "A song for X · With love, Y". Necesita Chromium (Playwright), que **no
corre bien en Render Starter** (512 MB, sin librerías del sistema), así que vive en el droplet de medios:

- Droplet: `service/vinyl.py` + `vinyl_pdf.py` + `fonts/`, `POST /vinyl-pdf` (Bearer `MEDIA_API_TOKEN`, un solo hilo + Chromium compartido,
  `--no-sandbox`). ~3.4 s para los 4 tamaños. Respaldo del servicio anterior: `/opt/tunecraft-media/service.bak-2026-10-03`.
  Acceso: `ssh -i ~/.ssh/advisor2 root@167.172.221.235`. **No imprimas `tunecraft-media-services/deploy/server.env` (tokens vivos).**
- Aquí: `/web/lyrics-pdf/{session}?size=8x10|11x14|A4|12x12`. Cache por hash de (título, letra, destinatario, firma) en `web_orders.vinyl_pdfs`.
  **Si el servicio de medios falla, entrega el PDF sencillo de `pdf_client.py`.**
- Datos del PDF: título, letra, `final_recipient` ("A song for X"), firma = `final_from` o el **primer nombre** de `customer_name`
  (mucha gente da el nombre completo pero prefiere apodo en una dedicatoria). El bot pregunta apodo/destinatario en una sola pregunta y los
  pasa como `from_name` y `recipient` en `finalizar_letra` (ambos opcionales).

## 10. Contenido de Etsy (lo que no está en el código)

Todo en `/Users/minds/Photo_Stocker/etsy_delivery/` (otro proyecto de Diego, mismo negocio de Etsy):

- `worker/index.js`: Worker de Cloudflare (`/api/redeem`, `/dl`, `/api/validate` para el wall art, endpoints admin de fotos, videos, secciones).
  Respaldos `index.js.bak-2026-10-03*`. Secretos en Cloudflare, no en el repo.
- `songs/`: `build_song_listing.py` (fotos/PDF), `build_song_video.py` (video), `texts.py` (título, descripción, tags), `assets/`.
- `scripts/`: `replace_images.py`, `upload_video.py`, `organize_sections.py`, `register_product.py`.
- Reglas aprendidas para listings y portadas: lo importante de la foto principal va al **centro** (Etsy recorta miniaturas a cuadrado,
  vertical y horizontal; la portada de canciones es cuadrada 3000×3000 con zona segura 2400×2250). La portada debe decir
  literalmente "personalized". Etsy prohíbe URLs/nombre del sitio externo en fotos, video y descripción (el link solo va en el PDF de entrega).
- Tienda ya configurada: 6 secciones, destacados, tagline, About (sincero: sin TIFF/RAW/170 MP/óleo, que **no** se ofrecen), 10 FAQs,
  mensaje digital corto, políticas (cancelaciones, privacidad). Precios: 299 y 599, **sin descuento ficticio**.

## 11. Cómo probar y operar

- Pruebas locales (no están en el repo; se corrieron con claves falsas y un Worker simulado): página `/etsy` sin dinero, errores del check,
  canje de crédito, pack de 3, variaciones (orden Suno→crédito, doble clic, agotado), guardia de idioma, PDF vinil con respaldo,
  regresión del sitio normal (`/`, `/cancion`, `/web/session` sin Etsy). Conviene volver a escribirlas si se toca algo de esto.
- Prueba real en producción: sesión con el pedido 720514 (`POST /web/session` + `/web/chat` + `/web/status`), verificada de punta a punta
  (chat → aprobación sin pago → 2 tomas → PDF vinil → variación). Compra real de Diego con un pedido auténtico de Etsy: **funcionó**.
- `render.yaml` no se tocó. Despliegue: `git push origin main` (Render autodeploy). Worker: `npx wrangler deploy` en
  `etsy_delivery/worker` (probar `/`, `/dl`, `/api/redeem` y `/api/validate` después). Droplet: `scp` + `systemctl restart tunecraft-media`
  (tarda ~10 s en arrancar; no reiniciar con un render de video en curso).

## 12. Pendiente / ideas

1. **Quitar `ETSY_TEST_ORDERS`** de Render antes de la publicidad.
2. **Campaña de Etsy Ads** al pack de 3 (Diego decidió anunciar el de MX$599; presupuesto mínimo US$1/día; punto de equilibrio del clic
   = ganancia neta por venta × tasa de conversión). Reseñas: solo reales; el vendedor **no** puede reseñar su propia tienda (Etsy y FTC).
3. La primera venta real del **pack** será su primera prueba con un pedido real de varios créditos (la lógica está probada con simulación).
4. Pendientes de producto: edición "Museum" con TIFF sin pérdida (idea de Diego, aparcada; no prometer TIFF/RAW/170 MP hasta que exista),
   trios de felt otoño y crochet (esperan escalado XL), que el aviso de privacidad pase por un abogado antes de escalar.
5. Si cambian los precios o aparece un listing nuevo de canciones: actualizar el KV `tunecraft-song` del Worker.
6. Cosas existentes que se notaron y **no** se tocaron: el mensaje de error del chat sale en español incluso en la landing EN.
