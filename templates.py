"""Generacion de HTML del sitio publico y del panel de administracion.

Sin framework de templates (no hay Node/pip disponible de forma confiable
en este entorno): son funciones Python que arman strings HTML. Mantener
cada funcion pequena y componer con `layout()`.
"""
import datetime
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


def brand_logo_html(marca_raw):
    return f'<img class="brand-logo" src="/static/img/logo.png" alt="{esc(marca_raw)}">'


def layout(title, body, active="home", admin=False, description=None, og_image="/og/default.png",
           canonical=None, json_ld=None, flash=None, site=None):
    site = site or {}
    marca_raw = site.get("marca", "Talcadatos")
    marca = esc(marca_raw)
    pie = esc(site.get("pie", "Talcadatos — directorio de pymes y emprendedores de Talca"))
    nav = admin_nav(active) if admin else public_nav(active, brand_logo_html(marca_raw))
    mobile_nav = ADMIN_MOBILE_NAV if admin else public_mobile_nav(active)
    active_attr = f' data-active="{active}"'
    desc = description or site.get("descripcion") or SITE_DESCRIPTION
    canonical_tag = f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ""
    ld_tag = f'<script type="application/ld+json">{json_ld}</script>' if json_ld else ""
    flash_html = f'<div class="flash">{esc(flash)}</div>' if flash else ""
    robots = '<meta name="robots" content="noindex">' if admin else ""
    footer = f"""<footer class="site-footer">
  <span>{pie}</span>
  <span><a href="/terminos">Términos</a> · <a href="/privacidad">Privacidad</a></span>
</footer>"""
    main = f"""<main class="wrap">
{flash_html}
{body}
</main>
{footer}"""
    contenido = f"""<div class="admin-shell">
{nav}
<div class="admin-main">
{main}
</div>
</div>""" if admin else f"{nav}\n{main}"
    return f"""<!doctype html>
<html lang="es-CL">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · {marca}</title>
<meta name="description" content="{esc(desc)}">
{robots}
{canonical_tag}
<meta property="og:type" content="website">
<meta property="og:site_name" content="{marca}">
<meta property="og:title" content="{esc(title)} · {marca}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:image" content="{esc(og_image)}">
<meta name="twitter:card" content="summary_large_image">
{ld_tag}
<link rel="icon" type="image/png" href="/static/img/favicon.png">
<meta name="theme-color" content="#E85D5D">
<link rel="manifest" href="/static/manifest.webmanifest">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/styles.css?v=20260901-18">
</head>
<body{active_attr}{' class="admin-body"' if admin else ''}>
{contenido}
{mobile_nav}
<script src="/static/app.js?v=20260901-12"></script>
</body>
</html>"""


def public_mobile_nav(active):
    def item(slug, href, icon, label):
        cls = ' class="is-active"' if slug == active else ""
        return f'<a href="{href}"{cls}><span aria-hidden="true">{icon}</span><span>{label}</span></a>'

    return f"""
<nav class="mobile-nav" aria-label="Navegación principal">
  {item("home", "/", "⌂", "Inicio")}
  {item("avisos", "/avisos", "◈", "Avisos")}
  {item("favoritos", "/favoritos", "★", "Favoritos")}
  <a href="/publicar" class="mobile-nav-cta{" is-active" if active == "publicar" else ""}">
    <span aria-hidden="true">＋</span><span>Publicar</span>
  </a>
</nav>
"""


ADMIN_MOBILE_NAV = """
<nav class="admin-mobile-nav" aria-label="Navegación de administración">
  <a href="/admin">Inicio</a><a href="/admin/editor">Editor</a><a href="/admin/contenido">Contenido</a>
  <a href="/admin/avisos">Avisos</a><a href="/admin/cuenta">Cuenta</a>
</nav>
"""


def public_nav(active, marca_html):
    def link(slug, href, label, extra_cls=""):
        cls = " ".join(c for c in (extra_cls, "is-active" if slug == active else "") if c)
        cls_attr = f' class="{cls}"' if cls else ""
        return f'<a href="{href}"{cls_attr}>{label}</a>'

    links = "".join([
        link("home", "/", "Inicio"),
        link("avisos", "/avisos", "Avisos"),
        link("favoritos", "/favoritos", "Favoritos"),
        link("publicar", "/publicar", "Publicar mi negocio", "btn btn-primary nav-cta"),
    ])
    return f"""
<header class="topbar">
  <div class="wrap topbar-inner">
    <a href="/" class="brand">{marca_html}</a>
    <nav class="topnav">
      {links}
    </nav>
  </div>
</header>
"""

ADMIN_NAV_GROUPS = [
    ("General", [
        ("dashboard", "/admin", "Dashboard", "◈"),
        ("analitica", "/admin/analitica", "Analítica", "⌁"),
        ("auditoria", "/admin/auditoria", "Auditoría", "◷"),
    ]),
    ("Contenido", [
        ("avisos", "/admin/avisos", "Avisos", "▦"),
        ("orden", "/admin/orden", "Orden de avisos", "⇅"),
        ("moderacion", "/admin/moderacion", "Moderación", "✓"),
        ("reportes", "/admin/reportes", "Reportes", "⚑"),
        ("contenido", "/admin/contenido", "Contenido", "✦"),
        ("editor", "/admin/editor", "Editor visual", "✎"),
    ]),
    ("Negocio", [
        ("anunciantes", "/admin/anunciantes", "Anunciantes", "⌂"),
        ("pagos", "/admin/pagos", "Pagos", "¤"),
        ("quieromiweb", "/admin/quieromiweb", "Quiero mi sitio web", "◫"),
        ("necesidades", "/admin/necesidades", "Necesidades", "↗"),
        ("alertas", "/admin/alertas", "Alertas", "◉"),
        ("sinonimos", "/admin/sinonimos", "Sinónimos", "≈"),
    ]),
    ("Cuenta", [
        ("usuarios", "/admin/usuarios", "Usuarios", "◍"),
        ("cuenta", "/admin/cuenta", "Mi cuenta", "⚙"),
    ]),
]


def admin_nav(active):
    import db
    try:
        pendientes = len(db.get_avisos(estado="pendiente"))
    except Exception:
        pendientes = 0

    def link(slug, href, label, icon):
        cls = " is-active" if slug == active else ""
        punto = '<span class="admin-sidedot" aria-label="Avisos pendientes"></span>' if slug == "moderacion" and pendientes else ""
        return f'<a href="{href}" class="admin-sidelink{cls}"><span class="admin-sideicon">{icon}</span>{label}{punto}</a>'

    def group(titulo, items):
        links = "".join(link(*item) for item in items)
        return f'<div class="admin-sidegroup"><span class="admin-sidegroup-title">{titulo}</span>{links}</div>'

    groups = "".join(group(titulo, items) for titulo, items in ADMIN_NAV_GROUPS)
    return f"""
<aside class="admin-sidebar">
  <a href="/admin" class="brand">📌 Talcadatos <span class="tag-admin">admin</span></a>
  <nav class="admin-sidenav">{groups}</nav>
  <div class="admin-sidebar-foot">
    <a href="/" class="btn btn-ghost btn-sm">Ver sitio</a>
    <a href="/admin/logout" class="btn btn-ghost btn-sm">Salir</a>
  </div>
</aside>
"""


def badge(texto, kind="mvp"):
    return f'<span class="badge badge-{kind}">{esc(texto)}</span>'


def estado_badge(estado):
    kinds = {"activo": "ok", "pendiente": "warn", "pausado": "muted", "rechazado": "bad"}
    return badge(estado, kinds.get(estado, "muted"))


def plan_badge(plan_nombre):
    kinds = {"Gratis": "muted", "Destacado": "gold", "Premium": "brick"}
    return badge(plan_nombre, kinds.get(plan_nombre, "muted"))


def origen_badge(es_demo):
    return badge("Demo", "muted") if es_demo else badge("Real", "ok")


def plan_cc(plan_nombre):
    mapa = {"Premium": ("P", "cc-premium"), "Destacado": ("D", "cc-destacado")}
    letra, clase = mapa.get(plan_nombre, ("R", "cc-regular"))
    return f'<span class="cc-tag {clase}" title="{esc(plan_nombre)}">{letra}</span>'


def plan_cc_editable(aviso_id, plan_nombre):
    plan_id_actual = {"Premium": "premium", "Destacado": "destacado"}.get(plan_nombre, "gratis")
    clase = {"Premium": "cc-premium", "Destacado": "cc-destacado"}.get(plan_nombre, "cc-regular")
    opciones = "".join(
        f'<option value="{pid}"{" selected" if pid == plan_id_actual else ""}>{letra}</option>'
        for pid, letra in (("premium", "P"), ("destacado", "D"), ("gratis", "R"))
    )
    return (
        f'<form method="post" action="/admin/avisos/{aviso_id}/cc" data-ajax-form data-ajax-reload>'
        f'<select name="plan_id" class="cc-tag cc-select {clase}" data-auto-submit '
        f'title="Cambiar categoría de cliente">{opciones}</select></form>'
    )


def es_nuevo(aviso, dias=3):
    creado = aviso.get("creado_en") or ""
    if not creado:
        return False
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=dias)).isoformat()
    return creado >= cutoff


def extracto(texto, largo=110):
    texto = (texto or "").strip()
    if len(texto) <= largo:
        return texto
    corte = texto[:largo].rsplit(" ", 1)[0]
    return corte + "…"


def whatsapp_url(whatsapp, negocio_nombre, titulo):
    numero = "".join(c for c in whatsapp if c.isdigit())
    mensaje = f"Hola {negocio_nombre}, vi tu aviso \"{titulo}\" en Talcadatos y quiero consultar por..."
    return f"https://wa.me/{numero}?text={quote(mensaje)}"


INSTAGRAM_ICON_SVG = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<rect x="3" y="3" width="18" height="18" rx="5"/>'
    '<circle cx="12" cy="12" r="4"/>'
    '<circle cx="17.2" cy="6.8" r="0.6" fill="currentColor" stroke="none"/>'
    '</svg>'
)


def instagram_link_html(url):
    if not url:
        return ""
    return (f'<a class="btn btn-ghost instagram-btn" href="{esc(url)}" target="_blank" rel="noopener nofollow" '
            f'title="Instagram" aria-label="Instagram">{INSTAGRAM_ICON_SVG}</a>')


def aviso_card(aviso, termino_busqueda=None, badge_mode=None):
    badge_html = ""
    if badge_mode == "plan" and aviso["plan_nombre"] in ("Destacado", "Premium"):
        badge_html = plan_badge(aviso["plan_nombre"])
    elif badge_mode == "nuevo" and es_nuevo(aviso):
        badge_html = badge("Nuevo", "ok")
    verificado_html = ('<span class="check" title="Negocio verificado">'
        '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">'
        '<path fill="#5B9EE8" d="M22.9 12.0 L22.62 12.7 L21.86 13.3 L20.83 13.76 L19.78 14.08 L18.96 14.36 L18.56 14.72 L18.6 15.25 L18.97 16.02 L19.48 17.0 L19.89 18.06 L20.0 19.02 L19.71 19.71 L19.02 20.0 L18.06 19.89 L17.0 19.48 L16.03 18.97 L15.25 18.6 L14.72 18.56 L14.36 18.96 L14.08 19.78 L13.76 20.83 L13.3 21.86 L12.7 22.62 L12.0 22.9 L11.3 22.62 L10.7 21.86 L10.24 20.83 L9.92 19.78 L9.64 18.96 L9.28 18.56 L8.75 18.6 L7.98 18.97 L7.0 19.48 L5.94 19.89 L4.98 20.0 L4.29 19.71 L4.0 19.02 L4.11 18.06 L4.52 17.0 L5.03 16.02 L5.4 15.25 L5.44 14.72 L5.04 14.36 L4.22 14.08 L3.17 13.76 L2.14 13.3 L1.38 12.7 L1.1 12.0 L1.38 11.3 L2.14 10.7 L3.17 10.24 L4.22 9.92 L5.04 9.64 L5.44 9.28 L5.4 8.75 L5.03 7.98 L4.52 7.0 L4.11 5.94 L4.0 4.98 L4.29 4.29 L4.98 4.0 L5.94 4.11 L7.0 4.52 L7.97 5.03 L8.75 5.4 L9.28 5.44 L9.64 5.04 L9.92 4.22 L10.24 3.17 L10.7 2.14 L11.3 1.38 L12.0 1.1 L12.7 1.38 L13.3 2.14 L13.76 3.17 L14.08 4.22 L14.36 5.04 L14.72 5.44 L15.25 5.4 L16.02 5.03 L17.0 4.52 L18.06 4.11 L19.02 4.0 L19.71 4.29 L20.0 4.98 L19.89 5.94 L19.48 7.0 L18.97 7.97 L18.6 8.75 L18.56 9.28 L18.96 9.64 L19.78 9.92 L20.83 10.24 L21.86 10.7 L22.62 11.3 Z"/>'
        '<path fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" d="M6.26 12.82L9.54 16.1L17.74 7.9"/>'
        '</svg></span>') if aviso["verificado"] else ""
    click_attr = f' data-termino="{esc(termino_busqueda)}"' if termino_busqueda else ""
    fav_attrs = f'data-fav-id="{aviso["id"]}"'
    foto_url = aviso.get("foto_url")
    foto_style_attr = ' style="object-position:top"' if aviso.get("foto_posicion") == "arriba" else ""
    fotos = ([foto_url] + (aviso.get("fotos_extra") or [])) if foto_url else []
    es_carrusel = len(fotos) >= 2
    if es_carrusel:
        slides = "".join(
            f'<img src="{esc(url)}" alt="{esc(aviso["titulo"])}" loading="eager" class="card-carousel-slide"{foto_style_attr}>'
            for url in fotos)
        dots = "".join(
            f'<span class="card-carousel-dot{" is-active" if i == 0 else ""}"></span>' for i in range(len(fotos)))
        foto_html = (f'<div class="card-carousel" data-carousel>'
                     f'<div class="card-carousel-track">{slides}</div>'
                     f'<div class="card-carousel-dots">{dots}</div></div>')
    elif foto_url:
        foto_html = f'<img src="{esc(foto_url)}" alt="{esc(aviso["titulo"])}"{foto_style_attr}>'
    else:
        foto_html = f'<span class="icon-tile"><span class="card-icon">{aviso["icono"]}</span></span>'
    chevrones_html = ("""
  <button type="button" class="card-carousel-nav card-carousel-prev" data-carousel-prev aria-label="Foto anterior">‹</button>
  <button type="button" class="card-carousel-nav card-carousel-next" data-carousel-next aria-label="Foto siguiente">›</button>""" if es_carrusel else "")
    return f"""
<article class="card" style="--card-accent:{esc(aviso['color'])}"{click_attr} data-aviso-id="{aviso['id']}">
  <a class="card-photo{' has-foto' if foto_url else ''}" href="{'/publicar' if aviso.get('es_demo') else f"/avisos/{aviso['id']}"}">
    {foto_html}
    {badge_html}
  </a>{chevrones_html}
  {"" if aviso.get('es_demo') else f'<button class="fav-btn" type="button" {fav_attrs} title="Guardar en favoritos" aria-label="Guardar en favoritos">☆</button>'}
  <div class="card-body">
    {f'''<a class="card-title" href="/publicar">¡Publícate hoy y empieza a vender más!</a>
    <div class="card-meta eyebrow-star"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2l2.9 6.6 7.1.7-5.5 4.8 1.7 6.9L12 17.3l-6.2 3.7 1.7-6.9L2 9.3l7.1-.7L12 2z"/></svg><span>Encuentra tu categoría</span></div>
    <p class="card-desc">Miles de personas en Talca buscan y contactan negocios cada semana. Publícate hoy.</p>
    <a class="btn btn-primary btn-block" href="/publicar">
      Publicar mi negocio →
    </a>''' if aviso.get('es_demo') else f'''<a class="card-title" href="/avisos/{aviso['id']}">{esc(aviso['titulo'])}</a>
    <div class="card-meta">
      <span>{esc(aviso['negocio_nombre'])} {verificado_html}</span>
      <span class="dot">·</span>
      <span>{esc(aviso['comuna'])}</span>
    </div>
    <div class="card-cat mono">{aviso['icono']} {esc(aviso['categoria_nombre'])}</div>
    <p class="card-desc">{esc(extracto(aviso.get('descripcion')))}</p>
    <a class="btn btn-whatsapp btn-block" href="/avisos/{aviso['id']}">
      Ver detalle
    </a>'''}
  </div>
</article>"""


def cards_grid(avisos, termino_busqueda=None, vacio_msg="No hay avisos que coincidan con tu búsqueda.", badge_mode=None):
    if not avisos:
        return f'<p class="empty-state">{esc(vacio_msg)}</p>'
    return '<div class="grid">' + "".join(aviso_card(a, termino_busqueda, badge_mode=badge_mode) for a in avisos) + "</div>"


def carousel(avisos, vacio_msg="Todavía no hay avisos destacados. ¡Sé el primero en publicar tu negocio!", badge_mode=None):
    if not avisos:
        return f'<p class="empty-state">{esc(vacio_msg)}</p>'
    items = "".join(aviso_card(a, badge_mode=badge_mode) for a in avisos)
    return f"""
<div class="carousel">
  <button class="carousel-arrow carousel-prev" type="button" aria-label="Ver anteriores">‹</button>
  <div class="carousel-track">{items}</div>
  <button class="carousel-arrow carousel-next" type="button" aria-label="Ver siguientes">›</button>
</div>"""


def categorias_pills(categorias, activa_slug=None):
    items = []
    for c in categorias:
        cls = "pill active" if c["slug"] == activa_slug else "pill"
        items.append(f'<a class="{cls}" href="/avisos?categoria={c["slug"]}">{c["icono"]} {esc(c["nombre"])}</a>')
    return '<div class="pills">' + "".join(items) + "</div>"


_ICONOS_RUBRO_PATHS = {
    "aluminios": '<path d="M5 21h6"/><path d="M7 21V4"/><path d="M7 5h11"/><path d="M15 5v4"/><path d="M18 5l-3 4"/>',
    "clases": '<path d="M4 5c3-1.5 6-1.5 8 0v14c-2-1.5-5-1.5-8 0V5Z"/><path d="M20 5c-3-1.5-6-1.5-8 0v14c2-1.5 5-1.5 8 0V5Z"/>',
    "contabilidad": '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M3 20h18"/>',
    "electricidad": '<path d="M13 3 5 13h6l-1 8 8-10h-6l1-8Z"/>',
    "gasfiteria": '<path d="M20 5a3.5 3.5 0 0 1-4.6 3.3L7 16.7a1.8 1.8 0 1 1-2.5-2.5l8.4-8.4A3.5 3.5 0 1 1 20 5Z"/>',
    "jardineria": '<path d="M4 20c8 0 14-6 14-14 0-1 0-2-.3-3C10 4 4 10 4 18c0 .7 0 1.4.1 2Z"/><path d="M4 20 15 9"/>',
    "panaderia": '<path d="M4 12c0-4.5 3.5-8 8-8s8 3.5 8 8-2 8-8 8-8-3.5-8-8Z"/><path d="M8 9l2 2M12 8l2 3M16 9l2 2"/>',
    "belleza": '<circle cx="6" cy="6" r="2.2"/><circle cx="6" cy="18" r="2.2"/><path d="M8 7.5 20 19M8 16.5 20 5"/>',
    "tecnologia": '<rect x="4" y="5" width="16" height="10" rx="1.2"/><path d="M2 19h20"/>',
    "vidrieria": '<rect x="4" y="4" width="16" height="16" rx="1.5"/><path d="M12 4v16M4 12h16"/>',
}


def icono_rubro_svg(slug, emoji_fallback="📌"):
    paths = _ICONOS_RUBRO_PATHS.get(slug)
    if not paths:
        return f'<span class="category-icon-emoji">{emoji_fallback}</span>'
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths}</svg>')


def categorias_grid(categorias):
    """Atajos visuales para descubrir rubros sin depender del buscador."""
    colores = ["#E85D5D", "#2B80D8", "#0AA39A", "#7D5CD6", "#D9921B", "#28A968"]
    items = []
    for i, c in enumerate(categorias):
        color = colores[i % len(colores)]
        items.append(
            f'<a class="category-card" style="--category-accent:{color}; --i:{i}" data-reveal '
            f'href="/avisos?categoria={quote(c["slug"])}">'
            f'<span class="category-icon">{icono_rubro_svg(c["slug"], c["icono"])}</span>'
            f'<span>{esc(c["nombre"])}</span><span class="category-arrow" aria-hidden="true">→</span></a>'
        )
    return '<div class="category-grid">' + "".join(items) + "</div>"
