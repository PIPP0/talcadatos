"""
Capa de datos de Talcadatos.

Usa SQLite (stdlib) como sustituto local de PostgreSQL + pgvector definido
en el PRD (seccion 8 y 12). El modelo de tablas sigue el PRD 1:1; la unica
diferencia real de produccion es que aqui no hay columna `embedding` vector
-- la busqueda "IA" vive en search.py con un motor de sinonimos+puntaje que
se puede reemplazar por embeddings reales sin tocar el resto del sitio
(ver comentario en search.py).
"""
import sqlite3
import os
import random
import hashlib
import secrets
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "talcadatos.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS categoria (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    icono TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sinonimo (
    id INTEGER PRIMARY KEY,
    categoria_id INTEGER NOT NULL REFERENCES categoria(id),
    palabra TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    precio_clp INTEGER NOT NULL,
    duracion_dias INTEGER NOT NULL,
    prioridad INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS negocio (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    whatsapp TEXT NOT NULL,
    email TEXT,
    verificado INTEGER NOT NULL DEFAULT 0,
    plan_id INTEGER REFERENCES plan(id),
    plan_vencimiento TEXT,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aviso (
    id INTEGER PRIMARY KEY,
    negocio_id INTEGER NOT NULL REFERENCES negocio(id),
    titulo TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    categoria_id INTEGER NOT NULL REFERENCES categoria(id),
    comuna TEXT NOT NULL,
    horario TEXT,
    color TEXT NOT NULL DEFAULT '#8C5F22',
    estado TEXT NOT NULL DEFAULT 'pendiente',
    vistas_total INTEGER NOT NULL DEFAULT 0,
    contactos_total INTEGER NOT NULL DEFAULT 0,
    publicado_en TEXT,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evento (
    id INTEGER PRIMARY KEY,
    aviso_id INTEGER REFERENCES aviso(id),
    tipo TEXT NOT NULL,
    termino_busqueda TEXT,
    sesion_hash TEXT,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_usuario (
    id INTEGER PRIMARY KEY,
    usuario TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'super_admin'
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now():
    return datetime.datetime.utcnow().isoformat()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(8)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def verify_password(password, stored):
    if "$" not in stored:
        return False
    salt, _ = stored.split("$", 1)
    return hash_password(password, salt) == stored


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

# Color de acento por categoria (fondo de la tarjeta y de la imagen OG).
COLOR_POR_CATEGORIA = {
    "vidrieria": "#6B4818",
    "gasfiteria": "#2F6B5E",
    "electricidad": "#9C4A32",
    "aluminios": "#6B4818",
    "clases": "#2F6B5E",
    "tecnologia": "#8C5F22",
    "panaderia": "#6B4818",
    "belleza": "#9C4A32",
    "jardineria": "#2F6B5E",
    "contabilidad": "#8C5F22",
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
    ("Gratis", 0, 36500, 0),
    ("Destacado", 9990, 30, 1),
    ("Premium", 19990, 30, 2),
]

NEGOCIOS = [
    # nombre, whatsapp, plan_idx, verificado
    ("Vidriería Maule", "+56912345001", 2, 1),
    ("Aluminios del Sur", "+56912345002", 1, 1),
    ("Gásfiter Express Talca", "+56912345003", 0, 0),
    ("Electricidad Rengo", "+56912345004", 1, 1),
    ("Inglés con Pauli", "+56912345005", 0, 0),
    ("PC Rápido Talca", "+56912345006", 2, 1),
    ("Panadería Doña Elba", "+56912345007", 1, 0),
    ("Salón Bella Maule", "+56912345008", 0, 0),
    ("Jardines del Maule", "+56912345009", 1, 1),
    ("Contabilidad Ríos & Asociados", "+56912345010", 2, 1),
    ("Vidrios y Cristales Central", "+56912345011", 0, 0),
    ("TecnoServicio Talca", "+56912345012", 0, 0),
]

AVISOS = [
    # negocio_idx, titulo, categoria_slug, comuna, descripcion, horario, color, estado
    (0, "Instalación y reparación de termopaneles", "vidrieria", "Talca",
     "Fabricamos e instalamos termopaneles y ventanas de PVC y aluminio a medida. "
     "Retiro de vidrios rotos y presupuesto sin costo.", "Lun a Vie 9:00-18:30", "#8C5F22", "activo"),
    (1, "Ventanas corredizas y estructuras de aluminio", "aluminios", "Talca",
     "Diseñamos e instalamos ventanas corredizas, puertas y cierres perimetrales en aluminio. "
     "Trabajamos con planos y también a pedido.", "Lun a Sáb 9:00-19:00", "#6B4818", "activo"),
    (2, "Gásfiter a domicilio, respuesta rápida", "gasfiteria", "Talca",
     "Reparación de fugas, destape de cañerías, instalación de artefactos sanitarios. "
     "Atención de urgencia el mismo día.", "Todos los días 8:00-21:00", "#2F6B5E", "activo"),
    (3, "Electricista certificado SEC", "electricidad", "Talca",
     "Instalaciones eléctricas domiciliarias y comerciales, certificación SEC, "
     "tableros y cambio de medidores.", "Lun a Vie 9:00-18:00", "#9C4A32", "activo"),
    (4, "Clases particulares de inglés, todos los niveles", "clases", "Talca",
     "Profesora con certificación internacional. Clases online o presenciales, "
     "preparación PSU/PAES y conversación.", "Tardes de lunes a viernes", "#2F6B5E", "activo"),
    (5, "Reparación de notebooks y computadores", "tecnologia", "Talca",
     "Formateo, cambio de piezas, eliminación de virus y mantención. "
     "Diagnóstico gratis, entrega en 24-48 horas.", "Lun a Sáb 10:00-19:00", "#8C5F22", "activo"),
    (6, "Pan amasado y tortas por encargo", "panaderia", "Talca",
     "Pan amasado todos los días, tortas y pasteles para cumpleaños y eventos. "
     "Pedidos con 48 horas de anticipación.", "Todos los días 7:30-20:00", "#6B4818", "activo"),
    (7, "Corte, color y peinados a domicilio", "belleza", "Talca",
     "Peluquería a domicilio para toda la familia. Cortes, color, peinados de evento "
     "y manicure.", "Lun a Sáb 9:00-20:00", "#9C4A32", "activo"),
    (8, "Mantención de jardines y poda de árboles", "jardineria", "Talca",
     "Corte de pasto, poda, diseño de jardines y mantención mensual para casas y "
     "condominios.", "Lun a Vie 8:00-17:00", "#2F6B5E", "activo"),
    (9, "Contabilidad para pymes y emprendedores", "contabilidad", "Talca",
     "Inicio de actividades, boletas electrónicas, declaración de renta e IVA mensual "
     "para pymes de la región.", "Lun a Vie 9:00-18:00", "#8C5F22", "activo"),
    (10, "Venta y reparación de vidrios y espejos", "vidrieria", "Maule",
     "Cortamos vidrios a medida, espejos y reparación de vidrios rotos en el hogar.",
     "Lun a Vie 9:00-18:00", "#6B4818", "activo"),
    (11, "Soporte técnico y redes para pymes", "tecnologia", "Talca",
     "Soporte técnico remoto y presencial, instalación de redes e impresoras "
     "para pequeñas empresas.", "Lun a Vie 9:00-18:00", "#9C4A32", "pendiente"),
]


TERMINOS_SIN_RESULTADO = [
    "veterinario 24 horas", "traductor jurado", "arriendo de andamios",
    "clases de yoga", "diseñador gráfico freelance", "mudanzas Talca",
]


def _fecha_aleatoria(dias_atras, rng):
    delta = datetime.timedelta(
        days=rng.randint(0, dias_atras),
        hours=rng.randint(0, 23),
        minutes=rng.randint(0, 59),
    )
    return (datetime.datetime.utcnow() - delta).isoformat()


def _sembrar_eventos(cur, rng):
    """Genera historial de vistas/contactos/búsquedas de las últimas 4 semanas
    para que el panel de admin (seccion 7 del PRD) tenga datos reales que mostrar."""
    avisos = cur.execute(
        "SELECT aviso.id, categoria.slug AS cat_slug, negocio.plan_id, plan.prioridad "
        "FROM aviso JOIN categoria ON categoria.id = aviso.categoria_id "
        "JOIN negocio ON negocio.id = aviso.negocio_id "
        "JOIN plan ON plan.id = negocio.plan_id "
        "WHERE aviso.estado = 'activo'"
    ).fetchall()

    terminos_por_cat = {}
    for row in cur.execute(
        "SELECT categoria.slug AS slug, sinonimo.palabra FROM sinonimo "
        "JOIN categoria ON categoria.id = sinonimo.categoria_id"
    ).fetchall():
        terminos_por_cat.setdefault(row["slug"], []).append(row["palabra"])

    for aviso in avisos:
        popularidad = 1 + aviso["prioridad"]  # destacados/premium tienden a tener mas trafico
        n_vistas = rng.randint(15, 90) * popularidad
        n_contactos = max(1, int(n_vistas * rng.uniform(0.06, 0.18)))
        n_busquedas = rng.randint(2, 10) * popularidad

        for _ in range(n_vistas):
            cur.execute(
                "INSERT INTO evento (aviso_id, tipo, sesion_hash, creado_en) VALUES (?,?,?,?)",
                (aviso["id"], "vista", f"s{rng.randint(1, 999999):06x}", _fecha_aleatoria(28, rng)),
            )
        for _ in range(n_contactos):
            cur.execute(
                "INSERT INTO evento (aviso_id, tipo, sesion_hash, creado_en) VALUES (?,?,?,?)",
                (aviso["id"], "click_whatsapp", f"s{rng.randint(1, 999999):06x}", _fecha_aleatoria(28, rng)),
            )
        terminos = terminos_por_cat.get(aviso["cat_slug"], [aviso["cat_slug"]])
        for _ in range(n_busquedas):
            termino = rng.choice(terminos)
            cur.execute(
                "INSERT INTO evento (aviso_id, tipo, termino_busqueda, sesion_hash, creado_en) "
                "VALUES (?,?,?,?,?)",
                (aviso["id"], "click_resultado_busqueda", termino,
                 f"s{rng.randint(1, 999999):06x}", _fecha_aleatoria(28, rng)),
            )

        cur.execute(
            "UPDATE aviso SET vistas_total = ?, contactos_total = ? WHERE id = ?",
            (n_vistas, n_contactos, aviso["id"]),
        )

    for termino in TERMINOS_SIN_RESULTADO:
        for _ in range(rng.randint(2, 8)):
            cur.execute(
                "INSERT INTO evento (aviso_id, tipo, termino_busqueda, sesion_hash, creado_en) "
                "VALUES (NULL, 'busqueda_sin_resultado', ?, ?, ?)",
                (termino, f"s{rng.randint(1, 999999):06x}", _fecha_aleatoria(28, rng)),
            )


def seed_if_empty():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript(SCHEMA)

    if cur.execute("SELECT COUNT(*) FROM categoria").fetchone()[0] == 0:
        cat_ids = {}
        for nombre, slug, icono in CATEGORIAS:
            cur.execute(
                "INSERT INTO categoria (nombre, slug, icono) VALUES (?, ?, ?)",
                (nombre, slug, icono),
            )
            cat_ids[slug] = cur.lastrowid

        for slug, palabras in SINONIMOS.items():
            cid = cat_ids[slug]
            for palabra in palabras:
                cur.execute(
                    "INSERT INTO sinonimo (categoria_id, palabra) VALUES (?, ?)",
                    (cid, palabra),
                )

        plan_ids = []
        for nombre, precio, dur, prioridad in PLANES:
            cur.execute(
                "INSERT INTO plan (nombre, precio_clp, duracion_dias, prioridad) VALUES (?, ?, ?, ?)",
                (nombre, precio, dur, prioridad),
            )
            plan_ids.append(cur.lastrowid)

        neg_ids = []
        for nombre, whatsapp, plan_idx, verificado in NEGOCIOS:
            cur.execute(
                "INSERT INTO negocio (nombre, whatsapp, verificado, plan_id, plan_vencimiento, creado_en) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (nombre, whatsapp, verificado, plan_ids[plan_idx],
                 "2026-12-31" if plan_idx > 0 else None, now()),
            )
            neg_ids.append(cur.lastrowid)

        for neg_idx, titulo, cat_slug, comuna, desc, horario, color, estado in AVISOS:
            cur.execute(
                "INSERT INTO aviso (negocio_id, titulo, descripcion, categoria_id, comuna, "
                "horario, color, estado, publicado_en, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (neg_ids[neg_idx], titulo, desc, cat_ids[cat_slug], comuna, horario, color,
                 estado, now() if estado == "activo" else None, now()),
            )

        _sembrar_eventos(cur, random.Random(42))

        cur.execute(
            "INSERT INTO admin_usuario (usuario, password, rol) VALUES (?, ?, ?)",
            ("admin", hash_password(os.environ.get("ADMIN_PASSWORD", "talca2026")), "super_admin"),
        )

        conn.commit()
    conn.close()
