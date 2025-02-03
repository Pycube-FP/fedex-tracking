const CACHE_NAME = 'fedex-scanner-v1';
const urlsToCache = [
  '/static/styles.css',
  '/static/manifest.json',
  '/static/icons/icon-72x72.png',
  '/static/icons/icon-96x96.png',
  '/static/icons/icon-128x128.png',
  '/static/icons/icon-144x144.png',
  '/static/icons/icon-152x152.png',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-384x384.png',
  '/static/icons/icon-512x512.png'
];

// Installation event
self.addEventListener('install', (event) => {
  console.log('[Service Worker] Installing Service Worker...', event);
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('[Service Worker] Caching app shell');
        return cache.addAll(urlsToCache)
          .then(() => {
            console.log('[Service Worker] All resources have been fetched and cached.');
          });
      })
      .catch(error => {
        console.error('[Service Worker] Error caching app shell:', error);
      })
  );
});

// Activation event
self.addEventListener('activate', (event) => {
  console.log('[Service Worker] Activating Service Worker...', event);
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            console.log('[Service Worker] Removing old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  return self.clients.claim();
});

// Fetch event
self.addEventListener('fetch', (event) => {
  // Only cache static assets
  if (event.request.url.includes('/static/')) {
    console.log('[Service Worker] Fetching static resource:', event.request.url);
    event.respondWith(
      caches.match(event.request)
        .then(response => {
          if (response) {
            console.log('[Service Worker] Returning cached resource:', event.request.url);
            return response;
          }
          console.log('[Service Worker] Fetching resource:', event.request.url);
          return fetch(event.request)
            .then(response => {
              // Check if we received a valid response
              if (!response || response.status !== 200 || response.type !== 'basic') {
                return response;
              }

              // Clone the response as it can only be consumed once
              const responseToCache = response.clone();

              caches.open(CACHE_NAME)
                .then(cache => {
                  console.log('[Service Worker] Caching new resource:', event.request.url);
                  cache.put(event.request, responseToCache);
                });

              return response;
            })
            .catch(error => {
              console.error('[Service Worker] Error fetching and caching new resource:', error);
            });
        })
    );
  } else {
    // For non-static assets, just fetch from network
    return fetch(event.request);
  }
});