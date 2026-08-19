function logEvento(tipo, avisoId, termino) {
  var payload = JSON.stringify({ tipo: tipo, aviso_id: avisoId || null, termino_busqueda: termino || null });
  if (navigator.sendBeacon) {
    navigator.sendBeacon("/api/evento", new Blob([payload], { type: "application/json" }));
  } else {
    fetch("/api/evento", { method: "POST", body: payload, keepalive: true });
  }
}

document.addEventListener("click", function (e) {
  var wa = e.target.closest("[data-wa-click]");
  if (wa) logEvento("click_whatsapp", wa.getAttribute("data-aviso-id"));

  var card = e.target.closest("[data-termino]");
  if (card) {
    var termino = card.getAttribute("data-termino");
    var avisoId = card.getAttribute("data-aviso-id");
    if (termino && (e.target.closest(".card-title") || e.target.closest(".card-photo"))) {
      logEvento("click_resultado_busqueda", avisoId, termino);
    }
  }
});

(function initSearch() {
  var form = document.getElementById("search-form");
  var input = document.getElementById("search-input");
  var results = document.getElementById("search-results");
  if (!form || !input || !results) return;

  var timer = null;

  function render(items, query) {
    if (!items.length) {
      results.innerHTML = '<div class="search-empty">Sin coincidencias todavía para "' + query + '". Prueba con otra palabra o <a href="/publicar">publica tu negocio</a> si nadie lo ofrece aún.</div>';
      results.hidden = false;
      return;
    }
    results.innerHTML = items.map(function (a) {
      var badge = a.destacado ? '<span class="search-badge">Destacado</span>' : "";
      return '<a class="search-item" href="/avisos/' + a.id + '" data-aviso-id="' + a.id + '" data-termino="' +
        query.replace(/"/g, "&quot;") + '">' +
        '<span class="search-item-icon">' + a.icono + '</span>' +
        '<span class="search-item-body"><strong>' + a.titulo + '</strong>' +
        '<span>' + a.negocio + ' · ' + a.comuna + '</span></span>' + badge + '</a>';
    }).join("");
    results.hidden = false;
  }

  input.addEventListener("input", function () {
    var q = input.value.trim();
    clearTimeout(timer);
    if (q.length < 2) {
      results.hidden = true;
      return;
    }
    timer = setTimeout(function () {
      fetch("/api/buscar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q: q }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) { render(data.resultados || [], q); });
    }, 220);
  });

  document.addEventListener("click", function (e) {
    if (!form.contains(e.target)) results.hidden = true;
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = input.value.trim();
    window.location.href = "/avisos?q=" + encodeURIComponent(q);
  });
})();

(function initAlertaForm() {
  var form = document.getElementById("alerta-form");
  if (!form) return;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var whatsapp = form.whatsapp.value.trim();
    fetch("/api/alerta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ termino: form.getAttribute("data-termino"), whatsapp: whatsapp }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        form.innerHTML = data.ok
          ? "¡Listo! Te avisamos por WhatsApp apenas haya un negocio de eso."
          : "No pudimos guardar tu WhatsApp, revisa el número e intenta de nuevo.";
      });
  });
})();

/* ---- favoritos (localStorage, sin backend) ---- */
(function initFavoritos() {
  var KEY = "talca_favoritos";

  function leer() {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; }
  }
  function guardar(datos) { localStorage.setItem(KEY, JSON.stringify(datos)); }

  function tarjetaHtml(d) {
    var badge = d.plan && d.plan !== "Gratis" ? '<span class="badge badge-gold">' + d.plan + "</span>" : "";
    var verificado = d.verificado ? '<span class="check">✔</span>' : "";
    return (
      '<article class="card" style="--card-accent:' + d.color + '">' +
      '<a class="card-photo" href="/avisos/' + d.id + '"><span class="card-icon">' + d.icono + "</span>" + badge + "</a>" +
      '<button class="fav-btn is-fav" type="button" data-fav-id="' + d.id + '" title="Quitar de favoritos">★</button>' +
      '<div class="card-body">' +
      '<a class="card-title" href="/avisos/' + d.id + '">' + d.titulo + "</a>" +
      '<div class="card-meta"><span>' + d.negocio + " " + verificado + "</span>" +
      '<span class="dot">·</span><span>' + d.comuna + "</span></div>" +
      '<div class="card-cat mono">' + d.icono + " " + d.categoria + "</div>" +
      "</div></article>"
    );
  }

  function actualizarBoton(btn) {
    var favs = leer();
    var esFav = !!favs[btn.getAttribute("data-fav-id")];
    btn.textContent = esFav ? "★" : "☆";
    btn.classList.toggle("is-fav", esFav);
  }

  document.querySelectorAll(".fav-btn[data-fav-id]").forEach(actualizarBoton);

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".fav-btn[data-fav-id]");
    if (!btn) return;
    e.preventDefault();
    var id = btn.getAttribute("data-fav-id");
    var favs = leer();
    if (favs[id]) {
      delete favs[id];
    } else {
      favs[id] = {
        id: id, titulo: btn.getAttribute("data-titulo") || "", negocio: btn.getAttribute("data-negocio") || "",
        comuna: btn.getAttribute("data-comuna") || "", categoria: btn.getAttribute("data-categoria") || "",
        icono: btn.getAttribute("data-icono") || "📌", color: btn.getAttribute("data-color") || "#9C82C2",
        verificado: btn.getAttribute("data-verificado") === "1", plan: btn.getAttribute("data-plan") || "Gratis",
      };
    }
    guardar(favs);
    document.querySelectorAll('.fav-btn[data-fav-id="' + id + '"]').forEach(actualizarBoton);
  });

  var mount = document.getElementById("favoritos-mount");
  if (mount) {
    var favs = leer();
    var items = Object.keys(favs).map(function (id) { return favs[id]; });
    mount.innerHTML = items.length
      ? '<div class="grid">' + items.map(tarjetaHtml).join("") + "</div>"
      : '<p class="fav-empty">Todavía no guardaste ningún aviso. Toca el ☆ en cualquier aviso para guardarlo aquí.</p>';
  }
})();
