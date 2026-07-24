(function () {
  "use strict";

  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  const sections = [
    {
      label: "NexUX",
      links: [
        { href: "/", text: "Inicio", icon: "NX", match: ["/"] },
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
        <span class="nx-shell-mark" aria-hidden="true">N</span>
        <span class="nx-shell-word">Nex<span>UX</span></span>
      </a>
      <button class="nx-shell-close" type="button" aria-label="Cerrar menú">×</button>
    </div>
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
})();
