"""
Talcadatos — servidor de desarrollo.

Implementa el MVP del PRD (secciones 6 y 7) con la libreria estandar de
Python (http.server + sqlite3), porque este entorno no tiene Node/npm
instalado. La estructura de rutas y datos sigue el PRD para poder migrarse
mas adelante a Next.js + Postgres + pgvector segun la seccion 12 sin
rediseñar nada.

Uso:
    python3 server.py [puerto]
"""
import sys
import os
import io
import re
import csv
import json
import secrets
import datetime
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlsplit, parse_qs, parse_qsl, quote, unquote

import db
import search
import ogimage
import templates as t

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
OG_CACHE_DIR = os.path.join(BASE_DIR, "og_cache")
os.makedirs(OG_CACHE_DIR, exist_ok=True)

SESSIONS = {}  # token -> {"usuario": str, "rol": "super_admin" | "moderador"}
STATIC_EXPORT_LOCK = threading.Lock()


# ---------------------------------------------------------------- helpers

def qs(query_string):
    return {k: v[0] for k, v in parse_qs(query_string).items()}


def current_admin(handler):
    cookie = SimpleCookie(handler.headers.get("Cookie", ""))
    token = cookie["talca_admin"].value if "talca_admin" in cookie else None
    return SESSIONS.get(token)


def is_admin(handler):
    return current_admin(handler) is not None


def auditar(handler, accion, detalle=""):
    admin = current_admin(handler)
    usuario = admin["usuario"] if admin else "?"
    db.crear_auditoria(usuario, accion, detalle)


def sincronizar_sitio_estatico():
    """Publica en docs/ los datos que se cambiaron en el admin.

    La vista dinámica (talcadatos.cl) lee Firestore en cada petición; docs/
    es solo el espejo para GitHub Pages, así que regenerarlo no debe demorar
    la respuesta al administrador -- corre en un hilo aparte. Un fallo de
    exportación no revierte el cambio ya guardado en Firestore.
    """
    def _tarea():
        with STATIC_EXPORT_LOCK:
            try:
                import export_static
                export_static.exportar()
            except Exception as exc:
                sys.stderr.write(f"No se pudo sincronizar la versión estática: {exc!r}\n")
    threading.Thread(target=_tarea, daemon=True).start()
    return True


def mensaje_sincronizacion(mensaje, actualizado):
    sufijo = " La versión estática también se actualizó." if actualizado else (
        " El sitio dinámico ya tiene el cambio; la versión estática se actualizará en la próxima publicación.")
    return mensaje + sufijo


def get_flash(handler):
    cookie = SimpleCookie(handler.headers.get("Cookie", ""))
    if "flash" in cookie and cookie["flash"].value:
        return unquote(cookie["flash"].value)
    return None


def _cookie_headers(set_cookie=None, clear_cookie=False, flash=None, clear_flash=False):
    headers = []
    if set_cookie:
        headers.append(("Set-Cookie", f"talca_admin={set_cookie}; Path=/; HttpOnly; SameSite=Lax"))
    if clear_cookie:
        headers.append(("Set-Cookie", "talca_admin=; Path=/; HttpOnly; Max-Age=0"))
    if flash:
        headers.append(("Set-Cookie", f"flash={quote(flash)}; Path=/; Max-Age=10; SameSite=Lax"))
    if clear_flash:
        headers.append(("Set-Cookie", "flash=; Path=/; Max-Age=0"))
    return headers


def render(handler, html, status=200, set_cookie=None, clear_cookie=False, clear_flash=False):
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    for k, v in _cookie_headers(set_cookie, clear_cookie, clear_flash=clear_flash):
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)


def render_json(handler, data, status=200):
    body = json.dumps(data).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def render_png(handler, data, status=200):
    handler.send_response(status)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=3600")
    handler.end_headers()
    handler.wfile.write(data)


def render_csv(handler, filename, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    data = buf.getvalue().encode("utf-8-sig")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def money(n):
    return f"{n:,}".replace(",", ".")


def redirect(handler, location, set_cookie=None, clear_cookie=False, flash=None):
    handler.send_response(302)
    handler.send_header("Location", location)
    for k, v in _cookie_headers(set_cookie, clear_cookie, flash=flash):
        handler.send_header(k, v)
    handler.end_headers()


def not_found(handler):
    render(handler, t.layout("No encontrado", "<div class='panel'><h1>404</h1><p>Esa página no existe.</p>"
                              "<a class='btn' href='/'>Volver al inicio</a></div>"), status=404)


def server_error(handler, exc):
    sys.stderr.write(f"ERROR {exc!r}\n")
    render(handler, t.layout(
        "Error", "<div class='panel'><h1>Algo salió mal</h1>"
        "<p>Ocurrió un error inesperado. Intenta de nuevo en unos segundos.</p>"
        "<a class='btn' href='/'>Volver al inicio</a></div>"), status=500)


def _origin(handler):
    host = handler.headers.get("Host", "localhost")
    proto = handler.headers.get("X-Forwarded-Proto", "http")
    return f"{proto}://{host}"


# ------------------------------------------------------- modo "en construcción"
# El sitio publico muestra una portada generica mientras se sigue afinando.
# La ruta secreta PREVIEW_PATH deja una cookie de larga duracion en el
# navegador que la visita y de ahi en adelante ese navegador ve el sitio
# real y completo, en las mismas URLs de siempre (sin prefijos ni reescritura
# de enlaces, para no arriesgar romper nada de lo ya construido).
PREVIEW_PATH = "/esteeselsitiodeprueba"
PREVIEW_COOKIE = "talca_preview"
_RUTAS_LIBRES_EXACTAS = ("/static", "/sw.js", "/api/mp-webhook")
_RUTAS_LIBRES_PREFIJOS = ("/static/", "/og/")


def _ruta_libre(path):
    """Rutas que siguen respondiendo igual sin importar el modo construccion
    (assets compartidos que el propio sitio necesita para funcionar)."""
    return path in _RUTAS_LIBRES_EXACTAS or any(path.startswith(p) for p in _RUTAS_LIBRES_PREFIJOS)


def _tiene_acceso_preview(handler):
    cookie = SimpleCookie(handler.headers.get("Cookie", ""))
    return PREVIEW_COOKIE in cookie and cookie[PREVIEW_COOKIE].value == "ok"


def _otorgar_preview(handler):
    handler.send_response(302)
    handler.send_header("Location", "/")
    handler.send_header("Set-Cookie", f"{PREVIEW_COOKIE}=ok; Path=/; Max-Age=15552000; HttpOnly; SameSite=Lax")
    handler.end_headers()


def pagina_en_construccion(handler):
    html = """<!doctype html>
<html lang="es-CL">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Talcadatos — Volvemos pronto</title>
<style>
  :root{color-scheme:light}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#FBF6F1;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,sans-serif;
       color:#2A2622;padding:24px;text-align:center}
  .card{max-width:420px}
  svg{width:120px;height:120px;margin:0 auto 20px}
  h1{font-size:1.5rem;margin:0 0 10px}
  p{font-size:1rem;line-height:1.5;color:#6B6259;margin:0}
  .brand{font-weight:800;color:#E85D5D}
</style>
</head>
<body>
  <div class="card">
    <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
      <circle cx="50" cy="50" r="48" fill="#F4E3DC"/>
      <g stroke="#E85D5D" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" fill="none">
        <path d="M32 62 L52 42 a6 6 0 0 1 8 8 L40 70 a6 6 0 0 1 -8 -8Z"/>
        <path d="M58 30 a10 10 0 1 0 12 12 l-6 -2 -4 -4 -2 -6Z" fill="#E85D5D" stroke="none"/>
      </g>
      <circle cx="50" cy="50" r="48" fill="none" stroke="#E8A05D" stroke-width="2" stroke-dasharray="4 6"/>
    </svg>
    <h1><span class="brand">📌 Talcadatos</span></h1>
    <p>Estamos preparando cosas nuevas. Vuelve a visitarnos pronto.</p>
  </div>
</body>
</html>"""
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


HONEYPOT_FIELD = "pagina_web"
HONEYPOT_HTML = (f'<input type="text" name="{HONEYPOT_FIELD}" class="hp-field" tabindex="-1" '
                  'autocomplete="off" aria-hidden="true">')


def _client_ip(handler):
    xff = handler.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return handler.client_address[0]


def _es_ajax(handler):
    return handler.headers.get("X-Requested-With") == "fetch"


def _es_bot(form):
    return bool(form.get(HONEYPOT_FIELD, "").strip())


def require_admin(handler):
    if not is_admin(handler):
        if _es_ajax(handler):
            _responder_error_ajax(handler, "Tu sesión expiró. Recarga la página e inicia sesión de nuevo.", 401)
        else:
            redirect(handler, "/admin/login", flash="Tu sesión expiró. Inicia sesión de nuevo.")
        return False
    return True


def require_role(handler, roles):
    admin = current_admin(handler)
    if not admin:
        if _es_ajax(handler):
            _responder_error_ajax(handler, "Tu sesión expiró. Recarga la página e inicia sesión de nuevo.", 401)
        else:
            redirect(handler, "/admin/login", flash="Tu sesión expiró. Inicia sesión de nuevo.")
        return False
    if admin["rol"] not in roles:
        render(handler, t.layout(
            "Sin permiso", "<div class='panel'><h1>No tienes permiso para ver esto</h1>"
            "<p>Tu rol es <code>" + t.esc(admin["rol"]) + "</code>. Esta sección es solo para: "
            + ", ".join(f"<code>{t.esc(r)}</code>" for r in roles) + ".</p>"
            "<a class='btn' href='/admin'>Volver al dashboard</a></div>",
            active="admin", admin=True), status=403)
        return False
    return True


# --------------------------------------------------------------- publico

def home(handler):
    sitio = db.get_contenido_sitio()
    activos = db.get_avisos(estado="activo", orden="destacados")
    destacados = [a for a in activos if a["plan_prioridad"] > 0][:6]
    recientes = db.get_avisos(estado="activo", orden="recientes", limit=8)
    tendencias = db.get_terminos_mas_buscados(4)
    if not tendencias:
        tendencias = [
            {"termino_busqueda": "gásfiter", "n": 42},
            {"termino_busqueda": "veterinaria", "n": 31},
            {"termino_busqueda": "notebook", "n": 24},
            {"termino_busqueda": "pan amasado", "n": 18},
        ]

    links_hoy = "".join(
        f'<a class="today-link" href="/avisos?q={quote(r["termino_busqueda"])}">'
        f'<span>{t.esc(r["termino_busqueda"])}</span><span aria-hidden="true">→</span></a>'
        for r in tendencias
    )
    trend_rows = "".join(
        f'<li><span class="trend-rank">{i + 1}</span><a href="/avisos?q={quote(r["termino_busqueda"])}">'
        f'{t.esc(r["termino_busqueda"])}</a><span class="trend-up">↑</span></li>'
        for i, r in enumerate(tendencias[:3])
    )

    body = f"""
<section class="hero" style="background-image: linear-gradient(180deg, rgba(10,12,18,.28) 0%, rgba(10,12,18,.46) 100%), url('{t.esc(sitio['hero_imagen_url'])}')">
  <p class="hero-location">📍 {t.esc(sitio['hero_ubicacion'])}</p>
  <h1>{t.esc(sitio['hero_titulo'])}</h1>
  <p class="hero-sub">{t.esc(sitio['hero_bajada'])}</p>
  <form class="search-box" id="search-form" autocomplete="off">
    <span class="search-icon">🔎</span>
    <input id="search-input" name="q" type="text" placeholder="{t.esc(sitio['hero_placeholder'])}">
    <button class="btn btn-primary" type="submit">Buscar</button>
    <div id="search-results" class="search-results" hidden></div>
  </form>
  <p class="hero-hint">{t.esc(sitio['hero_ayuda'])}</p>
</section>

<section class="trust-strip" data-reveal aria-label="Beneficios de Talcadatos">
  <div style="--trust-accent:#1DA851">
    <span class="trust-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21s7-6.5 7-12a7 7 0 1 0-14 0c0 5.5 7 12 7 12Z"/><circle cx="12" cy="9" r="2.3"/></svg></span>
    <p><strong>Hecho en Talca</strong><small>Datos y negocios de tu ciudad.</small></p>
  </div>
  <div style="--trust-accent:#0AA39A">
    <span class="trust-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h16v11H8l-4 4V5Z"/></svg></span>
    <p><strong>Contacto directo</strong><small>Habla por WhatsApp, sin intermediarios.</small></p>
  </div>
  <div style="--trust-accent:#2B80D8">
    <span class="trust-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 16l6-6 4 4 6-8"/><path d="M15 6h5v5"/></svg></span>
    <p><strong>Oportunidades reales</strong><small>Encuentra o publica lo que hace falta.</small></p>
  </div>
</section>

<section class="section section-featured" data-reveal>
  <div class="section-head">
    <div><span class="eyebrow">{t.esc(sitio['destacados_eyebrow'])}</span><h2>{t.esc(sitio['destacados_titulo'])}</h2></div>
    <a href="/avisos">Ver todos →</a>
  </div>
  {t.carousel(destacados, badge_mode="plan")}
</section>

<section class="section local-now" data-reveal>
  <div class="section-head"><div><span class="eyebrow">{t.esc(sitio['hoy_eyebrow'])}</span><h2>{t.esc(sitio['hoy_titulo'])}</h2></div></div>
  <div class="local-now-grid">
    <div class="today-card">
      <span class="section-icon">🔥</span>
      <h3>Lo más buscado hoy</h3>
      <p>Atajos a lo que Talca está necesitando ahora.</p>
      <div class="today-links">{links_hoy}</div>
    </div>
    <div class="today-card today-card-soft">
      <span class="section-icon">💬</span>
      <h3>Resuelve directo</h3>
      <p>Contacta a cada negocio por WhatsApp, sin intermediarios ni comisiones.</p>
      <a class="btn btn-ghost btn-sm" href="/avisos?orden=populares">Ver más contactados</a>
    </div>
  </div>
</section>

<section class="section" data-reveal>
  <div class="section-head">
    <div><span class="eyebrow">Nuevos en Talcadatos</span><h2>Recién publicados</h2></div>
    <a href="/avisos">Ver todos →</a>
  </div>
  {t.cards_grid(recientes, badge_mode="nuevo")}
</section>

<section class="section local-story" data-reveal>
  <figure class="local-story-visual">
    <img src="{t.esc(sitio['explorar_imagen_url'])}" alt="Emprendedores atendiendo una feria de comercio local" loading="lazy">
    <figcaption><span></span> Cerca, útil y hecho por personas</figcaption>
  </figure>
  <div class="local-story-copy">
    <span class="eyebrow">Comercio que se siente cerca</span>
    <h2>Descubre a quien hace las cosas bien, a unas cuadras de ti.</h2>
    <p>Desde oficios que resuelven el día hasta productos y clases que merecen ser encontrados. Talcadatos pone lo local primero.</p>
    <div class="local-story-points">
      <span>◆ Información clara</span><span>◆ Negocios verificables</span><span>◆ Atención humana</span>
    </div>
    <a class="btn btn-ghost" href="/avisos">Explorar negocios locales <span aria-hidden="true">→</span></a>
  </div>
</section>

<section class="section trend-section" data-reveal>
  <div class="trend-copy">
    <span class="eyebrow">{t.esc(sitio['tendencias_eyebrow'])}</span>
    <h2>{t.esc(sitio['tendencias_titulo'])}</h2>
    <p>{t.esc(sitio['tendencias_bajada'])}</p>
    <a href="/avisos" class="text-link">Explorar todos los avisos →</a>
  </div>
  <ol class="trend-list">{trend_rows}</ol>
</section>

<section class="need-cta" data-reveal>
  <div><span class="eyebrow">{t.esc(sitio['necesidad_eyebrow'])}</span><h2>{t.esc(sitio['necesidad_titulo'])}</h2>
  <p>{t.esc(sitio['necesidad_bajada'])}</p></div>
  <a class="btn btn-primary btn-lg" href="/necesito">{t.esc(sitio['necesidad_boton'])}</a>
</section>

<section class="how" data-reveal>
  <div class="how-step"><span class="how-n">1</span><h3>Busca lo que necesitas</h3><p>Escribe en el buscador o explora por rubro.</p></div>
  <div class="how-step"><span class="how-n">2</span><h3>Elige con confianza</h3><p>Revisa categoría, ubicación, horario y verificación.</p></div>
  <div class="how-step"><span class="how-n">3</span><h3>Contacta y resuelve</h3><p>Un clic basta para hablar directo por WhatsApp.</p></div>
</section>

<section class="business-cta" data-reveal>
  <div class="business-cta-copy"><span class="eyebrow">{t.esc(sitio['pymes_eyebrow'])}</span><h2>{t.esc(sitio['pymes_titulo'])}</h2>
  <p>{t.esc(sitio['pymes_bajada'])}</p><a class="btn btn-ghost btn-lg" href="/publicar">{t.esc(sitio['pymes_boton'])} <span aria-hidden="true">→</span></a></div>
  <figure class="business-cta-visual"><img src="{t.esc(sitio['pymes_imagen_url'])}" alt="Emprendedora preparando productos en su negocio local" loading="lazy"><figcaption>Tu vitrina también puede estar aquí.</figcaption></figure>
</section>
"""
    render(handler, t.layout("Avisos de pymes y emprendedores de Talca", body, active="home",
                              og_image=f"{_origin(handler)}/og/default.png", site=sitio))


def listado(handler, query):
    sitio = db.get_contenido_sitio()
    params = qs(query)
    q = params.get("q", "").strip()
    categoria_slug = params.get("categoria", "")
    comuna = params.get("comuna", "")
    orden = params.get("orden", "relevancia")

    categorias = db.get_categorias()
    comunas = db.get_comunas_activas()

    if q:
        avisos = search.buscar_avisos(db.get_avisos(estado="activo"), db.get_sinonimos_por_categoria(), q, limite=40)
        titulo_pagina = f'Resultados para "{q}"'
    else:
        avisos = db.get_avisos(estado="activo", categoria_slug=categoria_slug or None,
                                comuna=comuna or None, orden=orden)
        titulo_pagina = "Avisos en Talca"

    def opt(value, current, label):
        sel = " selected" if value == current else ""
        return f'<option value="{t.esc(value)}"{sel}>{t.esc(label)}</option>'

    cat_options = opt("", categoria_slug, "Todas las categorías") + "".join(
        opt(c["slug"], categoria_slug, f"{c['icono']} {c['nombre']}") for c in categorias)
    comuna_options = opt("", comuna, "Todas las comunas") + "".join(
        opt(c, comuna, c) for c in comunas)
    orden_options = "".join(
        opt(v, orden, label) for v, label in
        [("relevancia", "Relevancia"), ("recientes", "Más recientes"), ("populares", "Más contactados")])

    if q and not avisos:
        resultados_html = f"""
<div class="empty-state alerta-box">
  <p>Todavía nadie ofrece "{t.esc(q)}" en Talcadatos.</p>
  <p class="small">Déjanos tu WhatsApp y te avisamos apenas se publique un negocio de ese rubro.</p>
  <form id="alerta-form" class="form form-inline" data-termino="{t.esc(q)}">
    <input name="whatsapp" required placeholder="+56 9 1234 5678">
    <button class="btn btn-primary btn-sm" type="submit">Avísenme</button>
  </form>
</div>"""
    else:
        resultados_html = t.cards_grid(avisos, termino_busqueda=q or None, badge_mode="plan")

    body = f"""
<div class="listado-head">
  <h1 id="listado-titulo">{t.esc(titulo_pagina)}</h1>
  <form class="filters" id="listado-filtros" method="get" action="/avisos">
    {f'<input type="hidden" name="q" value="{t.esc(q)}">' if q else ""}
    <select name="categoria" data-autosubmit>{cat_options}</select>
    <select name="comuna" data-autosubmit>{comuna_options}</select>
    <select name="orden" data-autosubmit>{orden_options}</select>
  </form>
</div>
<div id="listado-resultados">
{resultados_html}
</div>
"""
    render(handler, t.layout(titulo_pagina, body, active="avisos", site=sitio))


def _necesito_body(categorias, sitio, form=None, errores=None):
    form = form or {}
    errores = errores or []
    value = lambda field, default="": t.esc(form.get(field, default))
    options = "".join(
        f'<option value="{t.esc(c["id"])}"'
        f'{" selected" if c["id"] == form.get("categoria_id") else ""}>'
        f'{c["icono"]} {t.esc(c["nombre"])}</option>'
        for c in categorias
    )
    errors_html = ("<div class='form-errors'><ul>" + "".join(f"<li>{t.esc(e)}</li>" for e in errores) +
                   "</ul></div>") if errores else ""
    return f"""
<section class="need-page">
  <div class="need-page-intro">
    <span class="eyebrow">Recomendaciones de la comunidad</span>
    <h1>{t.esc(sitio['necesito_titulo'])}</h1>
    <p class="lede">{t.esc(sitio['necesito_bajada'])}</p>
    <div class="trust-points"><span>✓ Ayuda a traer nuevos negocios a Talca</span><span>✓ Sin costo para ti</span><span>✓ Te avisamos por WhatsApp si calza</span></div>
  </div>
  <div class="panel need-form-panel">
    <h2>Cuéntanos qué te gustaría ver</h2>
    {errors_html}
    <form method="post" action="/necesito" class="form" id="necesito-form">
      {HONEYPOT_HTML}
      <label>¿En qué rubro?
        <select name="categoria_id" required><option value="">Selecciona una categoría</option>{options}</select>
      </label>
      <label>¿Qué te gustaría ver?
        <textarea name="descripcion" required maxlength="500" rows="4" placeholder="Ej: Una veterinaria de urgencia cerca del centro.">{value("descripcion")}</textarea>
      </label>
      <label>Sector o comuna
        <input name="sector" required maxlength="120" value="{value("sector", "Talca")}" placeholder="Ej: Las Rastras, Talca">
      </label>
      <label>WhatsApp para responderte
        <input name="whatsapp" required inputmode="tel" placeholder="+56 9 1234 5678" value="{value("whatsapp")}">
      </label>
      <button class="btn btn-primary btn-lg" type="submit">Enviar recomendación</button>
      <p class="hint">Tu número no se publica: solo se usa para avisarte si aparece un negocio que calce con lo que pediste.</p>
    </form>
  </div>
</section>
"""


def necesito_form(handler, ok=False, form=None, errores=None):
    categorias = db.get_categorias()
    sitio = db.get_contenido_sitio()
    if ok:
        body = """
<div class="panel panel-ok">
  <div class="success-icon">✓</div>
  <h1>¡Gracias por tu recomendación!</h1>
  <p>La tenemos en cuenta para recomendar nuevos comercios en Talca. Si aparece un negocio que calza, te contactamos por WhatsApp.</p>
  <a class="btn btn-primary" href="/avisos">Seguir explorando</a>
</div>"""
        return render(handler, t.layout("Recomendación enviada", body, active="necesito", site=sitio))
    render(handler, t.layout("Recomendar un negocio", _necesito_body(categorias, sitio, form, errores), active="necesito", site=sitio))


def necesito_submit(handler, form):
    if _es_bot(form):
        return redirect(handler, "/necesito?ok=1")
    if not db.verificar_limite(_client_ip(handler), "necesito"):
        return necesito_form(handler, form=form,
                              errores=["Ya enviaste varias recomendaciones seguidas. Espera un poco antes de volver a intentar."])
    categorias = db.get_categorias()
    categoria_ids = {c["id"] for c in categorias}
    descripcion = form.get("descripcion", "").strip()
    sector = form.get("sector", "").strip()
    whatsapp = form.get("whatsapp", "").strip()
    errores = []
    if form.get("categoria_id") not in categoria_ids:
        errores.append("Elige el rubro que mejor representa tu necesidad.")
    if len(descripcion) < 12:
        errores.append("Cuéntanos un poco más sobre lo que necesitas.")
    if not sector:
        errores.append("Indica el sector o comuna donde lo necesitas.")
    if len("".join(c for c in whatsapp if c.isdigit())) < 8:
        errores.append("Ingresa un WhatsApp válido con código de país.")
    if errores:
        return necesito_form(handler, form=form, errores=errores)

    cuando = form.get("cuando") if form.get("cuando") in ("Hoy", "Esta semana", "Este mes", "Flexible") else "Flexible"
    db.crear_necesidad(form["categoria_id"], descripcion[:500], sector[:120], cuando, whatsapp[:40])
    redirect(handler, "/necesito?ok=1")


def detalle(handler, aviso_id, query="", contabilizar=True):
    sitio = db.get_contenido_sitio()
    reportado = qs(query).get("reportado") == "1"
    aviso = db.get_aviso(aviso_id)
    if not aviso or aviso["estado"] != "activo":
        return not_found(handler)

    if contabilizar:
        db.registrar_evento("vista", aviso_id=aviso_id)
        db.incrementar_vistas(aviso_id)

    relacionados = db.get_avisos(estado="activo", categoria_slug=aviso["categoria_slug"],
                                  excluir_id=str(aviso_id), orden="destacados", limit=3)

    wa = t.whatsapp_url(aviso["whatsapp"], aviso["negocio_nombre"], aviso["titulo"])
    destacado_html = t.plan_badge(aviso["plan_nombre"]) if aviso["plan_nombre"] != "Gratis" else ""
    verificado_html = '<span class="check">✔ Negocio verificado</span>' if aviso["verificado"] else ""

    canonical = f"{_origin(handler)}/avisos/{aviso_id}"
    mapa_url = ("https://www.google.com/maps/search/?api=1&query=" +
                quote(f"{aviso['negocio_nombre']} {aviso['comuna']} Chile"))
    qr_url = f"/avisos/{aviso_id}/qr.png"
    reportado_html = ('<p class="flash" style="margin-top:16px">Gracias, tu reporte quedó registrado para revisión.'
                       '</p>') if reportado else ""
    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": aviso["negocio_nombre"],
        "description": aviso["descripcion"],
        "areaServed": aviso["comuna"],
        "address": {"@type": "PostalAddress", "addressLocality": aviso["comuna"], "addressCountry": "CL"},
        "telephone": aviso["whatsapp"],
        "url": canonical,
    }, ensure_ascii=False)

    foto_url = aviso.get("foto_url")
    foto_html = (f'<img src="{t.esc(foto_url)}" alt="{t.esc(aviso["titulo"])}" loading="eager">'
                 if foto_url else f'<span class="icon-tile big"><span class="card-icon big">{aviso["icono"]}</span></span>')
    fotos_extra = aviso.get("fotos_extra") or []
    galeria_html = ("<div class=\"detalle-galeria\">" + "".join(
        f'<a href="{t.esc(url)}" target="_blank" rel="noopener"><img src="{t.esc(url)}" alt="{t.esc(aviso["titulo"])}" loading="lazy"></a>'
        for url in fotos_extra
    ) + "</div>") if fotos_extra else ""
    body = f"""
<div class="detalle">
  <div class="detalle-photo{' has-foto' if foto_url else ''}" style="--card-accent:{t.esc(aviso['color'])}">
    {foto_html}
    {destacado_html}
    <button class="fav-btn" type="button" data-fav-id="{aviso['id']}" data-titulo="{t.esc(aviso['titulo'])}"
       data-negocio="{t.esc(aviso['negocio_nombre'])}" data-comuna="{t.esc(aviso['comuna'])}"
       data-categoria="{t.esc(aviso['categoria_nombre'])}" data-icono="{aviso['icono']}"
       data-color="{t.esc(aviso['color'])}" data-verificado="{'1' if aviso['verificado'] else ''}"
       data-plan="{t.esc(aviso['plan_nombre'])}"
       title="Guardar en favoritos" aria-label="Guardar en favoritos">☆</button>
  </div>
  <div class="detalle-body">
    <div class="mono detalle-cat">{aviso['icono']} {t.esc(aviso['categoria_nombre'])} · {t.esc(aviso['comuna'])}</div>
    <h1>{t.esc(aviso['titulo'])}</h1>
    <div class="detalle-negocio">{t.esc(aviso['negocio_nombre'])} {verificado_html}</div>
    <p class="detalle-desc">{t.esc(aviso['descripcion'])}</p>
    {f'<p class="detalle-horario"><strong>Horario:</strong> {t.esc(aviso["horario"])}</p>' if aviso["horario"] else ""}
    {reportado_html}
    <a class="btn btn-whatsapp btn-lg" href="{wa}" target="_blank" rel="noopener"
       data-aviso-id="{aviso['id']}" data-wa-click="1">
       💬 Escribir por WhatsApp
    </a>
    <div class="detalle-share">
      <button class="btn btn-ghost" type="button" data-share-btn>Compartir aviso</button>
      <a class="btn btn-ghost" href="{mapa_url}" target="_blank" rel="noopener">📍 Ver en el mapa</a>
      <details class="report-details">
        <summary class="btn btn-ghost report-summary">Reportar aviso</summary>
        <form method="post" action="/avisos/{aviso_id}/reportar" class="form report-form">
          {HONEYPOT_HTML}
          <textarea name="motivo" rows="2" required placeholder="¿Qué está mal con este aviso? Ej: negocio cerrado, información falsa..."></textarea>
          <button class="btn btn-bad btn-sm" type="submit">Enviar reporte</button>
        </form>
      </details>
    </div>
    <div class="qr-block">
      <img src="{qr_url}" alt="Código QR de este aviso" width="110" height="110" loading="lazy">
      <span class="small">Escanea para abrir este aviso desde el celular, o imprime el QR en tu local.</span>
    </div>
  </div>
</div>
{galeria_html}
{"<section class='section'><h2>También te puede servir</h2>" + t.cards_grid(relacionados, badge_mode="plan") + "</section>" if relacionados else ""}
"""
    resumen = aviso["descripcion"][:157] + "…" if len(aviso["descripcion"]) > 160 else aviso["descripcion"]
    render(handler, t.layout(
        aviso["titulo"], body, active="avisos", description=resumen,
        og_image=f"{_origin(handler)}/og/{aviso_id}.png", canonical=canonical, json_ld=json_ld, site=sitio,
    ))


def _publicar_body(categorias, sitio, form=None, errores=None):
    form = form or {}
    errores = errores or []
    cat_options = "".join(
        f'<option value="{c["id"]}"{" selected" if str(c["id"]) == form.get("categoria_id") else ""}>'
        f'{c["icono"]} {t.esc(c["nombre"])}</option>' for c in categorias)
    comuna_actual = form.get("comuna") or "Talca"
    comuna_options = "".join(
        f'<option value="{c}"{" selected" if c == comuna_actual else ""}>{c}</option>' for c in ("Talca", "Maule"))
    v = lambda campo, default="": t.esc(form.get(campo, default))
    errores_html = ('<div class="form-errors"><ul>' + "".join(f"<li>{t.esc(e)}</li>" for e in errores) +
                     "</ul></div>") if errores else ""
    return f"""
<div class="panel">
  <h1>{t.esc(sitio['publicar_titulo'])}</h1>
  <p class="lede">{t.esc(sitio['publicar_bajada'])}</p>
  {errores_html}
  <form method="post" action="/publicar" class="form" enctype="multipart/form-data">
    {HONEYPOT_HTML}
    {f'<input type="hidden" name="sub_token" value="{t.esc(form["_sub_token"])}">' if form.get('_sub_token') else ''}
    <label>Nombre del negocio
      <input name="nombre_negocio" required maxlength="120" value="{v('nombre_negocio')}">
    </label>
    <label>Foto de tu negocio o trabajo (opcional)
      <input name="foto" type="file" accept="image/jpeg,image/png,image/webp">
      <span class="hint">JPG, PNG o WebP, máximo 5 MB. Si no subes una, usamos un ícono del rubro.</span>
    </label>
    <label>WhatsApp de contacto
      <input name="whatsapp" required placeholder="+56 9 1234 5678" value="{v('whatsapp')}">
    </label>
    <label>Correo electrónico
      <input name="email" type="email" required placeholder="tucorreo@ejemplo.cl" value="{v('email')}">
      <span class="hint">Te avisamos por aquí cuando tu aviso quede publicado.</span>
    </label>
    <label>Categoría
      <select name="categoria_id" required>{cat_options}</select>
    </label>
    <label>Título del aviso
      <input name="titulo" required maxlength="120" placeholder="Ej: Instalación de ventanas y termopaneles" value="{v('titulo')}">
    </label>
    <label>Descripción
      <textarea name="descripcion" required rows="4" placeholder="Cuéntale a tus futuros clientes qué haces, cómo trabajas y qué te diferencia.">{v('descripcion')}</textarea>
    </label>
    <label>Comuna
      <select name="comuna" required>{comuna_options}</select>
    </label>
    <label>Horario de atención (opcional)
      <select data-horario-preset>
        <option value="">Elige un horario típico, o escribe el tuyo abajo…</option>
        <option value="Lun a Vie 9:00-18:00">Lun a Vie, 9:00 a 18:00</option>
        <option value="Lun a Sáb 9:00-20:00">Lun a Sáb, 9:00 a 20:00</option>
        <option value="Todos los días 9:00-21:00">Todos los días, 9:00 a 21:00</option>
        <option value="A convenir por WhatsApp">A convenir por WhatsApp</option>
      </select>
      <input name="horario" placeholder="Ej: Lun a Vie 9:00-13:00 y 15:00-19:00" value="{v('horario')}">
    </label>
    <label class="check-label">
      <input type="checkbox" name="acepto_terminos" required{' checked' if form.get('acepto_terminos') else ''}>
      <span>Declaro que la información de mi negocio es real y acepto los
      <a href="/terminos" target="_blank" rel="noopener">Términos de uso</a> y la
      <a href="/privacidad" target="_blank" rel="noopener">Política de privacidad</a> de Talcadatos.</span>
    </label>
    <button class="btn btn-primary btn-lg" type="submit">Enviar aviso</button>
  </form>
</div>
"""


def _paywall_body(sub_token=None, estado=None, error=None):
    error_html = f'<div class="form-errors"><ul><li>{t.esc(error)}</li></ul></div>' if error else ""
    if estado == "pendiente":
        return f"""
<div class="panel panel-suscripcion">
  <h1>Confirmando tu pago…</h1>
  <p>Esto puede tardar unos segundos. Si ya completaste el pago en Mercado Pago, recarga esta página.</p>
  <a class="btn btn-primary" href="/publicar?sub={t.esc(sub_token)}">Ya pagué, actualizar</a>
</div>"""
    if estado == "cancelada" and not error:
        error_html = '<div class="form-errors"><ul><li>Tu suscripción no se completó. Intenta de nuevo.</li></ul></div>'

    def fmt(n):
        return f"{n:,}".replace(",", ".")

    def tarjeta_plan(p):
        precio_html = (
            f'<span class="precio-tachado">${fmt(p["precio_normal"])}/mes</span>'
            f'<span class="precio-actual">${fmt(p["precio"])}/mes</span>'
            if p.get("precio_normal") else
            f'<span class="precio-actual">${fmt(p["precio"])}/mes</span>'
        )
        beneficios_html = "".join(f"<li>✓ {t.esc(b)}</li>" for b in p["beneficios"])
        return f"""
<div class="plan-card{' plan-card-recomendado' if p.get('recomendado') else ''}">
  {'<span class="plan-ribbon">Más elegido</span>' if p.get('recomendado') else ''}
  <h3>{t.esc(p['nombre'])}</h3>
  <div class="plan-precio">{precio_html}</div>
  <ul class="plan-beneficios">{beneficios_html}</ul>
  <button class="btn {'btn-primary' if p.get('recomendado') else 'btn-ghost'} btn-lg" type="submit" name="plan" value="{p['id']}">Elegir {t.esc(p['nombre'])}</button>
</div>"""

    tarjetas = "".join(tarjeta_plan(p) for p in PLANES_SUSCRIPCION)
    return f"""
<div class="panel panel-suscripcion">
  <h1>Publica tu negocio en Talcadatos</h1>
  <p class="lede">Para seguir creciendo, publicar un aviso en Talcadatos tiene un costo mensual. Elige el plan que más te acomode.</p>
  {error_html}
  <form method="post" action="/suscripcion/iniciar" class="form">
    {HONEYPOT_HTML}
    <label>Correo electrónico
      <input name="email" type="email" required placeholder="tucorreo@ejemplo.cl">
    </label>
    <div class="planes-grid">{tarjetas}</div>
  </form>
  <p class="hint">Pago seguro procesado por Mercado Pago. Puedes cancelar tu suscripción cuando quieras.</p>
</div>
"""


def publicar_form(handler, ok=False, sub_token=None, form=None, errores=None):
    categorias = db.get_categorias()
    sitio = db.get_contenido_sitio()

    if ok:
        body = f"""
<div class="panel panel-ok">
  <h1>¡Listo! Tu aviso fue enviado 🎉</h1>
  <p>Quedó en revisión. Nuestro equipo lo aprueba normalmente el mismo día y te avisamos por correo
  apenas se publique.</p>
  <a class="btn btn-primary" href="/">Volver al inicio</a>
</div>"""
        return render(handler, t.layout("Aviso enviado", body, active="publicar", site=sitio))

    if db.get_config_pagos()["suscripcion_activa"]:
        sub = db.get_suscripcion_pendiente(sub_token) if sub_token else None
        if not sub or sub.get("estado") != "activa":
            body = _paywall_body(sub_token, sub.get("estado") if sub else None)
            return render(handler, t.layout("Publica tu negocio", body, active="publicar", site=sitio))
        form = dict(form or {})
        form.setdefault("email", sub.get("email", ""))
        form["_sub_token"] = sub_token

    render(handler, t.layout("Publicar mi negocio", _publicar_body(categorias, sitio, form, errores), active="publicar", site=sitio))


def _validar_publicar(form, categoria_ids):
    errores = []
    if not form.get("nombre_negocio", "").strip():
        errores.append("Ingresa el nombre de tu negocio.")
    digitos = "".join(c for c in form.get("whatsapp", "") if c.isdigit())
    if len(digitos) < 8:
        errores.append("Ingresa un WhatsApp válido, con código de país (ej: +56 9 1234 5678).")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", form.get("email", "").strip()):
        errores.append("Ingresa un correo electrónico válido.")
    if form.get("categoria_id") not in categoria_ids:
        errores.append("Elige una categoría para tu aviso.")
    if not form.get("titulo", "").strip():
        errores.append("Ingresa un título para el aviso.")
    if not form.get("descripcion", "").strip():
        errores.append("Cuéntanos brevemente en qué consiste tu servicio.")
    if not form.get("comuna", "").strip():
        errores.append("Ingresa la comuna donde atiendes.")
    if not form.get("acepto_terminos"):
        errores.append("Debes aceptar los términos de uso para publicar tu negocio.")
    return errores


_EXT_POR_TIPO = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def publicar_submit(handler, form, foto=None):
    if _es_bot(form):
        return redirect(handler, "/publicar?ok=1")
    sub_token = form.get("sub_token", "")
    plan_id = "gratis"
    if db.get_config_pagos()["suscripcion_activa"]:
        sub = db.get_suscripcion_pendiente(sub_token) if sub_token else None
        if not sub or sub.get("estado") != "activa":
            return redirect(handler, "/publicar")
        plan_id = sub.get("plan_id", "gratis")
    if not db.verificar_limite(_client_ip(handler), "publicar"):
        return publicar_form(handler, sub_token=sub_token or None, form=form,
                              errores=["Ya enviaste varios avisos seguidos. Espera un poco antes de volver a intentar."])
    categorias = db.get_categorias()
    categoria_ids = {c["id"] for c in categorias}
    errores = _validar_publicar(form, categoria_ids)
    if foto and foto["content_type"] not in _EXT_POR_TIPO:
        errores.append("La foto debe ser JPG, PNG o WebP.")
    elif foto and len(foto["data"]) > 5 * 1024 * 1024:
        errores.append("La foto es muy pesada (máximo 5 MB).")
    if errores:
        return publicar_form(handler, sub_token=sub_token or None, form=form, errores=errores)

    foto_url = None
    if foto:
        ext = _EXT_POR_TIPO[foto["content_type"]]
        foto_url = db.subir_foto_aviso(foto["data"], foto["content_type"], ext)

    slug = form["categoria_id"]
    color = db.COLOR_POR_CATEGORIA.get(slug, "#5E7CE2")
    negocio_id, _token_acceso = db.crear_negocio(
        form.get("nombre_negocio", "").strip()[:120], form.get("whatsapp", "").strip(),
        plan_id=plan_id, terminos_ip=_client_ip(handler), email=form.get("email", "").strip()[:200],
        verificado=(plan_id == "premium"))
    db.crear_aviso(
        negocio_id, form.get("titulo", "").strip()[:120], form.get("descripcion", "").strip(),
        slug, form.get("comuna", "Talca").strip(), form.get("horario", "").strip(), color, estado="pendiente",
        foto_url=foto_url)
    if sub_token:
        db.actualizar_suscripcion_pendiente(sub_token, negocio_id=negocio_id)
    redirect(handler, "/publicar?ok=1")


def suscripcion_iniciar_submit(handler, form):
    sitio = db.get_contenido_sitio()
    if _es_bot(form):
        return redirect(handler, "/publicar")
    email = form.get("email", "").strip()[:200]
    plan = PLANES_SUSCRIPCION_POR_ID.get(form.get("plan", ""))
    if not plan:
        body = _paywall_body(error="Elige un plan para continuar.")
        return render(handler, t.layout("Publica tu negocio", body, active="publicar", site=sitio))
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        body = _paywall_body(error="Ingresa un correo electrónico válido.")
        return render(handler, t.layout("Publica tu negocio", body, active="publicar", site=sitio))
    sub_token = secrets.token_urlsafe(16)
    db.crear_suscripcion_pendiente(sub_token, email, plan["id"])
    origin = _origin(handler)
    try:
        resp = _crear_preapproval(email, sub_token, origin, plan["precio"], plan["nombre"])
        init_point = resp.get("init_point") or resp.get("sandbox_init_point")
    except Exception as exc:
        sys.stderr.write(f"ERROR creando preapproval MP: {exc!r}\n")
        init_point = None
    if not init_point:
        body = _paywall_body(error="No pudimos iniciar el pago. Intenta de nuevo en unos minutos.")
        return render(handler, t.layout("Publica tu negocio", body, active="publicar", site=sitio))
    db.actualizar_suscripcion_pendiente(sub_token, preapproval_id=resp.get("id"))
    redirect(handler, init_point)


def api_mp_webhook(handler, body, query):
    try:
        data = json.loads(body or "{}") if body else {}
    except Exception:
        data = {}
    parametros = qs(query)
    preapproval_id = (data.get("data") or {}).get("id") or parametros.get("id") or parametros.get("data.id")
    if not preapproval_id:
        return render_json(handler, {"ok": True})
    try:
        info = _mp_request("GET", f"/preapproval/{preapproval_id}")
    except Exception as exc:
        sys.stderr.write(f"ERROR consultando preapproval MP {preapproval_id}: {exc!r}\n")
        return render_json(handler, {"ok": True})
    external_reference = info.get("external_reference")
    status = info.get("status")
    if external_reference:
        nuevo_estado = "activa" if status == "authorized" else "cancelada" if status == "cancelled" else "pendiente"
        db.actualizar_suscripcion_pendiente(external_reference, estado=nuevo_estado, mp_status=status)
    render_json(handler, {"ok": True})


def api_buscar(handler, body):
    data = json.loads(body or "{}")
    q = (data.get("q") or "").strip()
    if len(q) < 2:
        return render_json(handler, {"resultados": []})
    avisos = search.buscar_avisos(db.get_avisos(estado="activo"), db.get_sinonimos_por_categoria(), q, limite=6)
    if not avisos:
        db.registrar_evento("busqueda_sin_resultado", termino_busqueda=q)
    resultados = [{
        "id": a["id"], "titulo": a["titulo"], "negocio": a["negocio_nombre"],
        "comuna": a["comuna"], "categoria": a["categoria_nombre"], "icono": a["icono"],
        "destacado": a["plan_nombre"] != "Gratis",
    } for a in avisos]
    render_json(handler, {"resultados": resultados})


def api_favoritos(handler, body):
    data = json.loads(body or "{}")
    ids = [str(i) for i in (data.get("ids") or [])][:60]
    avisos = []
    for aviso_id in ids:
        a = db.get_aviso(aviso_id)
        if a and a["estado"] == "activo":
            avisos.append(a)
    resultados = [{
        "id": a["id"], "titulo": a["titulo"], "negocio": a["negocio_nombre"],
        "comuna": a["comuna"], "categoria": a["categoria_nombre"], "icono": a["icono"],
        "color": a["color"], "foto_url": a.get("foto_url") or "",
        "verificado": a["verificado"], "plan": a["plan_nombre"],
    } for a in avisos]
    render_json(handler, {"resultados": resultados})


def api_evento(handler, body):
    data = json.loads(body or "{}")
    tipo = data.get("tipo")
    aviso_id = data.get("aviso_id")
    termino = data.get("termino_busqueda")
    if tipo not in ("click_whatsapp", "click_resultado_busqueda"):
        return render_json(handler, {"ok": False}, status=400)
    db.registrar_evento(tipo, aviso_id=aviso_id, termino_busqueda=termino)
    if tipo == "click_whatsapp" and aviso_id:
        db.incrementar_contactos(aviso_id)
    render_json(handler, {"ok": True})


# ----------------------------------------------------------------- admin

def admin_login_form(handler, error=False):
    msg = '<p class="form-error">Usuario o contraseña incorrectos.</p>' if error else ""
    flash = get_flash(handler)
    body = f"""
<div class="panel panel-narrow">
  <h1>Ingreso administrador</h1>
  {msg}
  <form method="post" action="/admin/login" class="form">
    <label>Usuario <input name="usuario" required autofocus></label>
    <label>Contraseña <input name="password" type="password" required></label>
    <button class="btn btn-primary btn-lg" type="submit">Ingresar</button>
  </form>
  <p class="hint">Usa las credenciales entregadas por el administrador del sitio.</p>
</div>
"""
    render(handler, t.layout("Ingreso admin", body, flash=flash), clear_flash=bool(flash))


def admin_login_submit(handler, form):
    password = form.get("password", "")
    row = db.get_admin_usuario(form.get("usuario", ""))
    if not row or not db.verify_password(password, row["password"]):
        return admin_login_form(handler, error=True)
    if db.necesita_rehash(row["password"]):
        db.actualizar_password_admin(row["usuario"], db.hash_password(password))
    token = secrets.token_urlsafe(24)
    SESSIONS[token] = {"usuario": row["usuario"], "rol": row["rol"]}
    redirect(handler, "/admin", set_cookie=token)


def admin_logout(handler):
    cookie = SimpleCookie(handler.headers.get("Cookie", ""))
    if "talca_admin" in cookie:
        SESSIONS.pop(cookie["talca_admin"].value, None)
    redirect(handler, "/admin/login", clear_cookie=True)


def _svg_serie_chart(serie, w=640, h=190):
    if not serie or not any(f["vistas"] or f["contactos"] for f in serie):
        return '<p class="empty-state">Sin datos suficientes en este período.</p>'
    pad_l, pad_r, pad_t, pad_b = 4, 4, 10, 6
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    n = len(serie)
    max_v = max(max(f["vistas"] for f in serie), max(f["contactos"] for f in serie), 1)

    def puntos(campo):
        return [
            (pad_l + (plot_w * i / (n - 1) if n > 1 else plot_w / 2),
             pad_t + plot_h - (plot_h * f[campo] / max_v))
            for i, f in enumerate(serie)
        ]

    def largo(pts):
        return sum(((pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5
                    for i in range(len(pts) - 1)) or 1

    def suave(pts):
        """Curva Catmull-Rom -> Bezier: mismos puntos, trazo redondeado en vez
        de segmentos rectos, se lee mucho mejor con series de 7-30 días."""
        if len(pts) < 3:
            return "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        d = f"M {pts[0][0]:.1f},{pts[0][1]:.1f} "
        total = len(pts)
        for i in range(total - 1):
            p0 = pts[i - 1] if i > 0 else pts[i]
            p1, p2 = pts[i], pts[i + 1]
            p3 = pts[i + 2] if i + 2 < total else p2
            c1x, c1y = p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6
            c2x, c2y = p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6
            d += f"C {c1x:.1f},{c1y:.1f} {c2x:.1f},{c2y:.1f} {p2[0]:.1f},{p2[1]:.1f} "
        return d.strip()

    def area_d(pts):
        base = pad_t + plot_h
        return f"{suave(pts)} L {pts[-1][0]:.1f},{base:.1f} L {pts[0][0]:.1f},{base:.1f} Z"

    def puntos_svg(pts, clase):
        return "".join(
            f'<circle class="chart-pt {clase}" cx="{x:.1f}" cy="{y:.1f}" r="3.5"></circle>'
            for x, y in pts
        )

    pv, pc = puntos("vistas"), puntos("contactos")
    serie_json = t.esc(json.dumps(serie, ensure_ascii=False))
    body = f"""
<div class="chart-line" data-reveal data-serie="{serie_json}">
  <svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" aria-label="Vistas y contactos por día">
    <path d="{area_d(pv)}" class="chart-area chart-area-vistas"></path>
    <path d="{area_d(pc)}" class="chart-area chart-area-contactos"></path>
    <path d="{suave(pv)}" class="chart-line-path chart-line-vistas" vector-effect="non-scaling-stroke" style="--len:{largo(pv):.1f}"></path>
    <path d="{suave(pc)}" class="chart-line-path chart-line-contactos" vector-effect="non-scaling-stroke" style="--len:{largo(pc):.1f}"></path>
    <line class="chart-hover-line" x1="0" y1="{pad_t}" x2="0" y2="{pad_t + plot_h}" vector-effect="non-scaling-stroke"></line>
    {puntos_svg(pv, "chart-pt-vistas")}
    {puntos_svg(pc, "chart-pt-contactos")}
  </svg>
  <div class="chart-tooltip"></div>
  <div class="chart-axis"><span>{t.esc(serie[0]['fecha'][5:])}</span><span>{t.esc(serie[-1]['fecha'][5:])}</span></div>
</div>
<div class="chart-legend">
  <span class="chart-legend-item"><i class="chart-dot chart-dot-vistas"></i>Vistas</span>
  <span class="chart-legend-item"><i class="chart-dot chart-dot-contactos"></i>Contactos WhatsApp</span>
</div>"""
    return body


def _svg_categoria_chart(categorias):
    if not categorias:
        return '<p class="empty-state">Aún no hay avisos activos para graficar.</p>'
    max_n = max(c["n"] for c in categorias) or 1
    filas = "".join(f"""
<div class="chart-bar-row" style="--i:{i}">
  <span class="chart-bar-label">{c['icono']} {t.esc(c['nombre'])}</span>
  <div class="chart-bar-track"><div class="chart-bar-fill" style="--w:{round(100 * c['n'] / max_n)}%; background:{c['color']}"></div></div>
  <span class="chart-bar-value mono">{c['n']}</span>
</div>""" for i, c in enumerate(categorias[:8]))
    return f'<div class="chart-bars" data-reveal>{filas}</div>'


def admin_dashboard(handler, query):
    dias = int(qs(query).get("dias", "30"))
    stats = db.get_dashboard_stats(dias)
    avisos_activos = stats["avisos_activos"]
    pendientes = stats["pendientes"]
    vistas = stats["vistas"]
    contactos = stats["contactos"]
    tasa = round(100 * contactos / vistas, 1) if vistas else 0.0
    anunciantes_pagando = stats["anunciantes_pagando"]
    mrr = stats["mrr"]
    top_vistos = stats["top_vistos"]
    top_contactados = stats["top_contactados"]

    mrr_fmt = f"{mrr:,}".replace(",", ".")

    def periodo_opt(valor, label):
        sel = " selected" if valor == dias else ""
        return f'<option value="{valor}"{sel}>{label}</option>'

    def top_list(rows, unidad):
        if not rows:
            return '<p class="empty-state">Sin datos en este período.</p>'
        items = "".join(
            f'<li><a href="/avisos/{r["id"]}">{t.esc(r["titulo"])}</a>'
            f'<span class="mono">{r["negocio_nombre"]}</span>'
            f'<strong>{r["n"]} {unidad}</strong></li>'
            for r in rows
        )
        return f'<ol class="top-list">{items}</ol>'

    def kpi(icon, kind, valor, label, i, contar=None):
        valor_html = f'<span class="count-up" data-target="{contar}">0</span>' if contar is not None else str(valor)
        return (f'<div class="kpi kpi-{kind}" data-reveal style="--i:{i}">'
                f'<span class="kpi-icon">{icon}</span>'
                f'<div><div class="n">{valor_html}</div><div class="l">{label}</div></div></div>')

    kpis = "".join([
        kpi("◈", "accent", avisos_activos, "avisos activos", 0, contar=avisos_activos),
        kpi("◔", "warn", pendientes, "pendientes de moderación", 1, contar=pendientes),
        kpi("↗", "accent", vistas, "vistas en el período", 2, contar=vistas),
        kpi("✓", "ok", contactos, "contactos WhatsApp en el período", 3, contar=contactos),
        kpi("⌁", "accent", f"{tasa}%", "tasa de conversión vista → contacto", 4),
        kpi("⌂", "gold", anunciantes_pagando, "anunciantes en plan pagado", 5, contar=anunciantes_pagando),
        kpi("✦", "gold", f"${mrr_fmt} CLP", "ingreso mensual recurrente (MRR)", 6),
    ])

    body = f"""
<div class="listado-head">
  <h1>Dashboard</h1>
  <form method="get" class="filters">
    <select name="dias" data-autosubmit>
      {periodo_opt(7, "Últimos 7 días")}{periodo_opt(30, "Últimos 30 días")}{periodo_opt(90, "Últimos 90 días")}
    </select>
  </form>
</div>
<div class="kpi-grid">
  {kpis}
</div>
<div class="two-col">
  <section class="panel">
    <h2>Vistas y contactos por día</h2>
    {_svg_serie_chart(stats["serie_diaria"])}
  </section>
  <section class="panel">
    <h2>Avisos activos por rubro</h2>
    {_svg_categoria_chart(stats["por_categoria"])}
  </section>
</div>
<section class="admin-quick" data-reveal>
  <div class="admin-quick-copy"><span class="eyebrow">Control del sitio</span><h2>¿Qué quieres administrar?</h2></div>
  <div class="admin-quick-grid">
    <a href="/admin/contenido"><span>✦</span><strong>Contenido</strong><small>Portada, textos y CTA</small></a>
    <a href="/admin/avisos"><span>◈</span><strong>Avisos</strong><small>Editar y publicar ofertas</small></a>
    <a href="/admin/anunciantes"><span>⌂</span><strong>Negocios</strong><small>Planes y verificación</small></a>
    <a href="/admin/necesidades"><span>↗</span><strong>Demanda</strong><small>Lo que Talca quiere ver</small></a>
  </div>
</section>
<div class="two-col">
  <section class="panel">
    <h2>Top 10 más vistos</h2>
    {top_list(top_vistos, "vistas")}
  </section>
  <section class="panel">
    <h2>Top 10 más contactados</h2>
    {top_list(top_contactados, "contactos")}
  </section>
</div>
"""
    render(handler, t.layout("Dashboard", body, active="dashboard", admin=True))


def admin_moderacion(handler):
    pendientes = db.get_avisos(estado="pendiente", orden="creado_asc")
    pendientes.sort(key=lambda a: (-a.get("plan_prioridad", 0), a.get("creado_en", "")))

    if not pendientes:
        rows = '<p class="empty-state">No hay avisos pendientes de moderación. 🎉</p>'
    else:
        rows = "".join(f"""
<div class="mod-row" data-reveal style="--i:{i}">
  <div class="mod-info">
    <div class="mono">{a['icono']} {t.esc(a['categoria_nombre'])} · {t.esc(a['comuna'])}</div>
    <h3>{t.esc(a['titulo'])} {t.plan_badge(a['plan_nombre']) if a['plan_nombre'] != 'Gratis' else ''}</h3>
    <p>{t.esc(a['negocio_nombre'])} · {t.esc(a['whatsapp'])}</p>
    <p class="mod-desc">{t.esc(a['descripcion'])}</p>
  </div>
  <div class="mod-actions">
    <form method="post" action="/admin/moderacion/{a['id']}/aprobar"><button class="btn btn-ok">Aprobar</button></form>
    <form method="post" action="/admin/moderacion/{a['id']}/rechazar"><button class="btn btn-bad">Rechazar</button></form>
  </div>
</div>""" for i, a in enumerate(pendientes))

    flash = get_flash(handler)
    body = f"<h1>Moderación</h1><p class='lede'>Avisos nuevos esperando revisión.</p>{rows}"
    render(handler, t.layout("Moderación", body, active="moderacion", admin=True, flash=flash),
           clear_flash=bool(flash))


def admin_moderar(handler, aviso_id, accion):
    nuevo_estado = "activo" if accion == "aprobar" else "rechazado"
    db.cambiar_estado_aviso(aviso_id, nuevo_estado)
    mensaje = "Aviso aprobado y publicado." if nuevo_estado == "activo" else "Aviso rechazado."
    auditar(handler, "aprobar" if nuevo_estado == "activo" else "rechazar", f"aviso {aviso_id}")
    if nuevo_estado == "activo":
        aviso = db.get_aviso(aviso_id)
        if aviso:
            negocio = db.get_negocio(aviso["negocio_id"])
            origin = _origin(handler)
            threading.Thread(target=_enviar_correo_aviso_aprobado, args=(aviso, negocio, origin), daemon=True).start()
    redirect(handler, "/admin/moderacion", flash=mensaje_sincronizacion(mensaje, sincronizar_sitio_estatico()))


AVISOS_POR_PAGINA = 10


def admin_avisos_lista(handler, query):
    params = qs(query)
    estado = params.get("estado", "")
    avisos_todos = db.get_avisos(estado=estado or None, orden="creado")

    total = len(avisos_todos)
    total_paginas = max(1, -(-total // AVISOS_POR_PAGINA))
    try:
        pagina = int(params.get("page", "1"))
    except ValueError:
        pagina = 1
    pagina = min(max(pagina, 1), total_paginas)
    inicio = (pagina - 1) * AVISOS_POR_PAGINA
    avisos = avisos_todos[inicio:inicio + AVISOS_POR_PAGINA]

    def opt(v, label):
        sel = " selected" if v == estado else ""
        return f'<option value="{v}"{sel}>{label}</option>'

    filas = "".join(f"""
<tr>
  <td><a href="/admin/avisos/{a['id']}">{t.esc(a['titulo'])}</a></td>
  <td>{t.esc(a['negocio_nombre'])}</td>
  <td class="mono">{t.esc(a['categoria_nombre'])}</td>
  <td>{t.estado_badge(a['estado'])}</td>
  <td>{t.origen_badge(a.get('es_demo', False))}</td>
  <td>{t.plan_cc(a.get('plan_nombre', 'Gratis'))}</td>
  <td class="mono">{a['vistas_total']}</td>
  <td class="mono">{a['contactos_total']}</td>
  <td class="admin-actions">
    <div class="admin-actions-row">
      <div class="admin-actions-icons">
        <a class="btn btn-icon btn-ghost" href="/admin/avisos/{a['id']}" title="Editar" aria-label="Editar">✎</a>
        <form method="post" action="/admin/avisos/{a['id']}/eliminar" data-ajax-delete
          data-confirm="¿Eliminar este aviso? No se puede deshacer.">
          <button class="btn btn-icon btn-bad" title="Eliminar" aria-label="Eliminar">🗑️</button>
        </form>
      </div>
      {f'''<div class="admin-actions-stack">
        <form method="post" action="/admin/avisos/{a['id']}/aprobar">
          <button class="btn btn-ok btn-sm">Aprobar</button>
        </form>
        <form method="post" action="/admin/avisos/{a['id']}/rechazar">
          <button class="btn btn-ghost btn-sm">Rechazar</button>
        </form>
      </div>''' if a['estado'] == 'pendiente' else ''}
    </div>
  </td>
</tr>""" for a in avisos)

    def pagina_href(n):
        qparams = f"page={n}"
        if estado:
            qparams = f"estado={t.esc(estado)}&{qparams}"
        return f"?{qparams}"

    paginacion_html = ""
    if total_paginas > 1:
        prev_html = (f'<a class="btn btn-ghost btn-sm" href="{pagina_href(pagina - 1)}">‹ Anterior</a>'
                     if pagina > 1 else '<span class="btn btn-ghost btn-sm is-disabled">‹ Anterior</span>')
        next_html = (f'<a class="btn btn-ghost btn-sm" href="{pagina_href(pagina + 1)}">Siguiente ›</a>'
                     if pagina < total_paginas else '<span class="btn btn-ghost btn-sm is-disabled">Siguiente ›</span>')
        paginacion_html = f"""
<div class="paginacion">
  {prev_html}
  <span class="paginacion-info">Página {pagina} de {total_paginas}</span>
  {next_html}
</div>"""

    body = f"""
<div class="listado-head">
  <h1>Avisos</h1>
  <div class="listado-head-actions">
    <form method="get" class="filters">
      <select name="estado" data-autosubmit>
        {opt('', 'Todos los estados')}{opt('activo', 'Activo')}{opt('pendiente', 'Pendiente')}
        {opt('pausado', 'Pausado')}{opt('rechazado', 'Rechazado')}
      </select>
    </form>
    <a class="btn btn-ghost" href="/admin/avisos.csv">Exportar CSV</a>
  </div>
</div>
<div class="tbl-wrap" data-reveal><table>
  <tr><th>Título</th><th>Negocio</th><th>Categoría</th><th>Estado</th><th>Origen</th><th>CC</th><th>Vistas</th><th>Contactos</th><th>Acciones</th></tr>
  {filas or "<tr><td colspan='9' class='empty-state'>Sin avisos.</td></tr>"}
</table></div>
{paginacion_html}
"""
    flash = get_flash(handler)
    render(handler, t.layout("Avisos", body, active="avisos", admin=True, flash=flash), clear_flash=bool(flash))


def admin_aviso_editar_form(handler, aviso_id, errores=None):
    aviso = db.get_aviso(aviso_id)
    categorias = db.get_categorias()
    if not aviso:
        return not_found(handler)
    flash = get_flash(handler)

    cat_options = "".join(
        f'<option value="{c["id"]}"{" selected" if c["id"] == aviso["categoria_id"] else ""}>'
        f'{c["icono"]} {t.esc(c["nombre"])}</option>' for c in categorias)
    estado_options = "".join(
        f'<option value="{e}"{" selected" if e == aviso["estado"] else ""}>{e}</option>'
        for e in ("pendiente", "activo", "pausado", "rechazado"))

    foto_url = aviso.get("foto_url")
    foto_preview = f'<img src="{t.esc(foto_url)}" alt="" class="campo-imagen-preview">' if foto_url else \
        '<p class="hint">Este aviso no tiene foto — se muestra el ícono del rubro.</p>'
    foto_quitar = ('<label class="check-label"><input type="checkbox" name="quitar_foto">'
                   '<span>Quitar la foto actual (vuelve a mostrar el ícono del rubro)</span></label>') if foto_url else ""
    errores_html = ("<div class='form-errors'><ul>" + "".join(f"<li>{t.esc(e)}</li>" for e in errores) +
                     "</ul></div>") if errores else ""
    fotos_extra = aviso.get("fotos_extra") or []
    es_premium = aviso.get("plan_nombre") == "Premium"
    galeria_items = "".join(f"""
<div class="galeria-item">
  <img src="{t.esc(url)}" alt="">
  <form method="post" action="/admin/avisos/{aviso_id}/fotos/eliminar" data-ajax-form data-ajax-reload>
    <input type="hidden" name="url" value="{t.esc(url)}">
    <button class="btn btn-icon btn-bad" title="Quitar foto" aria-label="Quitar foto">🗑️</button>
  </form>
</div>""" for url in fotos_extra)
    slots_vacios = max(0, db.FOTOS_EXTRA_MAX - len(fotos_extra))
    galeria_add_boxes = "".join(f"""
<form method="post" action="/admin/avisos/{aviso_id}/fotos/agregar" enctype="multipart/form-data"
  class="galeria-slot-add" data-ajax-form data-ajax-reload>
  <label>
    <input type="file" name="foto" accept="image/jpeg,image/png,image/webp" required
      onchange="this.form.requestSubmit()">
    <span class="galeria-add-plus">+</span>
    <span class="galeria-add-text">Agregar imagen</span>
  </label>
</form>""" for _ in range(slots_vacios))
    galeria_seccion = ""
    if es_premium:
        galeria_seccion = f"""
    <div class="campo-galeria">
      <span class="campo-galeria-label">Fotos adicionales (Premium) — hasta {db.FOTOS_EXTRA_MAX}</span>
      <div class="galeria-grid">{galeria_items}{galeria_add_boxes}</div>
    </div>"""
    body = f"""
<div class="panel">
  <h1>Editar aviso</h1>
  <p class="lede">{t.esc(aviso['negocio_nombre'])} · {t.esc(aviso['whatsapp'])} {t.plan_cc(aviso.get('plan_nombre', 'Gratis'))}</p>
  {errores_html}
  <form method="post" action="/admin/avisos/{aviso_id}" class="form" enctype="multipart/form-data"
    data-ajax-form data-ajax-redirect="/admin/avisos">
    <label>Título <input name="titulo" required value="{t.esc(aviso['titulo'])}"></label>
    <label>Descripción <textarea name="descripcion" rows="4" required>{t.esc(aviso['descripcion'])}</textarea></label>
    <label>Categoría <select name="categoria_id">{cat_options}</select></label>
    <label>Comuna <input name="comuna" value="{t.esc(aviso['comuna'])}"></label>
    <label>Horario <input name="horario" value="{t.esc(aviso['horario'] or '')}"></label>
    <label>Estado <select name="estado">{estado_options}</select></label>
    <label class="campo-imagen">Foto del aviso
      {foto_preview}
      <input type="file" name="foto" accept="image/jpeg,image/png,image/webp">
      <span class="hint">JPG, PNG o WebP, máx. 5 MB. Deja vacío para no cambiarla.</span>
    </label>
    {foto_quitar}
    <div class="form-actions">
      <a class="btn btn-ghost btn-lg" href="/admin/avisos">Cancelar</a>
      <button class="btn btn-primary btn-lg" type="submit">Guardar cambios</button>
    </div>
  </form>
  {galeria_seccion}
</div>
"""
    render(handler, t.layout("Editar aviso", body, active="avisos", admin=True, flash=flash), clear_flash=bool(flash))


def _responder_error_ajax(handler, mensaje, status=422):
    data = mensaje.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def admin_aviso_editar_submit(handler, aviso_id, form, archivos=None):
    ajax = _es_ajax(handler)
    actual = db.get_aviso(aviso_id)
    if not actual:
        if ajax:
            return _responder_error_ajax(handler, "Este aviso ya no existe.", 404)
        return not_found(handler)
    archivo_foto = (archivos or {}).get("foto")
    foto_url = None
    if archivo_foto:
        if archivo_foto["content_type"] not in _EXT_POR_TIPO:
            if ajax:
                return _responder_error_ajax(handler, "La foto debe ser JPG, PNG o WebP.")
            return admin_aviso_editar_form(handler, aviso_id,
                                            errores=["La foto debe ser JPG, PNG o WebP."])
        if len(archivo_foto["data"]) > 5 * 1024 * 1024:
            if ajax:
                return _responder_error_ajax(handler, "La foto es muy pesada (máximo 5 MB).")
            return admin_aviso_editar_form(handler, aviso_id,
                                            errores=["La foto es muy pesada (máximo 5 MB)."])
        ext = _EXT_POR_TIPO[archivo_foto["content_type"]]
        foto_url = db.subir_imagen(archivo_foto["data"], archivo_foto["content_type"], ext, carpeta="avisos")
    elif form.get("quitar_foto"):
        foto_url = ""
    nuevo_estado = form.get("estado", actual["estado"])
    ok = db.editar_aviso(
        aviso_id, form.get("titulo", ""), form.get("descripcion", ""), form.get("categoria_id"),
        form.get("comuna", ""), form.get("horario", ""), nuevo_estado, foto_url=foto_url)
    if not ok:
        if ajax:
            return _responder_error_ajax(handler, "Este aviso ya no existe.", 404)
        return not_found(handler)
    _og_cache_evict(aviso_id)
    auditar(handler, "editar_aviso", f"aviso {aviso_id}")
    if actual["estado"] != "activo" and nuevo_estado == "activo":
        aviso_fresco = db.get_aviso(aviso_id)
        if aviso_fresco:
            negocio = db.get_negocio(aviso_fresco["negocio_id"])
            origin = _origin(handler)
            threading.Thread(target=_enviar_correo_aviso_aprobado, args=(aviso_fresco, negocio, origin),
                              daemon=True).start()
    actualizado = sincronizar_sitio_estatico()
    if ajax:
        handler.send_response(204)
        handler.end_headers()
        return
    redirect(handler, "/admin/avisos", flash=mensaje_sincronizacion("Cambios guardados.", actualizado))


RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
RESEND_REPLY_TO = os.environ.get("RESEND_REPLY_TO", "futuroiadesarrollo@gmail.com")

MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")
MP_PRECIO_PROMO = 1990
MP_PRECIO_NORMAL = 5990

PLANES_SUSCRIPCION = [
    {
        "id": "gratis", "nombre": "Básico", "precio": MP_PRECIO_PROMO, "precio_normal": MP_PRECIO_NORMAL,
        "beneficios": ["Tu negocio visible en Talcadatos", "Contacto directo por WhatsApp",
                       "Aparece en búsquedas y filtros"],
    },
    {
        "id": "destacado", "nombre": "Destacado", "precio": 9990, "precio_normal": None, "recomendado": True,
        "beneficios": ["Todo lo de Básico", "Aparece en la sección Destacados de la portada",
                       "Insignia \"Destacado\" en tu aviso", "Mejor posición en los listados",
                       "Revisión de tu aviso más rápida"],
    },
    {
        "id": "premium", "nombre": "Premium", "precio": 19990, "precio_normal": None,
        "beneficios": ["Todo lo de Destacado", "Revisión de tu aviso con la máxima prioridad",
                       "Prioridad máxima en resultados y destacados", "Insignia \"Premium\" en tu aviso",
                       "Negocio verificado ✔ automáticamente", "Galería de varias fotos en tu aviso",
                       "Atención y soporte prioritario"],
    },
]
PLANES_SUSCRIPCION_POR_ID = {p["id"]: p for p in PLANES_SUSCRIPCION}


def _mp_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"https://api.mercadopago.com{path}", data=data, method=method,
        headers={
            "Authorization": f"Bearer {MP_ACCESS_TOKEN}", "Content-Type": "application/json",
            "User-Agent": "Talcadatos/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode(errors="replace")
        sys.stderr.write(f"ERROR MP API {method} {path}: {exc.code} {detalle}\n")
        raise


def _crear_preapproval(email, external_reference, origin, precio, nombre_plan):
    payload = {
        "reason": f"Talcadatos - Plan {nombre_plan} (publicación mensual de aviso)",
        "external_reference": external_reference,
        "payer_email": email,
        "auto_recurring": {
            "frequency": 1, "frequency_type": "months",
            "transaction_amount": precio, "currency_id": "CLP",
        },
        "back_url": f"{origin}/publicar?sub={external_reference}",
        "notification_url": f"{origin}/api/mp-webhook",
        "status": "pending",
    }
    return _mp_request("POST", "/preapproval", payload)


def _enviar_correo_aviso_aprobado(aviso, negocio, origin):
    destinatario = (negocio or {}).get("email") or ""
    if not RESEND_API_KEY or not destinatario:
        return
    link_aviso = f"{origin}/avisos/{aviso['id']}"
    html = f"""
<p>Hola {t.esc(negocio.get('nombre', ''))},</p>
<p>Buenas noticias: tu aviso <strong>{t.esc(aviso['titulo'])}</strong> ya fue aprobado y está publicado en Talcadatos.</p>
<p><a href="{t.esc(link_aviso)}">Ver tu aviso</a></p>
<p>Gracias por sumarte a Talcadatos, el directorio de pymes y emprendedores de Talca.</p>
<p>El equipo de Talcadatos</p>
"""
    payload = json.dumps({
        "from": RESEND_FROM_EMAIL, "to": [destinatario], "reply_to": RESEND_REPLY_TO,
        "subject": "¡Tu aviso ya está en Talcadatos! 🎉", "html": html,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json",
            "User-Agent": "Talcadatos/1.0",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        sys.stderr.write(f"ERROR enviando correo de aprobacion (aviso {aviso['id']}): {exc!r}\n")


def admin_aviso_foto_agregar_submit(handler, aviso_id, form, archivos=None):
    ajax = _es_ajax(handler)
    archivos = archivos or {}
    foto = archivos.get("foto")
    if foto and foto["content_type"] in _EXT_POR_TIPO and len(foto["data"]) <= 5 * 1024 * 1024:
        ext = _EXT_POR_TIPO[foto["content_type"]]
        url = db.subir_foto_aviso(foto["data"], foto["content_type"], ext)
        if db.agregar_foto_extra(aviso_id, url):
            auditar(handler, "agregar_foto_galeria", f"aviso {aviso_id}")
            actualizado = sincronizar_sitio_estatico()
            flash = mensaje_sincronizacion("Foto agregada a la galería.", actualizado)
        else:
            flash = f"Ya tiene el máximo de {db.FOTOS_EXTRA_MAX} fotos adicionales."
            if ajax:
                return _responder_error_ajax(handler, flash)
    else:
        flash = "La foto debe ser JPG, PNG o WebP de máximo 5 MB."
        if ajax:
            return _responder_error_ajax(handler, flash)
    if ajax:
        handler.send_response(204)
        handler.end_headers()
        return
    redirect(handler, f"/admin/avisos/{aviso_id}", flash=flash)


def admin_aviso_foto_eliminar_submit(handler, aviso_id, form):
    ajax = _es_ajax(handler)
    url = form.get("url", "")
    if url:
        db.eliminar_foto_extra(aviso_id, url)
        auditar(handler, "eliminar_foto_galeria", f"aviso {aviso_id}")
    actualizado = sincronizar_sitio_estatico()
    if ajax:
        handler.send_response(204)
        handler.end_headers()
        return
    redirect(handler, f"/admin/avisos/{aviso_id}", flash=mensaje_sincronizacion("Foto eliminada.", actualizado))


def admin_aviso_aprobar(handler, aviso_id):
    db.cambiar_estado_aviso(aviso_id, "activo")
    auditar(handler, "aprobar", f"aviso {aviso_id}")
    aviso = db.get_aviso(aviso_id)
    if aviso:
        negocio = db.get_negocio(aviso["negocio_id"])
        origin = _origin(handler)
        threading.Thread(target=_enviar_correo_aviso_aprobado, args=(aviso, negocio, origin), daemon=True).start()
    redirect(handler, "/admin/avisos",
             flash=mensaje_sincronizacion("Aviso aprobado y publicado.", sincronizar_sitio_estatico()))


def admin_aviso_rechazar(handler, aviso_id):
    db.cambiar_estado_aviso(aviso_id, "rechazado")
    auditar(handler, "rechazar", f"aviso {aviso_id}")
    redirect(handler, "/admin/avisos",
             flash=mensaje_sincronizacion("Aviso rechazado.", sincronizar_sitio_estatico()))


def admin_aviso_eliminar(handler, aviso_id):
    db.eliminar_aviso(aviso_id)
    _og_cache_evict(aviso_id)
    auditar(handler, "eliminar_aviso", f"aviso {aviso_id}")
    actualizado = sincronizar_sitio_estatico()
    if _es_ajax(handler):
        handler.send_response(204)
        handler.end_headers()
        return
    redirect(handler, "/admin/avisos", flash=mensaje_sincronizacion("Aviso eliminado.", actualizado))


def admin_anunciantes(handler):
    planes = db.get_planes()
    planes_por_id = {p["id"]: p for p in planes}
    conteo_avisos = db.contar_avisos_por_negocio()
    negocios = []
    for n in db.get_negocios():
        plan = planes_por_id.get(n.get("plan_id"), {})
        row = dict(n)
        row["plan_nombre"] = plan.get("nombre", "Gratis")
        row["precio_clp"] = plan.get("precio_clp", 0)
        row["n_avisos"] = conteo_avisos.get(n["id"], 0)
        negocios.append(row)
    negocios.sort(key=lambda n: n["nombre"])

    plan_options_tpl = "".join(f'<option value="{p["id"]}">{p["nombre"]} (${p["precio_clp"]:,})</option>'.replace(",", ".")
                                for p in planes)

    filas = "".join(f"""
<tr>
  <td>{t.esc(n['nombre'])}<div class="mono small">{t.esc(n['whatsapp'])}</div></td>
  <td>{t.plan_badge(n['plan_nombre'])}</td>
  <td class="mono">{n['plan_vencimiento'] or '—'}</td>
  <td class="mono">{n['n_avisos']}</td>
  <td>{'✔ verificado' if n['verificado'] else '—'}</td>
  <td class="admin-actions">
    <form method="post" action="/admin/anunciantes/{n['id']}/plan" class="inline-form">
      <select name="plan_id">{plan_options_tpl}</select>
      <button class="btn btn-ghost btn-sm">Activar/renovar</button>
    </form>
    <form method="post" action="/admin/anunciantes/{n['id']}/verificar" class="inline-form">
      <button class="btn btn-ghost btn-sm">{'Quitar verificación' if n['verificado'] else 'Verificar'}</button>
    </form>
  </td>
</tr>""" for n in negocios)

    body = f"""
<div class="listado-head">
  <h1>Anunciantes y planes</h1>
  <a class="btn btn-ghost" href="/admin/anunciantes.csv">Exportar CSV</a>
</div>
<p class="lede">Activa manualmente un plan pagado (transferencia confirmada) o marca un negocio como verificado.</p>
<div class="tbl-wrap" data-reveal><table>
  <tr><th>Negocio</th><th>Plan actual</th><th>Vence</th><th>Avisos</th><th>Verificado</th><th>Acciones</th></tr>
  {filas}
</table></div>
"""
    flash = get_flash(handler)
    render(handler, t.layout("Anunciantes y planes", body, active="anunciantes", admin=True, flash=flash),
           clear_flash=bool(flash))


def admin_anunciante_plan(handler, negocio_id, form):
    plan_id = form.get("plan_id")
    plan = db.get_plan(plan_id)
    vencimiento = None
    if plan and plan["precio_clp"] > 0:
        vencimiento = (datetime.date.today() + datetime.timedelta(days=plan["duracion_dias"])).isoformat()
    db.cambiar_plan_negocio(negocio_id, plan_id, vencimiento)
    if plan and plan["precio_clp"] > 0:
        db.crear_pago(negocio_id, plan_id, plan["precio_clp"])
    nombre_plan = plan["nombre"] if plan else "?"
    auditar(handler, "cambiar_plan", f"negocio {negocio_id} -> {nombre_plan}")
    redirect(handler, "/admin/anunciantes",
             flash=mensaje_sincronizacion(f"Plan actualizado a {nombre_plan}.", sincronizar_sitio_estatico()))


def admin_anunciante_verificar(handler, negocio_id):
    nuevo = db.toggle_verificado_negocio(negocio_id)
    mensaje = "Negocio verificado." if nuevo else "Verificación removida."
    auditar(handler, "verificar_negocio" if nuevo else "quitar_verificacion", f"negocio {negocio_id}")
    redirect(handler, "/admin/anunciantes", flash=mensaje_sincronizacion(mensaje, sincronizar_sitio_estatico()))


def admin_analitica(handler):
    avisos = db.get_avisos(estado_ne="rechazado", orden="vistas")
    mas_buscados = db.get_terminos_mas_buscados(15)
    sin_resultado = db.get_terminos_sin_resultado(15)

    filas = "".join(f"""
<tr>
  <td><a href="/avisos/{a['id']}">{t.esc(a['titulo'])}</a><div class="mono small">{t.esc(a['negocio_nombre'])}</div></td>
  <td class="mono">{a['vistas_total']}</td>
  <td class="mono">{a['contactos_total']}</td>
  <td class="mono">{round(100 * a['contactos_total'] / a['vistas_total'], 1) if a['vistas_total'] else 0}%</td>
  <td>{t.plan_badge(a['plan_nombre'])}</td>
</tr>""" for a in avisos)

    def term_list(rows, label):
        if not rows:
            return f'<p class="empty-state">Sin {label} registradas todavía.</p>'
        items = "".join(f'<li><span>{t.esc(r["termino_busqueda"])}</span><strong>{r["n"]}</strong></li>' for r in rows)
        return f'<ul class="term-list">{items}</ul>'

    body = f"""
<h1>Analítica</h1>
<div class="two-col">
  <section class="panel">
    <h2>Términos más buscados</h2>
    {term_list(mas_buscados, "búsquedas")}
  </section>
  <section class="panel">
    <h2>Búsquedas sin resultado relevante</h2>
    <p class="lede">Oportunidad comercial: rubros que la gente busca en Talca y aún no tienen anunciante.</p>
    {term_list(sin_resultado, "búsquedas")}
  </section>
</div>
<section class="panel">
  <h2>Métricas por aviso</h2>
  <div class="tbl-wrap" data-reveal><table>
    <tr><th>Aviso</th><th>Vistas</th><th>Contactos</th><th>Conversión</th><th>Plan</th></tr>
    {filas}
  </table></div>
</section>
"""
    render(handler, t.layout("Analítica", body, active="analitica", admin=True))


def admin_avisos_csv(handler):
    avisos = db.get_avisos(orden="creado")
    rows = [(a["id"], a["titulo"], a["negocio_nombre"], a["categoria_nombre"], a["comuna"],
              a["estado"], a["plan_nombre"], a["vistas_total"], a["contactos_total"]) for a in avisos]
    render_csv(handler, "avisos.csv",
               ["id", "titulo", "negocio", "categoria", "comuna", "estado", "plan", "vistas", "contactos"], rows)


def admin_anunciantes_csv(handler):
    planes_por_id = {p["id"]: p for p in db.get_planes()}
    negocios = sorted(db.get_negocios(), key=lambda n: n["nombre"])
    rows = [(n["id"], n["nombre"], n["whatsapp"], planes_por_id.get(n.get("plan_id"), {}).get("nombre", "Gratis"),
              n.get("plan_vencimiento") or "", "si" if n.get("verificado") else "no") for n in negocios]
    render_csv(handler, "anunciantes.csv", ["id", "nombre", "whatsapp", "plan", "vence", "verificado"], rows)


def admin_pagos_csv(handler):
    pagos = db.get_pagos()
    rows = [(p["creado_en"][:10], p["negocio_nombre"], p["plan_nombre"], p["precio_clp"]) for p in pagos]
    render_csv(handler, "pagos.csv", ["fecha", "negocio", "plan", "precio_clp"], rows)


def admin_reportes(handler):
    reportes = db.get_reportes_pendientes()
    if not reportes:
        filas = '<p class="empty-state">No hay reportes pendientes. 🎉</p>'
    else:
        filas = "".join(f"""
<div class="mod-row" data-reveal style="--i:{i}">
  <div class="mod-info">
    <h3><a href="/avisos/{r['aviso_id']}">{t.esc(r['aviso_titulo'])}</a></h3>
    <p class="mod-desc">Motivo: {t.esc(r['motivo'])}</p>
    <p class="small mono">{r['creado_en'][:16].replace('T', ' ')}</p>
  </div>
  <div class="mod-actions">
    <form method="post" action="/admin/reportes/{r['id']}/descartar"><button class="btn btn-ghost">Descartar</button></form>
  </div>
</div>""" for i, r in enumerate(reportes))
    flash = get_flash(handler)
    body = f"<h1>Reportes</h1><p class='lede'>Avisos que algún visitante marcó como sospechosos o desactualizados.</p>{filas}"
    render(handler, t.layout("Reportes", body, active="reportes", admin=True, flash=flash), clear_flash=bool(flash))


def admin_reporte_descartar(handler, reporte_id):
    db.descartar_reporte(reporte_id)
    auditar(handler, "descartar_reporte", f"reporte {reporte_id}")
    redirect(handler, "/admin/reportes", flash="Reporte descartado.")


def admin_sinonimos(handler):
    categorias = db.get_categorias()
    sinonimos = db.get_sinonimos()

    por_categoria = {}
    for s in sinonimos:
        por_categoria.setdefault(s["categoria_slug"], []).append(s)

    cat_options = "".join(f'<option value="{c["id"]}">{c["icono"]} {t.esc(c["nombre"])}</option>' for c in categorias)

    bloques = ""
    for c in categorias:
        items = por_categoria.get(c["id"], [])
        if items:
            chips = "".join(
                f'<form method="post" action="/admin/sinonimos/{s["id"]}/eliminar" class="chip-form">'
                f'<span class="chip">{t.esc(s["palabra"])} <button class="chip-x" title="Eliminar">×</button></span>'
                f'</form>' for s in items
            )
        else:
            chips = '<span class="small">Sin sinónimos todavía.</span>'
        bloques += f"""
<div class="panel">
  <h2>{c['icono']} {t.esc(c['nombre'])}</h2>
  <div class="chip-row">{chips}</div>
</div>"""

    flash = get_flash(handler)
    body = f"""
<h1>Sinónimos del buscador</h1>
<p class="lede">Cuando alguien busca una de estas palabras, el buscador también le muestra avisos de la categoría
asociada (ej: "ventana" muestra vidriería y aluminios). Es la tabla de respaldo del buscador "IA" que describe el PRD.</p>
<div class="panel">
  <form method="post" action="/admin/sinonimos/agregar" class="form form-inline">
    <select name="categoria_id" required>{cat_options}</select>
    <input name="palabra" required placeholder="Palabra o frase, ej: destape de cañerías">
    <button class="btn btn-primary" type="submit">Agregar</button>
  </form>
</div>
{bloques}
"""
    render(handler, t.layout("Sinónimos", body, active="sinonimos", admin=True, flash=flash), clear_flash=bool(flash))


def admin_sinonimo_agregar(handler, form):
    palabra = form.get("palabra", "").strip()
    categoria_slug = form.get("categoria_id")
    if palabra and categoria_slug:
        db.crear_sinonimo(categoria_slug, palabra)
        auditar(handler, "agregar_sinonimo", palabra)
        actualizado = sincronizar_sitio_estatico()
        return redirect(handler, "/admin/sinonimos", flash=mensaje_sincronizacion("Sinónimo agregado.", actualizado))
    redirect(handler, "/admin/sinonimos", flash="Completa una palabra y su categoría.")


def admin_sinonimo_eliminar(handler, sinonimo_id):
    db.eliminar_sinonimo(sinonimo_id)
    auditar(handler, "eliminar_sinonimo", f"id {sinonimo_id}")
    redirect(handler, "/admin/sinonimos",
             flash=mensaje_sincronizacion("Sinónimo eliminado.", sincronizar_sitio_estatico()))


def admin_auditoria(handler):
    registros = db.get_auditoria(limit=200)
    filas = "".join(f"""
<tr>
  <td class="mono small">{r['creado_en'][:16].replace('T', ' ')}</td>
  <td>{t.esc(r['usuario'])}</td>
  <td class="mono">{t.esc(r['accion'])}</td>
  <td>{t.esc(r['detalle'] or '')}</td>
</tr>""" for r in registros)
    body = f"""
<h1>Auditoría</h1>
<p class="lede">Últimas 200 acciones de administradores: quién aprobó, rechazó, editó o cambió un plan, y cuándo.</p>
<div class="tbl-wrap" data-reveal><table>
  <tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Detalle</th></tr>
  {filas or "<tr><td colspan='4' class='empty-state'>Sin registros todavía.</td></tr>"}
</table></div>
"""
    render(handler, t.layout("Auditoría", body, active="auditoria", admin=True))


def admin_pagos(handler):
    pagos = db.get_pagos()
    total = sum(p["precio_clp"] for p in pagos)
    filas = "".join(f"""
<tr>
  <td class="mono small">{p['creado_en'][:10]}</td>
  <td>{t.esc(p['negocio_nombre'])}</td>
  <td>{t.plan_badge(p['plan_nombre'])}</td>
  <td class="mono">${money(p['precio_clp'])}</td>
</tr>""" for p in pagos)

    suscripciones = db.get_suscripciones()
    plan_nombre_por_id = {p["id"]: p["nombre"] for p in PLANES_SUSCRIPCION}
    filas_sub = "".join(f"""
<tr>
  <td class="mono small">{t.esc((s.get('creado_en') or '')[:10])}</td>
  <td>{t.esc(s.get('negocio_nombre') or s.get('email', ''))}</td>
  <td>{t.plan_badge(plan_nombre_por_id.get(s.get('plan_id'), s.get('plan_id', '')))}</td>
  <td>{t.estado_badge(s.get('estado', ''))}</td>
  <td class="mono small">{t.esc(s.get('preapproval_id') or '—')}</td>
</tr>""" for s in suscripciones)
    body = f"""
<div class="listado-head">
  <h1>Historial de pagos</h1>
  <a class="btn btn-ghost" href="/admin/pagos.csv">Exportar CSV</a>
</div>
<div class="kpi-grid"><div class="kpi"><div class="n">${money(total)} CLP</div><div class="l">total histórico activado</div></div></div>
<div class="tbl-wrap" data-reveal><table>
  <tr><th>Fecha</th><th>Negocio</th><th>Plan</th><th>Monto</th></tr>
  {filas or "<tr><td colspan='4' class='empty-state'>Sin pagos registrados todavía.</td></tr>"}
</table></div>

<div class="panel">
  <h2>Suscripciones Mercado Pago</h2>
  <p class="lede">Si un cliente pide que le devuelvas dinero, busca su fila y copia el ID de suscripción —
    con eso lo encuentras en el panel de Mercado Pago para hacer el reembolso. Talcadatos nunca guarda
    datos de tarjeta ni de cuenta bancaria, solo esta referencia.</p>
</div>
<div class="tbl-wrap" data-reveal><table>
  <tr><th>Fecha</th><th>Negocio / email</th><th>Plan</th><th>Estado</th><th>ID suscripción (Mercado Pago)</th></tr>
  {filas_sub or "<tr><td colspan='5' class='empty-state'>Sin suscripciones todavía.</td></tr>"}
</table></div>
"""
    render(handler, t.layout("Pagos", body, active="pagos", admin=True))


def admin_alertas(handler):
    alertas = db.get_alertas_pendientes()
    filas = "".join(f"""
<tr>
  <td>{t.esc(a['termino'])}</td>
  <td class="mono">{t.esc(a['whatsapp'])}</td>
  <td class="mono small">{a['creado_en'][:10]}</td>
  <td><form method="post" action="/admin/alertas/{a['id']}/atendida"><button class="btn btn-ghost btn-sm">Marcar atendida</button></form></td>
</tr>""" for a in alertas)
    body = f"""
<h1>Alertas de demanda</h1>
<p class="lede">Personas que buscaron algo que nadie ofrece todavía y dejaron su WhatsApp para que las contactemos
apenas exista un negocio de ese rubro — son prospectos de venta directa (PRD §17).</p>
<div class="tbl-wrap" data-reveal><table>
  <tr><th>Buscaban</th><th>WhatsApp</th><th>Fecha</th><th></th></tr>
  {filas or "<tr><td colspan='4' class='empty-state'>Sin alertas pendientes.</td></tr>"}
</table></div>
"""
    render(handler, t.layout("Alertas de demanda", body, active="alertas", admin=True))


def admin_alerta_atendida(handler, alerta_id):
    db.marcar_alerta_atendida(alerta_id)
    redirect(handler, "/admin/alertas", flash="Marcada como atendida.")


def admin_necesidades(handler):
    necesidades = db.get_necesidades_pendientes()
    filas = "".join(f"""
<tr>
  <td><strong>{n['icono']} {t.esc(n['categoria_nombre'])}</strong></td>
  <td>{t.esc(n['descripcion'])}<div class="small">📍 {t.esc(n['sector'])}</div></td>
  <td class="mono">{t.esc(n['whatsapp'])}</td>
  <td class="mono small">{n['creado_en'][:10]}</td>
  <td><form method="post" action="/admin/necesidades/{n['id']}/atendida"><button class="btn btn-ghost btn-sm">Gestionada</button></form></td>
</tr>""" for n in necesidades)
    flash = get_flash(handler)
    body = f"""
<h1>Lo que Talca quiere ver</h1>
<p class="lede">Negocios y servicios que la gente recomendó — úsalas para invitar nuevos comercios o avisarles a los que ya están.</p>
<div class="tbl-wrap" data-reveal><table>
  <tr><th>Rubro</th><th>Recomendación</th><th>WhatsApp</th><th>Fecha</th><th></th></tr>
  {filas or "<tr><td colspan='5' class='empty-state'>No hay recomendaciones nuevas.</td></tr>"}
</table></div>
"""
    render(handler, t.layout("Lo que Talca quiere ver", body, active="necesidades", admin=True, flash=flash),
           clear_flash=bool(flash))


def admin_necesidad_atendida(handler, necesidad_id):
    db.marcar_necesidad_atendida(necesidad_id)
    auditar(handler, "gestionar_necesidad", f"necesidad {necesidad_id}")
    redirect(handler, "/admin/necesidades", flash="Necesidad marcada como gestionada.")


def contenido_grupos(sitio):
    """Campos editables compartidos por el CMS tradicional y el editor visual."""
    def campo(clave, etiqueta, largo=False):
        valor = t.esc(sitio.get(clave, ""))
        if largo:
            return f'<label>{etiqueta}<textarea name="{clave}" rows="3" maxlength="600">{valor}</textarea></label>'
        return f'<label>{etiqueta}<input name="{clave}" required maxlength="600" value="{valor}"></label>'

    def campo_imagen(clave, etiqueta):
        url_actual = sitio.get(clave, "")
        preview = f'<img src="{t.esc(url_actual)}" alt="" class="campo-imagen-preview">' if url_actual else ""
        return f'''<label class="campo-imagen">{etiqueta}
      {preview}
      <input type="file" name="{clave}" accept="image/jpeg,image/png,image/webp">
      <span class="hint">JPG, PNG o WebP, máx. 5 MB. Deja vacío para no cambiarla.</span>
    </label>'''

    return [
        ("Marca y pie de página", campo("marca", "Nombre de la marca") + campo("pie", "Texto del pie de página") +
         campo("descripcion", "Descripción para buscadores y redes", True)),
        ("Imágenes del sitio", campo_imagen("hero_imagen_url", "Foto de portada (hero)") +
         campo_imagen("explorar_imagen_url", "Imagen de la sección \"Comercio que se siente cerca\"") +
         campo_imagen("pymes_imagen_url", "Imagen del llamado a publicar negocio")),
        ("Portada", campo("hero_ubicacion", "Ubicación") + campo("hero_titulo", "Título principal", True) +
         campo("hero_bajada", "Bajada", True) + campo("hero_placeholder", "Texto del buscador") +
         campo("hero_ayuda", "Ayuda bajo el buscador")),
        ("Secciones de descubrimiento", campo("destacados_eyebrow", "Antetítulo de destacados") +
         campo("destacados_titulo", "Título de destacados") + campo("rubros_eyebrow", "Antetítulo de rubros") +
         campo("rubros_titulo", "Título de rubros") + campo("hoy_eyebrow", "Antetítulo de actualidad") +
         campo("hoy_titulo", "Título de actualidad") + campo("tendencias_eyebrow", "Antetítulo de tendencias") +
         campo("tendencias_titulo", "Título de tendencias") + campo("tendencias_bajada", "Bajada de tendencias", True)),
        ("Llamados a la acción", campo("necesidad_eyebrow", "Antetítulo de necesidad") +
         campo("necesidad_titulo", "Título de necesidad") + campo("necesidad_bajada", "Bajada de necesidad", True) +
         campo("necesidad_boton", "Botón de necesidad") + campo("pymes_eyebrow", "Antetítulo para pymes") +
         campo("pymes_titulo", "Título para pymes") + campo("pymes_bajada", "Bajada para pymes", True) +
         campo("pymes_boton", "Botón para pymes")),
        ("Páginas Recomendar negocio y Publicar", campo("necesito_titulo", "Título de Recomendar negocio", True) +
         campo("necesito_bajada", "Bajada de Recomendar negocio", True) +
         campo("publicar_titulo", "Título de Publicar") + campo("publicar_bajada", "Bajada de Publicar", True)),
    ]


def admin_contenido(handler):
    sitio = db.get_contenido_sitio()
    flash = get_flash(handler)
    suscripcion_activa = db.get_config_pagos()["suscripcion_activa"]
    precio_fmt = f"{MP_PRECIO_PROMO:,}".replace(",", ".")
    grupos = "".join(
        f'<section class="panel cms-section"><h2>{titulo}</h2><div class="form-grid">{campos}</div></section>'
        for titulo, campos in contenido_grupos(sitio)
    )
    body = f"""
<div class="admin-page-head">
  <div><span class="eyebrow">CMS de Talcadatos</span><h1>Contenido del sitio</h1>
  <p class="lede">Edita textos, llamados a la acción y la identidad de las páginas públicas. Los avisos, negocios y usuarios se gestionan desde sus secciones propias.</p></div>
  <a class="btn btn-ghost" href="/admin/editor">Abrir editor visual</a>
</div>
<section class="panel cms-section">
  <h2>Cobro de suscripción</h2>
  <p class="lede">Cuando está activo, el botón "Publicar mi negocio" lleva a una pantalla de suscripción mensual
  (${precio_fmt}/mes) antes de mostrar el formulario. Mientras está apagado, publicar sigue siendo gratis.</p>
  <form method="post" action="/admin/suscripcion/toggle" class="inline-form">
    <button class="btn {'btn-bad' if suscripcion_activa else 'btn-primary'} btn-lg" type="submit">
      {'Desactivar cobro (volver a gratis)' if suscripcion_activa else 'Activar cobro de suscripción'}
    </button>
    <span class="hint">Estado actual: <strong>{'activo, se cobra' if suscripcion_activa else 'inactivo, gratis'}</strong></span>
  </form>
</section>
<form method="post" action="/admin/contenido" class="form cms-form" enctype="multipart/form-data">
  {grupos}
  <div class="cms-save"><span class="hint">Los cambios se aplican al instante en la versión con servidor.</span><button class="btn btn-primary btn-lg" type="submit">Guardar cambios</button></div>
</form>
"""
    render(handler, t.layout("Contenido del sitio", body, active="contenido", admin=True, flash=flash),
           clear_flash=bool(flash))


def admin_suscripcion_toggle_submit(handler):
    actual = db.get_config_pagos()["suscripcion_activa"]
    db.set_suscripcion_activa(not actual)
    auditar(handler, "toggle_suscripcion", "activada" if not actual else "desactivada")
    mensaje = "Cobro de suscripción activado." if not actual else "Cobro de suscripción desactivado, publicar es gratis."
    redirect(handler, "/admin/contenido", flash=mensaje)


CAMPOS_IMAGEN_SITIO = ("hero_imagen_url", "explorar_imagen_url", "pymes_imagen_url")


def admin_contenido_submit(handler, form, archivos=None):
    archivos = archivos or {}
    errores_imagen = []
    for campo in CAMPOS_IMAGEN_SITIO:
        archivo = archivos.get(campo)
        if not archivo:
            continue
        if archivo["content_type"] not in _EXT_POR_TIPO:
            errores_imagen.append(f"La imagen de \"{campo}\" debe ser JPG, PNG o WebP.")
            continue
        if len(archivo["data"]) > 5 * 1024 * 1024:
            errores_imagen.append(f"La imagen de \"{campo}\" es muy pesada (máximo 5 MB).")
            continue
        ext = _EXT_POR_TIPO[archivo["content_type"]]
        form[campo] = db.subir_imagen(archivo["data"], archivo["content_type"], ext, carpeta="sitio")
    db.actualizar_contenido_sitio(form)
    auditar(handler, "actualizar_contenido_sitio", "portada y páginas públicas")
    destino = "/admin/editor" if form.get("volver") == "editor" else "/admin/contenido"
    flash = "Algunas imágenes no se pudieron guardar: " + " ".join(errores_imagen) if errores_imagen \
        else mensaje_sincronizacion("Contenido actualizado.", sincronizar_sitio_estatico())
    redirect(handler, destino, flash=flash)


def admin_editor(handler):
    """Vista fiel del sitio junto a todos sus campos de contenido editables."""
    sitio = db.get_contenido_sitio()
    flash = get_flash(handler)
    grupos = "".join(
        f'''<details class="editor-fields"{' open' if indice == 0 else ''}>
  <summary>{titulo}<span>Editar</span></summary>
  <div class="form-grid">{campos}</div>
</details>'''
        for indice, (titulo, campos) in enumerate(contenido_grupos(sitio))
    )
    body = f"""
<div class="editor-page">
  <div class="admin-page-head editor-page-head">
    <div><span class="eyebrow">Editor visual</span><h1>El sitio, editable en un solo lugar</h1>
    <p class="lede">La derecha es una réplica en vivo de Talcadatos. Edita cada texto a la izquierda, guarda y la vista se actualizará.</p></div>
    <a class="btn btn-ghost" href="/" target="_blank" rel="noopener">Abrir sitio ↗</a>
  </div>
  <div class="editor-layout">
    <aside class="editor-controls">
      <div class="editor-controls-head"><strong>Contenido y datos</strong><span>Todos los campos públicos</span></div>
      <label class="editor-route-label">Vista previa
        <select id="editor-page-select" aria-label="Página que se muestra en la vista previa">
          <option value="/">Inicio</option><option value="/avisos">Avisos</option>
          <option value="/necesito">Recomendar negocio</option><option value="/publicar">Publicar negocio</option><option value="/ayuda">Ayuda</option>
        </select>
      </label>
      <form method="post" action="/admin/contenido" class="form editor-form" enctype="multipart/form-data">
        <input type="hidden" name="volver" value="editor">
        {grupos}
        <button class="btn btn-primary editor-save" type="submit">Guardar y actualizar vista</button>
      </form>
      <div class="editor-data-links">
        <strong>Editar información publicada</strong>
        <a href="/admin/avisos">Avisos y servicios <span>→</span></a>
        <a href="/admin/anunciantes">Negocios y planes <span>→</span></a>
        <a href="/admin/sinonimos">Categorías y búsquedas <span>→</span></a>
        <a href="/admin/necesidades">Recomendaciones de la comunidad <span>→</span></a>
        <a href="/admin/usuarios">Usuarios administradores <span>→</span></a>
      </div>
    </aside>
    <section class="editor-preview-panel" aria-label="Vista previa del sitio">
      <div class="editor-preview-bar"><span class="editor-live-dot"></span><strong>Réplica del sitio público</strong><span class="editor-preview-url">talca.cl<span id="editor-page-name">/</span></span></div>
      <iframe id="editor-preview" src="/" title="Vista previa de Talcadatos"></iframe>
    </section>
  </div>
</div>
"""
    render(handler, t.layout("Editor visual", body, active="editor", admin=True, flash=flash),
           clear_flash=bool(flash))


def admin_cuenta(handler, error=None):
    admin = current_admin(handler)
    if not admin:
        return redirect(handler, "/admin/login")
    mensaje = f'<p class="form-error">{t.esc(error)}</p>' if error else ""
    flash = get_flash(handler)
    body = f"""
<div class="panel panel-narrow">
  <span class="eyebrow">Cuenta de administrador</span>
  <h1>{t.esc(admin['usuario'])}</h1>
  <p class="lede">Rol: <strong>{t.esc(admin['rol'])}</strong>. Cambia tu contraseña cuando lo necesites.</p>
  {mensaje}
  <form method="post" action="/admin/cuenta" class="form">
    <label>Contraseña actual <input name="actual" type="password" required autocomplete="current-password"></label>
    <label>Nueva contraseña <input name="nueva" type="password" required minlength="10" autocomplete="new-password"></label>
    <label>Repite la nueva contraseña <input name="confirmacion" type="password" required minlength="10" autocomplete="new-password"></label>
    <button class="btn btn-primary" type="submit">Actualizar contraseña</button>
  </form>
</div>
"""
    render(handler, t.layout("Mi cuenta", body, active="cuenta", admin=True, flash=flash), clear_flash=bool(flash))


def admin_cuenta_submit(handler, form):
    admin = current_admin(handler)
    if not admin:
        return redirect(handler, "/admin/login")
    usuario = admin["usuario"]
    registro = db.get_admin_usuario(usuario)
    if not registro or not db.verify_password(form.get("actual", ""), registro["password"]):
        return admin_cuenta(handler, "La contraseña actual no es correcta.")
    nueva = form.get("nueva", "")
    if len(nueva) < 10:
        return admin_cuenta(handler, "La nueva contraseña debe tener al menos 10 caracteres.")
    if nueva != form.get("confirmacion", ""):
        return admin_cuenta(handler, "La confirmación de contraseña no coincide.")
    db.actualizar_password_admin(usuario, db.hash_password(nueva))
    auditar(handler, "actualizar_password", usuario)
    redirect(handler, "/admin/cuenta", flash="Contraseña actualizada.")


def admin_usuarios(handler):
    usuarios = db.get_admin_usuarios()
    filas = "".join(f"""
<tr>
  <td>{t.esc(u['usuario'])}</td>
  <td>{t.badge(u['rol'], 'gold' if u['rol'] == 'super_admin' else 'muted')}</td>
  <td class="admin-actions">
    <form method="post" action="/admin/usuarios/{u['id']}/eliminar" data-ajax-delete
      data-confirm="¿Eliminar este usuario admin?">
      <button class="btn btn-icon btn-bad" title="Eliminar" aria-label="Eliminar">🗑️</button>
    </form>
  </td>
</tr>""" for u in usuarios)
    flash = get_flash(handler)
    body = f"""
<h1>Usuarios administradores</h1>
<p class="lede"><code>super_admin</code> tiene acceso completo. <code>moderador</code> solo puede aprobar/rechazar
avisos y revisar reportes (PRD §7.5).</p>
<div class="panel">
  <form method="post" action="/admin/usuarios/crear" class="form form-inline">
    <input name="usuario" required placeholder="usuario">
    <input name="password" type="password" required placeholder="contraseña">
    <select name="rol"><option value="moderador">moderador</option><option value="super_admin">super_admin</option></select>
    <button class="btn btn-primary" type="submit">Crear</button>
  </form>
</div>
<div class="tbl-wrap" data-reveal><table>
  <tr><th>Usuario</th><th>Rol</th><th></th></tr>
  {filas}
</table></div>
"""
    render(handler, t.layout("Usuarios administradores", body, active="usuarios", admin=True, flash=flash),
           clear_flash=bool(flash))


def admin_usuario_crear(handler, form):
    usuario = form.get("usuario", "").strip()
    password = form.get("password", "")
    rol = form.get("rol") if form.get("rol") in ("super_admin", "moderador") else "moderador"
    if not usuario or not password:
        return redirect(handler, "/admin/usuarios", flash="Usuario y contraseña son obligatorios.")
    creado = db.crear_admin_usuario(usuario, db.hash_password(password), rol)
    if not creado:
        return redirect(handler, "/admin/usuarios", flash="Ese usuario ya existe.")
    auditar(handler, "crear_usuario_admin", f"{usuario} ({rol})")
    redirect(handler, "/admin/usuarios", flash=f"Usuario {usuario} creado.")


def admin_usuario_eliminar(handler, usuario):
    eliminado = db.eliminar_admin_usuario(usuario)
    if eliminado:
        auditar(handler, "eliminar_usuario_admin", usuario)
        mensaje = f"Usuario {usuario} eliminado."
    else:
        mensaje = "No puedes eliminar el único usuario administrador que queda."
    if _es_ajax(handler):
        if eliminado:
            handler.send_response(204)
            handler.end_headers()
        else:
            data = mensaje.encode("utf-8")
            handler.send_response(409)
            handler.send_header("Content-Type", "text/plain; charset=utf-8")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
        return
    redirect(handler, "/admin/usuarios", flash=mensaje)


GUIAS = {
    "como-elegir-gasfiter-en-talca": {
        "titulo": "Cómo elegir un gásfiter en Talca: 5 señales de confianza",
        "descripcion": "Qué revisar antes de contratar un gásfiter en Talca, para evitar sorpresas y malos arreglos.",
        "categoria": "gasfiteria",
        "cuerpo": """
<p class="lede">Una fuga o una cañería rota no da tiempo para investigar mucho — pero unos minutos de más
al elegir a quién llamar pueden evitarte un segundo arreglo la semana siguiente. Estas son cinco cosas que vale
la pena revisar.</p>
<h2>1. Que atienda en tu comuna, no "en toda la región"</h2>
<p>Un gásfiter que realmente trabaja en tu sector suele llegar más rápido y conoce mejor los problemas típicos
de las instalaciones del barrio (presión de agua, antigüedad de las cañerías, etc.).</p>
<h2>2. Que te dé un precio antes de empezar</h2>
<p>Para trabajos que no son una emergencia, pide una estimación por WhatsApp antes de que llegue — foto o video
del problema ayuda a que la cotización sea más precisa.</p>
<h2>3. Que explique qué encontró, no solo que "ya quedó"</h2>
<p>Un buen profesional te cuenta qué causó el problema, no solo lo soluciona. Eso también te dice si el arreglo
es definitivo o parche.</p>
<h2>4. Urgencias 24/7 vs. horario de oficina</h2>
<p>No todos atienden de noche o fin de semana — si es algo que puede esperar, preguntar el horario de atención
te ahorra cobros de urgencia innecesarios.</p>
<h2>5. Referencias o negocio verificado</h2>
<p>En Talcadatos, los negocios con la marca <strong>✔ verificado</strong> pasaron una revisión adicional del
equipo — es una señal más, aunque no reemplaza tu propio criterio.</p>
<p><a class="btn btn-whatsapp" href="/avisos?categoria=gasfiteria">Ver gásfiteres en Talca →</a></p>
""",
    },
    "a-quien-llamar-en-talca": {
        "titulo": "Guía rápida: a quién llamar en Talca según lo que necesites",
        "descripcion": "Un mapa rápido de rubros y cuándo conviene llamar a cada uno, para no perder tiempo buscando.",
        "categoria": None,
        "cuerpo": """
<p class="lede">Cuando algo se rompe o necesitas resolver algo puntual, lo difícil no es encontrar un número —
es saber a quién exactamente llamar primero. Esta guía junta los rubros más buscados en Talca con una idea
rápida de cuándo corresponde cada uno.</p>
<h2>🔧 Gásfitería</h2>
<p>Fugas, baja presión de agua, instalación de artefactos sanitarios, calefont. Casi siempre vale la pena
preguntar si atienden urgencias.</p>
<h2>💡 Electricidad</h2>
<p>Cortes de luz en un sector de la casa, instalación de enchufes o luminarias, certificación SEC para
trámites. Un electricista certificado es clave si necesitas el certificado para notificar la conexión.</p>
<h2>🪟 Vidriería y ventanas</h2>
<p>Vidrios rotos, termopaneles, cambio de sellos. Mientras más rápido lo resuelvas, menos filtraciones de
agua o aire vas a tener.</p>
<h2>🏗️ Aluminios y estructuras</h2>
<p>Estructuras metálicas, cierres, ampliaciones livianas — normalmente conviene pedir una visita para medir
antes de cotizar.</p>
<h2>📚 Clases particulares</h2>
<p>Reforzamiento escolar, idiomas, preparación de pruebas — revisa nuestra <a href="/guias/clases-particulares-talca">guía
específica</a> para elegir bien.</p>
<h2>📊 Contabilidad y trámites</h2>
<p>Iniciar actividades, declaraciones de impuestos, boletas — útil tenerlo resuelto antes de que se acerque
la fecha límite, no el mismo día.</p>
<p><a class="btn btn-whatsapp" href="/avisos">Explorar todos los rubros →</a></p>
""",
    },
    "clases-particulares-talca": {
        "titulo": "Qué preguntar antes de contratar una clase particular en Talca",
        "descripcion": "Preguntas clave antes de elegir profesor particular en Talca, para colegio, idiomas o preparación de pruebas.",
        "categoria": "clases",
        "cuerpo": """
<p class="lede">Ya sea para reforzar una materia, aprender un idioma o preparar una prueba, elegir bien al
profesor particular hace la diferencia entre avanzar rápido o dar vueltas en círculo. Antes de agendar la
primera clase, vale la pena preguntar esto.</p>
<h2>¿Clases presenciales, online, o ambas?</h2>
<p>Define esto primero — cambia bastante la logística y a veces también el precio.</p>
<h2>¿Tiene experiencia con el nivel o la edad específica?</h2>
<p>No es lo mismo enseñar inglés conversacional a un adulto que preparar a un niño para una prueba del colegio.
Pregunta directamente si ha trabajado con casos parecidos al tuyo.</p>
<h2>¿Cómo mide el avance?</h2>
<p>Un buen profesor particular puede contarte, aunque sea de forma simple, cómo va a saber si las clases están
funcionando — no solo "vamos viendo".</p>
<h2>¿Qué pasa si necesitas cancelar una clase?</h2>
<p>Pregunta la política de cancelación antes de la primera clase, no después de la primera vez que la
necesites.</p>
<h2>Empieza con una clase de prueba</h2>
<p>Si es posible, pide una primera clase para ver si hay buena conexión antes de comprometerte a un paquete
completo.</p>
<p><a class="btn btn-whatsapp" href="/avisos?categoria=clases">Ver clases particulares en Talca →</a></p>
""",
    },
}


FAQ = [
    ("¿Cómo publico mi negocio?", "Ve a \"Publicar mi negocio\", completa el formulario y tu aviso queda en "
     "revisión. Normalmente se aprueba el mismo día."),
    ("¿Cuánto cuesta publicar?", "Publicar es gratis. Si quieres aparecer primero en los listados y en el "
     "buscador, puedes pasar a un plan Destacado o Premium."),
    ("¿Cómo me contactan los clientes?", "Directo por WhatsApp: cada aviso tiene un botón que abre una "
     "conversación contigo con un mensaje ya escrito. No hay intermediarios ni comisión por contacto."),
    ("¿Por qué mi aviso no aparece todavía?", "Los avisos nuevos pasan por una revisión rápida antes de "
     "publicarse. Si pasaron más de 24 horas y no aparece, contáctanos."),
    ("¿Puedo tener más de un aviso?", "Sí, en los planes Destacado y Premium. El plan Gratis incluye un aviso."),
    ("¿Qué hago si un aviso me parece falso o desactualizado?", "Ábrelo y usa el botón \"Reportar aviso\" — "
     "nuestro equipo lo revisa."),
]


def ayuda(handler):
    sitio = db.get_contenido_sitio()
    items = "".join(f"""
<details class="faq-item">
  <summary>{t.esc(pregunta)}</summary>
  <p>{t.esc(respuesta)}</p>
</details>""" for pregunta, respuesta in FAQ)
    guias_links = "".join(
        f'<li><a href="/guias/{slug}">{t.esc(g["titulo"])}</a></li>' for slug, g in GUIAS.items())
    body = f"""
<div class="panel panel-narrow">
  <h1>Preguntas frecuentes</h1>
  <div class="faq">{items}</div>
  <p class="lede">¿Tu pregunta no está aquí? Escríbenos por WhatsApp desde cualquier aviso, o publica tu negocio
  y te contactamos nosotros.</p>
  <h2>Guías</h2>
  <ul>{guias_links}</ul>
</div>
"""
    render(handler, t.layout("Ayuda", body, active="ayuda", site=sitio))


def guia_detalle(handler, slug):
    guia = GUIAS.get(slug)
    if not guia:
        return not_found(handler)
    sitio = db.get_contenido_sitio()
    canonical = f"{_origin(handler)}/guias/{slug}"
    body = f"""
<div class="panel panel-narrow">
  <span class="eyebrow">Guía</span>
  <h1>{t.esc(guia['titulo'])}</h1>
  {guia['cuerpo']}
</div>
"""
    render(handler, t.layout(guia["titulo"], body, active="ayuda", description=guia["descripcion"],
                              canonical=canonical, site=sitio))


def terminos(handler):
    sitio = db.get_contenido_sitio()
    body = f"""
<div class="panel panel-narrow">
  <h1>Términos de uso</h1>
  <p class="lede">Última actualización: {datetime.date.today().isoformat()}</p>
  <p>{t.esc(sitio['marca'])} es un directorio que conecta a personas de Talca con pymes y emprendedores locales.
  Publicar un aviso es gratuito y queda sujeto a revisión antes de aparecer en el sitio.</p>
  <h2>Qué puedes publicar</h2>
  <p>La información de tu negocio debe ser real, propia y estar vigente. No se permite publicar contenido falso,
  ofensivo, ilegal, ni suplantar a otro negocio o persona. Nos reservamos el derecho de rechazar o dar de baja
  cualquier aviso que no cumpla con esto, sin necesidad de previo aviso.</p>
  <h2>El contacto es directo</h2>
  <p>{t.esc(sitio['marca'])} solo conecta: cuando alguien te escribe por WhatsApp desde un aviso, esa conversación
  y cualquier acuerdo comercial es entre esa persona y tu negocio. No somos parte de esa transacción ni
  respondemos por la calidad, precio o resultado del servicio.</p>
  <h2>Exactitud de la información</h2>
  <p>Toda la información de cada aviso (descripción, horarios, WhatsApp, fotos) la ingresa directamente el
  negocio que publica, no {t.esc(sitio['marca'])}. No verificamos de forma exhaustiva cada dato ni garantizamos
  que esté siempre actualizado. La insignia <strong>✔ verificado</strong> indica una revisión adicional de
  nuestro equipo, pero tampoco es una garantía absoluta. Recomendamos siempre confirmar directamente con el
  negocio antes de acordar o pagar por un servicio.</p>
  <h2>Responsabilidad de quien publica</h2>
  <p>Si publicas un negocio, eres el único responsable de que la información que ingresas sea veraz, esté
  actualizada y no infrinja derechos de terceros (por ejemplo, usar el nombre, logo o fotos de otro negocio sin
  autorización). Te comprometes a responder por cualquier reclamo que se origine por información falsa,
  engañosa o que infrinja derechos de terceros que hayas publicado, incluyendo los costos razonables en que
  {t.esc(sitio['marca'])} pueda incurrir por ese motivo.</p>
  <h2>Contenido que subes (fotos y textos)</h2>
  <p>Las fotos y textos que subes siguen siendo tuyos. Al publicarlos, nos das permiso para mostrarlos en el
  sitio y usarlos con fines de promoción del directorio (por ejemplo, en redes sociales), siempre relacionados
  con tu propio aviso. Puedes pedir que se elimine tu contenido en cualquier momento.</p>
  <h2>Uso permitido de la información publicada</h2>
  <p>El contenido del sitio (avisos, datos de contacto, etc.) es para uso personal de quien busca un servicio en
  Talca. No está permitido extraer, copiar o recopilar de forma masiva y automatizada ("scraping") los avisos o
  los datos de contacto publicados, ni usarlos para enviar publicidad no solicitada o para fines distintos a
  contactar al negocio por el servicio que ofrece.</p>
  <h2>Limitación de responsabilidad</h2>
  <p>{t.esc(sitio['marca'])} es una plataforma de intermediación: pone en contacto a personas con negocios
  locales, pero no participa, garantiza ni supervisa los acuerdos, pagos o servicios que resulten de ese
  contacto. En la máxima medida permitida por la ley, no somos responsables por daños, pérdidas o perjuicios
  derivados del uso del sitio, de la información publicada por terceros, o de tratos comerciales entre usuarios
  y negocios.</p>
  <h2>Suspensión de avisos y cuentas</h2>
  <p>Podemos suspender, pausar o eliminar cualquier aviso o cuenta de administrador, sin previo aviso, ante
  incumplimiento de estos términos, uso indebido de la plataforma, o a solicitud de una autoridad competente.</p>
  <h2>Reportes y moderación</h2>
  <p>Cualquier persona puede reportar un aviso que le parezca incorrecto o engañoso. Revisamos los reportes y
  podemos pausar o eliminar avisos según corresponda.</p>
  <h2>Ley aplicable</h2>
  <p>Estos términos se rigen por las leyes de la República de Chile. Cualquier controversia se somete a los
  tribunales ordinarios de justicia de Talca.</p>
  <h2>Cambios</h2>
  <p>Podemos actualizar estos términos en cualquier momento; los cambios importantes se reflejan en la fecha de
  arriba. Seguir usando el sitio después de un cambio implica que lo aceptas.</p>
  <p class="hint">¿Dudas sobre estos términos? Escríbenos desde el WhatsApp de cualquier aviso publicado, o desde
  <a href="/publicar">el formulario de publicar</a> si quieres que te contactemos.</p>
</div>
"""
    render(handler, t.layout("Términos de uso", body, active="terminos", site=sitio))


def privacidad(handler):
    sitio = db.get_contenido_sitio()
    body = f"""
<div class="panel panel-narrow">
  <h1>Privacidad</h1>
  <p class="lede">Última actualización: {datetime.date.today().isoformat()}</p>
  <p>Acá explicamos, en simple, qué datos guarda {t.esc(sitio['marca'])} y para qué.</p>
  <h2>Cuando publicas un negocio</h2>
  <p>Guardamos el nombre de tu negocio, tu WhatsApp, la descripción del aviso, la comuna y, si subes una, la foto
  que elegiste. Esa información se muestra públicamente en tu aviso una vez aprobado — es lo esperable para que
  la gente pueda encontrarte y contactarte.</p>
  <h2>Cuando recomiendas un negocio o reportas un aviso</h2>
  <p>Guardamos lo que escribes y, si lo dejas, tu WhatsApp — solo para poder avisarte si aparece algo que calza, o
  para dar seguimiento al reporte. No publicamos esa información en el sitio.</p>
  <h2>Favoritos</h2>
  <p>Los favoritos (☆) no se guardan en nuestros servidores — quedan solo en el navegador que estás usando
  (<code>localStorage</code>). Si borras los datos del sitio, cambias de navegador o de celular, se pierden. No
  tenemos forma de verlos ni de saber qué marcaste como favorito.</p>
  <h2>Dirección IP y datos técnicos</h2>
  <p>Cuando publicas un negocio, recomiendas uno o reportas un aviso, registramos también la dirección IP y la
  fecha de ese envío. Lo usamos únicamente para prevenir spam y abuso de los formularios, y como respaldo de que
  quien publicó un negocio aceptó los <a href="/terminos">Términos de uso</a> en esa fecha.</p>
  <h2>Dónde se guardan tus datos</h2>
  <p>La información se almacena en servidores de Google Cloud (infraestructura con cifrado en tránsito y en
  reposo). No compartimos acceso a esta base de datos con nadie fuera del equipo que administra Talcadatos.</p>
  <h2>Cuánto tiempo guardamos tus datos</h2>
  <p>Mientras tu aviso esté activo o pendiente de revisión. Si pides que eliminemos tu aviso, borramos la
  información asociada, salvo lo mínimo que debamos conservar por un tiempo razonable para efectos de seguridad
  o para responder ante un reclamo (por ejemplo, el registro de aceptación de términos).</p>
  <h2>Qué no hacemos</h2>
  <p>No vendemos tus datos a terceros ni los usamos para enviarte publicidad de otras empresas. No pedimos
  contraseña ni creamos una cuenta para navegar el sitio o publicar un aviso.</p>
  <h2>Tus derechos</h2>
  <p>De acuerdo a la ley chilena de protección de datos personales, puedes pedirnos en cualquier momento
  <strong>acceder</strong> a los datos que tenemos sobre tu negocio, <strong>rectificarlos</strong> si están
  desactualizados o son incorrectos, o <strong>eliminarlos</strong> (dar de baja tu aviso y su información).
  Escríbenos por WhatsApp desde el mismo aviso, o repórtalo indicando el motivo, y lo resolvemos a la brevedad.</p>
</div>
"""
    render(handler, t.layout("Privacidad", body, active="privacidad", site=sitio))


def favoritos(handler):
    sitio = db.get_contenido_sitio()
    body = """
<h1>Tus favoritos</h1>
<p class="lede">Los avisos que guardaste con el ☆ quedan aquí, solo en este navegador.</p>
<div id="favoritos-mount"><p class="empty-state">Cargando…</p></div>
"""
    render(handler, t.layout("Favoritos", body, active="favoritos", site=sitio))


def api_alerta(handler, body):
    data = json.loads(body or "{}")
    termino = (data.get("termino") or "").strip()[:120]
    whatsapp = (data.get("whatsapp") or "").strip()
    digitos = "".join(c for c in whatsapp if c.isdigit())
    if not termino or len(digitos) < 8:
        return render_json(handler, {"ok": False, "error": "Datos incompletos"}, status=400)
    db.crear_alerta(termino, whatsapp)
    render_json(handler, {"ok": True})


def aviso_reportar(handler, aviso_id, form):
    if _es_bot(form) or not db.verificar_limite(_client_ip(handler), "reportar", maximo=10):
        return redirect(handler, f"/avisos/{aviso_id}?reportado=1")
    motivo = form.get("motivo", "").strip()[:300] or "Sin motivo especificado"
    if db.get_aviso(aviso_id):
        db.crear_reporte(aviso_id, motivo)
    redirect(handler, f"/avisos/{aviso_id}?reportado=1")


# --------------------------------------------------------------- SEO / OG

def _og_cache_path(aviso_id):
    return os.path.join(OG_CACHE_DIR, f"{aviso_id}.png")


def _og_cache_evict(aviso_id):
    path = _og_cache_path(aviso_id)
    if os.path.isfile(path):
        os.remove(path)


def og_aviso(handler, aviso_id):
    cache_path = _og_cache_path(aviso_id)
    if os.path.isfile(cache_path):
        with open(cache_path, "rb") as f:
            return render_png(handler, f.read())
    aviso = db.get_aviso(aviso_id)
    if not aviso:
        handler.send_response(404)
        handler.end_headers()
        return
    data = ogimage.generar(aviso)
    with open(cache_path, "wb") as f:
        f.write(data)
    render_png(handler, data)


def og_default(handler):
    path = os.path.join(OG_CACHE_DIR, "default.png")
    if not os.path.isfile(path):
        with open(path, "wb") as f:
            f.write(ogimage.generar_default())
    with open(path, "rb") as f:
        render_png(handler, f.read())


def qr_aviso(handler, aviso_id):
    path = os.path.join(OG_CACHE_DIR, f"qr_{aviso_id}.png")
    if not os.path.isfile(path):
        aviso = db.get_aviso(aviso_id)
        if not aviso:
            handler.send_response(404)
            handler.end_headers()
            return
        canonical = f"{_origin(handler)}/avisos/{aviso_id}"
        with open(path, "wb") as f:
            f.write(ogimage.generar_qr(canonical))
    with open(path, "rb") as f:
        render_png(handler, f.read())


def robots_txt(handler):
    body = f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {_origin(handler)}/sitemap.xml\n"
    data = body.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def sitemap_xml(handler):
    origin = _origin(handler)
    ids = [a["id"] for a in db.get_avisos(estado="activo")]
    urls = ([f"{origin}/", f"{origin}/avisos", f"{origin}/publicar", f"{origin}/necesito",
             f"{origin}/ayuda", f"{origin}/terminos", f"{origin}/privacidad"]
            + [f"{origin}/guias/{slug}" for slug in GUIAS]
            + [f"{origin}/avisos/{i}" for i in ids])
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    data = body.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/xml; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length).decode("utf-8") if length else ""

    def _form(self):
        return {k: v for k, v in parse_qsl(self._body())}

    def _form_multipart(self):
        """Parsea multipart/form-data: devuelve (campos_de_texto, archivos).
        archivos es {nombre_campo: {"filename", "content_type", "data"}} para
        cada input de tipo file que realmente traiga un archivo seleccionado."""
        import cgi
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            return self._form(), {}
        fs = cgi.FieldStorage(
            fp=self.rfile, headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype,
                     "CONTENT_LENGTH": self.headers.get("Content-Length", "0")})
        form, archivos = {}, {}
        for key in fs.keys():
            item = fs[key]
            filename = getattr(item, "filename", None)
            if filename:
                if filename.strip():
                    archivos[key] = {"filename": filename, "content_type": item.type, "data": item.value}
            else:
                form[key] = item.value
        return form, archivos

    def end_headers(self):
        """Cabeceras de seguridad estandar para toda respuesta, en un solo
        lugar en vez de repetirlas en cada funcion de ruta."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data: blob: https://storage.googleapis.com; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'self'"
        )
        super().end_headers()

    def do_GET(self):
        parts = urlsplit(self.path)
        path, query = parts.path, parts.query

        if path in (PREVIEW_PATH, PREVIEW_PATH + "/"):
            return _otorgar_preview(self)
        if not _ruta_libre(path) and not _tiene_acceso_preview(self):
            return pagina_en_construccion(self)

        segs = [s for s in path.split("/") if s != ""]

        try:
            if path == "/":
                return home(self)
            if path == "/explorar":
                return redirect(self, "/avisos")
            if path == "/avisos":
                return listado(self, query)
            if len(segs) == 2 and segs[0] == "avisos" and segs[1].isdigit():
                return detalle(self, int(segs[1]), query)
            if path == "/publicar":
                return publicar_form(self, ok=qs(query).get("ok") == "1", sub_token=qs(query).get("sub"))
            if path == "/api/mp-webhook":
                return api_mp_webhook(self, None, query)
            if path == "/necesito":
                return necesito_form(self, ok=qs(query).get("ok") == "1")
            if path == "/sw.js":
                return self._static("/static/sw.js")
            if path == "/static" or path.startswith("/static/"):
                return self._static(path)
            if path == "/robots.txt":
                return robots_txt(self)
            if path == "/sitemap.xml":
                return sitemap_xml(self)
            if path == "/og/default.png":
                return og_default(self)
            if len(segs) == 2 and segs[0] == "og" and segs[1].endswith(".png") and segs[1][:-4].isdigit():
                return og_aviso(self, int(segs[1][:-4]))
            if len(segs) == 3 and segs[0] == "avisos" and segs[1].isdigit() and segs[2] == "qr.png":
                return qr_aviso(self, int(segs[1]))

            if path == "/admin/login":
                return admin_login_form(self)
            if path == "/admin/logout":
                return admin_logout(self)
            if path == "/admin":
                return admin_dashboard(self, query) if require_admin(self) else None
            if path == "/admin/moderacion":
                return admin_moderacion(self) if require_admin(self) else None
            if path == "/admin/reportes":
                return admin_reportes(self) if require_admin(self) else None
            if path == "/admin/avisos":
                return admin_avisos_lista(self, query) if require_role(self, {"super_admin"}) else None
            if len(segs) == 3 and segs[0] == "admin" and segs[1] == "avisos" and segs[2].isdigit():
                return admin_aviso_editar_form(self, int(segs[2])) if require_role(self, {"super_admin"}) else None
            if path == "/admin/avisos.csv":
                return admin_avisos_csv(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/anunciantes":
                return admin_anunciantes(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/anunciantes.csv":
                return admin_anunciantes_csv(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/analitica":
                return admin_analitica(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/sinonimos":
                return admin_sinonimos(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/auditoria":
                return admin_auditoria(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/pagos":
                return admin_pagos(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/pagos.csv":
                return admin_pagos_csv(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/alertas":
                return admin_alertas(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/necesidades":
                return admin_necesidades(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/editor":
                return admin_editor(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/contenido":
                return admin_contenido(self) if require_role(self, {"super_admin"}) else None
            if path == "/admin/cuenta":
                return admin_cuenta(self) if require_admin(self) else None
            if path == "/admin/usuarios":
                return admin_usuarios(self) if require_role(self, {"super_admin"}) else None
            if path == "/ayuda":
                return ayuda(self)
            if len(segs) == 2 and segs[0] == "guias":
                return guia_detalle(self, segs[1])
            if path == "/terminos":
                return terminos(self)
            if path == "/privacidad":
                return privacidad(self)
            if path == "/favoritos":
                return favoritos(self)

            return not_found(self)
        except BrokenPipeError:
            pass
        except Exception as exc:
            return server_error(self, exc)

    def do_POST(self):
        parts = urlsplit(self.path)
        path = parts.path

        if not _ruta_libre(path) and not _tiene_acceso_preview(self):
            return pagina_en_construccion(self)

        segs = [s for s in path.split("/") if s != ""]

        try:
            if path == "/publicar":
                form, archivos = self._form_multipart()
                return publicar_submit(self, form, archivos.get("foto"))
            if path == "/suscripcion/iniciar":
                return suscripcion_iniciar_submit(self, self._form())
            if path == "/api/mp-webhook":
                return api_mp_webhook(self, self._body(), parts.query)
            if path == "/necesito":
                return necesito_submit(self, self._form())
            if path == "/api/buscar":
                return api_buscar(self, self._body())
            if path == "/api/favoritos":
                return api_favoritos(self, self._body())
            if path == "/api/evento":
                return api_evento(self, self._body())
            if path == "/api/alerta":
                return api_alerta(self, self._body())
            if len(segs) == 3 and segs[0] == "avisos" and segs[1].isdigit() and segs[2] == "reportar":
                return aviso_reportar(self, int(segs[1]), self._form())
            if path == "/admin/login":
                return admin_login_submit(self, self._form())
            if path == "/admin/contenido":
                if not require_role(self, {"super_admin"}):
                    return None
                form, archivos = self._form_multipart()
                return admin_contenido_submit(self, form, archivos)
            if path == "/admin/suscripcion/toggle":
                if not require_role(self, {"super_admin"}):
                    return None
                return admin_suscripcion_toggle_submit(self)
            if path == "/admin/cuenta":
                return admin_cuenta_submit(self, self._form()) if require_admin(self) else None

            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "moderacion" and segs[3] in ("aprobar", "rechazar"):
                return admin_moderar(self, int(segs[2]), segs[3]) if require_admin(self) else None
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "reportes" and segs[3] == "descartar":
                return admin_reporte_descartar(self, int(segs[2])) if require_admin(self) else None
            if len(segs) == 3 and segs[0] == "admin" and segs[1] == "avisos" and segs[2].isdigit():
                if not require_role(self, {"super_admin"}):
                    return None
                form, archivos = self._form_multipart()
                return admin_aviso_editar_submit(self, int(segs[2]), form, archivos)
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "avisos" and segs[3] == "eliminar":
                return admin_aviso_eliminar(self, int(segs[2])) if require_role(self, {"super_admin"}) else None
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "avisos" and segs[3] == "aprobar":
                return admin_aviso_aprobar(self, int(segs[2])) if require_role(self, {"super_admin"}) else None
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "avisos" and segs[3] == "rechazar":
                return admin_aviso_rechazar(self, int(segs[2])) if require_role(self, {"super_admin"}) else None
            if (len(segs) == 5 and segs[0] == "admin" and segs[1] == "avisos" and segs[3] == "fotos"
                    and segs[4] == "agregar"):
                if not require_role(self, {"super_admin"}):
                    return None
                form, archivos = self._form_multipart()
                return admin_aviso_foto_agregar_submit(self, int(segs[2]), form, archivos)
            if (len(segs) == 5 and segs[0] == "admin" and segs[1] == "avisos" and segs[3] == "fotos"
                    and segs[4] == "eliminar"):
                if not require_role(self, {"super_admin"}):
                    return None
                form, _archivos = self._form_multipart()
                return admin_aviso_foto_eliminar_submit(self, int(segs[2]), form)
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "anunciantes" and segs[3] == "plan":
                return admin_anunciante_plan(self, int(segs[2]), self._form()) if require_role(self, {"super_admin"}) else None
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "anunciantes" and segs[3] == "verificar":
                return admin_anunciante_verificar(self, int(segs[2])) if require_role(self, {"super_admin"}) else None
            if path == "/admin/sinonimos/agregar":
                return admin_sinonimo_agregar(self, self._form()) if require_role(self, {"super_admin"}) else None
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "sinonimos" and segs[3] == "eliminar":
                return admin_sinonimo_eliminar(self, int(segs[2])) if require_role(self, {"super_admin"}) else None
            if path == "/admin/usuarios/crear":
                return admin_usuario_crear(self, self._form()) if require_role(self, {"super_admin"}) else None
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "usuarios" and segs[3] == "eliminar":
                return admin_usuario_eliminar(self, segs[2]) if require_role(self, {"super_admin"}) else None
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "alertas" and segs[3] == "atendida":
                return admin_alerta_atendida(self, int(segs[2])) if require_role(self, {"super_admin"}) else None
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "necesidades" and segs[3] == "atendida":
                return admin_necesidad_atendida(self, int(segs[2])) if require_role(self, {"super_admin"}) else None

            return not_found(self)
        except BrokenPipeError:
            pass
        except Exception as exc:
            return server_error(self, exc)

    def _static(self, path):
        rel = path[len("/static/"):] if path.startswith("/static/") else ""
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self.send_response(404)
            self.end_headers()
            return
        ctype = "text/css" if full.endswith(".css") else \
                "application/javascript" if full.endswith(".js") else \
                "application/manifest+json" if full.endswith(".webmanifest") else \
                "image/jpeg" if full.endswith((".jpg", ".jpeg")) else \
                "image/png" if full.endswith(".png") else "application/octet-stream"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8002))
    db.seed_if_empty()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Talcadatos corriendo en http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
