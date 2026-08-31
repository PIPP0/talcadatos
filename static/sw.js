const CACHE = "talcadatos-shell-v3";
const SCOPE = self.registration.scope;
const SHELL = [SCOPE, new URL("static/styles.css", SCOPE).href, new URL("static/app.js", SCOPE).href];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((nombres) => Promise.all(nombres.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  // Las fotos de avisos viven en un bucket aparte (storage.googleapis.com).
  // No son parte del "shell" que necesita soporte offline, así que se dejan
  // pasar sin que el service worker intervenga (evita bugs de Safari con
  // fetch de terceros dentro de un service worker).
  if (new URL(event.request.url).origin !== self.location.origin) return;
  // El contenido del sitio puede cambiar desde el admin. Las páginas HTML se
  // consultan primero en red para que Pages muestre el último export; el cache
  // queda solo como respaldo si la persona se quedó sin conexión.
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
      const copy = response.clone();
      if (response.ok && new URL(event.request.url).origin === self.location.origin) {
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
      }
      return response;
    }))
  );
});
