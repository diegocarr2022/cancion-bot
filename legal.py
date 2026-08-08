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
