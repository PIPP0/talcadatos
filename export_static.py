"""
Genera una version estatica del sitio publico en docs/, para publicarla con
GitHub Pages. GitHub Pages solo sirve archivos estaticos -- no hay Python
corriendo -- asi que aca quedan deshabilitados: el buscador "IA" (llama a
/api/buscar), el registro de eventos, el formulario de publicar, y todo el
panel de administracion. La navegacion, las fichas de cada aviso y los
botones de WhatsApp (son links wa.me directos, no necesitan servidor) SI
funcionan igual que en la version con servidor.

Uso:
    python3 export_static.py
"""
import os
import io
import re
import shutil
import tempfile

import db
import server
import ogimage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
PAGES_HOST = "pipp0.github.io"
PAGES_BASE = f"https://{PAGES_HOST}/talcadatos"

NOTICE = (
    '<div class="flash static-notice">'
    "🔧 Vista de demostración estática (GitHub Pages) — el buscador, los filtros, "
    'el formulario de publicar y el panel de administración no están activos aquí '
    "porque no hay servidor corriendo. La navegación y los botones de WhatsApp sí "
    'funcionan. <a href="https://github.com/PIPP0/talcadatos">Ver el código y cómo '
    "correrlo con servidor completo →</a></div>"
)


class FakeHandler:
    """Imita lo minimo que las funciones de rutas de server.py necesitan de un
    http.server.BaseHTTPRequestHandler, para poder llamarlas directo sin
    levantar un servidor real ni hacer peticiones de red."""

    def __init__(self):
        self.headers = {"Host": PAGES_HOST}
        self.wfile = io.BytesIO()
        self.status = 200

    def send_response(self, code):
        self.status = code

    def send_header(self, k, v):
        pass

    def end_headers(self):
        pass

    def html(self):
        return self.wfile.getvalue().decode("utf-8")


def _postprocess(html):
    """Reescribe la salida del sitio dinamico para que sirva como estatico:
    agrega el prefijo /talcadatos (Pages sirve el repo bajo un subpath),
    convierte rutas de aviso a carpetas con index.html, e inserta el aviso."""
    prefix = "/talcadatos"
    html = html.replace("http://" + PAGES_HOST + "/", PAGES_BASE + "/")
    html = re.sub(r'(href|src|action)="/(?!talcadatos)', rf'\1="{prefix}/', html)
    html = re.sub(r'href="' + re.escape(prefix) + r'/avisos/(\d+)"',
                   rf'href="{prefix}/avisos/\1/"', html)
    html = html.replace('<main class="wrap">', '<main class="wrap">\n' + NOTICE, 1)
    html = re.sub(
        r'\s*<span>Panel de administración: <a href="[^"]*">/admin</a></span>', "", html)
    return html


def _write(path, content_bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content_bytes)


def main():
    if os.path.isdir(DOCS_DIR):
        shutil.rmtree(DOCS_DIR)
    os.makedirs(DOCS_DIR)

    # Trabajar sobre una copia de la base de datos: las rutas de detalle
    # registran una "vista" cada vez que se llaman, y no queremos que
    # generar el export infle las metricas de la demo real.
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    shutil.copy(db.DB_PATH, tmp_db)
    db.DB_PATH = tmp_db

    conn = db.get_conn()
    aviso_ids = [r["id"] for r in conn.execute("SELECT id FROM aviso WHERE estado='activo'").fetchall()]
    avisos_full = {r["id"]: r for r in conn.execute(server.AVISO_SELECT).fetchall()}
    conn.close()

    # Home
    h = FakeHandler()
    server.home(h)
    _write(os.path.join(DOCS_DIR, "index.html"), _postprocess(h.html()).encode("utf-8"))

    # Listado
    h = FakeHandler()
    server.listado(h, "")
    _write(os.path.join(DOCS_DIR, "avisos", "index.html"), _postprocess(h.html()).encode("utf-8"))

    # Publicar (formulario visible, pero inerte sin servidor)
    h = FakeHandler()
    server.publicar_form(h)
    _write(os.path.join(DOCS_DIR, "publicar", "index.html"), _postprocess(h.html()).encode("utf-8"))

    # Detalle de cada aviso activo
    for aviso_id in aviso_ids:
        h = FakeHandler()
        server.detalle(h, aviso_id)
        _write(os.path.join(DOCS_DIR, "avisos", str(aviso_id), "index.html"),
               _postprocess(h.html()).encode("utf-8"))

    # Imagenes Open Graph (generadas directo con ogimage, sin pasar por HTTP)
    for aviso_id in aviso_ids:
        data = ogimage.generar(avisos_full[aviso_id])
        _write(os.path.join(DOCS_DIR, "og", f"{aviso_id}.png"), data)
    _write(os.path.join(DOCS_DIR, "og", "default.png"), ogimage.generar_default())

    # Estaticos: CSS igual, JS con el buscador reemplazado por un aviso inerte
    shutil.copytree(os.path.join(BASE_DIR, "static"), os.path.join(DOCS_DIR, "static"))
    static_js = os.path.join(DOCS_DIR, "static", "app.js")
    with open(static_js, "r", encoding="utf-8") as f:
        js = f.read()
    js = js.replace(
        "(function initSearch() {",
        "(function initSearch() {\n"
        "  // Deshabilitado en la version estatica de GitHub Pages: no hay /api/buscar.\n"
        "  var __disabled = true;\n"
        "  if (__disabled) {\n"
        "    var form0 = document.getElementById('search-form');\n"
        "    if (form0) form0.addEventListener('submit', function (e) {\n"
        "      e.preventDefault();\n"
        "      alert('El buscador necesita el servidor corriendo. Revisa el README del repo para probarlo completo.');\n"
        "    });\n"
        "    return;\n"
        "  }\n",
    )
    with open(static_js, "w", encoding="utf-8") as f:
        f.write(js)

    # robots.txt / sitemap.xml estaticos
    urls = [f"{PAGES_BASE}/", f"{PAGES_BASE}/avisos/"] + [f"{PAGES_BASE}/avisos/{i}/" for i in aviso_ids]
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    _write(os.path.join(DOCS_DIR, "sitemap.xml"), sitemap.encode("utf-8"))
    _write(os.path.join(DOCS_DIR, "robots.txt"),
           f"User-agent: *\nAllow: /\nSitemap: {PAGES_BASE}/sitemap.xml\n".encode("utf-8"))
    _write(os.path.join(DOCS_DIR, ".nojekyll"), b"")

    os.remove(tmp_db)
    print(f"Listo: {DOCS_DIR} generado con {len(aviso_ids)} avisos.")


if __name__ == "__main__":
    main()
