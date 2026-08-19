# Talcadatos

Sitio de avisos de pymes y emprendedores de Talca, construido en base al PRD.
MVP funcional: sitio público con buscador "IA" y filtros, avisos destacados,
detalle con WhatsApp directo, y panel de administración completo.

**Vista en vivo:** https://pipp0.github.io/talcadatos/
Es una versión sin servidor (GitHub Pages), pero el **buscador y los filtros
funcionan de verdad** — corren en JavaScript en el navegador
([pages_assets/search-client.js](pages_assets/search-client.js) reimplementa
el mismo algoritmo de `search.py` contra `avisos.json`). Lo único que no
funciona ahí es publicar un aviso nuevo y el panel de admin, porque esos
necesitan un servidor con estado compartido real (que todos los visitantes
vean el mismo cambio). Para esa parte, corre el servidor localmente (ver más
abajo) o despliega en Render.

Para regenerar la versión estática después de cambios: `python3 export_static.py`
(reescribe `docs/`, que Pages sirve automáticamente al hacer push).

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

http://localhost:8002/admin — usuario `admin`, contraseña `talca2026`
(o la que definas en la variable de entorno `ADMIN_PASSWORD`).

## Desplegar en Render (gratis, con tu cuenta de GitHub)

Este repo incluye `render.yaml`, así que el despliegue es automático:

1. Entra a [render.com](https://render.com) y elige **"Sign in with GitHub"** (misma cuenta, sin password nuevo).
2. **New → Blueprint** y selecciona este repositorio (`talcadatos`).
3. Render detecta `render.yaml` solo y genera una contraseña de admin aleatoria
   (variable `ADMIN_PASSWORD`) — la ves en el dashboard del servicio, pestaña *Environment*.
4. En unos minutos queda con un link público tipo `https://talcadatos.onrender.com`.

Nota: el plan free de Render "duerme" el servicio tras un rato sin visitas (la
primera carga después de eso tarda ~30s en despertar) y el disco es efímero,
así que la base de datos se reinicia con los datos de ejemplo si el servicio
se reinicia. Para persistencia real, ver la sección de arquitectura recomendada
del PRD (Postgres vía Supabase).

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

## Funcionalidades del PRD §17 (extras de valor) ya implementadas

- **Reportar aviso** — botón en el detalle, alimenta una cola de moderación separada
  (`/admin/reportes`).
- **Sinónimos editables** — `/admin/sinonimos`: agregar o quitar palabras por categoría sin
  tocar código, para mejorar el buscador con el tiempo.
- **Roles de admin** — `super_admin` (todo) y `moderador` (solo aprobar/rechazar avisos y ver
  reportes, como pide el PRD §7.5). Gestión de usuarios en `/admin/usuarios`.
- **Auditoría** — `/admin/auditoria` registra quién aprobó, rechazó, editó, cambió un plan o
  verificó un negocio, y cuándo.
- **Historial de pagos** — `/admin/pagos`, se registra cada vez que se activa un plan pagado.
- **Exportación CSV** — avisos, anunciantes y pagos, cada uno con su botón "Exportar CSV".
- **Alertas de demanda** — cuando una búsqueda no encuentra nada, se puede dejar un WhatsApp
  para avisar apenas exista un negocio de ese rubro; los leads quedan en `/admin/alertas`.
- **Favoritos** — botón ☆ en cada aviso, guardado en `localStorage` (sin cuenta ni backend);
  página `/favoritos`. Funciona igual en la versión de servidor y en la estática de GitHub Pages.
- **Mapa y código QR** — cada aviso tiene un link a Google Maps y un QR descargable/imprimible
  que apunta a su ficha.
- **Ayuda / FAQ** — página `/ayuda` con un acordeón nativo (`<details>`, sin JS).
- **Panel de autoservicio del anunciante** — al publicar, el negocio recibe un link
  `/mi-negocio/<token>` de solo lectura con sus propias estadísticas (vistas, contactos,
  conversión), sin necesitar usuario/contraseña.

## Qué queda fuera (y por qué)

- **Pasarela de pago real (Webpay/MercadoPago)**: requiere una cuenta de comercio y credenciales
  que no existen en este entorno. El PRD ya contempla activación manual como parte del MVP
  (Fase 1) y automatizarla como Fase 3 — la tabla `pago` y el flujo de planes ya están listos
  para conectarse a una pasarela real sin rediseñar nada.
- **Embeddings de IA reales**: necesitan una API key (OpenAI u otro proveedor). `search.py` ya
  está aislado para ese swap, ver más abajo.
- **Rate limiting real, hash de contraseña con más iteraciones (bcrypt/argon2)**: quedan
  pendientes para un despliegue de producción real; ver siguiente sección.

## Qué falta para producción

Ver PRD §15 (roadmap). Lo más relevante para pasar de este prototipo a producción:
subir fotos reales (hoy son íconos por categoría), pasar SQLite → Postgres + pgvector,
embeddings reales de IA, pasarela de pago automática (Webpay/MercadoPago), rate limiting
real (hoy no lo hay) y un hash de contraseña con más iteraciones (bcrypt/argon2) para el admin.
