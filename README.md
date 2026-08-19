# Talcadatos

Sitio de avisos de pymes y emprendedores de Talca, construido en base al PRD.
MVP funcional: sitio público con buscador "IA" y filtros, avisos destacados,
detalle con WhatsApp directo, y panel de administración completo.

## Por qué Python y no Next.js

El PRD (sección 12) recomienda Next.js + Postgres + pgvector para producción.
Este entorno no tiene Node.js instalado, así que el MVP se construyó con la
librería estándar de Python (`http.server` + `sqlite3`), sin dependencias que
instalar. La estructura de datos y rutas sigue el PRD 1:1, para poder migrar
a la stack de producción sin rediseñar nada.

## Cómo correrlo

```bash
cd talcadatos
python3 server.py 8002
```

Abre http://localhost:8002 — la base de datos (`talcadatos.db`) y los datos
de ejemplo se crean solos la primera vez que corre.

También puedes usar el botón de vista previa de Claude Code (`talcadatos` en
`.claude/launch.json`, puerto 8002).

## Admin

http://localhost:8002/admin — usuario `admin`, contraseña `talca2026`.

## Estructura

- `db.py` — esquema SQLite + datos y eventos de ejemplo (sigue el modelo de datos del PRD §8).
- `search.py` — el buscador "por necesidad" del PRD §9: sinónimos por rubro + puntaje de texto.
  Sin llave de API en este entorno no se generaron embeddings reales; la función
  `buscar_avisos()` está aislada para reemplazarse por embeddings (OpenAI + pgvector)
  sin tocar el resto del sitio.
- `ogimage.py` — genera la tarjeta de vista previa (1200×630) que se ve cuando alguien
  reenvía un aviso por WhatsApp (usa Pillow + fuentes del sistema).
- `templates.py` — HTML del sitio (sin framework de templates).
- `server.py` — rutas del sitio público y del admin.
- `static/` — CSS y el JS del buscador en vivo + registro de eventos.

## Además del MVP base

- **SEO/marketing**: meta tags Open Graph + Twitter Card, imagen de vista previa generada
  por aviso (clave porque el canal de contacto es WhatsApp — la gente reenvía avisos),
  datos estructurados `schema.org/LocalBusiness`, `robots.txt` y `sitemap.xml` dinámico.
- **Conversión**: barra de prueba social (negocios activos, contactos generados, rubros)
  y sección "cómo funciona" en 3 pasos en la home.
- **UX del admin**: mensajes de confirmación (flash) tras aprobar/rechazar/editar/activar plan.
- **Robustez**: validación server-side del formulario de publicar (con errores legibles y
  los datos ingresados preservados), páginas 404/500 propias en vez de que el servidor truene.
- **Seguridad**: la contraseña de admin se guarda con hash (SHA-256 + salt) en vez de texto plano.

## Qué falta para producción

Ver PRD §15 (roadmap). Lo más relevante para pasar de este prototipo a producción:
subir fotos reales (hoy son íconos por categoría), pasar SQLite → Postgres + pgvector,
embeddings reales de IA, pasarela de pago automática (Webpay/MercadoPago), rate limiting
real (hoy no lo hay) y un hash de contraseña con más iteraciones (bcrypt/argon2) para el admin.
