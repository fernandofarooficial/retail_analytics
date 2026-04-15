const CACHE = 'retail-mobile-v4';

const APP_SHELL = [
  '/retail_analytics/m/',
  '/retail_analytics/m/login',
  '/retail_analytics/static/mobile/css/mobile.css',
  '/retail_analytics/static/icons/icon-192.png',
  '/retail_analytics/static/icons/icon-512.png',
  '/retail_analytics/static/img/logo_retail_analytics_br_1.png',
];

// Instala e faz cache do app shell
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

// Remove caches antigos
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Estratégia: network-first para HTML (dados sempre frescos),
// cache-first para assets estáticos
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Ignora requisições não-GET e de outros domínios
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;

  // Assets estáticos → cache-first
  if (url.pathname.startsWith('/retail_analytics/static/')) {
    e.respondWith(
      caches.match(e.request).then(cached =>
        cached || fetch(e.request).then(res => {
          const clone = res.clone();
          caches.open(CACHE).then(cache => cache.put(e.request, clone));
          return res;
        })
      )
    );
    return;
  }

  // Páginas HTML → network-first com fallback offline
  if (url.pathname.startsWith('/retail_analytics/m/')) {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request))
    );
  }
});
