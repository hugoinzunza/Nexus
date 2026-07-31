const SCRIPT_URL =
  "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";

export class TradingViewSpikeError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "TradingViewSpikeError";
    this.code = code;
  }
}

export class TradingViewWidgetAdapter {
  constructor({ timeoutMs = 15000, now = () => Date.now() } = {}) {
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
      throw new TypeError("timeoutMs must be positive");
    }
    this.providerId = "tradingview-widget";
    this.timeoutMs = timeoutMs;
    this.now = now;
    this.lifecycle = "detached";
    this.code = null;
    this.retryable = false;
    this.container = null;
    this.wrapper = null;
    this.iframe = null;
    this.observer = null;
    this.session = null;
    this.mountKey = null;
    this.metrics = {
      mountAttempts: 0,
      mountFailures: 0,
      destroyCalls: 0,
      lastMountLatencyMs: null,
      lastErrorCode: null,
      iframeLoads: 0,
    };
  }

  capabilities() {
    // The public iframe widget exposes configuration, not runtime chart methods.
    return Object.freeze([]);
  }

  health() {
    if (
      this.lifecycle === "ready" &&
      (!this.iframe || !this.iframe.isConnected)
    ) {
      this.lifecycle = "degraded";
      this.code = "tradingview.iframe-missing";
      this.retryable = true;
    }
    return Object.freeze({
      providerId: this.providerId,
      lifecycle: this.lifecycle,
      checkedAtMs: this.now(),
      code: this.code,
      retryable: this.retryable,
    });
  }

  async mount(container, options) {
    this.#validateContainer(container);
    const config = this.#buildConfig(options);
    const key = JSON.stringify(config);
    if (this.session) {
      if (this.container === container && this.mountKey === key) {
        return this.session;
      }
      throw new TradingViewSpikeError(
        "tradingview.already-mounted",
        "Destroy the current widget before changing configuration.",
      );
    }
    if (this.lifecycle === "destroyed") {
      throw new TradingViewSpikeError(
        "tradingview.destroyed",
        "A destroyed adapter cannot be mounted again.",
      );
    }

    const started = this.now();
    this.metrics.mountAttempts += 1;
    this.lifecycle = "mounting";
    this.code = null;
    this.retryable = false;
    this.container = container;
    this.mountKey = key;
    this.wrapper = document.createElement("div");
    this.wrapper.className = "tradingview-widget-container";
    this.wrapper.style.height = "100%";
    this.wrapper.style.width = "100%";

    const widgetTarget = document.createElement("div");
    widgetTarget.className = "tradingview-widget-container__widget";
    widgetTarget.style.height = "calc(100% - 32px)";
    widgetTarget.style.width = "100%";
    this.wrapper.appendChild(widgetTarget);
    this.wrapper.appendChild(this.#attribution(config.symbol));

    const script = document.createElement("script");
    script.type = "text/javascript";
    script.src = SCRIPT_URL;
    script.async = true;
    script.textContent = JSON.stringify(config);
    this.wrapper.appendChild(script);
    container.replaceChildren(this.wrapper);

    try {
      this.iframe = await this.#waitForIframe(script);
    } catch (error) {
      this.metrics.mountFailures += 1;
      this.metrics.lastErrorCode =
        error?.code || "tradingview.mount-failed";
      this.lifecycle =
        error?.code === "tradingview.load-timeout" ? "degraded" : "failed";
      this.code = this.metrics.lastErrorCode;
      this.retryable = true;
      this.#cleanupNodes();
      throw error;
    }

    const mountedAtMs = this.now();
    this.metrics.iframeLoads += 1;
    this.metrics.lastMountLatencyMs = Math.max(0, mountedAtMs - started);
    this.metrics.lastErrorCode = null;
    this.lifecycle = "ready";
    this.code = null;
    this.retryable = false;
    this.session = Object.freeze({
      providerId: this.providerId,
      targetRef: options.targetRef,
      symbol: options.symbol,
      interval: options.interval,
      themeRef: options.themeRef ?? null,
      mountedAtMs,
    });
    return this.session;
  }

  async setSymbol() {
    throw this.#unsupported("set_symbol");
  }

  async setInterval() {
    throw this.#unsupported("set_interval");
  }

  async setTheme() {
    throw this.#unsupported("set_theme");
  }

  async fullscreen() {
    throw this.#unsupported("fullscreen");
  }

  async destroy() {
    if (this.lifecycle === "destroyed") return;
    this.metrics.destroyCalls += 1;
    this.#cleanupNodes();
    this.session = null;
    this.mountKey = null;
    this.container = null;
    this.lifecycle = "destroyed";
    this.code = null;
    this.retryable = false;
  }

  stats() {
    return Object.freeze({
      providerId: this.providerId,
      product: "advanced-real-time-chart-widget",
      capabilities: [],
      lifecycle: this.health().lifecycle,
      ...this.metrics,
      runtimeMutation: false,
      advancedChartsLibrary: false,
    });
  }

  #validateContainer(container) {
    if (!(container instanceof HTMLElement)) {
      throw new TypeError("container must be an HTMLElement");
    }
  }

  #buildConfig(options = {}) {
    const symbolMap = {
      TOTAL: "CRYPTOCAP:TOTAL",
      BTCUSDT: "BINANCE:BTCUSDT.P",
      ETHUSDT: "BINANCE:ETHUSDT.P",
      SOLUSDT: "BINANCE:SOLUSDT.P",
      ADAUSDT: "BINANCE:ADAUSDT.P",
      XRPUSDT: "BINANCE:XRPUSDT.P",
    };
    const intervalMap = {
      "15m": "15",
      "1h": "60",
      "4h": "240",
      "1D": "D",
      "1W": "W",
    };
    if (!options.targetRef || !symbolMap[options.symbol]) {
      throw new TradingViewSpikeError(
        "tradingview.invalid-symbol",
        "The symbol is not in the static TradingView map.",
      );
    }
    if (!intervalMap[options.interval]) {
      throw new TradingViewSpikeError(
        "tradingview.invalid-interval",
        "The interval is not in the static TradingView map.",
      );
    }
    if (
      options.themeRef != null &&
      !["light", "dark"].includes(options.themeRef)
    ) {
      throw new TradingViewSpikeError(
        "tradingview.invalid-theme",
        "The public widget only accepts light or dark.",
      );
    }
    const config = {
      autosize: true,
      symbol: symbolMap[options.symbol],
      interval: intervalMap[options.interval],
      timezone: "Etc/UTC",
      style: "1",
      locale: "es",
      allow_symbol_change: true,
      calendar: false,
      support_host: "https://www.tradingview.com",
    };
    if (options.themeRef != null) config.theme = options.themeRef;
    return config;
  }

  #waitForIframe(script) {
    return new Promise((resolve, reject) => {
      let settled = false;
      let observedIframe = null;
      const finish = (callback, value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this.observer?.disconnect();
        this.observer = null;
        callback(value);
      };
      const watchIframe = () => {
        const iframe = this.wrapper?.querySelector("iframe");
        if (!iframe || iframe === observedIframe) return;
        observedIframe = iframe;
        iframe.addEventListener(
          "load",
          () => finish(resolve, iframe),
          { once: true },
        );
      };
      this.observer = new MutationObserver(watchIframe);
      this.observer.observe(this.wrapper, {
        childList: true,
        subtree: true,
      });
      watchIframe();
      script.addEventListener(
        "error",
        () =>
          finish(
            reject,
            new TradingViewSpikeError(
              "tradingview.script-error",
              "TradingView embed script failed to load.",
            ),
          ),
        { once: true },
      );
      const timer = setTimeout(
        () =>
          finish(
            reject,
            new TradingViewSpikeError(
              "tradingview.load-timeout",
              "TradingView iframe did not become ready before timeout.",
            ),
          ),
        this.timeoutMs,
      );
    });
  }

  #attribution(symbol) {
    const attribution = document.createElement("div");
    attribution.className = "tradingview-widget-copyright";
    const link = document.createElement("a");
    link.href = `https://www.tradingview.com/symbols/${encodeURIComponent(
      symbol.split(":")[1],
    )}/?exchange=BINANCE`;
    link.rel = "noopener nofollow";
    link.target = "_blank";
    link.textContent = "Chart by TradingView";
    attribution.appendChild(link);
    return attribution;
  }

  #unsupported(capability) {
    return new TradingViewSpikeError(
      "tradingview.capability-unsupported",
      `${capability} is not available in the public iframe widget.`,
    );
  }

  #cleanupNodes() {
    this.observer?.disconnect();
    this.observer = null;
    this.iframe = null;
    this.wrapper?.remove();
    this.wrapper = null;
  }
}
