/* Switch de tema NexUX (claro/oscuro).
   El tema YA fue aplicado por el script inline del <head> (sin parpadeo). Acá solo
   cableamos el botón #theme-toggle de la barra; si la página no trae uno, inyectamos
   uno flotante. La elección se recuerda por dispositivo en localStorage. */
(function () {
  function cur() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }
  function sync(btn) {
    var dark = cur() === "dark";
    if (btn) btn.textContent = dark ? "Claro" : "Oscuro";
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute("content", dark ? "#0b0d12" : "#f4f5f8");
  }
  function toggle() {
    var t = cur() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("nexux-theme", t); } catch (e) {}
    sync(document.getElementById("theme-toggle"));
  }
  function init() {
    var btn = document.getElementById("theme-toggle");
    if (!btn) {
      btn = document.createElement("button");
      btn.id = "theme-toggle";
      btn.type = "button";
      btn.className = "theme-fab";
      btn.setAttribute("aria-label", "Cambiar tema claro/oscuro");
      document.body.appendChild(btn);
    }
    btn.addEventListener("click", toggle);
    sync(btn);
  }
  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
