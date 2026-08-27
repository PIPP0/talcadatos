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
import sys

import db
import server
import ogimage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
PAGES_HOST = "pipp0.github.io"
PAGES_PREFIX = "/talcadatos"
PAGES_BASE = f"https://{PAGES_HOST}{PAGES_PREFIX}"

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
    # El QR se forma con la URL dinámica. En Pages debe apuntar a la carpeta
    # estática real, incluido el prefijo del repositorio.
    html = re.sub(r'data=http%3A//pipp0\.github\.io/avisos/(\d+)',
                  rf'data=https%3A//{PAGES_HOST}{PAGES_PREFIX}/avisos/\1/', html)
    html = re.sub(
        r'\s*<span>Panel de administración: <a href="[^"]*">/admin</a></span>', "", html)
    return "\n".join(line.rstrip() for line in html.splitlines()) + "\n"


def _write(path, content_bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content_bytes)


def _usar_snapshot_estatico():
    """Permite regenerar Pages sin red usando el último snapshot publicado.

    Es útil para diseño y QA local. El export normal sigue leyendo Firestore,
    que es el origen de verdad cuando hay conectividad.
    """
    snapshot_dir = os.path.join(BASE_DIR, "pages_assets", "static_snapshot")
    data_path = os.path.join(snapshot_dir, "avisos.json")
    sin_path = os.path.join(snapshot_dir, "sinonimos.json")
    if not os.path.isfile(data_path) or not os.path.isfile(sin_path):
        raise RuntimeError("No existe un snapshot estático previo para exportar sin red.")
    with open(data_path, "r", encoding="utf-8") as f:
        avisos = json.load(f)
    with open(sin_path, "r", encoding="utf-8") as f:
        sinonimos = json.load(f)

    for aviso in avisos:
        aviso["estado"] = "activo"
        aviso.setdefault("horario", "")

    categorias = {}
    for aviso in avisos:
        slug = aviso["categoria_slug"]
        categorias.setdefault(slug, {
            "id": slug, "slug": slug, "nombre": aviso["categoria_nombre"], "icono": aviso["icono"],
        })

    def get_categorias():
        return sorted((dict(c) for c in categorias.values()), key=lambda c: c["nombre"])

    def get_avisos(estado=None, estado_ne=None, categoria_slug=None, comuna=None,
                   negocio_id=None, excluir_id=None, orden="creado", limit=None):
        filas = [dict(a) for a in avisos]
        if estado is not None:
            filas = [a for a in filas if a["estado"] == estado]
        if estado_ne is not None:
            filas = [a for a in filas if a["estado"] != estado_ne]
        if categoria_slug:
            filas = [a for a in filas if a["categoria_slug"] == categoria_slug]
        if comuna:
            filas = [a for a in filas if a["comuna"] == comuna]
        if excluir_id is not None:
            filas = [a for a in filas if str(a["id"]) != str(excluir_id)]
        if negocio_id is not None:
            filas = []

        if orden in ("destacados", "relevancia"):
            filas.sort(key=lambda a: (a.get("plan_prioridad", 0), a.get("publicado_en") or ""), reverse=True)
        elif orden == "recientes":
            filas.sort(key=lambda a: a.get("publicado_en") or "", reverse=True)
        elif orden == "populares":
            filas.sort(key=lambda a: a.get("contactos_total", 0), reverse=True)
        elif orden == "vistas":
            filas.sort(key=lambda a: a.get("vistas_total", 0), reverse=True)
        return filas[:limit] if limit else filas

    def get_aviso(aviso_id):
        return next((dict(a) for a in avisos if str(a["id"]) == str(aviso_id)), None)

    db.get_categorias = get_categorias
    db.get_avisos = get_avisos
    db.get_aviso = get_aviso
    db.get_comunas_activas = lambda: sorted({a["comuna"] for a in avisos})
    db.get_sinonimos_por_categoria = lambda: sinonimos
    db.get_contenido_sitio = lambda: dict(db.CONTENIDO_SITIO_POR_DEFECTO)
    db.get_terminos_mas_buscados = lambda limit=15: [
        {"termino_busqueda": termino, "n": n}
        for termino, n in [("gásfiter", 42), ("veterinaria", 31), ("notebook", 24), ("pan amasado", 18)]
    ][:limit]


def exportar(offline=False):
    """Regenera docs/ desde Firestore para la versión estática del sitio.

    También se invoca después de los cambios públicos hechos en el admin, de
    forma que la versión estática y la dinámica siempre usen el mismo origen.
    """
    if offline:
        _usar_snapshot_estatico()
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

    # Explorar y "Necesito esto". El segundo explica su limitación en la versión estática.
    h = FakeHandler()
    server.explorar(h)
    _write(os.path.join(DOCS_DIR, "explorar", "index.html"), _postprocess(h.html()).encode("utf-8"))

    h = FakeHandler()
    server.necesito_form(h)
    _write(os.path.join(DOCS_DIR, "necesito", "index.html"), _postprocess(h.html()).encode("utf-8"))

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
        server.detalle(h, aviso_id, contabilizar=False)
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
    shutil.copyfile(os.path.join(BASE_DIR, "static", "sw.js"), os.path.join(DOCS_DIR, "sw.js"))
    search_client = os.path.join(BASE_DIR, "pages_assets", "search-client.js")
    with open(search_client, "r", encoding="utf-8") as f:
        js = f.read().replace("__PAGES_PREFIX__", PAGES_PREFIX)
    with open(os.path.join(DOCS_DIR, "static", "app.js"), "w", encoding="utf-8") as f:
        f.write(js)
    manifest_path = os.path.join(DOCS_DIR, "static", "manifest.webmanifest")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["start_url"] = PAGES_PREFIX + "/"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

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
    urls = ([f"{PAGES_BASE}/", f"{PAGES_BASE}/explorar/", f"{PAGES_BASE}/avisos/", f"{PAGES_BASE}/necesito/", f"{PAGES_BASE}/ayuda/"]
            + [f"{PAGES_BASE}/avisos/{i}/" for i in aviso_ids])
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
    _write(os.path.join(DOCS_DIR, "sitemap.xml"), sitemap.encode("utf-8"))
    _write(os.path.join(DOCS_DIR, "robots.txt"),
           f"User-agent: *\nAllow: /\nSitemap: {PAGES_BASE}/sitemap.xml\n".encode("utf-8"))
    _write(os.path.join(DOCS_DIR, ".nojekyll"), b"")

    print(f"Listo: {DOCS_DIR} generado con {len(aviso_ids)} avisos.")


def main():
    exportar(offline="--offline" in sys.argv[1:])


if __name__ == "__main__":
    main()
