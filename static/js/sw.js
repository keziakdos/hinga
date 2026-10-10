/* Hinga service worker (V2.6) : consultation hors ligne des annonces et fiches. */
const CACHE = 'hinga-v1';
const CORE = [
  '/', '/calendar', '/hors-ligne',
  '/static/css/fonts.css', '/static/css/style.css', '/static/css/print.css',
  '/static/vendor/tailwind.js', '/static/vendor/chart.js',
  '/static/vendor/phosphor/regular.css',
  '/static/img/placeholder.svg', '/static/img/favicon.png', '/static/img/icon-192.png'
];
const PAGE_EXACT = ['/', '/calendar', '/tips', '/journal', '/echanges'];
const PAGE_PREFIXES = ['/plant/', '/tip/', '/journal/', '/echanges/'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(CORE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function cacheablePage(url) {
  if (PAGE_EXACT.includes(url.pathname)) return true;
  return PAGE_PREFIXES.some((p) => url.pathname.startsWith(p));
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((cache) => cache.put(req, copy));
        return res;
      }).catch(() => caches.match('/static/img/placeholder.svg')))
    );
    return;
  }
  if (!cacheablePage(url)) return;
  event.respondWith(
    fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((cache) => cache.put(req, copy));
      return res;
    }).catch(() => caches.match(req).then((hit) => hit || caches.match('/hors-ligne')))
  );
});
