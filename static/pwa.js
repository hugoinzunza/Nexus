/**
 * pwa.js — registro del service worker y utilidades de web push.
 *
 * Se carga en todas las páginas de Nexus. Hoy solo registra el service worker
 * (para que la app sea instalable). El registro de push queda expuesto en
 * `window.NexusPush` para cuando activemos las alertas; no se pide permiso de
 * notificaciones automáticamente (eso sería molesto): se hará desde un botón.
 */

(function () {
  if (!('serviceWorker' in navigator)) return;

  let swReg = null;
  navigator.serviceWorker
    .register('/sw.js', { scope: '/' })
    .then((reg) => { swReg = reg; })
    .catch((err) => console.warn('[Nexus] no se pudo registrar el SW:', err));

  // Convierte la clave pública VAPID (base64url) al formato que pide el navegador.
  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  // API pública para activar alertas más adelante (se llamará desde un botón).
  window.NexusPush = {
    async activar() {
      if (!swReg) swReg = await navigator.serviceWorker.ready;
      const res = await fetch('/api/push/public-key').then((r) => r.json());
      if (!res.configurado || !res.key) {
        throw new Error('El servidor todavía no tiene claves VAPID configuradas.');
      }
      const permiso = await Notification.requestPermission();
      if (permiso !== 'granted') throw new Error('Permiso de notificaciones denegado.');

      const sub = await swReg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(res.key),
      });
      await fetch('/api/push/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sub),
      });
      return true;
    },
  };
})();
