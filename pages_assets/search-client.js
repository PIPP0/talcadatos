/*
 * Talcadatos — version cliente del buscador y los filtros, solo para el
 * export estatico de GitHub Pages (docs/). Es un port a JS de search.py:
 * mismo algoritmo (sinonimos por rubro + puntaje de texto), pero corriendo
 * en el navegador contra avisos.json/sinonimos.json en vez de contra
 * PostgreSQL/SQLite, porque GitHub Pages no puede correr el backend Python.
 *
 * __PAGES_PREFIX__ lo reemplaza export_static.py por el subpath real del
 * sitio publicado (ej. "/talcadatos").
 */
(function () {
  "use strict";
  var PREFIX = "__PAGES_PREFIX__";
  var DATA_BASE = PREFIX + "/static";
  var dataPromise = null;

  function cargarDatos() {
    if (!dataPromise) {
      dataPromise = Promise.all([
        fetch(DATA_BASE + "/avisos.json").then(function (r) { return r.json(); }),
        fetch(DATA_BASE + "/sinonimos.json").then(function (r) { return r.json(); }),
      ]).then(function (res) {
        return { avisos: res[0], sinonimos: res[1] };
      });
    }
    return dataPromise;
  }

  function normalizar(s) {
    return String(s || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  }

  function stem(palabra) {
    if (palabra.length > 5 && palabra.slice(-2) === "es") return palabra.slice(0, -2);
    if (palabra.length > 4 && palabra.slice(-1) === "s") return palabra.slice(0, -1);
    return palabra;
  }

  function tokens(texto) {
    return normalizar(texto).split(/[^a-z0-9]+/).filter(function (t) { return t.length > 2; }).map(stem);
  }

  function interseccion(a, b) {
    var n = 0;
    a.forEach(function (t) { if (b.has(t)) n++; });
    return n;
  }

  function buscarAvisos(query, avisos, sinonimosPorCategoria, limite) {
    var qNorm = normalizar(query);
    var qTokens = new Set(tokens(query));
    if (qTokens.size === 0) return [];

    var resultados = [];
    avisos.forEach(function (a) {
      var score = 0;
      var tNorm = normalizar(a.titulo), cNorm = normalizar(a.categoria_nombre), dNorm = normalizar(a.descripcion);
      if (tNorm.indexOf(qNorm) !== -1) score += 4;
      if (cNorm.indexOf(qNorm) !== -1) score += 3;
      if (dNorm.indexOf(qNorm) !== -1) score += 1.5;

      var tTokens = new Set(tokens(a.titulo)), dTokens = new Set(tokens(a.descripcion));
      score += 2.5 * interseccion(qTokens, tTokens);
      score += 1.0 * interseccion(qTokens, dTokens);

      var sinonimos = sinonimosPorCategoria[a.categoria_slug] || [];
      for (var i = 0; i < sinonimos.length; i++) {
        var pNorm = normalizar(sinonimos[i]);
        if (qNorm.indexOf(pNorm) !== -1 || pNorm.indexOf(qNorm) !== -1) { score += 3.5; break; }
        var pTokens = tokens(sinonimos[i]);
        if (pTokens.some(function (t) { return qTokens.has(t); })) { score += 2.0; break; }
      }

      if (score <= 0) return;
      score += (a.plan_prioridad || 0) * 0.6;
      resultados.push([score, a]);
    });

    resultados.sort(function (x, y) { return y[0] - x[0]; });
    return resultados.slice(0, limite).map(function (r) { return r[1]; });
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function planBadgeHtml(planNombre) {
    if (planNombre === "Gratis") return "";
    var kind = planNombre === "Premium" ? "brick" : "gold";
    return '<span class="badge badge-' + kind + '">' + esc(planNombre) + "</span>";
  }

  function whatsappUrl(whatsapp, negocioNombre, titulo) {
    var numero = String(whatsapp).replace(/\D/g, "");
    var mensaje = 'Hola ' + negocioNombre + ', vi tu aviso "' + titulo + '" en Talcadatos y quiero consultar por...';
    return "https://wa.me/" + numero + "?text=" + encodeURIComponent(mensaje);
  }

  function avisoCardHtml(a, termino) {
    var badge = a.plan_nombre !== "Gratis" ? planBadgeHtml(a.plan_nombre) : "";
    var verificado = a.verificado ? '<span class="check" title="Negocio verificado">✔</span>' : "";
    var wa = whatsappUrl(a.whatsapp, a.negocio_nombre, a.titulo);
    var clickAttr = termino ? ' data-termino="' + esc(termino) + '"' : "";
    var href = PREFIX + "/avisos/" + a.id + "/";
    return (
      '<article class="card" style="--card-accent:' + esc(a.color) + '"' + clickAttr + ' data-aviso-id="' + a.id + '">' +
      '<a class="card-photo" href="' + href + '"><span class="card-icon">' + a.icono + "</span>" + badge + "</a>" +
      '<div class="card-body">' +
      '<a class="card-title" href="' + href + '">' + esc(a.titulo) + "</a>" +
      '<div class="card-meta"><span>' + esc(a.negocio_nombre) + " " + verificado + "</span>" +
      '<span class="dot">·</span><span>' + esc(a.comuna) + "</span></div>" +
      '<div class="card-cat mono">' + a.icono + " " + esc(a.categoria_nombre) + "</div>" +
      '<a class="btn btn-whatsapp btn-block" href="' + wa + '" target="_blank" rel="noopener">Contactar por WhatsApp</a>' +
      "</div></article>"
    );
  }

  function cardsGridHtml(avisos, termino, vacioMsg) {
    if (!avisos.length) {
      return '<p class="empty-state">' + esc(vacioMsg) + "</p>";
    }
    return '<div class="grid">' + avisos.map(function (a) { return avisoCardHtml(a, termino); }).join("") + "</div>";
  }

  // ---- Buscador en vivo de la portada ----
  function initHomeSearch() {
    var form = document.getElementById("search-form");
    var input = document.getElementById("search-input");
    var results = document.getElementById("search-results");
    if (!form || !input || !results) return;

    var timer = null;

    function render(items, query) {
      if (!items.length) {
        results.innerHTML = '<div class="search-empty">Sin coincidencias todavía para "' + esc(query) +
          '". Prueba con otra palabra o <a href="' + PREFIX + '/publicar/">publica tu negocio</a> si nadie lo ofrece aún.</div>';
        results.hidden = false;
        return;
      }
      results.innerHTML = items.map(function (a) {
        var badge = a.plan_nombre !== "Gratis" ? '<span class="search-badge">Destacado</span>' : "";
        var href = PREFIX + "/avisos/" + a.id + "/";
        return '<a class="search-item" href="' + href + '"><span class="search-item-icon">' + a.icono + "</span>" +
          '<span class="search-item-body"><strong>' + esc(a.titulo) + "</strong><span>" +
          esc(a.negocio_nombre) + " · " + esc(a.comuna) + "</span></span>" + badge + "</a>";
      }).join("");
      results.hidden = false;
    }

    input.addEventListener("input", function () {
      var q = input.value.trim();
      clearTimeout(timer);
      if (q.length < 2) { results.hidden = true; return; }
      timer = setTimeout(function () {
        cargarDatos().then(function (data) {
          render(buscarAvisos(q, data.avisos, data.sinonimos, 6), q);
        });
      }, 200);
    });

    document.addEventListener("click", function (e) {
      if (!form.contains(e.target)) results.hidden = true;
    });

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var q = input.value.trim();
      window.location.href = PREFIX + "/avisos/?q=" + encodeURIComponent(q);
    });
  }

  // ---- Filtros y resultados de /avisos ----
  function initListado() {
    var mount = document.getElementById("listado-resultados");
    if (!mount) return;

    var params = new URLSearchParams(window.location.search);
    var q = (params.get("q") || "").trim();
    var categoria = params.get("categoria") || "";
    var comuna = params.get("comuna") || "";
    var orden = params.get("orden") || "relevancia";

    var form = document.getElementById("listado-filtros");
    if (form) {
      if (form.categoria) form.categoria.value = categoria;
      if (form.comuna) form.comuna.value = comuna;
      if (form.orden) form.orden.value = orden;
    }

    cargarDatos().then(function (data) {
      var titulo = document.getElementById("listado-titulo");
      var lista;
      if (q) {
        lista = buscarAvisos(q, data.avisos, data.sinonimos, 40);
        if (titulo) titulo.textContent = 'Resultados para "' + q + '"';
      } else {
        lista = data.avisos.filter(function (a) {
          return (!categoria || a.categoria_slug === categoria) && (!comuna || a.comuna === comuna);
        });
        if (orden === "recientes") {
          lista = lista.slice().sort(function (a, b) { return (b.publicado_en || "").localeCompare(a.publicado_en || ""); });
        } else if (orden === "populares") {
          lista = lista.slice().sort(function (a, b) { return (b.contactos_total || 0) - (a.contactos_total || 0); });
        } else {
          lista = lista.slice().sort(function (a, b) {
            return (b.plan_prioridad - a.plan_prioridad) || (b.publicado_en || "").localeCompare(a.publicado_en || "");
          });
        }
        if (titulo) titulo.textContent = "Explorar avisos";
      }
      mount.innerHTML = cardsGridHtml(lista, q || null, "No hay avisos que coincidan con tu búsqueda.");
    });
  }

  function logEvento() {
    // No hay backend en GitHub Pages para registrar vistas/contactos: no-op.
  }

  // El formulario de publicar necesita guardar en un servidor compartido
  // (que todos los visitantes vean el aviso nuevo) -- eso no existe en
  // GitHub Pages, asi que se avisa en vez de dejar que el POST falle solo.
  function initPublicarForm() {
    var form = document.querySelector('form[action$="/publicar"]');
    if (!form) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      alert(
        "Esta vista estática no puede guardar avisos nuevos (necesita un servidor real).\n\n" +
        "Corre el sitio con el servidor Python incluido en el repo para probar el flujo completo de publicación."
      );
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initHomeSearch();
    initListado();
    initPublicarForm();
  });

  window.logEvento = logEvento;
})();
