"""Generacion de HTML del sitio publico y del panel de administracion.

Sin framework de templates (no hay Node/pip disponible de forma confiable
en este entorno): son funciones Python que arman strings HTML. Mantener
cada funcion pequena y componer con `layout()`.
"""
from urllib.parse import quote


def esc(texto):
    if texto is None:
        return ""
    return (
        str(texto)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


SITE_DESCRIPTION = ("Encuentra pymes y emprendedores de Talca por lo que necesitas y escríbeles "
                     "directo por WhatsApp. Ventanas, gásfitería, clases, tecnología y más.")


def layout(title, body, active="home", admin=False, description=None, og_image="/og/default.png",
           canonical=None, json_ld=None, flash=None):
    nav = ADMIN_NAV if admin else PUBLIC_NAV
    active_attr = f' data-active="{active}"'
    desc = description or SITE_DESCRIPTION
    canonical_tag = f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ""
    ld_tag = f'<script type="application/ld+json">{json_ld}</script>' if json_ld else ""
    flash_html = f'<div class="flash">{esc(flash)}</div>' if flash else ""
    robots = '<meta name="robots" content="noindex">' if admin else ""
    return f"""<!doctype html>
<html lang="es-CL">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · Talcadatos</title>
<meta name="description" content="{esc(desc)}">
{robots}
{canonical_tag}
<meta property="og:type" content="website">
<meta property="og:site_name" content="Talcadatos">
<meta property="og:title" content="{esc(title)} · Talcadatos">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:image" content="{esc(og_image)}">
<meta name="twitter:card" content="summary_large_image">
{ld_tag}
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>📌</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/styles.css">
</head>
<body{active_attr}>
{nav}
<main class="wrap">
{flash_html}
{body}
</main>
<footer class="site-footer">
  <span>Talcadatos — directorio de pymes y emprendedores de Talca</span>
  <span>Panel de administración: <a href="/admin">/admin</a></span>
</footer>
<script src="/static/app.js"></script>
</body>
</html>"""


PUBLIC_NAV = """
<header class="topbar">
  <div class="wrap topbar-inner">
    <a href="/" class="brand">📌 Talcadatos</a>
    <nav class="topnav">
      <a href="/avisos">Explorar</a>
      <a href="/publicar" class="btn btn-ghost">Publicar mi negocio</a>
    </nav>
  </div>
</header>
"""

ADMIN_NAV = """
<header class="topbar topbar-admin">
  <div class="wrap topbar-inner">
    <a href="/admin" class="brand">📌 Talcadatos <span class="tag-admin">admin</span></a>
    <nav class="topnav">
      <a href="/admin">Dashboard</a>
      <a href="/admin/moderacion">Moderación</a>
      <a href="/admin/avisos">Avisos</a>
      <a href="/admin/anunciantes">Anunciantes y planes</a>
      <a href="/" class="btn btn-ghost">Ver sitio</a>
      <a href="/admin/logout" class="btn btn-ghost">Salir</a>
    </nav>
  </div>
</header>
"""


def badge(texto, kind="mvp"):
    return f'<span class="badge badge-{kind}">{esc(texto)}</span>'


def estado_badge(estado):
    kinds = {"activo": "ok", "pendiente": "warn", "pausado": "muted", "rechazado": "bad"}
    return badge(estado, kinds.get(estado, "muted"))


def plan_badge(plan_nombre):
    kinds = {"Gratis": "muted", "Destacado": "gold", "Premium": "brick"}
    return badge(plan_nombre, kinds.get(plan_nombre, "muted"))


def whatsapp_url(whatsapp, negocio_nombre, titulo):
    numero = "".join(c for c in whatsapp if c.isdigit())
    mensaje = f"Hola {negocio_nombre}, vi tu aviso \"{titulo}\" en Talcadatos y quiero consultar por..."
    return f"https://wa.me/{numero}?text={quote(mensaje)}"


def aviso_card(aviso, termino_busqueda=None):
    destacado = aviso["plan_nombre"] in ("Destacado", "Premium")
    badge_html = plan_badge(aviso["plan_nombre"]) if destacado else ""
    verificado_html = '<span class="check" title="Negocio verificado">✔</span>' if aviso["verificado"] else ""
    click_attr = f' data-termino="{esc(termino_busqueda)}"' if termino_busqueda else ""
    wa = whatsapp_url(aviso["whatsapp"], aviso["negocio_nombre"], aviso["titulo"])
    return f"""
<article class="card" style="--card-accent:{esc(aviso['color'])}"{click_attr} data-aviso-id="{aviso['id']}">
  <a class="card-photo" href="/avisos/{aviso['id']}">
    <span class="card-icon">{aviso['icono']}</span>
    {badge_html}
  </a>
  <div class="card-body">
    <a class="card-title" href="/avisos/{aviso['id']}">{esc(aviso['titulo'])}</a>
    <div class="card-meta">
      <span>{esc(aviso['negocio_nombre'])} {verificado_html}</span>
      <span class="dot">·</span>
      <span>{esc(aviso['comuna'])}</span>
    </div>
    <div class="card-cat mono">{aviso['icono']} {esc(aviso['categoria_nombre'])}</div>
    <a class="btn btn-whatsapp btn-block" href="{wa}" target="_blank" rel="noopener"
       data-aviso-id="{aviso['id']}" data-wa-click="1">
      Contactar por WhatsApp
    </a>
  </div>
</article>"""


def cards_grid(avisos, termino_busqueda=None, vacio_msg="No hay avisos que coincidan con tu búsqueda."):
    if not avisos:
        return f'<p class="empty-state">{esc(vacio_msg)}</p>'
    return '<div class="grid">' + "".join(aviso_card(a, termino_busqueda) for a in avisos) + "</div>"


def categorias_pills(categorias, activa_slug=None):
    items = []
    for c in categorias:
        cls = "pill active" if c["slug"] == activa_slug else "pill"
        items.append(f'<a class="{cls}" href="/avisos?categoria={c["slug"]}">{c["icono"]} {esc(c["nombre"])}</a>')
    return '<div class="pills">' + "".join(items) + "</div>"
