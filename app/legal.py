"""
Paginas de Terminos y Condiciones / Aviso de Privacidad, servidas en
/terminos y /privacidad. Necesarias para que Facebook Ads y Google Ads
aprueben campañas que llevan a una landing con checkout - ambas plataformas
piden que cualquier pagina que pida datos personales o cobre dinero tenga
estas politicas visibles y enlazadas.

IMPORTANTE: esto es un borrador razonable, no asesoria legal. Cubre lo
basico (que datos se recolectan, para que, con quien se comparten, politica
de reembolsos) pero conviene que un abogado lo revise antes de escalar el
negocio en serio, sobre todo la parte de la LFPDPPP (proteccion de datos en
Mexico) si el volumen de clientes crece.
"""

from app.config import BRAND_NAME_EN

_BASE_STYLE = """
<style>
  body { font-family: -apple-system, sans-serif; max-width: 680px; margin: 0 auto;
         padding: 40px 20px 80px; color: #292018; line-height: 1.6; }
  h1 { font-size: 24px; } h2 { font-size: 18px; margin-top: 32px; }
  a { color: #d96b2b; }
  .volver { display:inline-block; margin-bottom: 24px; color:#9a8b73; text-decoration:none; }
</style>
"""

TERMINOS_HTML = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>Términos y Condiciones</title>{_BASE_STYLE}</head>
<body>
<a class="volver" href="/cancion">&larr; Volver</a>
<h1>Términos y Condiciones</h1>
<p>Última actualización: 2026. Al usar este sitio y comprar una canción personalizada, aceptas lo siguiente:</p>

<h2>1. El servicio</h2>
<p>Ofrecemos canciones personalizadas generadas con inteligencia artificial (IA), a partir de la información
que nos proporcionas (para quién es, ocasión, estilo musical, detalles y anécdotas). El precio vigente se
muestra antes de pagar.</p>

<h2>2. Proceso y tiempos de entrega</h2>
<p>Después de aprobar la letra y confirmar el pago, la canción se genera automáticamente. El tiempo típico de
generación es de unos minutos, pero puede variar según la demanda del proveedor de generación musical. La
entrega se hace mediante un link de descarga que aparece en esta misma página y, como respaldo, por correo
electrónico.</p>

<h2>3. Naturaleza del producto</h2>
<p>Al ser un contenido digital personalizado y generado específicamente para ti (no un producto genérico de
stock), la compra se considera completada una vez que se entrega el archivo de audio. Si el archivo no llega
o presenta un problema técnico real (por ejemplo, no se genera o el audio está dañado), contáctanos para
resolverlo sin costo adicional (reintento o reembolso, según el caso).</p>

<h2>4. Uso de la canción</h2>
<p>La canción es para uso personal (regalo, ocasión especial, etc.). No garantizamos derechos de autor
registrados ni licencias comerciales sobre el resultado generado por IA.</p>

<h2>5. Contenido del pedido</h2>
<p>No aceptamos pedidos con contenido difamatorio, discriminatorio, que incite a la violencia, o que infrinja
derechos de terceros. Nos reservamos el derecho de rechazar o cancelar (con reembolso) cualquier pedido que
viole esto.</p>

<h2>6. Pagos</h2>
<p>Los pagos se procesan a través de un proveedor externo de pagos (dLocal Go). No almacenamos datos de tarjetas
en nuestros servidores.</p>

<h2>7. Contacto</h2>
<p>Para dudas, soporte o solicitudes relacionadas con tu pedido, escríbenos por los canales de contacto
indicados en el sitio.</p>
</body></html>
"""

PRIVACIDAD_HTML = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>Aviso de Privacidad</title>{_BASE_STYLE}</head>
<body>
<a class="volver" href="/cancion">&larr; Volver</a>
<h1>Aviso de Privacidad</h1>
<p>Última actualización: 2026.</p>

<h2>1. Datos que recolectamos</h2>
<p>Para poder crear y entregarte tu canción personalizada, recolectamos: tu correo electrónico (para enviarte
el archivo final), la información que nos compartes sobre la canción (para quién es, ocasión, estilo, detalles
y anécdotas), y datos técnicos básicos de tu visita (como la dirección IP y el navegador, con fines de
seguridad y para medir el origen de las visitas desde anuncios).</p>

<h2>2. Para qué usamos tus datos</h2>
<p>Usamos estos datos únicamente para: generar la letra y el estilo de tu canción, procesar el pago, entregarte
el archivo final por correo y en esta página, y darte soporte si tienes algún problema con tu pedido.</p>

<h2>3. Con quién se comparten</h2>
<p>Compartimos la información estrictamente necesaria con los proveedores que hacen posible el servicio:
el proveedor de pagos (dLocal Go, para procesar tu pago), el proveedor de generación musical por IA (para crear
el audio a partir de la letra y el estilo), y nuestro proveedor de correo (para enviarte el archivo final). No
vendemos ni compartimos tus datos con terceros para fines publicitarios.</p>

<h2>4. Cuánto tiempo conservamos tus datos</h2>
<p>Conservamos la información de tu pedido mientras sea necesario para brindarte soporte relacionado con esa
compra.</p>

<h2>5. Tus derechos (ARCO)</h2>
<p>Puedes solicitar acceder, rectificar, cancelar u oponerte al uso de tus datos personales (derechos ARCO)
escribiéndonos por los canales de contacto indicados en el sitio.</p>

<h2>6. Menores de edad</h2>
<p>Este servicio no está dirigido a menores de edad. Si eres menor de edad, pide a un adulto responsable que
realice la compra.</p>
</body></html>
"""

# ---------------------------------------------------------------------------
# Version en ingles (EE.UU., ago 2026) - servida en /terms y /privacy (ver
# main.py). NO es una traduccion literal de las de arriba: se quito la
# seccion de derechos ARCO/LFPDPPP (especifica de la ley mexicana de
# proteccion de datos, no aplica en EE.UU.) y se reemplazo por una clausula
# generica de contacto para acceder/corregir/borrar datos, dejando el marco
# legal especifico (CCPA u otro, segun estado) para cuando un abogado lo
# revise. Se menciona PayPal como pasarela de pago para EE.UU. (dLocal Go
# solo aplica a MX/PE/CO).
#
# IMPORTANTE: igual que las versiones en espanol, esto sigue siendo un
# borrador razonable, NO asesoria legal - y las versiones en ingles cargan
# mas riesgo que una traduccion directa sugeriria (marco de proteccion al
# consumidor distinto al mexicano). Revisar con un abogado antes de escalar
# gasto en serio en EE.UU.
# ---------------------------------------------------------------------------
TERMS_HTML_EN = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{BRAND_NAME_EN} — Terms &amp; Conditions</title>{_BASE_STYLE}</head>
<body>
<a class="volver" href="/">&larr; Back</a>
<h1>{BRAND_NAME_EN} — Terms &amp; Conditions</h1>
<p>Last updated: 2026. By using this site and purchasing a personalized song from {BRAND_NAME_EN}, you agree to the following:</p>

<h2>1. The service</h2>
<p>{BRAND_NAME_EN} offers personalized songs generated with artificial intelligence (AI), based on the information you
provide us (who it's for, occasion, musical style, details and anecdotes). The current price is shown before
you pay.</p>

<h2>2. Process and delivery time</h2>
<p>After approving the lyrics and confirming payment, the song is generated automatically. Typical generation
time is a few minutes, but it can vary depending on demand on the music-generation provider's side. Delivery
happens via a download link that appears on this same page and, as a backup, by email.</p>

<h2>3. Nature of the product</h2>
<p>Since this is personalized digital content generated specifically for you (not a generic stock product), the
purchase is considered complete once the audio file is delivered. If the file doesn't arrive or has a real
technical problem (for example, it fails to generate or the audio is corrupted), contact us to resolve it at no
extra cost (retry or refund, depending on the case).</p>

<h2>4. Use of the song</h2>
<p>The song is for personal use (gift, special occasion, etc.). We do not guarantee registered copyright or
commercial licenses over AI-generated output.</p>

<h2>5. Order content</h2>
<p>We don't accept orders with defamatory or discriminatory content, content that incites violence, or that
infringes on third-party rights. We reserve the right to refuse or cancel (with a refund) any order that
violates this.</p>

<h2>6. Payments</h2>
<p>Payments are processed through an external payment provider (PayPal for customers in the United States;
dLocal Go for other regions). We do not store card data on our servers.</p>

<h2>7. Contact</h2>
<p>For questions, support, or requests related to your order, reach us through the contact channels listed on
the site.</p>
</body></html>
"""

PRIVACY_HTML_EN = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{BRAND_NAME_EN} — Privacy Notice</title>{_BASE_STYLE}</head>
<body>
<a class="volver" href="/">&larr; Back</a>
<h1>{BRAND_NAME_EN} — Privacy Notice</h1>
<p>Last updated: 2026.</p>

<h2>1. Data we collect</h2>
<p>To create and deliver your personalized song, we collect: your email address (to send you the final file),
the information you share with us about the song (who it's for, occasion, style, details and anecdotes), and
basic technical data about your visit (like IP address and browser, for security purposes and to measure where
visits from ads come from).</p>

<h2>2. What we use your data for</h2>
<p>We use this data solely to: generate the lyrics and style of your song, process payment, deliver the final
file by email and on this page, and provide support if you have any issue with your order.</p>

<h2>3. Who we share it with</h2>
<p>We share the strictly necessary information with the providers that make the service possible: the payment
provider (PayPal or dLocal Go, depending on your region, to process your payment), the AI music-generation
provider (to create the audio from the lyrics and style), and our email provider (to send you the final file).
We do not sell or share your data with third parties for advertising purposes.</p>

<h2>4. How long we keep your data</h2>
<p>We keep your order information for as long as needed to provide support related to that purchase.</p>

<h2>5. Your rights</h2>
<p>You can request to access, correct, or delete your personal data by contacting us through the contact
channels listed on the site.</p>

<h2>6. Minors</h2>
<p>This service is not directed at minors. If you are a minor, please have a responsible adult make the
purchase.</p>
</body></html>
"""
