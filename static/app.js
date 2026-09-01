/* El logo y "Inicio" siempre llevan arriba del todo, aunque ya estés en "/"
   (si no, un clic ahí no hace nada porque la URL no cambia). */
document.addEventListener("click", function (e) {
  var link = e.target.closest('a[href="/"]');
  if (!link) return;
  if (location.pathname === "/" && !location.search && !location.hash) {
    e.preventDefault();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
});

/* Botón X sobre la foto actual (en editar aviso / campos de imagen del admin):
   la oculta y marca el checkbox oculto "quitar_foto" para que el servidor la borre. */
document.addEventListener("click", function (e) {
  var btn = e.target.closest("[data-quitar-foto]");
  if (!btn) return;
  var campo = btn.closest("label") || btn.closest(".form");
  if (!campo) return;
  var flag = campo.querySelector("[data-quitar-foto-flag]");
  if (flag) flag.checked = true;
  var wrap = btn.closest(".campo-imagen-preview-wrap");
  if (wrap) wrap.remove();
});

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
  if (e.target.matches("[data-auto-submit]")) e.target.form.requestSubmit();
});

/* "error" no burbujea, hay que escucharlo en fase de captura para delegarlo. */
document.addEventListener("error", function (e) {
  if (e.target.matches && e.target.matches(".card-carousel-slide")) {
    e.target.style.visibility = "hidden";
  }
}, true);

/* Vista previa instantanea al elegir una foto nueva en un campo de imagen,
   antes solo se veia la foto vieja hasta guardar. */
document.addEventListener("change", function (e) {
  if (!e.target.matches(".campo-imagen input[type=file]")) return;
  var input = e.target;
  var file = input.files && input.files[0];
  if (!file) return;
  var campo = input.closest(".campo-imagen");
  var img = campo.querySelector(".campo-imagen-preview");
  if (!img) {
    img = document.createElement("img");
    img.className = "campo-imagen-preview";
    img.alt = "";
    campo.insertBefore(img, input);
  }
  img.src = URL.createObjectURL(file);
});

/* ---- modal de confirmacion / aviso, reemplaza confirm() nativo y el
   banner .flash silencioso por un popup que la persona no se pierde ---- */
var appModalEl = null;
function getAppModal() {
  if (appModalEl) return appModalEl;
  var back = document.createElement("div");
  back.className = "app-modal-backdrop";
  back.innerHTML =
    '<div class="app-modal" role="alertdialog" aria-modal="true">' +
    '<button class="app-modal-close" type="button" aria-label="Cerrar">×</button>' +
    '<div class="app-modal-icon"></div>' +
    '<p class="app-modal-text"></p>' +
    '<div class="app-modal-actions"></div>' +
    "</div>";
  document.body.appendChild(back);
  appModalEl = back;
  return back;
}

function mostrarAviso(mensaje, tipo) {
  var modal = getAppModal();
  var icono = modal.querySelector(".app-modal-icon");
  icono.className = "app-modal-icon " + (tipo || "ok");
  icono.textContent = tipo === "warn" ? "!" : "✓";
  modal.querySelector(".app-modal-text").textContent = mensaje;
  var acciones = modal.querySelector(".app-modal-actions");
  acciones.className = "app-modal-actions single";
  acciones.innerHTML = "";
  modal.classList.add("is-open");
  function cerrar() { modal.classList.remove("is-open"); clearTimeout(modal._timer); }
  modal.onclick = function (e) { if (e.target === modal) cerrar(); };
  modal.querySelector(".app-modal-close").onclick = cerrar;
  clearTimeout(modal._timer);
  modal._timer = setTimeout(cerrar, 3200);
}

function pedirConfirmacion(mensaje) {
  return new Promise(function (resolve) {
    var modal = getAppModal();
    clearTimeout(modal._timer);
    var icono = modal.querySelector(".app-modal-icon");
    icono.className = "app-modal-icon warn";
    icono.textContent = "!";
    modal.querySelector(".app-modal-text").textContent = mensaje;
    var acciones = modal.querySelector(".app-modal-actions");
    acciones.className = "app-modal-actions";
    acciones.innerHTML =
      '<button class="btn btn-ghost" type="button" data-r="0">Cancelar</button>' +
      '<button class="btn btn-bad" type="button" data-r="1">Eliminar</button>';
    function resolver(valor) {
      modal.classList.remove("is-open");
      acciones.removeEventListener("click", onClick);
      modal.onclick = null;
      resolve(valor);
    }
    function onClick(e) {
      var btn = e.target.closest("button[data-r]");
      if (!btn) return;
      resolver(btn.getAttribute("data-r") === "1");
    }
    acciones.addEventListener("click", onClick);
    modal.onclick = function (e) { if (e.target === modal) resolver(false); };
    modal.querySelector(".app-modal-close").onclick = function () { resolver(false); };
    modal.classList.add("is-open");
  });
}

function ejecutarAjaxDelete(form) {
  var fila = form.closest("tr");
  var boton = form.querySelector("button");
  if (boton) boton.disabled = true;
  fetch(form.action, { method: "POST", headers: { "X-Requested-With": "fetch" } })
    .then(function (res) {
      if (res.ok) {
        mostrarAviso("Eliminado correctamente.", "ok");
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
      mostrarAviso((err && err.message) || "No se pudo eliminar. Intenta de nuevo.", "warn");
    });
}

function ejecutarAjaxForm(form) {
  var boton = form.querySelector('button[type=submit]');
  var textoOriginal = boton ? boton.textContent : "";
  if (boton) {
    boton.disabled = true;
    boton.textContent = "Guardando…";
  }
  var datos = new FormData(form);
  fetch(form.action, { method: form.method || "POST", body: datos, headers: { "X-Requested-With": "fetch" } })
    .then(function (res) {
      if (res.ok) {
        mostrarAviso("Cambios guardados.", "ok");
        if (form.hasAttribute("data-ajax-reload")) {
          setTimeout(function () { window.location.reload(); }, 400);
          return;
        }
        var destino = form.getAttribute("data-ajax-redirect");
        if (destino) setTimeout(function () { window.location.href = destino; }, 700);
        else if (boton) { boton.disabled = false; boton.textContent = textoOriginal; }
        return;
      }
      return res.text().then(function (txt) { throw new Error(txt); });
    })
    .catch(function (err) {
      if (boton) {
        boton.disabled = false;
        boton.textContent = textoOriginal;
      }
      mostrarAviso((err && err.message) || "No se pudo guardar. Intenta de nuevo.", "warn");
    });
}

document.addEventListener("submit", function (e) {
  var form = e.target;
  var msg = form.getAttribute("data-confirm");
  if (msg) {
    e.preventDefault();
    pedirConfirmacion(msg).then(function (ok) {
      if (!ok) return;
      if (form.matches("[data-ajax-delete]")) {
        ejecutarAjaxDelete(form);
      } else {
        form.submit();
      }
    });
    return;
  }
  if (form.matches("[data-ajax-form]")) {
    e.preventDefault();
    ejecutarAjaxForm(form);
    return;
  }
  if (!form.matches("[data-ajax-delete]")) return;
  e.preventDefault();
  ejecutarAjaxDelete(form);
});

function iniciarCarousels() {
  document.querySelectorAll("[data-carousel]").forEach(function (car) {
    if (car.dataset.carouselInit) return;
    car.dataset.carouselInit = "1";
    var tarjeta = car.closest(".card, .detalle-photo");
    if (!tarjeta) return;
    var track = car.querySelector(".card-carousel-track");
    var slides = car.querySelectorAll(".card-carousel-slide");
    var dots = car.querySelectorAll(".card-carousel-dot");
    var prev = tarjeta.querySelector("[data-carousel-prev]");
    var next = tarjeta.querySelector("[data-carousel-next]");
    var n = slides.length;
    if (n < 2) return;
    var i = 0;
    var timer = null;
    function ir(idx) {
      i = (idx + n) % n;
      track.style.transform = "translateX(-" + i * 100 + "%)";
      dots.forEach(function (d, di) { d.classList.toggle("is-active", di === i); });
    }
    function reiniciarAuto() {
      if (timer) clearInterval(timer);
      timer = setInterval(function () { ir(i + 1); }, 3500);
    }
    if (prev) prev.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      ir(i - 1);
      reiniciarAuto();
    });
    if (next) next.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      ir(i + 1);
      reiniciarAuto();
    });
    tarjeta.addEventListener("mouseenter", function () { if (timer) clearInterval(timer); });
    tarjeta.addEventListener("mouseleave", reiniciarAuto);
    reiniciarAuto();
  });
}

document.addEventListener("DOMContentLoaded", function () {
  iniciarCarousels();
  var flash = document.querySelector(".flash");
  var texto = flash ? flash.textContent.trim() : "";
  if (texto) mostrarAviso(texto, "ok");
});

document.addEventListener("click", function (e) {
  var share = e.target.closest("[data-share-btn]");
  if (!share) return;
  navigator.clipboard.writeText(window.location.href);
  share.textContent = "¡Link copiado!";
});

document.addEventListener("change", function (e) {
  if (!e.target.matches("[data-horario-preset]")) return;
  var select = e.target;
  if (!select.value) return;
  var label = select.closest("label");
  var input = label && label.querySelector('input[name="horario"]');
  if (!input) return;
  input.value = select.value;
  input.focus();
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

  function escHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function tarjetaHtml(d) {
    var badge = d.plan && d.plan !== "Gratis" ? '<span class="badge badge-gold">' + escHtml(d.plan) + "</span>" : "";
    var verificado = d.verificado ? '<span class="check">✔</span>' : "";
    var fotos = d.foto_url ? [d.foto_url].concat(d.fotos_extra || []) : [];
    var chevrones = "";
    var foto;
    if (fotos.length >= 2) {
      var slides = fotos.map(function (u) {
        return '<img src="' + escHtml(u) + '" alt="" loading="eager" onerror="this.style.visibility=\'hidden\'" class="card-carousel-slide">';
      }).join("");
      var dots = fotos.map(function (u, i) {
        return '<span class="card-carousel-dot' + (i === 0 ? " is-active" : "") + '"></span>';
      }).join("");
      foto = '<div class="card-carousel" data-carousel><div class="card-carousel-track">' + slides +
        '</div><div class="card-carousel-dots">' + dots + "</div></div>";
      chevrones =
        '<button type="button" class="card-carousel-nav card-carousel-prev" data-carousel-prev aria-label="Foto anterior">‹</button>' +
        '<button type="button" class="card-carousel-nav card-carousel-next" data-carousel-next aria-label="Foto siguiente">›</button>';
    } else if (d.foto_url) {
      foto = '<img src="' + escHtml(d.foto_url) + '" alt="">';
    } else {
      foto = '<span class="icon-tile"><span class="card-icon">' + d.icono + "</span></span>";
    }
    return (
      '<article class="card" style="--card-accent:' + escHtml(d.color) + '">' +
      '<a class="card-photo' + (d.foto_url ? " has-foto" : "") + '" href="/avisos/' + d.id + '">' + foto + badge + "</a>" +
      chevrones +
      '<button class="fav-btn is-fav" type="button" data-fav-id="' + d.id + '" title="Quitar de favoritos">★</button>' +
      '<div class="card-body">' +
      '<a class="card-title" href="/avisos/' + d.id + '">' + escHtml(d.titulo) + "</a>" +
      '<div class="card-meta"><span>' + escHtml(d.negocio) + " " + verificado + "</span>" +
      '<span class="dot">·</span><span>' + escHtml(d.comuna) + "</span></div>" +
      '<div class="card-cat mono">' + d.icono + " " + escHtml(d.categoria) + "</div>" +
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
      favs[id] = true;
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
    var ids = Object.keys(leer());
    var vacioHtml = '<p class="fav-empty">Todavía no guardaste ningún aviso. Toca el ☆ en cualquier aviso para guardarlo aquí.</p>';
    if (!ids.length) {
      mount.innerHTML = vacioHtml;
    } else {
      mount.innerHTML = '<p class="fav-empty">Cargando tus favoritos…</p>';
      fetch("/api/favoritos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: ids }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var items = data.resultados || [];
          var vigentes = {};
          items.forEach(function (d) { vigentes[d.id] = true; });
          guardar(vigentes);
          mount.innerHTML = items.length
            ? '<div class="grid">' + items.map(tarjetaHtml).join("") + "</div>"
            : vacioHtml;
          iniciarCarousels();
        })
        .catch(function () {
          mount.innerHTML = '<p class="fav-empty">No se pudieron cargar tus favoritos. Intenta de nuevo más tarde.</p>';
        });
    }
  }
})();

/* ---- admin: orden de avisos por arrastrar y soltar ---- */
(function initOrdenLista() {
  var lista = document.getElementById("orden-lista");
  if (!lista) return;
  var guardarUrl = lista.getAttribute("data-orden-guardar-url");
  var filtroChk = document.getElementById("orden-solo-destacados");

  if (filtroChk) {
    filtroChk.addEventListener("change", function () {
      lista.querySelectorAll(".orden-fila").forEach(function (fila) {
        var esDestacado = fila.getAttribute("data-orden-destacado") === "1";
        fila.classList.toggle("orden-oculta", filtroChk.checked && !esDestacado);
      });
    });
  }

  function guardarOrden() {
    var ids = Array.from(lista.querySelectorAll(".orden-fila")).map(function (f) {
      return f.getAttribute("data-orden-id");
    });
    fetch(guardarUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
      body: JSON.stringify({ ids: ids }),
    })
      .then(function (r) { mostrarAviso(r.ok ? "Orden guardado." : "No se pudo guardar el orden.", r.ok ? "ok" : "warn"); })
      .catch(function () { mostrarAviso("No se pudo guardar el orden.", "warn"); });
  }

  var arrastrando = null;
  var puntoY = 0;

  lista.addEventListener("pointerdown", function (e) {
    var handle = e.target.closest(".orden-handle");
    if (!handle) return;
    var fila = handle.closest(".orden-fila");
    if (!fila) return;
    e.preventDefault();
    arrastrando = fila;
    puntoY = e.clientY;
    fila.classList.add("orden-arrastrando");
  });

  document.addEventListener("pointermove", function (e) {
    if (!arrastrando) return;
    var delta = e.clientY - puntoY;
    arrastrando.style.transform = "translateY(" + delta + "px)";

    var filas = Array.from(lista.querySelectorAll(".orden-fila:not(.orden-oculta)"));
    var siguiente = null;
    for (var i = 0; i < filas.length; i++) {
      if (filas[i] === arrastrando) continue;
      var box = filas[i].getBoundingClientRect();
      if (e.clientY < box.top + box.height / 2) { siguiente = filas[i]; break; }
    }
    var actualSiguiente = arrastrando.nextElementSibling;
    var necesitaMover = siguiente ? actualSiguiente !== siguiente : lista.lastElementChild !== arrastrando;
    if (necesitaMover) {
      if (siguiente) lista.insertBefore(arrastrando, siguiente);
      else lista.appendChild(arrastrando);
      puntoY = e.clientY;
      arrastrando.style.transform = "translateY(0px)";
    }
  });

  function soltar() {
    if (!arrastrando) return;
    arrastrando.classList.remove("orden-arrastrando");
    arrastrando.style.transform = "";
    arrastrando = null;
    guardarOrden();
  }

  document.addEventListener("pointerup", soltar);
  document.addEventListener("pointercancel", soltar);
})();

/* ---- encuesta: modal con estrellas + comentario, reutilizado en dos
   momentos (tras escribir por WhatsApp, y al terminar de publicar un
   negocio). No es obligatoria: se puede cerrar o enviar vacía. ---- */
(function initEncuesta() {
  var KEY = "talca_encuesta_activa";
  var DIAS_ESPERA = 30;
  var overlayEl = null;

  function yaRespondida() {
    try {
      var v = localStorage.getItem(KEY);
      if (!v) return false;
      return Date.now() - Number(v) < DIAS_ESPERA * 24 * 60 * 60 * 1000;
    } catch (e) { return false; }
  }
  function marcarMostrada() {
    try { localStorage.setItem(KEY, String(Date.now())); } catch (e) {}
  }

  function getOverlay() {
    if (overlayEl) return overlayEl;
    var back = document.createElement("div");
    back.className = "app-modal-backdrop";
    back.innerHTML =
      '<div class="app-modal encuesta-activa-modal" role="dialog" aria-modal="true">' +
      '<button class="app-modal-close" type="button" aria-label="Cerrar">×</button>' +
      '<p class="app-modal-text"></p>' +
      '<div class="encuesta-estrellas" role="radiogroup" aria-label="Calificación de 1 a 5 estrellas">' +
      [1, 2, 3, 4, 5].map(function (n) {
        return '<button type="button" data-estrella="' + n + '" aria-label="' + n + ' estrellas">★</button>';
      }).join("") +
      "</div>" +
      '<textarea class="encuesta-comentario" rows="2" maxlength="500" placeholder="Cuéntanos más (opcional)"></textarea>' +
      '<div class="app-modal-actions single"><button class="btn btn-primary" type="button" data-encuesta-enviar>Enviar</button></div>' +
      "</div>";
    document.body.appendChild(back);
    overlayEl = back;
    return back;
  }

  function preguntar(tipo, avisoId, pregunta) {
    var overlay = getOverlay();
    overlay.querySelector(".app-modal-text").textContent = pregunta;
    var estrellas = overlay.querySelectorAll("[data-estrella]");
    var textarea = overlay.querySelector(".encuesta-comentario");
    var calificacion = null;
    textarea.value = "";
    estrellas.forEach(function (b) { b.classList.remove("is-activa"); });

    function pintar(n) {
      estrellas.forEach(function (b) {
        b.classList.toggle("is-activa", Number(b.getAttribute("data-estrella")) <= n);
      });
    }
    function onEstrellaClick(e) {
      var b = e.target.closest("[data-estrella]");
      if (!b) return;
      calificacion = Number(b.getAttribute("data-estrella"));
      pintar(calificacion);
    }
    function cerrar() {
      overlay.classList.remove("is-open");
      overlay.querySelector(".encuesta-estrellas").removeEventListener("click", onEstrellaClick);
      overlay.querySelector("[data-encuesta-enviar]").removeEventListener("click", onEnviar);
      overlay.onclick = null;
    }
    function onEnviar() {
      var comentario = textarea.value.trim();
      if (calificacion === null && !comentario) {
        cerrar();
        return;
      }
      fetch("/api/encuesta", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipo: tipo, aviso_id: avisoId, calificacion: calificacion, comentario: comentario }),
      }).catch(function () {});
      cerrar();
      mostrarAviso("¡Gracias por tu respuesta!", "ok");
    }
    overlay.querySelector(".encuesta-estrellas").addEventListener("click", onEstrellaClick);
    overlay.querySelector("[data-encuesta-enviar]").addEventListener("click", onEnviar);
    overlay.onclick = function (e) { if (e.target === overlay) cerrar(); };
    overlay.querySelector(".app-modal-close").onclick = cerrar;
    overlay.classList.add("is-open");
  }

  document.addEventListener("click", function (e) {
    var link = e.target.closest("[data-wa-click]");
    if (!link || yaRespondida()) return;
    var avisoId = link.getAttribute("data-aviso-id");
    marcarMostrada();
    setTimeout(function () { preguntar("activa", avisoId, "¿Cómo calificarías tu experiencia?"); }, 4000);
  });

  document.addEventListener("DOMContentLoaded", function () {
    if (!document.querySelector("[data-encuesta-publicar]")) return;
    setTimeout(function () {
      preguntar("publicar", null, "¿Cómo fue publicar tu negocio en Talcadatos?");
    }, 1200);
  });
})();
