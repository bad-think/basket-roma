// ============================================================
// Service Worker — Roma Basket Casa PWA
// v2 — Strategia differenziata per asset statici e dati
// ============================================================

const CACHE_VERSION = 'basket-roma-v3';
const STATIC_CACHE  = `${CACHE_VERSION}-static`;
const DATA_CACHE    = `${CACHE_VERSION}-data`;

// Asset statici: immutabili tra un refresh e l'altro
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
];

// ── INSTALL: pre-cache asset statici ─────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(STATIC_CACHE)
      .then(c => c.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())   // attiva subito senza aspettare il vecchio SW
  );
});

// ── ACTIVATE: elimina cache versioni precedenti ───────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys
          .filter(k => k !== STATIC_CACHE && k !== DATA_CACHE)
          .map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())  // prendi controllo immediato di tutte le tab
  );
});

// ── FETCH: routing differenziato ─────────────────────────────
self.addEventListener('fetch', e => {
  const { url } = e.request;
  const path = new URL(url).pathname;

  // 1. API Anthropic → sempre rete, mai cache
  if (url.includes('api.anthropic.com')) {
    e.respondWith(fetch(e.request));
    return;
  }

  // 2. Google APIs (CSE) → sempre rete, mai cache
  if (url.includes('googleapis.com')) {
    e.respondWith(fetch(e.request));
    return;
  }

  // 3. data.json → Network-First con fallback cache
  //    Se la rete risponde entro 4s → aggiorna cache e notifica l'app
  //    Se offline/lenta → serve dalla cache
  if (path.endsWith('data.json')) {
    e.respondWith(networkFirstData(e.request));
    return;
  }

  // 4. Altri JSON (escluso manifest) → Network-First
  if (path.endsWith('.json') && !path.endsWith('manifest.json')) {
    e.respondWith(networkFirstData(e.request));
    return;
  }

  // 5. Google Fonts e CDN esterni → Cache-First
  if (url.includes('fonts.googleapis.com') || url.includes('fonts.gstatic.com')) {
    e.respondWith(cacheFirstStatic(e.request));
    return;
  }

  // 6. HTML (index.html, /) → Stale-While-Revalidate
  //    Serve dalla cache subito (veloce), ma aggiorna in background.
  //    Alla visita successiva l'utente ha la versione aggiornata.
  if (path === '/' || path.endsWith('.html')) {
    e.respondWith(staleWhileRevalidate(e.request));
    return;
  }

  // 7. Asset statici (JS, CSS, immagini, manifest) → Cache-First
  e.respondWith(cacheFirstStatic(e.request));
});

// ── Network-First per data.json ───────────────────────────────
async function networkFirstData(request) {
  const cache = await caches.open(DATA_CACHE);

  // Race: rete vs timeout 4 secondi
  const networkPromise = fetch(request.clone())
    .then(async response => {
      if (response.ok) {
        // Salva in cache e notifica tutti i client aperti
        await cache.put(request, response.clone());
        notifyClients('DATA_UPDATED');
      }
      return response;
    });

  const timeoutPromise = new Promise((_, reject) =>
    setTimeout(() => reject(new Error('timeout')), 4000)
  );

  try {
    return await Promise.race([networkPromise, timeoutPromise]);
  } catch {
    // Rete assente o lenta → servi dalla cache
    const cached = await cache.match(request);
    if (cached) return cached;
    // Nessuna cache → risposta di emergenza
    return new Response(
      JSON.stringify({ error: 'offline', last_updated: null, matches: [], standings: {} }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    );
  }
}

// ── Stale-While-Revalidate per HTML ──────────────────────────
//    Serve dalla cache subito (caricamento istantaneo), intanto aggiorna
//    dalla rete. Alla visita successiva l'utente ha la versione nuova
//    senza bisogno di hard-refresh.
async function staleWhileRevalidate(request) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request)
    .then(response => {
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  // Cache presente → servila subito, la rete aggiorna in background
  // Cache assente → aspetta la rete
  return cached || await fetchPromise ||
    new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
}

// ── Cache-First per asset statici ────────────────────────────
async function cacheFirstStatic(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Risorsa non in cache e offline — restituisce 503 silenzioso
    return new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
  }
}

// ── Notifica ai client ────────────────────────────────────────
async function notifyClients(type) {
  const clients = await self.clients.matchAll({ includeUncontrolled: true });
  clients.forEach(client => client.postMessage({ type }));
}

// ── Ricevi messaggi dai client (es. SKIP_WAITING da applyUpdate()) ─────────
self.addEventListener('message', e => {
  if (e.data && e.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
