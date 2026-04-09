const CACHE_NAME = 'roma-basket-v2';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.map(k => { if(k !== CACHE_NAME) return caches.delete(k); })
    ))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  // Strategia Stale-While-Revalidate: mostra subito la cache, aggiorna in background
  event.respondWith(
    caches.open(CACHE_NAME).then(cache => {
      return cache.match(event.request).then(response => {
        const fetchPromise = fetch(event.request).then(networkResponse => {
          if (networkResponse.ok) {
            cache.put(event.request, networkResponse.clone());
            // Se è il data.json, invia un messaggio alla pagina se è cambiato
            if (event.request.url.includes('data.json')) {
              networkResponse.clone().json().then(newData => {
                self.clients.matchAll().then(clients => {
                  clients.forEach(client => client.postMessage({
                    type: 'DATA_UPDATED',
                    lastUpdate: newData.last_updated
                  }));
                });
              });
            }
          }
          return networkResponse;
        });
        return response || fetchPromise;
      });
    })
  );
});
