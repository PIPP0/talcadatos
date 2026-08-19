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
import json
import secrets
import datetime
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

SESSIONS = set()


# ---------------------------------------------------------------- helpers

def qs(query_string):
    return {k: v[0] for k, v in parse_qs(query_string).items()}


def is_admin(handler):
    cookie = SimpleCookie(handler.headers.get("Cookie", ""))
    token = cookie["talca_admin"].value if "talca_admin" in cookie else None
    return token in SESSIONS


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
    return f"http://{host}"


def require_admin(handler):
    if not is_admin(handler):
        redirect(handler, "/admin/login")
        return False
    return True


AVISO_SELECT = """
SELECT aviso.*, negocio.nombre AS negocio_nombre, negocio.whatsapp,
       negocio.verificado, categoria.nombre AS categoria_nombre,
       categoria.slug AS categoria_slug, categoria.icono,
       plan.prioridad AS plan_prioridad, plan.nombre AS plan_nombre
FROM aviso
JOIN negocio ON negocio.id = aviso.negocio_id
JOIN categoria ON categoria.id = aviso.categoria_id
JOIN plan ON plan.id = negocio.plan_id
"""


# --------------------------------------------------------------- publico

def home(handler):
    conn = db.get_conn()
    categorias = conn.execute("SELECT * FROM categoria ORDER BY nombre").fetchall()
    destacados = conn.execute(
        AVISO_SELECT + " WHERE aviso.estado='activo' AND plan.prioridad > 0 "
        "ORDER BY plan.prioridad DESC, aviso.publicado_en DESC LIMIT 6"
    ).fetchall()
    recientes = conn.execute(
        AVISO_SELECT + " WHERE aviso.estado='activo' ORDER BY aviso.publicado_en DESC LIMIT 8"
    ).fetchall()
    n_negocios = conn.execute("SELECT COUNT(DISTINCT negocio_id) c FROM aviso WHERE estado='activo'").fetchone()["c"]
    n_contactos = conn.execute("SELECT COUNT(*) c FROM evento WHERE tipo='click_whatsapp'").fetchone()["c"]
    n_categorias = conn.execute(
        "SELECT COUNT(DISTINCT categoria_id) c FROM aviso WHERE estado='activo'").fetchone()["c"]
    conn.close()

    body = f"""
<section class="hero">
  <h1>Encuentra al negocio de Talca que necesitas, al toque.</h1>
  <p class="hero-sub">Escribe lo que buscas —"ventanas", "clases de inglés", "gásfiter"— y Talcadatos te muestra
  al negocio local correcto, con WhatsApp directo para escribirle ahora mismo.</p>
  <form class="search-box" id="search-form" autocomplete="off">
    <span class="search-icon">🔎</span>
    <input id="search-input" name="q" type="text" placeholder="¿Qué estás buscando? Ej: ventanas, pan amasado, clases de inglés…">
    <button class="btn btn-primary" type="submit">Buscar</button>
    <div id="search-results" class="search-results" hidden></div>
  </form>
  {t.categorias_pills(categorias)}
</section>

<section class="stat-bar">
  <div><strong>{n_negocios}</strong><span>negocios activos en Talca</span></div>
  <div><strong>{n_contactos}</strong><span>contactos por WhatsApp generados</span></div>
  <div><strong>{n_categorias}</strong><span>rubros distintos</span></div>
</section>

<section class="section">
  <div class="section-head">
    <h2>Destacados de esta semana</h2>
    <a href="/avisos">Ver todos →</a>
  </div>
  {t.cards_grid(destacados, vacio_msg="Todavía no hay avisos destacados. ¡Sé el primero en Publicar tu negocio!")}
</section>

<section class="how">
  <div class="how-step"><span class="how-n">1</span><h3>Busca lo que necesitas</h3><p>Escribe en el buscador o filtra por categoría y comuna.</p></div>
  <div class="how-step"><span class="how-n">2</span><h3>Elige un negocio</h3><p>Revisa su ficha: qué ofrece, dónde atiende y su horario.</p></div>
  <div class="how-step"><span class="how-n">3</span><h3>Escríbele por WhatsApp</h3><p>Un clic y quedas hablando directo con el negocio, sin intermediarios.</p></div>
</section>

<section class="section">
  <div class="section-head">
    <h2>Recién publicados</h2>
    <a href="/avisos">Ver todos →</a>
  </div>
  {t.cards_grid(recientes)}
</section>
"""
    render(handler, t.layout("Avisos de pymes y emprendedores de Talca", body, active="home",
                              og_image=f"{_origin(handler)}/og/default.png"))


def listado(handler, query):
    params = qs(query)
    q = params.get("q", "").strip()
    categoria_slug = params.get("categoria", "")
    comuna = params.get("comuna", "")
    orden = params.get("orden", "relevancia")

    conn = db.get_conn()
    categorias = conn.execute("SELECT * FROM categoria ORDER BY nombre").fetchall()
    comunas = [r["comuna"] for r in conn.execute(
        "SELECT DISTINCT comuna FROM aviso WHERE estado='activo' ORDER BY comuna").fetchall()]

    if q:
        avisos = search.buscar_avisos(conn, q, limite=40)
        titulo_pagina = f'Resultados para "{q}"'
    else:
        sql = AVISO_SELECT + " WHERE aviso.estado='activo'"
        args = []
        if categoria_slug:
            sql += " AND categoria.slug = ?"
            args.append(categoria_slug)
        if comuna:
            sql += " AND aviso.comuna = ?"
            args.append(comuna)
        if orden == "recientes":
            sql += " ORDER BY aviso.publicado_en DESC"
        elif orden == "populares":
            sql += " ORDER BY aviso.contactos_total DESC"
        else:
            sql += " ORDER BY plan.prioridad DESC, aviso.publicado_en DESC"
        avisos = conn.execute(sql, args).fetchall()
        titulo_pagina = "Explorar avisos"
    conn.close()

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

    body = f"""
<div class="listado-head">
  <h1>{t.esc(titulo_pagina)}</h1>
  <form class="filters" method="get" action="/avisos">
    {f'<input type="hidden" name="q" value="{t.esc(q)}">' if q else ""}
    <select name="categoria" onchange="this.form.submit()">{cat_options}</select>
    <select name="comuna" onchange="this.form.submit()">{comuna_options}</select>
    <select name="orden" onchange="this.form.submit()">{orden_options}</select>
  </form>
</div>
{t.cards_grid(avisos, termino_busqueda=q or None)}
"""
    render(handler, t.layout(titulo_pagina, body, active="avisos"))


def detalle(handler, aviso_id):
    conn = db.get_conn()
    aviso = conn.execute(AVISO_SELECT + " WHERE aviso.id = ?", (aviso_id,)).fetchone()
    if not aviso or aviso["estado"] != "activo":
        conn.close()
        return not_found(handler)

    conn.execute(
        "INSERT INTO evento (aviso_id, tipo, sesion_hash, creado_en) VALUES (?, 'vista', ?, ?)",
        (aviso_id, secrets.token_hex(4), db.now()),
    )
    conn.execute("UPDATE aviso SET vistas_total = vistas_total + 1 WHERE id = ?", (aviso_id,))
    conn.commit()

    relacionados = conn.execute(
        AVISO_SELECT + " WHERE aviso.estado='activo' AND categoria.id = ? AND aviso.id != ? "
        "ORDER BY plan.prioridad DESC LIMIT 3",
        (aviso["categoria_id"], aviso_id),
    ).fetchall()
    conn.close()

    wa = t.whatsapp_url(aviso["whatsapp"], aviso["negocio_nombre"], aviso["titulo"])
    destacado_html = t.plan_badge(aviso["plan_nombre"]) if aviso["plan_nombre"] != "Gratis" else ""
    verificado_html = '<span class="check">✔ Negocio verificado</span>' if aviso["verificado"] else ""

    canonical = f"{_origin(handler)}/avisos/{aviso_id}"
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

    body = f"""
<div class="detalle">
  <div class="detalle-photo" style="--card-accent:{t.esc(aviso['color'])}">
    <span class="card-icon big">{aviso['icono']}</span>
    {destacado_html}
  </div>
  <div class="detalle-body">
    <div class="mono detalle-cat">{aviso['icono']} {t.esc(aviso['categoria_nombre'])} · {t.esc(aviso['comuna'])}</div>
    <h1>{t.esc(aviso['titulo'])}</h1>
    <div class="detalle-negocio">{t.esc(aviso['negocio_nombre'])} {verificado_html}</div>
    <p class="detalle-desc">{t.esc(aviso['descripcion'])}</p>
    {f'<p class="detalle-horario"><strong>Horario:</strong> {t.esc(aviso["horario"])}</p>' if aviso["horario"] else ""}
    <a class="btn btn-whatsapp btn-lg" href="{wa}" target="_blank" rel="noopener"
       data-aviso-id="{aviso['id']}" data-wa-click="1">
       💬 Escribir por WhatsApp
    </a>
    <div class="detalle-share">
      <button class="btn btn-ghost" type="button" onclick="navigator.clipboard.writeText(window.location.href); this.textContent='¡Link copiado!'">Compartir aviso</button>
    </div>
  </div>
</div>
{"<section class='section'><h2>También te puede servir</h2>" + t.cards_grid(relacionados) + "</section>" if relacionados else ""}
"""
    resumen = aviso["descripcion"][:157] + "…" if len(aviso["descripcion"]) > 160 else aviso["descripcion"]
    render(handler, t.layout(
        aviso["titulo"], body, active="avisos", description=resumen,
        og_image=f"{_origin(handler)}/og/{aviso_id}.png", canonical=canonical, json_ld=json_ld,
    ))


def _publicar_body(categorias, form=None, errores=None):
    form = form or {}
    errores = errores or []
    cat_options = "".join(
        f'<option value="{c["id"]}"{" selected" if str(c["id"]) == form.get("categoria_id") else ""}>'
        f'{c["icono"]} {t.esc(c["nombre"])}</option>' for c in categorias)
    v = lambda campo, default="": t.esc(form.get(campo, default))
    errores_html = ('<div class="form-errors"><ul>' + "".join(f"<li>{t.esc(e)}</li>" for e in errores) +
                     "</ul></div>") if errores else ""
    return f"""
<div class="panel">
  <h1>Publica tu negocio en Talcadatos</h1>
  <p class="lede">Es gratis. Completa el formulario y tu aviso queda listo para revisión — normalmente
  se aprueba el mismo día.</p>
  {errores_html}
  <form method="post" action="/publicar" class="form">
    <label>Nombre del negocio
      <input name="nombre_negocio" required maxlength="120" value="{v('nombre_negocio')}">
    </label>
    <label>WhatsApp de contacto
      <input name="whatsapp" required placeholder="+56 9 1234 5678" value="{v('whatsapp')}">
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
      <input name="comuna" required value="{v('comuna', 'Talca')}">
    </label>
    <label>Horario de atención (opcional)
      <input name="horario" placeholder="Lun a Vie 9:00-18:00" value="{v('horario')}">
    </label>
    <button class="btn btn-primary btn-lg" type="submit">Enviar aviso</button>
  </form>
</div>
"""


def publicar_form(handler, ok=False, form=None, errores=None):
    conn = db.get_conn()
    categorias = conn.execute("SELECT * FROM categoria ORDER BY nombre").fetchall()
    conn.close()

    if ok:
        body = """
<div class="panel panel-ok">
  <h1>¡Listo! Tu aviso fue enviado 🎉</h1>
  <p>Quedó en revisión. Nuestro equipo lo aprueba normalmente el mismo día y aparecerá en Talcadatos
  apenas se publique.</p>
  <a class="btn btn-primary" href="/">Volver al inicio</a>
</div>"""
        return render(handler, t.layout("Aviso enviado", body, active="publicar"))

    render(handler, t.layout("Publicar mi negocio", _publicar_body(categorias, form, errores), active="publicar"))


def _validar_publicar(form, categoria_ids):
    errores = []
    if not form.get("nombre_negocio", "").strip():
        errores.append("Ingresa el nombre de tu negocio.")
    digitos = "".join(c for c in form.get("whatsapp", "") if c.isdigit())
    if len(digitos) < 8:
        errores.append("Ingresa un WhatsApp válido, con código de país (ej: +56 9 1234 5678).")
    if form.get("categoria_id") not in categoria_ids:
        errores.append("Elige una categoría para tu aviso.")
    if not form.get("titulo", "").strip():
        errores.append("Ingresa un título para el aviso.")
    if not form.get("descripcion", "").strip():
        errores.append("Cuéntanos brevemente en qué consiste tu servicio.")
    if not form.get("comuna", "").strip():
        errores.append("Ingresa la comuna donde atiendes.")
    return errores


def publicar_submit(handler, form):
    conn = db.get_conn()
    categorias = conn.execute("SELECT id, slug FROM categoria").fetchall()
    categoria_ids = {str(c["id"]) for c in categorias}
    errores = _validar_publicar(form, categoria_ids)
    if errores:
        conn.close()
        return publicar_form(handler, form=form, errores=errores)

    slug = next(c["slug"] for c in categorias if str(c["id"]) == form["categoria_id"])
    color = db.COLOR_POR_CATEGORIA.get(slug, "#8C5F22")
    gratis_id = conn.execute("SELECT id FROM plan WHERE nombre='Gratis'").fetchone()["id"]
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO negocio (nombre, whatsapp, verificado, plan_id, plan_vencimiento, creado_en) "
        "VALUES (?, ?, 0, ?, NULL, ?)",
        (form.get("nombre_negocio", "").strip()[:120], form.get("whatsapp", "").strip(), gratis_id, db.now()),
    )
    negocio_id = cur.lastrowid
    cur.execute(
        "INSERT INTO aviso (negocio_id, titulo, descripcion, categoria_id, comuna, horario, "
        "color, estado, publicado_en, creado_en) VALUES (?,?,?,?,?,?,?, 'pendiente', NULL, ?)",
        (negocio_id, form.get("titulo", "").strip()[:120], form.get("descripcion", "").strip(),
         form.get("categoria_id"), form.get("comuna", "Talca").strip(), form.get("horario", "").strip(),
         color, db.now()),
    )
    conn.commit()
    conn.close()
    redirect(handler, "/publicar?ok=1")


def api_buscar(handler, body):
    data = json.loads(body or "{}")
    q = (data.get("q") or "").strip()
    conn = db.get_conn()
    if len(q) < 2:
        conn.close()
        return render_json(handler, {"resultados": []})
    avisos = search.buscar_avisos(conn, q, limite=6)
    if not avisos:
        conn.execute(
            "INSERT INTO evento (aviso_id, tipo, termino_busqueda, sesion_hash, creado_en) "
            "VALUES (NULL, 'busqueda_sin_resultado', ?, ?, ?)",
            (q, secrets.token_hex(4), db.now()),
        )
        conn.commit()
    conn.close()
    resultados = [{
        "id": a["id"], "titulo": a["titulo"], "negocio": a["negocio_nombre"],
        "comuna": a["comuna"], "categoria": a["categoria_nombre"], "icono": a["icono"],
        "destacado": a["plan_nombre"] != "Gratis",
    } for a in avisos]
    render_json(handler, {"resultados": resultados})


def api_evento(handler, body):
    data = json.loads(body or "{}")
    tipo = data.get("tipo")
    aviso_id = data.get("aviso_id")
    termino = data.get("termino_busqueda")
    if tipo not in ("click_whatsapp", "click_resultado_busqueda"):
        return render_json(handler, {"ok": False}, status=400)
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO evento (aviso_id, tipo, termino_busqueda, sesion_hash, creado_en) VALUES (?,?,?,?,?)",
        (aviso_id, tipo, termino, secrets.token_hex(4), db.now()),
    )
    if tipo == "click_whatsapp" and aviso_id:
        conn.execute("UPDATE aviso SET contactos_total = contactos_total + 1 WHERE id = ?", (aviso_id,))
    conn.commit()
    conn.close()
    render_json(handler, {"ok": True})


# ----------------------------------------------------------------- admin

def admin_login_form(handler, error=False):
    msg = '<p class="form-error">Usuario o contraseña incorrectos.</p>' if error else ""
    body = f"""
<div class="panel panel-narrow">
  <h1>Ingreso administrador</h1>
  {msg}
  <form method="post" action="/admin/login" class="form">
    <label>Usuario <input name="usuario" required autofocus></label>
    <label>Contraseña <input name="password" type="password" required></label>
    <button class="btn btn-primary btn-lg" type="submit">Ingresar</button>
  </form>
  <p class="hint">Demo: usuario <code>admin</code> / contraseña <code>talca2026</code></p>
</div>
"""
    render(handler, t.layout("Ingreso admin", body))


def admin_login_submit(handler, form):
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM admin_usuario WHERE usuario = ?", (form.get("usuario", ""),)
    ).fetchone()
    conn.close()
    if not row or not db.verify_password(form.get("password", ""), row["password"]):
        return admin_login_form(handler, error=True)
    token = secrets.token_urlsafe(24)
    SESSIONS.add(token)
    redirect(handler, "/admin", set_cookie=token)


def admin_logout(handler):
    cookie = SimpleCookie(handler.headers.get("Cookie", ""))
    if "talca_admin" in cookie:
        SESSIONS.discard(cookie["talca_admin"].value)
    redirect(handler, "/admin/login", clear_cookie=True)


def admin_dashboard(handler, query):
    dias = int(qs(query).get("dias", "30"))
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=dias)).isoformat()
    conn = db.get_conn()

    avisos_activos = conn.execute("SELECT COUNT(*) c FROM aviso WHERE estado='activo'").fetchone()["c"]
    pendientes = conn.execute("SELECT COUNT(*) c FROM aviso WHERE estado='pendiente'").fetchone()["c"]
    vistas = conn.execute(
        "SELECT COUNT(*) c FROM evento WHERE tipo='vista' AND creado_en >= ?", (cutoff,)).fetchone()["c"]
    contactos = conn.execute(
        "SELECT COUNT(*) c FROM evento WHERE tipo='click_whatsapp' AND creado_en >= ?", (cutoff,)).fetchone()["c"]
    tasa = round(100 * contactos / vistas, 1) if vistas else 0.0
    anunciantes_pagando = conn.execute(
        "SELECT COUNT(*) c FROM negocio JOIN plan ON plan.id = negocio.plan_id "
        "WHERE plan.precio_clp > 0 AND (negocio.plan_vencimiento IS NULL OR negocio.plan_vencimiento >= date('now'))"
    ).fetchone()["c"]
    mrr = conn.execute(
        "SELECT COALESCE(SUM(plan.precio_clp),0) s FROM negocio JOIN plan ON plan.id = negocio.plan_id "
        "WHERE plan.precio_clp > 0 AND (negocio.plan_vencimiento IS NULL OR negocio.plan_vencimiento >= date('now'))"
    ).fetchone()["s"]

    top_vistos = conn.execute(
        "SELECT aviso.id, aviso.titulo, negocio.nombre AS negocio_nombre, COUNT(*) n "
        "FROM evento JOIN aviso ON aviso.id = evento.aviso_id JOIN negocio ON negocio.id = aviso.negocio_id "
        "WHERE evento.tipo='vista' AND evento.creado_en >= ? "
        "GROUP BY aviso.id ORDER BY n DESC LIMIT 10", (cutoff,)
    ).fetchall()
    top_contactados = conn.execute(
        "SELECT aviso.id, aviso.titulo, negocio.nombre AS negocio_nombre, COUNT(*) n "
        "FROM evento JOIN aviso ON aviso.id = evento.aviso_id JOIN negocio ON negocio.id = aviso.negocio_id "
        "WHERE evento.tipo='click_whatsapp' AND evento.creado_en >= ? "
        "GROUP BY aviso.id ORDER BY n DESC LIMIT 10", (cutoff,)
    ).fetchall()
    conn.close()

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

    body = f"""
<div class="listado-head">
  <h1>Dashboard</h1>
  <form method="get" class="filters">
    <select name="dias" onchange="this.form.submit()">
      {periodo_opt(7, "Últimos 7 días")}{periodo_opt(30, "Últimos 30 días")}{periodo_opt(90, "Últimos 90 días")}
    </select>
  </form>
</div>
<div class="kpi-grid">
  <div class="kpi"><div class="n">{avisos_activos}</div><div class="l">avisos activos</div></div>
  <div class="kpi"><div class="n">{pendientes}</div><div class="l">pendientes de moderación</div></div>
  <div class="kpi"><div class="n">{vistas}</div><div class="l">vistas en el período</div></div>
  <div class="kpi"><div class="n">{contactos}</div><div class="l">contactos WhatsApp en el período</div></div>
  <div class="kpi"><div class="n">{tasa}%</div><div class="l">tasa de conversión vista → contacto</div></div>
  <div class="kpi"><div class="n">{anunciantes_pagando}</div><div class="l">anunciantes en plan pagado</div></div>
  <div class="kpi"><div class="n">${mrr_fmt} CLP</div><div class="l">ingreso mensual recurrente (MRR)</div></div>
</div>
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
    render(handler, t.layout("Dashboard", body, active="admin", admin=True))


def admin_moderacion(handler):
    conn = db.get_conn()
    pendientes = conn.execute(
        AVISO_SELECT + " WHERE aviso.estado='pendiente' ORDER BY aviso.creado_en ASC"
    ).fetchall()
    conn.close()

    if not pendientes:
        rows = '<p class="empty-state">No hay avisos pendientes de moderación. 🎉</p>'
    else:
        rows = "".join(f"""
<div class="mod-row">
  <div class="mod-info">
    <div class="mono">{a['icono']} {t.esc(a['categoria_nombre'])} · {t.esc(a['comuna'])}</div>
    <h3>{t.esc(a['titulo'])}</h3>
    <p>{t.esc(a['negocio_nombre'])} · {t.esc(a['whatsapp'])}</p>
    <p class="mod-desc">{t.esc(a['descripcion'])}</p>
  </div>
  <div class="mod-actions">
    <form method="post" action="/admin/moderacion/{a['id']}/aprobar"><button class="btn btn-ok">Aprobar</button></form>
    <form method="post" action="/admin/moderacion/{a['id']}/rechazar"><button class="btn btn-bad">Rechazar</button></form>
  </div>
</div>""" for a in pendientes)

    flash = get_flash(handler)
    body = f"<h1>Moderación</h1><p class='lede'>Avisos nuevos esperando revisión.</p>{rows}"
    render(handler, t.layout("Moderación", body, active="admin", admin=True, flash=flash),
           clear_flash=bool(flash))


def admin_moderar(handler, aviso_id, accion):
    nuevo_estado = "activo" if accion == "aprobar" else "rechazado"
    conn = db.get_conn()
    if nuevo_estado == "activo":
        conn.execute("UPDATE aviso SET estado=?, publicado_en=? WHERE id=?", (nuevo_estado, db.now(), aviso_id))
    else:
        conn.execute("UPDATE aviso SET estado=? WHERE id=?", (nuevo_estado, aviso_id))
    conn.commit()
    conn.close()
    mensaje = "Aviso aprobado y publicado." if nuevo_estado == "activo" else "Aviso rechazado."
    redirect(handler, "/admin/moderacion", flash=mensaje)


def admin_avisos_lista(handler, query):
    params = qs(query)
    estado = params.get("estado", "")
    conn = db.get_conn()
    sql = AVISO_SELECT + " WHERE 1=1"
    args = []
    if estado:
        sql += " AND aviso.estado = ?"
        args.append(estado)
    sql += " ORDER BY aviso.creado_en DESC"
    avisos = conn.execute(sql, args).fetchall()
    conn.close()

    def opt(v, label):
        sel = " selected" if v == estado else ""
        return f'<option value="{v}"{sel}>{label}</option>'

    filas = "".join(f"""
<tr>
  <td><a href="/admin/avisos/{a['id']}">{t.esc(a['titulo'])}</a></td>
  <td>{t.esc(a['negocio_nombre'])}</td>
  <td class="mono">{t.esc(a['categoria_nombre'])}</td>
  <td>{t.estado_badge(a['estado'])}</td>
  <td class="mono">{a['vistas_total']}</td>
  <td class="mono">{a['contactos_total']}</td>
  <td>
    <a class="btn btn-ghost btn-sm" href="/admin/avisos/{a['id']}">Editar</a>
    <form method="post" action="/admin/avisos/{a['id']}/eliminar" style="display:inline"
      onsubmit="return confirm('¿Eliminar este aviso? No se puede deshacer.')">
      <button class="btn btn-bad btn-sm">Eliminar</button>
    </form>
  </td>
</tr>""" for a in avisos)

    body = f"""
<div class="listado-head">
  <h1>Avisos</h1>
  <form method="get" class="filters">
    <select name="estado" onchange="this.form.submit()">
      {opt('', 'Todos los estados')}{opt('activo', 'Activo')}{opt('pendiente', 'Pendiente')}
      {opt('pausado', 'Pausado')}{opt('rechazado', 'Rechazado')}
    </select>
  </form>
</div>
<div class="tbl-wrap"><table>
  <tr><th>Título</th><th>Negocio</th><th>Categoría</th><th>Estado</th><th>Vistas</th><th>Contactos</th><th>Acciones</th></tr>
  {filas or "<tr><td colspan='7' class='empty-state'>Sin avisos.</td></tr>"}
</table></div>
"""
    flash = get_flash(handler)
    render(handler, t.layout("Avisos", body, active="admin", admin=True, flash=flash), clear_flash=bool(flash))


def admin_aviso_editar_form(handler, aviso_id):
    conn = db.get_conn()
    aviso = conn.execute(AVISO_SELECT + " WHERE aviso.id=?", (aviso_id,)).fetchone()
    categorias = conn.execute("SELECT * FROM categoria ORDER BY nombre").fetchall()
    conn.close()
    if not aviso:
        return not_found(handler)

    cat_options = "".join(
        f'<option value="{c["id"]}"{" selected" if c["id"] == aviso["categoria_id"] else ""}>'
        f'{c["icono"]} {t.esc(c["nombre"])}</option>' for c in categorias)
    estado_options = "".join(
        f'<option value="{e}"{" selected" if e == aviso["estado"] else ""}>{e}</option>'
        for e in ("pendiente", "activo", "pausado", "rechazado"))

    body = f"""
<div class="panel">
  <h1>Editar aviso</h1>
  <p class="lede">{t.esc(aviso['negocio_nombre'])} · {t.esc(aviso['whatsapp'])}</p>
  <form method="post" action="/admin/avisos/{aviso_id}" class="form">
    <label>Título <input name="titulo" required value="{t.esc(aviso['titulo'])}"></label>
    <label>Descripción <textarea name="descripcion" rows="4" required>{t.esc(aviso['descripcion'])}</textarea></label>
    <label>Categoría <select name="categoria_id">{cat_options}</select></label>
    <label>Comuna <input name="comuna" value="{t.esc(aviso['comuna'])}"></label>
    <label>Horario <input name="horario" value="{t.esc(aviso['horario'] or '')}"></label>
    <label>Estado <select name="estado">{estado_options}</select></label>
    <button class="btn btn-primary btn-lg" type="submit">Guardar cambios</button>
  </form>
</div>
"""
    render(handler, t.layout("Editar aviso", body, active="admin", admin=True))


def admin_aviso_editar_submit(handler, aviso_id, form):
    conn = db.get_conn()
    actual = conn.execute("SELECT estado, publicado_en FROM aviso WHERE id=?", (aviso_id,)).fetchone()
    if not actual:
        conn.close()
        return not_found(handler)
    nuevo_estado = form.get("estado", actual["estado"])
    publicado_en = actual["publicado_en"]
    if nuevo_estado == "activo" and not publicado_en:
        publicado_en = db.now()
    conn.execute(
        "UPDATE aviso SET titulo=?, descripcion=?, categoria_id=?, comuna=?, horario=?, estado=?, publicado_en=? "
        "WHERE id=?",
        (form.get("titulo", ""), form.get("descripcion", ""), form.get("categoria_id"),
         form.get("comuna", ""), form.get("horario", ""), nuevo_estado, publicado_en, aviso_id),
    )
    conn.commit()
    conn.close()
    _og_cache_evict(aviso_id)
    redirect(handler, "/admin/avisos", flash="Cambios guardados.")


def admin_aviso_eliminar(handler, aviso_id):
    conn = db.get_conn()
    conn.execute("DELETE FROM evento WHERE aviso_id=?", (aviso_id,))
    conn.execute("DELETE FROM aviso WHERE id=?", (aviso_id,))
    conn.commit()
    conn.close()
    _og_cache_evict(aviso_id)
    redirect(handler, "/admin/avisos", flash="Aviso eliminado.")


def admin_anunciantes(handler):
    conn = db.get_conn()
    negocios = conn.execute(
        "SELECT negocio.*, plan.nombre AS plan_nombre, plan.precio_clp, "
        "(SELECT COUNT(*) FROM aviso WHERE aviso.negocio_id = negocio.id) AS n_avisos "
        "FROM negocio JOIN plan ON plan.id = negocio.plan_id ORDER BY negocio.nombre"
    ).fetchall()
    planes = conn.execute("SELECT * FROM plan ORDER BY prioridad").fetchall()
    conn.close()

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
<h1>Anunciantes y planes</h1>
<p class="lede">Activa manualmente un plan pagado (transferencia confirmada) o marca un negocio como verificado.</p>
<div class="tbl-wrap"><table>
  <tr><th>Negocio</th><th>Plan actual</th><th>Vence</th><th>Avisos</th><th>Verificado</th><th>Acciones</th></tr>
  {filas}
</table></div>
"""
    flash = get_flash(handler)
    render(handler, t.layout("Anunciantes y planes", body, active="admin", admin=True, flash=flash),
           clear_flash=bool(flash))


def admin_anunciante_plan(handler, negocio_id, form):
    plan_id = form.get("plan_id")
    conn = db.get_conn()
    plan = conn.execute("SELECT * FROM plan WHERE id=?", (plan_id,)).fetchone()
    vencimiento = None
    if plan and plan["precio_clp"] > 0:
        vencimiento = (datetime.date.today() + datetime.timedelta(days=plan["duracion_dias"])).isoformat()
    conn.execute("UPDATE negocio SET plan_id=?, plan_vencimiento=? WHERE id=?", (plan_id, vencimiento, negocio_id))
    conn.commit()
    nombre_plan = plan["nombre"] if plan else "?"
    conn.close()
    redirect(handler, "/admin/anunciantes", flash=f"Plan actualizado a {nombre_plan}.")


def admin_anunciante_verificar(handler, negocio_id):
    conn = db.get_conn()
    actual = conn.execute("SELECT verificado FROM negocio WHERE id=?", (negocio_id,)).fetchone()
    nuevo = 0 if actual["verificado"] else 1
    conn.execute("UPDATE negocio SET verificado=? WHERE id=?", (nuevo, negocio_id))
    conn.commit()
    conn.close()
    mensaje = "Negocio verificado." if nuevo else "Verificación removida."
    redirect(handler, "/admin/anunciantes", flash=mensaje)


def admin_analitica(handler):
    conn = db.get_conn()
    avisos = conn.execute(
        AVISO_SELECT + " WHERE aviso.estado != 'rechazado' ORDER BY aviso.vistas_total DESC"
    ).fetchall()
    mas_buscados = conn.execute(
        "SELECT termino_busqueda, COUNT(*) n FROM evento WHERE tipo='click_resultado_busqueda' "
        "AND termino_busqueda IS NOT NULL GROUP BY termino_busqueda ORDER BY n DESC LIMIT 15"
    ).fetchall()
    sin_resultado = conn.execute(
        "SELECT termino_busqueda, COUNT(*) n FROM evento WHERE tipo='busqueda_sin_resultado' "
        "GROUP BY termino_busqueda ORDER BY n DESC LIMIT 15"
    ).fetchall()
    conn.close()

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
  <div class="tbl-wrap"><table>
    <tr><th>Aviso</th><th>Vistas</th><th>Contactos</th><th>Conversión</th><th>Plan</th></tr>
    {filas}
  </table></div>
</section>
"""
    render(handler, t.layout("Analítica", body, active="admin", admin=True))


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
    conn = db.get_conn()
    aviso = conn.execute(AVISO_SELECT + " WHERE aviso.id = ?", (aviso_id,)).fetchone()
    conn.close()
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
    conn = db.get_conn()
    ids = [r["id"] for r in conn.execute("SELECT id FROM aviso WHERE estado='activo'").fetchall()]
    conn.close()
    urls = [f"{origin}/", f"{origin}/avisos", f"{origin}/publicar"] + [f"{origin}/avisos/{i}" for i in ids]
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

    def do_GET(self):
        parts = urlsplit(self.path)
        path, query = parts.path, parts.query
        segs = [s for s in path.split("/") if s != ""]

        try:
            if path == "/":
                return home(self)
            if path == "/avisos":
                return listado(self, query)
            if len(segs) == 2 and segs[0] == "avisos" and segs[1].isdigit():
                return detalle(self, int(segs[1]))
            if path == "/publicar":
                return publicar_form(self, ok=qs(query).get("ok") == "1")
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

            if path == "/admin/login":
                return admin_login_form(self)
            if path == "/admin/logout":
                return admin_logout(self)
            if path == "/admin":
                return admin_dashboard(self, query) if require_admin(self) else None
            if path == "/admin/moderacion":
                return admin_moderacion(self) if require_admin(self) else None
            if path == "/admin/avisos":
                return admin_avisos_lista(self, query) if require_admin(self) else None
            if len(segs) == 3 and segs[0] == "admin" and segs[1] == "avisos" and segs[2].isdigit():
                return admin_aviso_editar_form(self, int(segs[2])) if require_admin(self) else None
            if path == "/admin/anunciantes":
                return admin_anunciantes(self) if require_admin(self) else None
            if path == "/admin/analitica":
                return admin_analitica(self) if require_admin(self) else None

            return not_found(self)
        except BrokenPipeError:
            pass
        except Exception as exc:
            return server_error(self, exc)

    def do_POST(self):
        parts = urlsplit(self.path)
        path = parts.path
        segs = [s for s in path.split("/") if s != ""]

        try:
            if path == "/publicar":
                return publicar_submit(self, self._form())
            if path == "/api/buscar":
                return api_buscar(self, self._body())
            if path == "/api/evento":
                return api_evento(self, self._body())
            if path == "/admin/login":
                return admin_login_submit(self, self._form())

            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "moderacion" and segs[3] in ("aprobar", "rechazar"):
                return admin_moderar(self, int(segs[2]), segs[3]) if require_admin(self) else None
            if len(segs) == 3 and segs[0] == "admin" and segs[1] == "avisos" and segs[2].isdigit():
                return admin_aviso_editar_submit(self, int(segs[2]), self._form()) if require_admin(self) else None
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "avisos" and segs[3] == "eliminar":
                return admin_aviso_eliminar(self, int(segs[2])) if require_admin(self) else None
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "anunciantes" and segs[3] == "plan":
                return admin_anunciante_plan(self, int(segs[2]), self._form()) if require_admin(self) else None
            if len(segs) == 4 and segs[0] == "admin" and segs[1] == "anunciantes" and segs[3] == "verificar":
                return admin_anunciante_verificar(self, int(segs[2])) if require_admin(self) else None

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
                "application/javascript" if full.endswith(".js") else "application/octet-stream"
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
