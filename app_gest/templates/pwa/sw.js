{% load static %}/* Service worker : rend l'application installable et affiche une page claire sans connexion.
   Règle de sécurité : on ne met JAMAIS en cache les pages de l'application (données privées, appareils partagés).
   Seuls les fichiers statiques sont mis en cache ; une page indisponible affiche la page « hors ligne ». */
const VERSION = "{{ version }}";
const STATIC_CACHE = "static-" + VERSION;
const OFFLINE_URL = "{% url 'pwa:offline' %}";
const STATIC_PREFIX = "{{ static_url }}";
const CDN_HOSTS = ["cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"];
const ICON = "{% static 'pwa/icons/icon-192.png' %}";
const PRECACHE = [
  OFFLINE_URL, ICON, "{% static 'pwa/icons/icon-512.png' %}",
  "{% static 'css/bar.css' %}", "{% static 'js/bar.js' %}"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => Promise.allSettled(PRECACHE.map((url) => cache.add(url))))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== STATIC_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// La page propose « Actualiser » quand une nouvelle version est prête
self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

// Fichiers statiques : on sert le cache tout de suite et on le met à jour en arrière-plan
function staleWhileRevalidate(request) {
  return caches.open(STATIC_CACHE).then((cache) =>
    cache.match(request).then((cached) => {
      const network = fetch(request).then((response) => {
        if (response && response.ok) cache.put(request, response.clone());
        return response;
      }).catch(() => cached);
      return cached || network;
    })
  );
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;                       // les envois (POST) vont toujours au serveur
  const url = new URL(request.url);

  if (request.mode === "navigate") {                          // pages : réseau, sinon page « hors ligne »
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }
  if (url.origin === self.location.origin && url.pathname.startsWith(STATIC_PREFIX)) {
    event.respondWith(staleWhileRevalidate(request));
  } else if (CDN_HOSTS.includes(url.hostname)) {
    event.respondWith(staleWhileRevalidate(request));
  }
  // tout le reste (API, WebSocket, fichiers privés du chat) passe directement par le réseau
});

// Notifications Web Push (voir notifications.PushSubscription)
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data ? event.data.text() : "" }; }
  event.waitUntil(self.registration.showNotification(data.title || "{{ 'BarManager' }}", {
    body: data.body || "", icon: ICON, badge: ICON, tag: data.tag || undefined, data: { url: data.url || "/" }
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if ("focus" in client && "navigate" in client) return client.focus().then(() => client.navigate(target));
      }
      return self.clients.openWindow(target);
    })
  );
});