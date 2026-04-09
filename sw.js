const CACHE_NAME = 'roma-basket-v3';
const ASSETS = ['./', './index.html', './manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
  )));
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.open(CACHE_NAME).then(cache => {
      return cache.match(event.request).then(response => {
        const fetchPromise = fetch(event.request).then(networkResponse => {
          if (networkResponse.ok) {
            cache.put(event.request, networkResponse.clone());
            if (event.request.url.includes('data.json')) {
              networkResponse.clone().json().then(newData => {
                self.clients.matchAll().then(clients => {
                  clients.forEach(c => c.postMessage({type: 'DATA_UPDATED', lastUpdate: newData.last_updated}));
                });
              });
            }
          }
          return networkResponse;
        });
        return response || fetchPromise;
      });
    }).catch(() => fetch(event.request))
  );
});
