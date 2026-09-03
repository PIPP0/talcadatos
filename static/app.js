/* Prefijo de ruta cuando el sitio se sirve bajo /espaciodeprueba_01 (ver
   render() en server.py); "" en el sitio real, así que el resto del archivo
   funciona igual en ambos. */
var BASE_PATH = document.body.getAttribute("data-base-path") || "";
var HOME_PATH = BASE_PATH + "/";

/* El logo y "Inicio" siempre llevan arriba del todo, aunque ya estés en "/"
   (si no, un clic ahí no hace nada porque la URL no cambia). */
document.addEventListener("click", function (e) {
  var link = e.target.closest('a[href="' + HOME_PATH + '"]');
  if (!link) return;
  if (location.pathname === HOME_PATH && !location.search && !location.hash) {
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
  if (window.pausarAutoCarousel) window.pausarAutoCarousel(track);
});

/* Avanza sola cada 12s mostrando el siguiente grupo de tarjetas (mismo paso
   que las flechas), y al llegar al final vuelve al principio en vez de
   quedarse pegada. Se detiene si el usuario interactua (flechas o scroll
   manual) y respeta a quien prefiere menos movimiento en pantalla. */
(function initAutoCarousel() {
  var prefiereMenosMovimiento = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefiereMenosMovimiento) return;

  var pausas = new WeakMap();

  window.pausarAutoCarousel = function (track) {
    var estado = pausas.get(track);
    if (!estado) return;
    clearTimeout(estado.reanudarTimer);
    estado.pausado = true;
    estado.reanudarTimer = setTimeout(function () { estado.pausado = false; }, 6000);
  };

  document.querySelectorAll(".carousel-track").forEach(function (track) {
    var estado = { pausado: false, reanudarTimer: null };
    pausas.set(track, estado);

    track.addEventListener("mouseenter", function () { estado.pausado = true; });
    track.addEventListener("mouseleave", function () { estado.pausado = false; });
    track.addEventListener("touchstart", function () { pausarAutoCarousel(track); }, { passive: true });

    setInterval(function () {
      if (estado.pausado) return;
      var alFinal = track.scrollLeft + track.clientWidth >= track.scrollWidth - 10;
      if (alFinal) {
        track.scrollTo({ left: 0, behavior: "smooth" });
      } else {
        track.scrollBy({ left: Math.round(track.clientWidth * 0.85), behavior: "smooth" });
      }
    }, 12000);
  });
})();

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

/* Id estable por navegador (no por persona) para poder distinguir, en
   metricas como "lo mas buscado", a alguien que repite la misma busqueda
   varias veces de gente distinta buscando lo mismo. No identifica a nadie. */
function sesionNavegador() {
  var KEY = "talca_sesion";
  try {
    var v = localStorage.getItem(KEY);
    if (!v) {
      v = Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem(KEY, v);
    }
    return v;
  } catch (e) {
    return "";
  }
}

function logEvento(tipo, avisoId, termino) {
  var payload = JSON.stringify({
    tipo: tipo, aviso_id: avisoId || null, termino_busqueda: termino || null, sesion: sesionNavegador(),
  });
  if (navigator.sendBeacon) {
    navigator.sendBeacon(BASE_PATH + "/api/evento", new Blob([payload], { type: "application/json" }));
  } else {
    fetch(BASE_PATH + "/api/evento", { method: "POST", body: payload, keepalive: true });
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
      results.innerHTML = '<div class="search-empty">Sin coincidencias todavía para "' + query + '". Prueba con otra palabra o <a href="' + BASE_PATH + '/publicar">publica tu negocio</a> si nadie lo ofrece aún.</div>';
      results.hidden = false;
      return;
    }
    results.innerHTML = items.map(function (a) {
      var badge = a.destacado ? '<span class="search-badge">Destacado</span>' : "";
      return '<a class="search-item" href="' + BASE_PATH + '/avisos/' + a.id + '" data-aviso-id="' + a.id + '" data-termino="' +
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
      fetch(BASE_PATH + "/api/buscar", {
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
    window.location.href = BASE_PATH + "/avisos?q=" + encodeURIComponent(q);
  });
})();

(function initAlertaForm() {
  var form = document.getElementById("alerta-form");
  if (!form) return;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var whatsapp = form.whatsapp.value.trim();
    fetch(BASE_PATH + "/api/alerta", {
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

  var VERIFICADO_SVG = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">' +
    '<path fill="#5B9EE8" d="M22.9 12.0 L22.62 12.7 L21.86 13.3 L20.83 13.76 L19.78 14.08 L18.96 14.36 L18.56 14.72 L18.6 15.25 L18.97 16.02 L19.48 17.0 L19.89 18.06 L20.0 19.02 L19.71 19.71 L19.02 20.0 L18.06 19.89 L17.0 19.48 L16.03 18.97 L15.25 18.6 L14.72 18.56 L14.36 18.96 L14.08 19.78 L13.76 20.83 L13.3 21.86 L12.7 22.62 L12.0 22.9 L11.3 22.62 L10.7 21.86 L10.24 20.83 L9.92 19.78 L9.64 18.96 L9.28 18.56 L8.75 18.6 L7.98 18.97 L7.0 19.48 L5.94 19.89 L4.98 20.0 L4.29 19.71 L4.0 19.02 L4.11 18.06 L4.52 17.0 L5.03 16.02 L5.4 15.25 L5.44 14.72 L5.04 14.36 L4.22 14.08 L3.17 13.76 L2.14 13.3 L1.38 12.7 L1.1 12.0 L1.38 11.3 L2.14 10.7 L3.17 10.24 L4.22 9.92 L5.04 9.64 L5.44 9.28 L5.4 8.75 L5.03 7.98 L4.52 7.0 L4.11 5.94 L4.0 4.98 L4.29 4.29 L4.98 4.0 L5.94 4.11 L7.0 4.52 L7.97 5.03 L8.75 5.4 L9.28 5.44 L9.64 5.04 L9.92 4.22 L10.24 3.17 L10.7 2.14 L11.3 1.38 L12.0 1.1 L12.7 1.38 L13.3 2.14 L13.76 3.17 L14.08 4.22 L14.36 5.04 L14.72 5.44 L15.25 5.4 L16.02 5.03 L17.0 4.52 L18.06 4.11 L19.02 4.0 L19.71 4.29 L20.0 4.98 L19.89 5.94 L19.48 7.0 L18.97 7.97 L18.6 8.75 L18.56 9.28 L18.96 9.64 L19.78 9.92 L20.83 10.24 L21.86 10.7 L22.62 11.3 Z"/>' +
    '<path fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" d="M6.26 12.82L9.54 16.1L17.74 7.9"/></svg>';
  var STAR_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M12 2l2.9 6.6 7.1.7-5.5 4.8 1.7 6.9L12 17.3l-6.2 3.7 1.7-6.9L2 9.3l7.1-.7L12 2z"/></svg>';

  function tarjetaHtml(d) {
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
    var cuerpo;
    if (d.es_demo) {
      cuerpo =
        '<a class="card-title" href="' + BASE_PATH + '/publicar">¡Publícate hoy y empieza a vender más!</a>' +
        '<div class="card-meta eyebrow-star">' + STAR_SVG + '<span>Encuentra tu categoría</span></div>' +
        '<p class="card-desc">Miles de personas en Talca buscan y contactan negocios cada semana. Publícate hoy.</p>' +
        '<a class="btn btn-primary btn-block" href="' + BASE_PATH + '/publicar">Publicar mi negocio →</a>';
    } else {
      var verificado = d.verificado ? '<span class="check" title="Negocio verificado">' + VERIFICADO_SVG + "</span>" : "";
      cuerpo =
        '<a class="card-title" href="' + BASE_PATH + '/avisos/' + d.id + '">' + escHtml(d.titulo) + "</a>" +
        '<div class="card-meta"><span>' + escHtml(d.negocio) + " " + verificado + "</span>" +
        '<span class="dot">·</span><span>' + escHtml(d.comuna) + "</span></div>" +
        '<div class="card-cat mono">' + d.icono + " " + escHtml(d.categoria) + "</div>";
    }
    var fotoHref = d.es_demo ? BASE_PATH + "/publicar" : BASE_PATH + "/avisos/" + d.id;
    var fotoBadge = !d.es_demo && d.plan && d.plan !== "Gratis" ? '<span class="badge badge-gold">' + escHtml(d.plan) + "</span>" : "";
    var favBtn = d.es_demo ? "" :
      '<button class="fav-btn is-fav" type="button" data-fav-id="' + d.id + '" title="Quitar de favoritos">★</button>';
    return (
      '<article class="card" style="--card-accent:' + escHtml(d.color) + '">' +
      '<a class="card-photo' + (d.foto_url ? " has-foto" : "") + '" href="' + fotoHref + '">' + foto + fotoBadge + "</a>" +
      chevrones + favBtn +
      '<div class="card-body">' + cuerpo + "</div></article>"
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
      fetch(BASE_PATH + "/api/favoritos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: ids }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var items = (data.resultados || []).filter(function (d) { return !d.es_demo; });
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
      fetch(BASE_PATH + "/api/encuesta", {
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
