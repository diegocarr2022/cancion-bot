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
<p>Última actualización: octubre de 2026.</p>

<h2>1. Datos que recolectamos</h2>
<p>Para poder crear y entregarte tu canción personalizada, recolectamos:</p>
<ul>
<li>tu correo electrónico (para enviarte el archivo final) y el nombre que nos compartes;</li>
<li>la información que nos compartes sobre la canción (para quién es, ocasión, estilo, detalles y anécdotas) y la
letra que apruebas;</li>
<li>si usas una función opcional de video, las fotos que subes (solo se usan para hacer tu video y se borran
automáticamente cuando queda listo);</li>
<li>datos técnicos y publicitarios de tu visita: dirección IP, navegador y dispositivo, país aproximado, la página o
anuncio que te trajo (como parámetros de campaña e identificadores de clic) y cookies de nuestras herramientas de
publicidad y analítica (ver sección 3).</li>
</ul>

<h2>2. Para qué usamos tus datos</h2>
<p>Los usamos para: generar la letra y el audio de tu canción, procesar el pago, entregarte los archivos finales por
correo y en esta página, darte soporte y mantener el servicio seguro. Si dejas un pedido sin terminar, o después de
entregarte tu canción, podemos escribirte por correo una o dos veces (por ejemplo para recordarte el pedido pendiente o
pedirte tu opinión); puedes pedirnos que dejemos de hacerlo. También usamos datos técnicos para medir qué anuncios
generan pedidos.</p>

<h2>3. Publicidad y analítica</h2>
<p>En nuestro sitio usamos el Pixel de Meta y herramientas de Google (Google Analytics / Google Ads) para medir qué
publicidad nos trae clientes. Estos proveedores pueden recibir información como las páginas que visitas, eventos de
compra e identificadores de cookies, y la tratan conforme a sus propios avisos de privacidad.</p>

<h2>4. Con quién se comparten</h2>
<p>Compartimos solo la información estrictamente necesaria con los proveedores que hacen posible el servicio:
nuestros proveedores de pago (dLocal Go o Stripe, según tu región), los proveedores de IA que escriben la letra y
generan el audio, nuestro proveedor de correo, nuestros proveedores de hosting y de procesamiento de archivos, y las
plataformas de publicidad mencionadas arriba. No vendemos tus datos personales.</p>

<h2>5. Tratamiento en otros países</h2>
<p>Nuestros proveedores pueden tratar datos en Estados Unidos y otros países. Elegimos proveedores que los protejan de
forma adecuada.</p>

<h2>6. Cuánto tiempo conservamos tus datos</h2>
<p>Conservamos la información de tu pedido mientras sea necesario para brindarte soporte relacionado con esa compra
y mientras la ley lo exija. Puedes pedirnos que la borremos antes.</p>

<h2>7. Tus derechos (ARCO)</h2>
<p>Puedes solicitar acceder, rectificar, cancelar u oponerte al uso de tus datos personales (derechos ARCO), o pedirnos
que dejemos de enviarte correos, escribiéndonos por los canales de contacto indicados en el sitio.</p>

<h2>8. Menores de edad</h2>
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
<p>Payments on this site are processed through an external payment provider (Stripe, or dLocal Go in some
regions). We do not store card data on our servers. Orders placed through our Etsy shop are paid on Etsy under
Etsy's terms.</p>

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
<p>Last updated: October 2026.</p>

<h2>1. Data we collect</h2>
<p>To create and deliver your personalized song we collect:</p>
<ul>
<li>your email address (to send you the final file) and the name you give us;</li>
<li>what you share with us about the song: who it's for, the occasion, the style, details and anecdotes, and the
lyrics you approve;</li>
<li>if you bought through our Etsy shop, your Etsy order number (we use it only to confirm your purchase with Etsy);</li>
<li>if you use an optional video feature, the photos you upload (they are only used to make your video and are
deleted automatically once it is ready);</li>
<li>technical and advertising data about your visit: IP address, browser and device, approximate country, the page
or ad that brought you to us (such as campaign parameters and click IDs), and cookies set by our advertising and
analytics tools (see section 3).</li>
</ul>

<h2>2. What we use your data for</h2>
<p>We use it to: generate the lyrics and the audio of your song, process your payment, deliver the final files by
email and on this site, give you support, and keep the service secure. If you leave an order unfinished, or after your
song is delivered, we may email you once or twice about it (for example to remind you of the unfinished order or to
ask for feedback); you can ask us to stop. We do not send these emails to customers who bought through Etsy. We also
use technical data to measure which ads lead to orders.</p>

<h2>3. Advertising and analytics</h2>
<p>On our own website we use the Meta Pixel and Google tools (Google Analytics / Google Ads) to measure which
advertising brings customers. These providers may receive information such as the pages you view, purchase events and
cookie identifiers, and handle it under their own privacy policies. We do not use these tools on the page where
customers of our Etsy shop enter their order number.</p>

<h2>4. Who we share it with</h2>
<p>We share only what is strictly necessary with the providers that make the service possible: our payment providers
(Stripe, or dLocal Go in some regions), the AI providers that write the lyrics and generate the audio, our email
provider, our hosting and file-processing providers, Etsy (to verify Etsy orders), and the advertising platforms
mentioned above. We do not sell your personal data.</p>

<h2>5. International processing</h2>
<p>Our providers may process data in the United States and other countries. We choose providers that protect it
appropriately.</p>

<h2>6. How long we keep your data</h2>
<p>We keep your order information for as long as needed to provide support related to that purchase, and for as
long as the law requires. You can ask us to delete it earlier.</p>

<h2>7. Your rights</h2>
<p>You can request to access, correct, or delete your personal data, or ask us to stop sending you emails, by
contacting us through the contact channels listed on the site (or by messaging us on Etsy if you bought there).
If you are in the European Union or California, you also have the rights granted to you by GDPR and CCPA.</p>

<h2>8. Minors</h2>
<p>This service is not directed at minors. If you are a minor, please have a responsible adult make the
purchase.</p>
</body></html>
"""
