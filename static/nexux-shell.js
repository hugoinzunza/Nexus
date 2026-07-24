(function () {
  "use strict";

  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  if (!document.querySelector('link[rel~="icon"]')) {
    const favicon = document.createElement("link");
    favicon.rel = "icon";
    favicon.type = "image/svg+xml";
    favicon.href = "/favicon.ico?v=2";
    document.head.appendChild(favicon);
  }
  const sections = [
    {
      label: "NexUX",
      links: [
        { href: "/", text: "Inicio", icon: "NX", match: ["/"] },
        { href: "/account", text: "Mi cuenta", icon: "YO", match: ["/account"] },
      ],
    },
    {
      label: "Mercado",
      links: [
        { href: "/m/trading/", text: "Trading", icon: "TV", match: ["/m/trading"] },
      ],
    },
    {
      label: "Resultados",
      links: [
        { href: "/m/journal/", text: "Diario", icon: "DR", match: ["/m/journal"] },
        { href: "/m/bot/", text: "Bot", icon: "BT", match: ["/m/bot"] },
      ],
    },
    {
      label: "Inteligencia",
      links: [
        { href: "/m/coinsignals/", text: "CoinSignals", icon: "CS", tag: "shadow", match: ["/m/coinsignals"] },
        { href: "/m/coinglass/", text: "CoinGlass", icon: "CG", tag: "research", match: ["/m/coinglass"] },
      ],
    },
    {
      label: "Research",
      links: [
        { href: "/m/trading/research-diario-v1", text: "Diario V1", icon: "D1", tag: "archivo", match: ["/m/trading/research-diario-v1"] },
        { href: "/m/trading/backtest", text: "Backtest SMC", icon: "BT", match: ["/m/trading/backtest"] },
        { href: "/m/trading/research-bta-v2", text: "BTA visual v2", icon: "B2", tag: "lab", match: ["/m/trading/research-bta-v2"] },
      ],
    },
  ];

  function isActive(item) {
    const matches = item.match || [];
    if (item.href === "/") {
      return path === "/";
    }
    if (item.href === "/m/trading/") {
      return path === "/m/trading";
    }
    return matches.some((prefix) => path === prefix || path.startsWith(prefix + "/"));
  }

  function linkMarkup(item) {
    const tag = item.tag ? `<span class="nx-shell-tag">${item.tag}</span>` : "";
    const active = isActive(item) ? " active" : "";
    return `<a class="nx-shell-link${active}" href="${item.href}">
      <span class="nx-shell-icon" aria-hidden="true">${item.icon}</span>
      <span>${item.text}</span>${tag}
    </a>`;
  }

  const nav = sections.map((section) => `
    <section class="nx-shell-group">
      <p class="nx-shell-label">${section.label}</p>
      ${section.links.map(linkMarkup).join("")}
    </section>`).join("");

  const shell = document.createElement("aside");
  shell.className = "nx-shell";
  shell.setAttribute("aria-label", "Navegación principal");
  shell.innerHTML = `
    <div class="nx-shell-brand">
      <a href="/">
        <svg class="nx-shell-mark" viewBox="0 0 100 100" aria-hidden="true">
          <defs>
            <linearGradient id="nx-mark-violet" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="#8b80ff"></stop>
              <stop offset="1" stop-color="#6c5ce7"></stop>
            </linearGradient>
            <linearGradient id="nx-mark-cyan" x1="1" y1="0" x2="0" y2="1">
              <stop offset="0" stop-color="#26d6f0"></stop>
              <stop offset="1" stop-color="#0b96ad"></stop>
            </linearGradient>
          </defs>
          <path d="M28 28 L72 72" stroke="url(#nx-mark-violet)" stroke-width="13" stroke-linecap="round" fill="none"></path>
          <path d="M72 28 L28 72" stroke="url(#nx-mark-cyan)" stroke-width="13" stroke-linecap="round" fill="none"></path>
        </svg>
        <span class="nx-shell-word">Nex<span>UX</span></span>
      </a>
      <button class="nx-shell-close" type="button" aria-label="Cerrar menú">×</button>
    </div>
    <a class="nx-shell-user" id="nx-shell-user" href="/account">
      <span class="nx-shell-avatar" id="nx-shell-avatar">—</span>
      <span class="nx-shell-user-copy">
        <strong id="nx-shell-user-name">Cargando cuenta</strong>
        <small id="nx-shell-user-meta">Comprobando sesión</small>
      </span>
    </a>
    <nav class="nx-shell-nav">${nav}</nav>
    <div class="nx-shell-foot">
      <div class="nx-shell-health" id="nx-shell-health"><i></i><span>Comprobando sistema</span></div>
    </div>`;

  const mobile = document.createElement("div");
  mobile.className = "nx-shell-mobile";
  const current = sections.flatMap((section) => section.links).find(isActive);
  mobile.innerHTML = `
    <button class="nx-shell-menu" type="button" aria-label="Abrir menú">≡</button>
    <strong>${current ? current.text : "Centro de control"}</strong>
    <span>NexUX</span>`;

  const backdrop = document.createElement("div");
  backdrop.className = "nx-shell-backdrop";

  document.body.classList.add("nx-has-shell");
  document.body.prepend(backdrop);
  document.body.prepend(mobile);
  document.body.prepend(shell);

  const openMenu = () => {
    shell.classList.add("open");
    backdrop.classList.add("open");
  };
  const closeMenu = () => {
    shell.classList.remove("open");
    backdrop.classList.remove("open");
  };
  mobile.querySelector("button").addEventListener("click", openMenu);
  shell.querySelector(".nx-shell-close").addEventListener("click", closeMenu);
  backdrop.addEventListener("click", closeMenu);
  shell.querySelectorAll(".nx-shell-link").forEach((link) => link.addEventListener("click", closeMenu));

  fetch("/health", { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error("health");
      return response.json();
    })
    .then((data) => {
      const health = document.getElementById("nx-shell-health");
      const count = Array.isArray(data.modules) ? data.modules.length : 0;
      health.classList.add(data.status === "ok" ? "ok" : "warn");
      health.querySelector("span").textContent = `${count} módulos disponibles`;
    })
    .catch(() => {
      const health = document.getElementById("nx-shell-health");
      health.classList.add("warn");
      health.querySelector("span").textContent = "Estado no disponible";
    });

  fetch("/me", { cache: "no-store" })
    .then((response) => response.json())
    .then((data) => {
      const user = data && data.user;
      const block = document.getElementById("nx-shell-user");
      const avatar = document.getElementById("nx-shell-avatar");
      const name = document.getElementById("nx-shell-user-name");
      const meta = document.getElementById("nx-shell-user-meta");
      if (!user) {
        block.href = "/login";
        name.textContent = "Ingresar";
        meta.textContent = "Cuenta personal";
        avatar.textContent = "→";
        return;
      }
      const display = user.name || user.email || "Mi cuenta";
      name.textContent = display;
      meta.textContent = user.role === "admin" ? "Administrador" : "Cuenta personal";
      if (user.role !== "admin") {
        const botLink = shell.querySelector('.nx-shell-link[href="/m/bot/"]');
        if (botLink) botLink.remove();
      }
      if (user.picture) {
        const image = document.createElement("img");
        image.src = user.picture;
        image.alt = "";
        avatar.replaceChildren(image);
      } else {
        avatar.textContent = display.slice(0, 1).toUpperCase();
      }
      const mobileName = mobile.querySelector("span");
      mobileName.textContent = display.split(" ")[0];
    })
    .catch(() => {
      document.getElementById("nx-shell-user-name").textContent = "Mi cuenta";
      document.getElementById("nx-shell-user-meta").textContent = "Estado no disponible";
    });
})();
