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
