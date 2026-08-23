"""
Genera una version estatica del sitio publico en docs/, para publicarla con
GitHub Pages. GitHub Pages solo sirve archivos estaticos -- no hay Python
corriendo -- pero el buscador y los filtros SI funcionan: se reimplemento el
mismo algoritmo de search.py en JS puro (pages_assets/search-client.js) que
corre en el navegador contra avisos.json/sinonimos.json. Lo que sigue sin
funcionar es lo que necesita escritura compartida real (que todos los
visitantes vean el mismo estado): el formulario de publicar y el panel de
administracion. La navegacion, las fichas de cada aviso y los botones de
WhatsApp (son links wa.me directos) funcionan igual que en la version con
servidor.

Uso:
    python3 export_static.py
"""
import os
import io
import re
import json
import shutil

import db
import server
import ogimage

# Generar el export no debe inflar las metricas reales de la demo en vivo:
# server.detalle() registra una "vista" y suma vistas_total cada vez que se
# llama, y aca lo llamamos una vez por aviso solo para capturar el HTML.
db.registrar_evento = lambda *a, **k: None
db.incrementar_vistas = lambda *a, **k: None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
PAGES_HOST = "pipp0.github.io"
PAGES_PREFIX = "/talcadatos"
PAGES_BASE = f"https://{PAGES_HOST}{PAGES_PREFIX}"

NOTICE = (
    '<div class="flash static-notice">'
    "🔧 Vista de demostración estática (GitHub Pages) — el buscador, los filtros y los "
    "favoritos funcionan (corren en tu navegador). Publicar un aviso, reportar y el panel "
    "de administración quedan inactivos aquí porque necesitan un servidor real. "
    '<a href="https://github.com/PIPP0/talcadatos">Ver el código y cómo correrlo '
    "completo →</a></div>"
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
    prefix = PAGES_PREFIX
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

    avisos_full = {a["id"]: a for a in db.get_avisos(estado="activo")}
    aviso_ids = list(avisos_full.keys())

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

    # Ayuda (FAQ, no necesita servidor) y Favoritos (se llena con JS/localStorage)
    h = FakeHandler()
    server.ayuda(h)
    _write(os.path.join(DOCS_DIR, "ayuda", "index.html"), _postprocess(h.html()).encode("utf-8"))

    h = FakeHandler()
    server.favoritos(h)
    _write(os.path.join(DOCS_DIR, "favoritos", "index.html"), _postprocess(h.html()).encode("utf-8"))

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

    # Estaticos: CSS igual; app.js se reemplaza por completo con la version
    # que trae el buscador/filtros funcionando en el navegador (sin backend).
    shutil.copytree(os.path.join(BASE_DIR, "static"), os.path.join(DOCS_DIR, "static"))
    search_client = os.path.join(BASE_DIR, "pages_assets", "search-client.js")
    with open(search_client, "r", encoding="utf-8") as f:
        js = f.read().replace("__PAGES_PREFIX__", PAGES_PREFIX)
    with open(os.path.join(DOCS_DIR, "static", "app.js"), "w", encoding="utf-8") as f:
        f.write(js)

    # Datos que consume ese JS: avisos activos + diccionario de sinonimos por rubro.
    avisos_json = [{
        "id": a["id"], "titulo": a["titulo"], "descripcion": a["descripcion"],
        "categoria_nombre": a["categoria_nombre"], "categoria_slug": a["categoria_slug"],
        "icono": a["icono"], "comuna": a["comuna"], "color": a["color"],
        "whatsapp": a["whatsapp"], "negocio_nombre": a["negocio_nombre"],
        "verificado": bool(a["verificado"]), "plan_nombre": a["plan_nombre"],
        "plan_prioridad": a["plan_prioridad"], "publicado_en": a["publicado_en"],
        "contactos_total": a["contactos_total"], "vistas_total": a["vistas_total"],
    } for a in avisos_full.values()]
    sinonimos_json = db.get_sinonimos_por_categoria()
    _write(os.path.join(DOCS_DIR, "static", "avisos.json"),
           json.dumps(avisos_json, ensure_ascii=False).encode("utf-8"))
    _write(os.path.join(DOCS_DIR, "static", "sinonimos.json"),
           json.dumps(sinonimos_json, ensure_ascii=False).encode("utf-8"))

    # robots.txt / sitemap.xml estaticos
    urls = ([f"{PAGES_BASE}/", f"{PAGES_BASE}/avisos/", f"{PAGES_BASE}/ayuda/"]
            + [f"{PAGES_BASE}/avisos/{i}/" for i in aviso_ids])
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    _write(os.path.join(DOCS_DIR, "sitemap.xml"), sitemap.encode("utf-8"))
    _write(os.path.join(DOCS_DIR, "robots.txt"),
           f"User-agent: *\nAllow: /\nSitemap: {PAGES_BASE}/sitemap.xml\n".encode("utf-8"))
    _write(os.path.join(DOCS_DIR, ".nojekyll"), b"")

    print(f"Listo: {DOCS_DIR} generado con {len(aviso_ids)} avisos.")


if __name__ == "__main__":
    main()
