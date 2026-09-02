"""
Capa de datos de Talcadatos -- Firestore (Firebase).

Estrategia deliberada para mantener esto simple y confiable: en vez de
traducir cada consulta SQL a un query de Firestore equivalente (Firestore
no tiene JOIN, y las consultas compuestas piden indices manuales), cada
funcion de lectura trae la coleccion completa a Python y filtra/ordena/junta
ahi. Con el tamano de datos de este sitio (decenas o cientos de documentos)
es rapido y evita por completo el problema de "falta un indice compuesto".
Si el sitio creciera mucho, ahi si conviene mover los filtros mas usados a
queries nativos de Firestore.

IDs: aviso, negocio, reporte, alerta y sinonimo usan un contador propio
(coleccion `_contadores`) para que sigan siendo numericos como "1", "2", ...
-- asi las rutas de server.py (`/avisos/<id>`, etc.) no tuvieron que
rediseñarse. categoria y plan usan su slug/nombre como id directamente.
evento, pago y auditoria usan el id automatico de Firestore porque nunca
se referencian por id en una URL.
"""
import os
import json
import time
import random
import hashlib
import secrets
import datetime

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud import storage as gcs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_KEY_PATH = os.path.join(BASE_DIR, "firebase-key.json")
_FOTOS_BUCKET = os.environ.get("FOTOS_BUCKET", "talcadatos-fotos")

_db = None
_storage_client = None

# categorias y planes casi no cambian (los edita un super_admin muy de vez en
# cuando), y _denormalizar_avisos los relee completos en cada llamada. Un
# cache corto en memoria evita esas dos lecturas completas de Firestore en
# cada carga de pagina publica, que es lo que hacia lenta la navegacion.
_CACHE_TTL = 30
_cache_colecciones = {}


CONTENIDO_SITIO_POR_DEFECTO = {
    "marca": "Talcadatos",
    "pie": "Talcadatos — directorio de pymes y emprendedores de Talca",
    "descripcion": "Encuentra pymes y emprendedores de Talca por lo que necesitas y escríbeles directo por WhatsApp. Ventanas, gásfitería, clases, tecnología y más.",
    "hero_ubicacion": "Talca, Chile",
    "hero_titulo": "Publícate ahora y haz crecer tu Pyme en Talca.",
    "hero_bajada": "Negocios, servicios, datos y oportunidades cerca de ti.",
    "hero_placeholder": "¿Qué estás buscando?",
    "hero_ayuda": "Prueba: gásfiter, veterinaria, clases particulares",
    "destacados_eyebrow": "Lo más buscado en Talca",
    "destacados_titulo": "Destacados",
    "rubros_eyebrow": "Encuentra más rápido",
    "rubros_titulo": "Explora por rubros",
    "hoy_eyebrow": "Actualidad local",
    "hoy_titulo": "Hoy en Talca",
    "tendencias_eyebrow": "Tendencias locales",
    "tendencias_titulo": "Lo que Talca está buscando",
    "tendencias_bajada": "Señales agregadas para descubrir servicios útiles y oportunidades locales.",
    "necesidad_eyebrow": "¿Qué te gustaría ver en Talca?",
    "necesidad_titulo": "Recomienda un negocio o servicio.",
    "necesidad_bajada": "Cuéntanos qué te gustaría encontrar en tu barrio — lo usamos para recomendar nuevos comercios a la comunidad y para invitar a emprendedores a sumarse.",
    "necesidad_boton": "Recomendar un negocio",
    "pymes_eyebrow": "Para pymes y emprendedores",
    "pymes_titulo": "Haz que Talca encuentre tu negocio.",
    "pymes_bajada": "Crea tu vitrina local gratis y empieza a recibir contactos reales.",
    "pymes_boton": "Publicar mi negocio",
    "necesito_titulo": "¿Qué te gustaría ver en Talca?",
    "necesito_bajada": "Cuéntanos qué negocio o servicio te gustaría encontrar en tu barrio. Con estas recomendaciones destacamos lo que Talca está pidiendo.",
    "publicar_titulo": "Publica tu negocio en Talcadatos",
    "publicar_bajada": "Es gratis. Completa el formulario y tu aviso queda listo para revisión — normalmente se aprueba el mismo día.",
    "hero_imagen_url": "/static/img/hero-talca.jpg",
    "explorar_imagen_url": "/static/img/feria-local-editorial.jpg",
    "pymes_imagen_url": "/static/img/comercio-local-editorial.jpg",
}


def _fs():
    global _db
    if _db is not None:
        return _db
    if not firebase_admin._apps:
        raw = os.environ.get("FIREBASE_CREDENTIALS_JSON")
        if raw:
            cred = credentials.Certificate(json.loads(raw))
        elif os.path.isfile(_KEY_PATH):
            cred = credentials.Certificate(_KEY_PATH)
        else:
            # En Cloud Run / GCP no hace falta ninguna de las dos: usa las
            # credenciales por defecto de la cuenta de servicio del servicio.
            cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    _db = firestore.client()
    return _db


def _storage():
    global _storage_client
    if _storage_client is not None:
        return _storage_client
    raw = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    if raw:
        from google.oauth2 import service_account
        info = json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(info)
        _storage_client = gcs.Client(credentials=creds, project=info["project_id"])
    elif os.path.isfile(_KEY_PATH):
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(_KEY_PATH)
        _storage_client = gcs.Client(credentials=creds, project=creds.project_id)
    else:
        _storage_client = gcs.Client()
    return _storage_client


def subir_imagen(datos, content_type, extension, carpeta="avisos"):
    """Sube una imagen al bucket publico y devuelve su URL. `carpeta` separa
    fotos de avisos ("avisos") de imagenes del sitio ("sitio")."""
    nombre = f"{carpeta}/{secrets.token_hex(12)}.{extension}"
    blob = _storage().bucket(_FOTOS_BUCKET).blob(nombre)
    blob.upload_from_string(datos, content_type=content_type)
    return f"https://storage.googleapis.com/{_FOTOS_BUCKET}/{nombre}"


def subir_foto_aviso(datos, content_type, extension):
    return subir_imagen(datos, content_type, extension, carpeta="avisos")


def now():
    return datetime.datetime.utcnow().isoformat()


def hash_password(password, salt=None):
    """Formato nuevo: scrypt$<salt_hex>$<hash_hex>. Más lento de fuerza bruta
    que el sha256+salt anterior, sin depender de ninguna libreria externa."""
    salt = salt or secrets.token_hex(16)
    derivado = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=2**14, r=8, p=1)
    return f"scrypt${salt}${derivado.hex()}"


def _hash_password_legacy(password, salt):
    return f"{salt}${hashlib.sha256((salt + password).encode('utf-8')).hexdigest()}"


def verify_password(password, stored):
    partes = stored.split("$")
    if len(partes) == 3 and partes[0] == "scrypt":
        _, salt, _ = partes
        return hash_password(password, salt) == stored
    if len(partes) == 2:
        salt, _ = partes
        return _hash_password_legacy(password, salt) == stored
    return False


def necesita_rehash(stored):
    """Contraseñas guardadas con el formato viejo (sha256) se re-hashean con
    scrypt la próxima vez que ese usuario inicia sesión con éxito."""
    return not stored.startswith("scrypt$")


def verificar_limite(ip, ruta, maximo=5, ventana_minutos=60):
    """Limite simple de envios por IP+ruta en una ventana de tiempo, para
    frenar flood/spam en los formularios publicos. Devuelve True si se
    permite el envio (y lo registra), False si ya se supero el limite.
    La coleccion `_rate_limits` tiene TTL configurado por fuera de este
    codigo (gcloud) para que los documentos viejos se autolimpien."""
    if not ip:
        return True
    bucket = datetime.datetime.utcnow().strftime("%Y%m%d%H")
    doc_id = f"{ruta}_{ip.replace(':', '_').replace('.', '_')}_{bucket}"
    fs = _fs()
    ref = fs.collection("_rate_limits").document(doc_id)
    transaction = fs.transaction()

    @firestore.transactional
    def _incrementar(tx):
        snap = ref.get(transaction=tx)
        actual = snap.get("conteo") if snap.exists else 0
        if actual and actual >= maximo:
            return False
        expira = datetime.datetime.utcnow() + datetime.timedelta(minutes=ventana_minutos + 10)
        tx.set(ref, {"conteo": (actual or 0) + 1, "expira_en": expira})
        return True

    return _incrementar(transaction)


def _next_id(coleccion):
    fs = _fs()
    ref = fs.collection("_contadores").document(coleccion)
    transaction = fs.transaction()

    @firestore.transactional
    def _incrementar(tx):
        snap = ref.get(transaction=tx)
        actual = snap.get("valor") if snap.exists else 0
        nuevo = actual + 1
        tx.set(ref, {"valor": nuevo})
        return nuevo

    return str(_incrementar(transaction))


def _all(coleccion):
    return {doc.id: doc.to_dict() for doc in _fs().collection(coleccion).stream()}


def _all_cacheado(coleccion):
    entrada = _cache_colecciones.get(coleccion)
    if entrada and (time.monotonic() - entrada[0]) < _CACHE_TTL:
        return entrada[1]
    datos = _all(coleccion)
    _cache_colecciones[coleccion] = (time.monotonic(), datos)
    return datos


def _con_id(d, doc_id):
    row = dict(d)
    row["id"] = doc_id
    return row


# -------------------------------------------------------- contenido del sitio

def get_config_pagos():
    doc = _fs().collection("configuracion").document("pagos").get()
    d = doc.to_dict() or {}
    return {"suscripcion_activa": bool(d.get("suscripcion_activa", False))}


def set_suscripcion_activa(activa):
    _fs().collection("configuracion").document("pagos").set({"suscripcion_activa": bool(activa)}, merge=True)


def crear_suscripcion_pendiente(token, email, plan_id="gratis"):
    _fs().collection("suscripciones_pendientes").document(token).set({
        "estado": "pendiente", "email": email, "plan_id": plan_id, "creado_en": now(),
    })


def get_suscripcion_pendiente(token):
    doc = _fs().collection("suscripciones_pendientes").document(token).get()
    return doc.to_dict() if doc.exists else None


def actualizar_suscripcion_pendiente(token, **campos):
    _fs().collection("suscripciones_pendientes").document(token).set(campos, merge=True)


def get_suscripciones():
    subs = _all("suscripciones_pendientes")
    negocios = _all("negocios")
    filas = []
    for token, s in subs.items():
        row = dict(s)
        row["token"] = token
        neg = negocios.get(s.get("negocio_id"), {})
        row["negocio_nombre"] = neg.get("nombre", "")
        filas.append(row)
    filas.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return filas


# ---------------------------------------------------- solicitudes de sitio web (/quieromiweb)

def crear_solicitud_web(token, nombre, negocio, email, whatsapp, descripcion):
    _fs().collection("solicitudes_web").document(token).set({
        "estado": "nueva", "nombre": nombre, "negocio": negocio, "email": email,
        "whatsapp": whatsapp, "descripcion": descripcion, "creado_en": now(),
    })


def get_solicitud_web(token):
    doc = _fs().collection("solicitudes_web").document(token).get()
    return doc.to_dict() if doc.exists else None


def actualizar_solicitud_web(token, **campos):
    _fs().collection("solicitudes_web").document(token).set(campos, merge=True)


def get_solicitudes_web_por_contacto(valor):
    """Busca por correo o por WhatsApp (lo que haya escrito la persona).
    Un mismo correo o WhatsApp puede tener mas de una solicitud (por ejemplo,
    dos negocios distintos) -- por eso esto devuelve una lista, no un solo
    resultado."""
    valor = (valor or "").strip().lower()
    digitos = "".join(c for c in valor if c.isdigit())
    if not valor:
        return []
    filas = []
    for token, s in _all("solicitudes_web").items():
        email_coincide = (s.get("email") or "").strip().lower() == valor
        whatsapp_coincide = bool(digitos) and digitos in "".join(
            c for c in (s.get("whatsapp") or "") if c.isdigit())
        if email_coincide or whatsapp_coincide:
            row = dict(s)
            row["token"] = token
            filas.append(row)
    filas.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return filas


def get_solicitudes_web():
    filas = []
    for token, s in _all("solicitudes_web").items():
        row = dict(s)
        row["token"] = token
        filas.append(row)
    filas.sort(key=lambda r: r.get("creado_en") or "", reverse=True)
    return filas


def get_contenido_sitio():
    """Obtiene el CMS de una sola página y aplica valores seguros por defecto."""
    doc = _fs().collection("configuracion").document("sitio").get()
    contenido = dict(CONTENIDO_SITIO_POR_DEFECTO)
    if doc.exists:
        contenido.update({k: v for k, v in (doc.to_dict() or {}).items()
                          if k in CONTENIDO_SITIO_POR_DEFECTO and isinstance(v, str) and v.strip()})
    return contenido


def actualizar_contenido_sitio(campos):
    datos = {}
    for clave, valor in campos.items():
        if clave not in CONTENIDO_SITIO_POR_DEFECTO:
            continue
        texto = str(valor or "").strip()[:600]
        if texto:
            datos[clave] = texto
    if datos:
        datos["actualizado_en"] = now()
        _fs().collection("configuracion").document("sitio").set(datos, merge=True)



# ------------------------------------------------------------- categorias

def _categoria_con_slug(c, slug):
    row = _con_id(c, slug)
    row["slug"] = slug
    return row


def get_categorias():
    cats = _all_cacheado("categorias")
    filas = [_categoria_con_slug(c, slug) for slug, c in cats.items()]
    filas.sort(key=lambda c: c["nombre"])
    return filas


def get_categoria(slug):
    doc = _fs().collection("categorias").document(slug).get()
    return _categoria_con_slug(doc.to_dict(), slug) if doc.exists else None


# ------------------------------------------------------------------ planes

def get_planes():
    planes = _all_cacheado("planes")
    filas = [_con_id(p, pid) for pid, p in planes.items()]
    filas.sort(key=lambda p: p["prioridad"])
    return filas


def get_plan(plan_id):
    doc = _fs().collection("planes").document(plan_id).get()
    return _con_id(doc.to_dict(), plan_id) if doc.exists else None


# ---------------------------------------------------------------- avisos

def _denormalizar_avisos(avisos_raw, negocios=None, categorias=None, planes=None):
    negocios = negocios if negocios is not None else _all("negocios")
    categorias = categorias if categorias is not None else _all_cacheado("categorias")
    planes = planes if planes is not None else _all_cacheado("planes")
    filas = []
    for aid, a in avisos_raw.items():
        neg = negocios.get(a.get("negocio_id"), {})
        cat = categorias.get(a.get("categoria_slug"), {})
        plan = planes.get(neg.get("plan_id", "gratis"), {})
        row = dict(a)
        row["id"] = aid
        row["negocio_nombre"] = neg.get("nombre", "")
        row["whatsapp"] = neg.get("whatsapp", "")
        row["email"] = neg.get("email", "")
        row["verificado"] = bool(neg.get("verificado", False))
        row["categoria_id"] = a.get("categoria_slug")
        row["categoria_nombre"] = cat.get("nombre", "")
        row["categoria_slug"] = a.get("categoria_slug")
        row["icono"] = cat.get("icono", "📌")
        row["plan_prioridad"] = plan.get("prioridad", 0)
        row["plan_nombre"] = plan.get("nombre", "Gratis")
        row["es_demo"] = bool(a.get("es_demo", False))
        filas.append(row)
    return filas


def _ordenar_avisos(filas, orden):
    if orden == "recientes":
        filas.sort(key=lambda a: a.get("publicado_en") or "", reverse=True)
    elif orden == "populares":
        filas.sort(key=lambda a: a.get("contactos_total", 0), reverse=True)
    elif orden == "vistas":
        filas.sort(key=lambda a: a.get("vistas_total", 0), reverse=True)
    elif orden == "creado_asc":
        filas.sort(key=lambda a: a.get("creado_en") or "")
    elif orden == "destacados" or orden == "relevancia":
        filas.sort(key=lambda a: a.get("publicado_en") or "", reverse=True)
        filas.sort(key=lambda a: a.get("plan_prioridad", 0), reverse=True)
        filas.sort(key=lambda a: a.get("orden_manual") if a.get("orden_manual") is not None else float("inf"))
    else:  # "creado"
        filas.sort(key=lambda a: a.get("creado_en") or "", reverse=True)
    return filas


def get_avisos(estado=None, estado_ne=None, categoria_slug=None, comuna=None,
               negocio_id=None, excluir_id=None, orden="creado", limit=None):
    filas = _denormalizar_avisos(_all("avisos"))

    if estado is not None:
        filas = [a for a in filas if a["estado"] == estado]
    if estado_ne is not None:
        filas = [a for a in filas if a["estado"] != estado_ne]
    if categoria_slug:
        filas = [a for a in filas if a["categoria_slug"] == categoria_slug]
    if comuna:
        filas = [a for a in filas if a["comuna"] == comuna]
    if negocio_id:
        filas = [a for a in filas if a["negocio_id"] == negocio_id]
    if excluir_id:
        filas = [a for a in filas if a["id"] != excluir_id]

    filas = _ordenar_avisos(filas, orden)

    if limit:
        filas = filas[:limit]
    return filas


def filtrar_avisos(filas, categoria_slug=None, comuna=None, orden="creado", limit=None):
    """Filtra/ordena una lista de avisos ya traida (por ejemplo con
    get_avisos()), sin volver a leer Firestore. Sirve para paginas como el
    listado publico que necesitan la lista completa (para sacar comunas
    disponibles) y ademas una version filtrada -- asi solo se lee una vez."""
    if categoria_slug:
        filas = [a for a in filas if a["categoria_slug"] == categoria_slug]
    if comuna:
        filas = [a for a in filas if a["comuna"] == comuna]
    filas = _ordenar_avisos(list(filas), orden)
    if limit:
        filas = filas[:limit]
    return filas


def guardar_orden_manual(ids_en_orden):
    """Reescribe orden_manual de cada aviso segun su posicion en ids_en_orden
    (0 = primero). Usado por la pantalla de arrastrar-y-soltar del admin."""
    fs = _fs()
    batch = fs.batch()
    for i, aid in enumerate(ids_en_orden):
        batch.update(fs.collection("avisos").document(str(aid)), {"orden_manual": i})
    batch.commit()


def get_aviso(aviso_id):
    doc = _fs().collection("avisos").document(str(aviso_id)).get()
    if not doc.exists:
        return None
    a = doc.to_dict()
    negocio = get_negocio(a.get("negocio_id")) or {}
    filas = _denormalizar_avisos(
        {doc.id: a},
        negocios={a.get("negocio_id"): negocio},
        categorias=_all_cacheado("categorias"),
        planes=_all_cacheado("planes"),
    )
    return filas[0] if filas else None


def get_avisos_por_ids(ids):
    """Trae varios avisos por id en un solo viaje a Firestore (en vez de un
    get_aviso() por cada uno, que hacia 4 lecturas separadas por aviso --
    esto era lo que hacia lenta la pagina de favoritos)."""
    ids = [str(i) for i in ids]
    todos = _all("avisos")
    subset = {aid: todos[aid] for aid in ids if aid in todos}
    return _denormalizar_avisos(subset)


def get_comunas_activas():
    comunas = {a["comuna"] for a in _all("avisos").values() if a.get("estado") == "activo"}
    return sorted(comunas)


def crear_aviso(negocio_id, titulo, descripcion, categoria_slug, comuna, horario, color, estado="pendiente",
                 foto_url=None, es_demo=False, direccion=None, web=None):
    aid = _next_id("avisos")
    _fs().collection("avisos").document(aid).set({
        "negocio_id": negocio_id, "titulo": titulo, "descripcion": descripcion,
        "categoria_slug": categoria_slug, "comuna": comuna, "horario": horario,
        "color": color, "estado": estado, "vistas_total": 0, "contactos_total": 0,
        "foto_url": foto_url, "es_demo": bool(es_demo), "direccion": direccion, "web": web,
        "publicado_en": now() if estado == "activo" else None, "creado_en": now(),
    })
    return aid


def editar_aviso(aviso_id, titulo, descripcion, categoria_slug, comuna, horario, estado, foto_url=None,
                  direccion=None, web=None):
    ref = _fs().collection("avisos").document(str(aviso_id))
    actual = ref.get().to_dict()
    if not actual:
        return False
    publicado_en = actual.get("publicado_en")
    if estado == "activo" and not publicado_en:
        publicado_en = now()
    datos = {
        "titulo": titulo, "descripcion": descripcion, "categoria_slug": categoria_slug,
        "comuna": comuna, "horario": horario, "estado": estado, "publicado_en": publicado_en,
        "direccion": direccion, "web": web,
    }
    if foto_url is not None:
        datos["foto_url"] = foto_url
    ref.update(datos)
    return True


FOTOS_EXTRA_MAX = 3


def agregar_foto_extra(aviso_id, url):
    ref = _fs().collection("avisos").document(str(aviso_id))
    doc = ref.get()
    if not doc.exists:
        return False
    actuales = doc.to_dict().get("fotos_extra") or []
    if len(actuales) >= FOTOS_EXTRA_MAX:
        return False
    actuales.append(url)
    ref.update({"fotos_extra": actuales})
    return True


def eliminar_foto_extra(aviso_id, url):
    ref = _fs().collection("avisos").document(str(aviso_id))
    doc = ref.get()
    if not doc.exists:
        return False
    actuales = [u for u in (doc.to_dict().get("fotos_extra") or []) if u != url]
    ref.update({"fotos_extra": actuales})
    return True


def cambiar_estado_aviso(aviso_id, estado):
    ref = _fs().collection("avisos").document(str(aviso_id))
    datos = {"estado": estado}
    if estado == "activo":
        datos["publicado_en"] = now()
    ref.update(datos)


def eliminar_aviso(aviso_id):
    aviso_id = str(aviso_id)
    fs = _fs()
    for doc in fs.collection("eventos").where("aviso_id", "==", aviso_id).stream():
        doc.reference.delete()
    for doc in fs.collection("reportes").where("aviso_id", "==", aviso_id).stream():
        doc.reference.delete()
    fs.collection("avisos").document(aviso_id).delete()


def incrementar_vistas(aviso_id):
    _fs().collection("avisos").document(str(aviso_id)).update({"vistas_total": firestore.Increment(1)})


def incrementar_contactos(aviso_id):
    _fs().collection("avisos").document(str(aviso_id)).update({"contactos_total": firestore.Increment(1)})


# --------------------------------------------------------------- negocios

def get_negocios():
    negs = _all("negocios")
    return [_con_id(n, nid) for nid, n in negs.items()]


def get_negocio(negocio_id):
    doc = _fs().collection("negocios").document(str(negocio_id)).get()
    return _con_id(doc.to_dict(), negocio_id) if doc.exists else None


def avisos_activos_por_contacto(whatsapp, email):
    """Cuenta avisos activos/pendientes de negocios con este mismo WhatsApp o
    correo, para frenar que una misma persona publique avisos sin límite."""
    wa_norm = "".join(c for c in (whatsapp or "") if c.isdigit())
    email_norm = (email or "").strip().lower()
    if not wa_norm and not email_norm:
        return 0
    negocios = _all("negocios")
    ids_match = set()
    for nid, n in negocios.items():
        n_wa = "".join(c for c in (n.get("whatsapp") or "") if c.isdigit())
        n_email = (n.get("email") or "").strip().lower()
        if (wa_norm and n_wa == wa_norm) or (email_norm and n_email == email_norm):
            ids_match.add(nid)
    if not ids_match:
        return 0
    avisos = _all("avisos")
    return sum(1 for a in avisos.values()
               if a.get("negocio_id") in ids_match and a.get("estado") in ("activo", "pendiente"))


def crear_negocio(nombre, whatsapp, plan_id="gratis", plan_vencimiento=None, terminos_ip=None, email=None,
                   verificado=False):
    nid = _next_id("negocios")
    token = secrets.token_urlsafe(12)
    _fs().collection("negocios").document(nid).set({
        "nombre": nombre, "whatsapp": whatsapp, "email": email, "verificado": bool(verificado),
        "plan_id": plan_id, "plan_vencimiento": plan_vencimiento,
        "token_acceso": token, "creado_en": now(),
        "terminos_aceptados_en": now(), "terminos_aceptados_ip": terminos_ip,
    })
    return nid, token


def cambiar_plan_negocio(negocio_id, plan_id, plan_vencimiento):
    _fs().collection("negocios").document(str(negocio_id)).update({
        "plan_id": plan_id, "plan_vencimiento": plan_vencimiento,
    })


def toggle_verificado_negocio(negocio_id):
    ref = _fs().collection("negocios").document(str(negocio_id))
    actual = ref.get().to_dict() or {}
    nuevo = not actual.get("verificado", False)
    ref.update({"verificado": nuevo})
    return nuevo


def contar_avisos_por_negocio():
    conteo = {}
    for a in _all("avisos").values():
        conteo[a.get("negocio_id")] = conteo.get(a.get("negocio_id"), 0) + 1
    return conteo


# ----------------------------------------------------------------- eventos

def registrar_evento(tipo, aviso_id=None, termino_busqueda=None, sesion=None):
    _fs().collection("eventos").add({
        "aviso_id": str(aviso_id) if aviso_id else None,
        "tipo": tipo,
        "termino_busqueda": termino_busqueda,
        "sesion_hash": sesion or secrets.token_hex(4),
        "creado_en": now(),
    })


def get_eventos():
    return list(_all("eventos").values())


# ------------------------------------------------------------- encuestas

def crear_encuesta(tipo, aviso_id, respuesta=None, calificacion=None, comentario=None):
    _fs().collection("encuestas").add({
        "tipo": tipo, "aviso_id": str(aviso_id) if aviso_id else None,
        "respuesta": respuesta, "calificacion": calificacion, "comentario": comentario,
        "creado_en": now(),
    })


def get_encuestas():
    filas = list(_all("encuestas").values())
    filas.sort(key=lambda e: e.get("creado_en") or "", reverse=True)
    return filas


# ------------------------------------------------------------- sinonimos

def get_sinonimos():
    sins = _all("sinonimos")
    categorias = _all("categorias")
    filas = []
    for sid, s in sins.items():
        row = _con_id(s, sid)
        row["categoria_nombre"] = categorias.get(s["categoria_slug"], {}).get("nombre", "")
        filas.append(row)
    filas.sort(key=lambda s: (s["categoria_nombre"], s["palabra"]))
    return filas


def get_sinonimos_por_categoria():
    por_cat = {}
    for s in _all("sinonimos").values():
        por_cat.setdefault(s["categoria_slug"], []).append(s["palabra"])
    return por_cat


def crear_sinonimo(categoria_slug, palabra):
    sid = _next_id("sinonimos")
    _fs().collection("sinonimos").document(sid).set({"categoria_slug": categoria_slug, "palabra": palabra})
    return sid


def eliminar_sinonimo(sinonimo_id):
    _fs().collection("sinonimos").document(str(sinonimo_id)).delete()


# --------------------------------------------------------- admin_usuario

def get_admin_usuario(usuario):
    doc = _fs().collection("admin_usuarios").document(usuario).get()
    return _con_id(doc.to_dict(), usuario) if doc.exists else None


def get_admin_usuarios():
    users = _all("admin_usuarios")
    filas = [_con_id(u, uid) for uid, u in users.items()]
    filas.sort(key=lambda u: u["usuario"])
    return filas


def crear_admin_usuario(usuario, password_hash, rol):
    ref = _fs().collection("admin_usuarios").document(usuario)
    if ref.get().exists:
        return False
    ref.set({"usuario": usuario, "password": password_hash, "rol": rol})
    return True


def actualizar_password_admin(usuario, password_hash):
    ref = _fs().collection("admin_usuarios").document(usuario)
    if not ref.get().exists:
        return False
    ref.update({"password": password_hash})
    return True


def eliminar_admin_usuario(usuario):
    total = len(list(_fs().collection("admin_usuarios").stream()))
    if total <= 1:
        return False
    _fs().collection("admin_usuarios").document(usuario).delete()
    return True


# ------------------------------------------------------------- reportes

def crear_reporte(aviso_id, motivo):
    rid = _next_id("reportes")
    _fs().collection("reportes").document(rid).set({
        "aviso_id": str(aviso_id), "motivo": motivo, "estado": "pendiente", "creado_en": now(),
    })
    return rid


def get_reportes_pendientes():
    reportes = _all("reportes")
    avisos = _all("avisos")
    filas = []
    for rid, r in reportes.items():
        if r.get("estado") != "pendiente":
            continue
        row = _con_id(r, rid)
        row["aviso_titulo"] = avisos.get(r["aviso_id"], {}).get("titulo", "(aviso eliminado)")
        filas.append(row)
    filas.sort(key=lambda r: r["creado_en"], reverse=True)
    return filas


def descartar_reporte(reporte_id):
    _fs().collection("reportes").document(str(reporte_id)).update({"estado": "descartado"})


# ------------------------------------------------------------- auditoria

def crear_auditoria(usuario, accion, detalle=""):
    _fs().collection("auditoria").add({
        "usuario": usuario, "accion": accion, "detalle": detalle, "creado_en": now(),
    })


def get_auditoria(limit=200):
    filas = list(_all("auditoria").values())
    filas.sort(key=lambda r: r["creado_en"], reverse=True)
    return filas[:limit]


# ----------------------------------------------------------------- pagos

def crear_pago(negocio_id, plan_id, precio_clp):
    _fs().collection("pagos").add({
        "negocio_id": str(negocio_id), "plan_id": plan_id, "precio_clp": precio_clp, "creado_en": now(),
    })


def get_pagos():
    pagos = list(_all("pagos").values())
    negocios = _all("negocios")
    planes = _all("planes")
    filas = []
    for p in pagos:
        row = dict(p)
        row["negocio_nombre"] = negocios.get(p["negocio_id"], {}).get("nombre", "(negocio eliminado)")
        row["plan_nombre"] = planes.get(p["plan_id"], {}).get("nombre", p["plan_id"])
        filas.append(row)
    filas.sort(key=lambda p: p["creado_en"], reverse=True)
    return filas


# --------------------------------------------------------------- alertas

def crear_alerta(termino, whatsapp):
    _fs().collection("alertas").add({
        "termino": termino, "whatsapp": whatsapp, "atendida": False, "creado_en": now(),
    })


def get_alertas_pendientes():
    alertas = _all("alertas")
    filas = [_con_id(a, aid) for aid, a in alertas.items() if not a.get("atendida")]
    filas.sort(key=lambda a: a["creado_en"], reverse=True)
    return filas


def marcar_alerta_atendida(alerta_id):
    _fs().collection("alertas").document(str(alerta_id)).update({"atendida": True})


# ------------------------------------------------------------ necesidades

def crear_necesidad(categoria_slug, descripcion, sector, cuando, whatsapp):
    """Guarda una solicitud para que el equipo conecte demanda con pymes."""
    nid = _next_id("necesidades")
    _fs().collection("necesidades").document(nid).set({
        "categoria_slug": categoria_slug,
        "descripcion": descripcion,
        "sector": sector,
        "cuando": cuando,
        "whatsapp": whatsapp,
        "estado": "nueva",
        "creado_en": now(),
    })
    return nid


def get_necesidades_pendientes():
    necesidades = _all("necesidades")
    categorias = _all("categorias")
    filas = []
    for nid, necesidad in necesidades.items():
        if necesidad.get("estado") != "nueva":
            continue
        row = _con_id(necesidad, nid)
        categoria = categorias.get(row.get("categoria_slug"), {})
        row["categoria_nombre"] = categoria.get("nombre", "Sin categoría")
        row["icono"] = categoria.get("icono", "📌")
        filas.append(row)
    filas.sort(key=lambda n: n.get("creado_en", ""), reverse=True)
    return filas


def marcar_necesidad_atendida(necesidad_id):
    _fs().collection("necesidades").document(str(necesidad_id)).update({"estado": "atendida"})


# ----------------------------------------------------------- estadisticas

def get_dashboard_stats(dias):
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=dias)).isoformat()
    avisos = _all("avisos")
    negocios = _all("negocios")
    planes = _all("planes")
    eventos = list(_all("eventos").values())

    avisos_activos = sum(1 for a in avisos.values() if a.get("estado") == "activo")
    pendientes = sum(1 for a in avisos.values() if a.get("estado") == "pendiente")

    eventos_periodo = [e for e in eventos if e.get("creado_en", "") >= cutoff]
    vistas = sum(1 for e in eventos_periodo if e.get("tipo") == "vista")
    contactos = sum(1 for e in eventos_periodo if e.get("tipo") == "click_whatsapp")

    hoy = datetime.date.today().isoformat()
    anunciantes_pagando = 0
    mrr = 0
    for n in negocios.values():
        plan = planes.get(n.get("plan_id", "gratis"), {})
        precio = plan.get("precio_clp", 0)
        vencimiento = n.get("plan_vencimiento")
        vigente = vencimiento is None or vencimiento >= hoy
        if precio > 0 and vigente:
            anunciantes_pagando += 1
            mrr += precio

    def top(tipo):
        conteo = {}
        for e in eventos_periodo:
            if e.get("tipo") == tipo and e.get("aviso_id"):
                conteo[e["aviso_id"]] = conteo.get(e["aviso_id"], 0) + 1
        filas = []
        for aviso_id, n in conteo.items():
            a = avisos.get(aviso_id)
            if not a:
                continue
            neg = negocios.get(a.get("negocio_id"), {})
            filas.append({"id": aviso_id, "titulo": a["titulo"], "negocio_nombre": neg.get("nombre", ""), "n": n})
        filas.sort(key=lambda f: f["n"], reverse=True)
        return filas[:10]

    dias_mostrados = min(dias, 30)
    por_dia = {}
    for i in range(dias_mostrados):
        fecha = (datetime.date.today() - datetime.timedelta(days=dias_mostrados - 1 - i)).isoformat()
        por_dia[fecha] = {"fecha": fecha, "vistas": 0, "contactos": 0}
    serie_cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=dias_mostrados)).isoformat()
    for e in eventos:
        creado = e.get("creado_en", "")
        if creado < serie_cutoff:
            continue
        fecha = creado[:10]
        fila = por_dia.get(fecha)
        if not fila:
            continue
        if e.get("tipo") == "vista":
            fila["vistas"] += 1
        elif e.get("tipo") == "click_whatsapp":
            fila["contactos"] += 1
    serie_diaria = [por_dia[f] for f in sorted(por_dia)]

    categorias = {slug: _categoria_con_slug(c, slug) for slug, c in _all("categorias").items()}
    conteo_cat = {}
    for a in avisos.values():
        if a.get("estado") != "activo":
            continue
        conteo_cat[a["categoria_slug"]] = conteo_cat.get(a["categoria_slug"], 0) + 1
    por_categoria = [
        {"slug": slug, "nombre": categorias[slug]["nombre"], "icono": categorias[slug]["icono"],
         "color": COLOR_POR_CATEGORIA.get(slug, "#8E93A1"), "n": n}
        for slug, n in conteo_cat.items() if slug in categorias
    ]
    por_categoria.sort(key=lambda c: c["n"], reverse=True)

    return {
        "avisos_activos": avisos_activos, "pendientes": pendientes,
        "vistas": vistas, "contactos": contactos,
        "anunciantes_pagando": anunciantes_pagando, "mrr": mrr,
        "serie_diaria": serie_diaria, "por_categoria": por_categoria,
        "top_vistos": top("vista"), "top_contactados": top("click_whatsapp"),
    }


_cache_terminos_buscados = {}  # limit -> (timestamp, resultado)


def get_terminos_mas_buscados(limit=15, dias=14):
    """`eventos` es la coleccion mas grande y mas escrita del sitio (un
    documento por cada vista/click), y esto se leia completa en cada carga
    del home -- de lejos lo mas lento de esa pagina. Se cachea el resultado
    ya calculado (no la coleccion completa, para no acumular memoria) un
    minuto: las tendencias de busqueda no necesitan ser al segundo.

    Se limita a los ultimos `dias` dias (por defecto 14): sin esto, un pico
    de clicks de hace meses (ej. datos de prueba) queda dominando "lo mas
    buscado" para siempre y deja de reflejar actividad real.

    Ademas cuenta sesiones de navegador distintas, no clicks sueltos: si
    alguien busca el mismo termino varias veces solo suma 1, para que no
    ensucie el ranking una sola persona insistiendo con la misma palabra."""
    cache_key = (limit, dias)
    entrada = _cache_terminos_buscados.get(cache_key)
    if entrada and (time.monotonic() - entrada[0]) < 60:
        return entrada[1]
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=dias)).isoformat()
    sesiones_por_termino = {}
    for e in _all("eventos").values():
        if (e.get("tipo") == "click_resultado_busqueda" and e.get("termino_busqueda")
                and e.get("creado_en", "") >= cutoff):
            termino = e["termino_busqueda"]
            clave_sesion = e.get("sesion_hash") or id(e)
            sesiones_por_termino.setdefault(termino, set()).add(clave_sesion)
    conteo = {k: len(v) for k, v in sesiones_por_termino.items()}
    filas = [{"termino_busqueda": k, "n": v} for k, v in conteo.items()]
    filas.sort(key=lambda f: f["n"], reverse=True)
    resultado = filas[:limit]
    _cache_terminos_buscados[cache_key] = (time.monotonic(), resultado)
    return resultado


def get_terminos_sin_resultado(limit=15):
    conteo = {}
    for e in _all("eventos").values():
        if e.get("tipo") == "busqueda_sin_resultado" and e.get("termino_busqueda"):
            conteo[e["termino_busqueda"]] = conteo.get(e["termino_busqueda"], 0) + 1
    filas = [{"termino_busqueda": k, "n": v} for k, v in conteo.items()]
    filas.sort(key=lambda f: f["n"], reverse=True)
    return filas[:limit]


# ------------------------------------------------------------------- seed

CATEGORIAS = [
    ("Vidriería y ventanas", "vidrieria", "🪟"),
    ("Gásfitería y plomería", "gasfiteria", "🔧"),
    ("Electricidad", "electricidad", "💡"),
    ("Aluminios y estructuras", "aluminios", "🏗️"),
    ("Clases particulares", "clases", "📚"),
    ("Tecnología y notebooks", "tecnologia", "💻"),
    ("Panadería y pastelería", "panaderia", "🥖"),
    ("Peluquería y belleza", "belleza", "💇"),
    ("Jardinería", "jardineria", "🌿"),
    ("Contabilidad y trámites", "contabilidad", "📊"),
]

COLOR_POR_CATEGORIA = {
    "vidrieria": "#5AC8FA",
    "gasfiteria": "#30D158",
    "electricidad": "#FFD60A",
    "aluminios": "#8E93A1",
    "clases": "#BF5AF2",
    "tecnologia": "#5E7CE2",
    "panaderia": "#FF9F45",
    "belleza": "#FF6482",
    "jardineria": "#34C759",
    "contabilidad": "#32C6D0",
    "otros": "#9AA0A6",
}

SINONIMOS = {
    "vidrieria": ["ventana", "ventanas", "vidrio", "vidrios", "cristal",
                  "termopanel", "reparar vidrio", "vidrio roto"],
    "gasfiteria": ["cañería", "filtración", "agua", "baño", "llave que gotea",
                   "destapar", "wc", "estanque", "fuga de agua"],
    "electricidad": ["corte de luz", "enchufe", "cortocircuito", "instalación eléctrica",
                      "tablero", "electricista"],
    "aluminios": ["ventanas", "puertas corredizas", "cierre perimetral", "reja",
                  "estructura metálica", "baranda"],
    "clases": ["inglés", "clases de inglés", "profesor particular", "reforzamiento",
               "matemáticas", "guitarra", "clases de música", "tutor"],
    "tecnologia": ["notebook", "computador", "pc lento", "reparación de celular",
                   "formatear", "virus", "impresora"],
    "panaderia": ["pan", "pan amasado", "tortas", "pasteles", "cumpleaños", "queque"],
    "belleza": ["corte de pelo", "peluquero", "manicure", "uñas", "maquillaje", "peinado"],
    "jardineria": ["pasto", "poda", "jardín", "paisajismo", "corte de pasto", "árboles"],
    "contabilidad": ["contador", "iva", "boletas", "inicio de actividades", "sii",
                      "declaración de renta", "pyme"],
}

PLANES = [
    ("gratis", "Gratis", 0, 36500, 0),
    ("destacado", "Destacado", 9990, 30, 1),
    ("premium", "Premium", 19990, 30, 2),
]

NEGOCIOS = [
    ("Vidriería Maule", "+56912345001", "premium", 1),
    ("Aluminios del Sur", "+56912345002", "destacado", 1),
    ("Gásfiter Express Talca", "+56912345003", "gratis", 0),
    ("Electricidad Rengo", "+56912345004", "destacado", 1),
    ("Inglés con Pauli", "+56912345005", "gratis", 0),
    ("PC Rápido Talca", "+56912345006", "premium", 1),
    ("Panadería Doña Elba", "+56912345007", "destacado", 0),
    ("Salón Bella Maule", "+56912345008", "gratis", 0),
    ("Jardines del Maule", "+56912345009", "destacado", 1),
    ("Contabilidad Ríos & Asociados", "+56912345010", "premium", 1),
    ("Vidrios y Cristales Central", "+56912345011", "gratis", 0),
    ("TecnoServicio Talca", "+56912345012", "gratis", 0),
]

AVISOS = [
    (0, "Instalación y reparación de termopaneles", "vidrieria", "Talca",
     "Fabricamos e instalamos termopaneles y ventanas de PVC y aluminio a medida. "
     "Retiro de vidrios rotos y presupuesto sin costo.", "Lun a Vie 9:00-18:30", "activo"),
    (1, "Ventanas corredizas y estructuras de aluminio", "aluminios", "Talca",
     "Diseñamos e instalamos ventanas corredizas, puertas y cierres perimetrales en aluminio. "
     "Trabajamos con planos y también a pedido.", "Lun a Sáb 9:00-19:00", "activo"),
    (2, "Gásfiter a domicilio, respuesta rápida", "gasfiteria", "Talca",
     "Reparación de fugas, destape de cañerías, instalación de artefactos sanitarios. "
     "Atención de urgencia el mismo día.", "Todos los días 8:00-21:00", "activo"),
    (3, "Electricista certificado SEC", "electricidad", "Talca",
     "Instalaciones eléctricas domiciliarias y comerciales, certificación SEC, "
     "tableros y cambio de medidores.", "Lun a Vie 9:00-18:00", "activo"),
    (4, "Clases particulares de inglés, todos los niveles", "clases", "Talca",
     "Profesora con certificación internacional. Clases online o presenciales, "
     "preparación PSU/PAES y conversación.", "Tardes de lunes a viernes", "activo"),
    (5, "Reparación de notebooks y computadores", "tecnologia", "Talca",
     "Formateo, cambio de piezas, eliminación de virus y mantención. "
     "Diagnóstico gratis, entrega en 24-48 horas.", "Lun a Sáb 10:00-19:00", "activo"),
    (6, "Pan amasado y tortas por encargo", "panaderia", "Talca",
     "Pan amasado todos los días, tortas y pasteles para cumpleaños y eventos. "
     "Pedidos con 48 horas de anticipación.", "Todos los días 7:30-20:00", "activo"),
    (7, "Corte, color y peinados a domicilio", "belleza", "Talca",
     "Peluquería a domicilio para toda la familia. Cortes, color, peinados de evento "
     "y manicure.", "Lun a Sáb 9:00-20:00", "activo"),
    (8, "Mantención de jardines y poda de árboles", "jardineria", "Talca",
     "Corte de pasto, poda, diseño de jardines y mantención mensual para casas y "
     "condominios.", "Lun a Vie 8:00-17:00", "activo"),
    (9, "Contabilidad para pymes y emprendedores", "contabilidad", "Talca",
     "Inicio de actividades, boletas electrónicas, declaración de renta e IVA mensual "
     "para pymes de la región.", "Lun a Vie 9:00-18:00", "activo"),
    (10, "Venta y reparación de vidrios y espejos", "vidrieria", "Maule",
     "Cortamos vidrios a medida, espejos y reparación de vidrios rotos en el hogar.",
     "Lun a Vie 9:00-18:00", "activo"),
    (11, "Soporte técnico y redes para pymes", "tecnologia", "Talca",
     "Soporte técnico remoto y presencial, instalación de redes e impresoras "
     "para pequeñas empresas.", "Lun a Vie 9:00-18:00", "pendiente"),
]

TERMINOS_SIN_RESULTADO = [
    "veterinario 24 horas", "traductor jurado", "arriendo de andamios",
    "clases de yoga", "diseñador gráfico freelance", "mudanzas Talca",
]


def _fecha_aleatoria(dias_atras, rng):
    delta = datetime.timedelta(days=rng.randint(0, dias_atras), hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
    return (datetime.datetime.utcnow() - delta).isoformat()


def seed_if_empty():
    fs = _fs()
    if list(fs.collection("categorias").limit(1).stream()):
        return

    for nombre, slug, icono in CATEGORIAS:
        fs.collection("categorias").document(slug).set({"nombre": nombre, "icono": icono})

    for slug, palabras in SINONIMOS.items():
        for palabra in palabras:
            crear_sinonimo(slug, palabra)

    for pid, nombre, precio, dur, prioridad in PLANES:
        fs.collection("planes").document(pid).set({
            "nombre": nombre, "precio_clp": precio, "duracion_dias": dur, "prioridad": prioridad,
        })

    neg_ids = []
    for nombre, whatsapp, plan_id, verificado in NEGOCIOS:
        nid = _next_id("negocios")
        fs.collection("negocios").document(nid).set({
            "nombre": nombre, "whatsapp": whatsapp, "verificado": bool(verificado),
            "plan_id": plan_id, "plan_vencimiento": "2026-12-31" if plan_id != "gratis" else None,
            "token_acceso": secrets.token_urlsafe(12), "creado_en": now(),
        })
        neg_ids.append(nid)

    aviso_ids = []
    for neg_idx, titulo, cat_slug, comuna, desc, horario, estado in AVISOS:
        aid = _next_id("avisos")
        fs.collection("avisos").document(aid).set({
            "negocio_id": neg_ids[neg_idx], "titulo": titulo, "descripcion": desc,
            "categoria_slug": cat_slug, "comuna": comuna, "horario": horario,
            "color": COLOR_POR_CATEGORIA[cat_slug], "estado": estado,
            "vistas_total": 0, "contactos_total": 0,
            "publicado_en": now() if estado == "activo" else None, "creado_en": now(),
        })
        aviso_ids.append((aid, cat_slug, estado, neg_idx))

    fs.collection("admin_usuarios").document("admin").set({
        "usuario": "admin", "password": hash_password(os.environ.get("ADMIN_PASSWORD", "talca2026")),
        "rol": "super_admin",
    })

    _sembrar_eventos(fs, aviso_ids, random.Random(42))


def _sembrar_eventos(fs, aviso_ids, rng):
    planes_prioridad = {"gratis": 0, "destacado": 1, "premium": 2}
    terminos_por_cat = {}
    for s in _all("sinonimos").values():
        terminos_por_cat.setdefault(s["categoria_slug"], []).append(s["palabra"])

    batch = fs.batch()
    ops = 0

    def add(coleccion, datos):
        nonlocal batch, ops
        batch.set(fs.collection(coleccion).document(), datos)
        ops += 1
        if ops >= 400:
            batch.commit()
            batch = fs.batch()
            ops = 0

    for aid, cat_slug, estado, neg_idx in aviso_ids:
        if estado != "activo":
            continue
        plan_id = NEGOCIOS[neg_idx][2]
        popularidad = 1 + planes_prioridad.get(plan_id, 0)
        n_vistas = rng.randint(15, 90) * popularidad
        n_contactos = max(1, int(n_vistas * rng.uniform(0.06, 0.18)))
        n_busquedas = rng.randint(2, 10) * popularidad

        for _ in range(n_vistas):
            add("eventos", {"aviso_id": aid, "tipo": "vista", "termino_busqueda": None,
                             "sesion_hash": f"s{rng.randint(1, 999999):06x}", "creado_en": _fecha_aleatoria(28, rng)})
        for _ in range(n_contactos):
            add("eventos", {"aviso_id": aid, "tipo": "click_whatsapp", "termino_busqueda": None,
                             "sesion_hash": f"s{rng.randint(1, 999999):06x}", "creado_en": _fecha_aleatoria(28, rng)})
        terminos = terminos_por_cat.get(cat_slug, [cat_slug])
        for _ in range(n_busquedas):
            add("eventos", {"aviso_id": aid, "tipo": "click_resultado_busqueda",
                             "termino_busqueda": rng.choice(terminos),
                             "sesion_hash": f"s{rng.randint(1, 999999):06x}", "creado_en": _fecha_aleatoria(28, rng)})

        fs.collection("avisos").document(aid).update({"vistas_total": n_vistas, "contactos_total": n_contactos})

    for termino in TERMINOS_SIN_RESULTADO:
        for _ in range(rng.randint(2, 8)):
            add("eventos", {"aviso_id": None, "tipo": "busqueda_sin_resultado", "termino_busqueda": termino,
                             "sesion_hash": f"s{rng.randint(1, 999999):06x}", "creado_en": _fecha_aleatoria(28, rng)})

    if ops:
        batch.commit()
