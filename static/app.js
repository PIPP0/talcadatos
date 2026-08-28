document.addEventListener("click", function (e) {
  var arrow = e.target.closest(".carousel-arrow");
  if (!arrow) return;
  var track = arrow.parentElement.querySelector(".carousel-track");
  if (!track) return;
  var paso = Math.round(track.clientWidth * 0.85) * (arrow.classList.contains("carousel-prev") ? -1 : 1);
  track.scrollBy({ left: paso, behavior: "smooth" });
});

/* Reemplaza atributos onchange/onclick/onsubmit inline, bloqueados por la
   Content-Security-Policy (script-src 'self' no permite inline handlers). */
document.addEventListener("change", function (e) {
  if (e.target.matches("select[data-autosubmit]")) e.target.form.submit();
});

document.addEventListener("submit", function (e) {
  var form = e.target;
  var msg = form.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) {
    e.preventDefault();
    return;
  }
  if (!form.matches("[data-ajax-delete]")) return;
  e.preventDefault();
  var fila = form.closest("tr");
  var boton = form.querySelector("button");
  if (boton) boton.disabled = true;
  fetch(form.action, { method: "POST", headers: { "X-Requested-With": "fetch" } })
    .then(function (res) {
      if (res.ok) {
        if (fila) {
          fila.style.transition = "opacity .25s ease, transform .25s ease";
          fila.style.opacity = "0";
          fila.style.transform = "translateX(10px)";
          setTimeout(function () { fila.remove(); }, 250);
        }
        return;
      }
      return res.text().then(function (txt) { throw new Error(txt); });
    })
    .catch(function (err) {
      if (boton) boton.disabled = false;
      window.alert((err && err.message) || "No se pudo eliminar. Intenta de nuevo.");
    });
});

document.addEventListener("click", function (e) {
  var share = e.target.closest("[data-share-btn]");
  if (!share) return;
  navigator.clipboard.writeText(window.location.href);
  share.textContent = "¡Link copiado!";
});

function animarConteo(span) {
  var target = parseFloat(span.getAttribute("data-target"));
  if (!isFinite(target) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    span.textContent = target;
    return;
  }
  var duracion = 900;
  var inicio = null;
  function paso(ts) {
    if (inicio === null) inicio = ts;
    var p = Math.min(1, (ts - inicio) / duracion);
    var facil = 1 - Math.pow(1 - p, 3);
    span.textContent = Math.round(target * facil).toLocaleString("es-CL");
    if (p < 1) requestAnimationFrame(paso);
  }
  requestAnimationFrame(paso);
}

/* Tooltip interactivo sobre los gráficos SVG del dashboard: al mover el
   mouse busca el punto más cercano y muestra fecha/valores exactos. */
function initChartHover() {
  document.querySelectorAll(".chart-line[data-serie]").forEach(function (wrap) {
    var serie;
    try {
      serie = JSON.parse(wrap.getAttribute("data-serie"));
    } catch (e) {
      return;
    }
    if (!serie || serie.length < 2) return;
    var svg = wrap.querySelector("svg");
    var hoverLine = wrap.querySelector(".chart-hover-line");
    var tooltip = wrap.querySelector(".chart-tooltip");
    var ptsV = wrap.querySelectorAll(".chart-pt-vistas");
    var ptsC = wrap.querySelectorAll(".chart-pt-contactos");
    var xs = Array.prototype.map.call(ptsV, function (c) { return parseFloat(c.getAttribute("cx")); });

    function indiceCercano(vbX) {
      var mejor = 0, dist = Infinity;
      xs.forEach(function (x, i) {
        var d = Math.abs(x - vbX);
        if (d < dist) { dist = d; mejor = i; }
      });
      return mejor;
    }

    function mover(e) {
      var rect = svg.getBoundingClientRect();
      var vb = svg.viewBox.baseVal;
      var relX = (e.clientX - rect.left) / rect.width;
      var vbX = vb.x + relX * vb.width;
      var i = indiceCercano(vbX);

      hoverLine.setAttribute("x1", xs[i]);
      hoverLine.setAttribute("x2", xs[i]);
      hoverLine.classList.add("is-active");
      ptsV.forEach(function (c, j) { c.classList.toggle("is-active", j === i); });
      ptsC.forEach(function (c, j) { c.classList.toggle("is-active", j === i); });

      var f = serie[i];
      tooltip.innerHTML = "<strong>" + f.fecha.slice(5) + "</strong><br>" +
        "<span class=\"tt-v\">" + f.vistas + " vistas</span><br>" +
        "<span class=\"tt-c\">" + f.contactos + " contactos</span>";
      var pxX = (xs[i] - vb.x) / vb.width * rect.width;
      var clamped = Math.min(Math.max(pxX, 46), rect.width - 46);
      tooltip.style.left = clamped + "px";
      tooltip.classList.add("is-active");
    }

    function salir() {
      hoverLine.classList.remove("is-active");
      tooltip.classList.remove("is-active");
      ptsV.forEach(function (c) { c.classList.remove("is-active"); });
      ptsC.forEach(function (c) { c.classList.remove("is-active"); });
    }

    svg.addEventListener("mousemove", mover);
    svg.addEventListener("mouseleave", salir);
    svg.addEventListener("touchmove", function (e) {
      if (e.touches[0]) mover(e.touches[0]);
    }, { passive: true });
  });
}

initChartHover();

function initReveals() {
  var blocks = document.querySelectorAll("[data-reveal]");
  if (!blocks.length) return;
  if (!window.IntersectionObserver || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    blocks.forEach(function (block) { block.classList.add("is-visible"); });
    return;
  }
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-visible");
      entry.target.querySelectorAll(".count-up").forEach(animarConteo);
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.12 });
  blocks.forEach(function (block) {
    block.classList.add("reveal");
    observer.observe(block);
  });
}

initReveals();

/* El editor usa la misma página pública dentro de un iframe: este selector
   cambia sólo la vista previa, sin perder los cambios aún no guardados. */
(function initEditorPreview() {
  var selector = document.getElementById("editor-page-select");
  var preview = document.getElementById("editor-preview");
  var pageName = document.getElementById("editor-page-name");
  if (!selector || !preview) return;
  selector.addEventListener("change", function () {
    var ruta = selector.value || "/";
    preview.src = ruta;
    if (pageName) pageName.textContent = ruta;
  });
})();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function () {
      // La app sigue funcionando normalmente si el navegador bloquea PWA/offline.
    });
  });
}

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
      results.hidden = false;
      results.innerHTML = '<div class="search-loading"><span></span>Buscando en Talca…</div>';
      fetch("/api/buscar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q: q }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) { render(data.resultados || [], q); })
        .catch(function () {
          results.innerHTML = '<div class="search-empty">No pudimos completar la búsqueda. Intenta nuevamente.</div>';
        });
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
    var agregando = !favs[id];
    if (favs[id]) {
      delete favs[id];
    } else {
      favs[id] = {
        id: id, titulo: btn.getAttribute("data-titulo") || "", negocio: btn.getAttribute("data-negocio") || "",
        comuna: btn.getAttribute("data-comuna") || "", categoria: btn.getAttribute("data-categoria") || "",
        icono: btn.getAttribute("data-icono") || "📌", color: btn.getAttribute("data-color") || "#B67818",
        verificado: btn.getAttribute("data-verificado") === "1", plan: btn.getAttribute("data-plan") || "Gratis",
      };
    }
    guardar(favs);
    document.querySelectorAll('.fav-btn[data-fav-id="' + id + '"]').forEach(function (boton) {
      actualizarBoton(boton);
      if (agregando) {
        boton.classList.remove("fav-pop");
        void boton.offsetWidth;
        boton.classList.add("fav-pop");
      }
    });
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
