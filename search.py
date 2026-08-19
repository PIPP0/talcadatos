"""
Motor de busqueda "por necesidad" de Talcadatos (PRD seccion 9).

Esta es la implementacion MVP: sin llave de API disponible en este entorno,
el matching semantico se resuelve con un diccionario de sinonimos por rubro
(tabla `sinonimo`, editable desde el admin en el PRD original) mas un
puntaje por coincidencia de texto. Es exactamente el "respaldo deterministico"
que el PRD describe en 9.2, adelantado para que la busqueda funcione de
verdad sin depender de una API externa.

Para pasar a la version de produccion del PRD (embeddings + pgvector,
seccion 9.1): reemplazar el cuerpo de `buscar_avisos` por (1) generar el
embedding de `query` con el modelo elegido, (2) comparar por similitud
coseno contra `aviso.embedding` en Postgres, y (3) aplicar el mismo boost
de destacados que ya esta aqui. El resto del sitio (rutas, eventos,
plantillas) no cambia.
"""
import re
import unicodedata


def _normalizar(texto):
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto


def _stem(palabra):
    """Recorte simple de plurales en español (pastel/pasteles, vidrio/vidrios)."""
    if len(palabra) > 5 and palabra.endswith("es"):
        return palabra[:-2]
    if len(palabra) > 4 and palabra.endswith("s"):
        return palabra[:-1]
    return palabra


def _tokens(texto):
    return [_stem(t) for t in re.split(r"[^a-z0-9]+", _normalizar(texto)) if len(t) > 2]


def buscar_avisos(conn, query, limite=20):
    query_norm = _normalizar(query)
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return []

    avisos = conn.execute(
        """
        SELECT aviso.*, negocio.nombre AS negocio_nombre, negocio.whatsapp,
               negocio.verificado, categoria.nombre AS categoria_nombre,
               categoria.slug AS categoria_slug, categoria.icono,
               plan.prioridad AS plan_prioridad, plan.nombre AS plan_nombre
        FROM aviso
        JOIN negocio ON negocio.id = aviso.negocio_id
        JOIN categoria ON categoria.id = aviso.categoria_id
        JOIN plan ON plan.id = negocio.plan_id
        WHERE aviso.estado = 'activo'
        """
    ).fetchall()

    sinonimos_por_categoria = {}
    for row in conn.execute("SELECT categoria_id, palabra FROM sinonimo").fetchall():
        sinonimos_por_categoria.setdefault(row["categoria_id"], []).append(
            _normalizar(row["palabra"])
        )

    resultados = []
    for aviso in avisos:
        score = 0.0
        titulo_norm = _normalizar(aviso["titulo"])
        desc_norm = _normalizar(aviso["descripcion"])
        cat_norm = _normalizar(aviso["categoria_nombre"])

        if query_norm in titulo_norm:
            score += 4
        if query_norm in cat_norm:
            score += 3
        if query_norm in desc_norm:
            score += 1.5

        titulo_tokens = set(_tokens(aviso["titulo"]))
        desc_tokens = set(_tokens(aviso["descripcion"]))
        score += 2.5 * len(query_tokens & titulo_tokens)
        score += 1.0 * len(query_tokens & desc_tokens)

        for palabra in sinonimos_por_categoria.get(aviso["categoria_id"], []):
            if palabra in query_norm or query_norm in palabra:
                score += 3.5
                break
            palabra_tokens = set(_tokens(palabra))
            if query_tokens & palabra_tokens:
                score += 2.0
                break

        if score <= 0:
            continue

        score += aviso["plan_prioridad"] * 0.6

        resultados.append((score, aviso))

    resultados.sort(key=lambda par: par[0], reverse=True)
    return [aviso for _, aviso in resultados[:limite]]
