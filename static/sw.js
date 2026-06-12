/**
 * Service Worker — Nexux PWA
 *
 * Lo justo para que Nexux sea instalable como app y reciba notificaciones push.
 * IMPORTANTE: NO interceptamos fetch ni cacheamos assets (network-passthrough),
 * así la PWA siempre toma la versión recién desplegada sin servir nada viejo.
 * Si en el futuro se agrega caché offline, debe ser network-first y versionada.
 */

const VERSION = 'nexus-v2';

self.addEventListener('install', () => {
  self.skipWaiting();   // el SW nuevo toma el control de inmediato
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // Limpieza defensiva: borra cualquier Cache Storage de versiones anteriores.
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

// Permite forzar la actualización del SW desde la página (postMessage 'skipWaiting').
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') self.skipWaiting();
});

// ── Notificaciones push (preparado para las alertas a futuro) ──────────────
self.addEventListener('push', (event) => {
  let data = { title: 'Nexux', body: 'Tienes una novedad' };
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data.body = event.data.text();
    }
  }
  const opts = {
    body: data.body || '',
    icon: '/static/icons/nexus-192.png',
    badge: '/static/icons/nexus-192.png',
    tag: data.tag || 'nexus',
    data: { url: data.url || '/' },
    requireInteraction: data.requireInteraction || false,
    vibrate: [200, 100, 200],
  };
  event.waitUntil(self.registration.showNotification(data.title || 'Nexux', opts));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = event.notification.data?.url || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientsList) => {
      for (const client of clientsList) {
        if ('focus' in client) {
          client.focus();
          if ('navigate' in client) client.navigate(target);
          return;
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});
