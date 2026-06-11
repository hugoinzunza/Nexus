/**
 * Service Worker — Nexus PWA
 *
 * Versión minimalista: lo justo para que Nexus sea instalable como app y, más
 * adelante, pueda recibir notificaciones push (alertas de trading). Sin caché
 * offline por ahora; lo agregamos si hace falta.
 */

const VERSION = 'nexus-v1';

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// ── Notificaciones push (preparado para las alertas a futuro) ──────────────
self.addEventListener('push', (event) => {
  let data = { title: 'Nexus', body: 'Tienes una novedad' };
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
  event.waitUntil(self.registration.showNotification(data.title || 'Nexus', opts));
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
