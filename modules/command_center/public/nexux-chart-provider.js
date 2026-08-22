const BINANCE_WS = "wss://fstream.binance.com/stream?streams=";
const MAX_PAGE = 1000;
const INDICATOR_STORAGE_KEY = "nexux.command-center.chart-indicators.v4";
const SMC_INTERVALS = new Set(["1m", "5m", "15m", "1h", "4h", "1D"]);
const INDICATOR_DEFAULTS = Object.freeze({
  volume: false,
  structure: false,
  fvg: false,
  ob: false,
  cdc: false,
  ema: false,
  rsi: false,
  adx: false,
});

// Series y cálculos canónicos: UNA sola definición, compartida con NexUX
// Trading. Antes esto estaba duplicado acá y en `app.js`, y dos copias del
// mismo algoritmo pueden divergir sin que nadie lo note (gate 1 del renderer
// compartido). Se re-exportan para no romper a quien importe del proveedor.
export {
  INTERVALS,
  intervalSpec,
  aggregateCandles,
  emaValues,
  rsiValues,
  adxValues,
} from "../../../static/nexux-chart-series.js";
export {
  CONTRATO_SMC,
  CDC_ROTULO,
  dibujarFvg,
  dibujarOb,
  dibujarCdc,
  dibujarSmc,
  normalizarAnalisis,
} from "../../../static/nexux-smc-primitive.js";
import {
  dibujarSmc,
  normalizarAnalisis,
} from "../../../static/nexux-smc-primitive.js";
import {
  intervalSpec,
  aggregateCandles,
  emaValues,
  rsiValues,
  adxValues,
} from "../../../static/nexux-chart-series.js";

const SYMBOLS = Object.freeze({
  BTCUSDT: { binance: "BTCUSDT", local: "BTC_USDT", label: "BTC / USDT Perpetuo" },
  ETHUSDT: { binance: "ETHUSDT", local: "ETH_USDT", label: "ETH / USDT Perpetuo" },
  SOLUSDT: { binance: "SOLUSDT", local: "SOL_USDT", label: "SOL / USDT Perpetuo" },
  XRPUSDT: { binance: "XRPUSDT", local: "XRP_USDT", label: "XRP / USDT Perpetuo" },
  ADAUSDT: { binance: "ADAUSDT", local: "ADA_USDT", label: "ADA / USDT Perpetuo" },
});

export class NexuxChartError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "NexuxChartError";
    this.code = code;
  }
}

function finite(value, name) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    throw new NexuxChartError("nexux-chart.invalid-candle", `${name} no es numérico.`);
  }
  return number;
}

export function normalizeBinanceKline(row) {
  if (!Array.isArray(row) || row.length < 6) {
    throw new NexuxChartError("nexux-chart.invalid-candle", "Binance devolvió una vela incompleta.");
  }
  return {
    t: finite(row[0], "time"),
    o: finite(row[1], "open"),
    h: finite(row[2], "high"),
    l: finite(row[3], "low"),
    c: finite(row[4], "close"),
    v: finite(row[5], "volume"),
  };
}

function loadIndicatorState() {
  try {
    const saved = JSON.parse(globalThis.localStorage?.getItem(INDICATOR_STORAGE_KEY) || "{}");
    return { ...INDICATOR_DEFAULTS, ...saved };
  } catch (_error) {
    return { ...INDICATOR_DEFAULTS };
  }
}

class NexuxSmcRenderer {
  constructor(source) {
    this.source = source;
  }

  draw(target) {
    const source = this.source;
    const payload = source.data;
    if (!payload?.analysis || !source.series || !source.chart) return;
    const timeScale = source.chart.timeScale();
    // El dibujo de FVG, OB y CDC es COMPARTIDO con NexUX Trading: vive en
    // /static/nexux-smc-primitive.js y es una sola implementación. Acá solo se
    // normaliza el payload y se aportan los conversores de coordenadas.
    const capas = normalizarAnalisis(payload.analysis, payload.show || {});
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      dibujarSmc(context, capas, {
        ancho: mediaSize.width,
        alto: mediaSize.height,
        yAt: (price) => source.series.priceToCoordinate(Number(price)),
        xAt: (ms) => timeScale.timeToCoordinate(Math.floor(Number(ms) / 1000)),
      });
    });
  }
}

class NexuxSmcPaneView {
  constructor(source) {
    this.rendererInstance = new NexuxSmcRenderer(source);
  }
  update() {}
  renderer() { return this.rendererInstance; }
  zOrder() { return "bottom"; }
}

class NexuxSmcPrimitive {
  constructor() {
    this.data = null;
    this.views = [new NexuxSmcPaneView(this)];
  }
  attached(parameters) {
    this.series = parameters.series;
    this.chart = parameters.chart;
    this.requestUpdate = parameters.requestUpdate;
  }
  detached() {
    this.series = null;
    this.chart = null;
  }
  setData(data) {
    this.data = data;
    this.requestUpdate?.();
  }
  updateAllViews() { this.views.forEach((view) => view.update()); }
  paneViews() { return this.views; }
}

function mergeCandles(left, right) {
  const byTime = new Map(left.map((candle) => [candle.t, candle]));
  for (const candle of right) byTime.set(candle.t, candle);
  return [...byTime.values()].sort((a, b) => a.t - b.t);
}

function formatPrice(value) {
  const magnitude = Math.abs(value);
  const digits = magnitude >= 1000 ? 1 : magnitude >= 10 ? 2 : magnitude >= 1 ? 4 : 6;
  return value.toLocaleString("es-CL", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatVolume(value) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return value.toFixed(2);
}

export class NexuxChartProvider {
  constructor({
    fetcher = (...args) => fetch(...args),
    WebSocketClass = globalThis.WebSocket,
    now = () => Date.now(),
  } = {}) {
    this.providerId = "nexux-chart";
    this.fetcher = fetcher;
    this.WebSocketClass = WebSocketClass;
    this.now = now;
    this.lifecycle = "detached";
    this.container = null;
    this.root = null;
    this.chart = null;
    this.series = null;
    this.volume = null;
    this.emaFast = null;
    this.emaSlow = null;
    this.rsi = null;
    this.adx = null;
    this.structureLines = [];
    this.smcPrimitive = null;
    this.structureAnalysis = null;
    this.structureRevision = 0;
    this.dataRevision = 0;
    this.indicatorState = loadIndicatorState();
    this.indicatorMenu = null;
    this.indicatorSummary = null;
    this.indicatorPaintAt = 0;
    this.smcTimer = null;
    this.legend = null;
    this.feedState = null;
    this.session = null;
    this.symbol = null;
    this.interval = null;
    this.candles = [];
    this.rawCandles = [];
    this.hasMore = false;
    this.loadingOlder = false;
    this.socket = null;
    this.reconnectTimer = null;
    this.reconnectAttempt = 0;
    this.refreshTimer = null;
    this.lastFrameAt = 0;
    this.lastBookPaintAt = 0;
    this.source = "nexux-trading";
    this.liveStream = null;
    this.sourceLabel = "NexUX Trading";
    this.onPrice = null;
    this.metrics = {
      mountAttempts: 0,
      mountFailures: 0,
      lastMountLatencyMs: null,
      websocketReconnects: 0,
      candlesLoaded: 0,
    };
  }

  capabilities() {
    return Object.freeze(["set_symbol", "set_interval", "set_theme", "fullscreen"]);
  }

  health() {
    if (this.lifecycle === "ready" && this.socket && this.lastFrameAt && this.now() - this.lastFrameAt > 30_000) {
      return Object.freeze({
        providerId: this.providerId,
        lifecycle: "degraded",
        checkedAtMs: this.now(),
        code: "nexux-chart.feed-stale",
        retryable: true,
      });
    }
    return Object.freeze({
      providerId: this.providerId,
      lifecycle: this.lifecycle,
      checkedAtMs: this.now(),
      code: null,
      retryable: this.lifecycle === "degraded",
    });
  }

  async mount(container, options = {}) {
    if (!(container instanceof HTMLElement)) throw new TypeError("container must be an HTMLElement");
    if (!globalThis.LightweightCharts) {
      throw new NexuxChartError("nexux-chart.engine-missing", "Lightweight Charts no está cargado.");
    }
    if (!SYMBOLS[options.symbol]) {
      throw new NexuxChartError("nexux-chart.invalid-symbol", "Símbolo no disponible.");
    }
    intervalSpec(options.interval);
    if (this.session) throw new NexuxChartError("nexux-chart.already-mounted", "El gráfico ya está montado.");

    const started = this.now();
    this.metrics.mountAttempts += 1;
    this.lifecycle = "mounting";
    this.container = container;
    this.symbol = options.symbol;
    this.interval = options.interval;
    this.onPrice = typeof options.onPrice === "function" ? options.onPrice : null;
    this.#buildSurface();
    try {
      await this.#loadInitial();
      this.#connectLive();
      this.smcTimer = setInterval(() => this.#refreshStructure(), 30_000);
    } catch (error) {
      this.metrics.mountFailures += 1;
      this.lifecycle = "degraded";
      this.#setFeed("degraded", "Feed no disponible");
      throw error;
    }
    const mountedAtMs = this.now();
    this.metrics.lastMountLatencyMs = Math.max(0, mountedAtMs - started);
    this.lifecycle = "ready";
    this.session = Object.freeze({
      providerId: this.providerId,
      targetRef: options.targetRef,
      symbol: options.symbol,
      interval: options.interval,
      themeRef: options.themeRef ?? "dark",
      mountedAtMs,
    });
    return this.session;
  }

  async setSymbol(symbol) {
    if (!SYMBOLS[symbol]) throw new NexuxChartError("nexux-chart.invalid-symbol", "Símbolo no disponible.");
    if (!this.session) throw new NexuxChartError("nexux-chart.not-mounted", "El gráfico no está montado.");
    this.symbol = symbol;
    await this.#reload();
    this.session = Object.freeze({ ...this.session, symbol });
  }

  async setInterval(interval) {
    intervalSpec(interval);
    if (!this.session) throw new NexuxChartError("nexux-chart.not-mounted", "El gráfico no está montado.");
    if (interval === this.interval) return this.session;

    const revision = ++this.dataRevision;
    const previousInterval = this.interval;
    this.structureRevision += 1;
    this.#closeSocket();
    this.#setFeed("loading", `Cargando ${interval}`);
    try {
      const page = await this.#requestPage(null, this.symbol, interval);
      if (revision !== this.dataRevision || this.lifecycle === "destroyed") return this.session;
      this.structureAnalysis = null;
      this.#applyStructureLines();
      this.#pushSmcOverlay();
      this.interval = interval;
      this.rawCandles = page.candles;
      this.candles = aggregateCandles(page.candles, interval);
      this.hasMore = page.hasMore;
      this.#adoptSource(page);
      this.#paint(true);
      this.#refreshStructure({ clear: true });
      this.metrics.candlesLoaded = this.candles.length;
      this.#connectLive();
      this.#setFeed("current", this.sourceLabel);
      this.session = Object.freeze({ ...this.session, interval });
      return this.session;
    } catch (error) {
      if (revision === this.dataRevision && this.lifecycle !== "destroyed") {
        this.interval = previousInterval;
        this.#connectLive();
        this.#setFeed("degraded", `No se pudo cargar ${interval}`);
      }
      throw error;
    }
  }

  async setTheme(themeRef) {
    if (themeRef !== "dark") {
      throw new NexuxChartError("nexux-chart.invalid-theme", "Command Center utiliza el tema oscuro NexUX.");
    }
  }

  async fullscreen() {
    await this.container?.requestFullscreen?.();
  }

  async destroy() {
    clearInterval(this.refreshTimer);
    clearInterval(this.smcTimer);
    clearTimeout(this.reconnectTimer);
    this.refreshTimer = null;
    this.reconnectTimer = null;
    this.#closeSocket();
    this.dataRevision += 1;
    this.structureRevision += 1;
    this.chart?.remove();
    this.chart = null;
    this.series = null;
    this.volume = null;
    this.emaFast = null;
    this.emaSlow = null;
    this.rsi = null;
    this.adx = null;
    this.structureLines = [];
    this.smcPrimitive = null;
    this.root?.remove();
    this.root = null;
    this.container = null;
    this.session = null;
    this.onPrice = null;
    this.lifecycle = "destroyed";
  }

  stats() {
    return Object.freeze({
      providerId: this.providerId,
      product: "nexux-futures-chart",
      lifecycle: this.health().lifecycle,
      capabilities: this.capabilities(),
      source: this.source,
      ...this.metrics,
    });
  }

  #buildSurface() {
    const LC = globalThis.LightweightCharts;
    const root = document.createElement("div");
    root.className = "nexux-chart";
    root.innerHTML = `
      <div class="nexux-chart-canvas"></div>
      <div class="nexux-chart-legend" aria-live="off"></div>
      <div class="nexux-chart-feed" data-state="loading"><i></i><span>Conectando Binance</span></div>
      <div class="nexux-chart-indicators">
        <button type="button" class="nexux-chart-indicator-trigger" aria-expanded="false">Indicadores</button>
        <div class="nexux-chart-indicator-menu" hidden></div>
        <span class="nexux-chart-indicator-summary"></span>
      </div>
      <button class="nexux-chart-now" type="button" title="Ir al presente" aria-label="Ir al presente">›</button>
      <a class="nexux-chart-credit" href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">Lightweight Charts™</a>`;
    this.container.replaceChildren(root);
    this.root = root;
    this.legend = root.querySelector(".nexux-chart-legend");
    this.feedState = root.querySelector(".nexux-chart-feed");
    this.indicatorMenu = root.querySelector(".nexux-chart-indicator-menu");
    this.indicatorSummary = root.querySelector(".nexux-chart-indicator-summary");
    const canvas = root.querySelector(".nexux-chart-canvas");
    this.chart = LC.createChart(canvas, {
      autoSize: true,
      layout: {
        background: { color: "#060b12" },
        textColor: "#9aa9bd",
        fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
        fontSize: 13,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "rgba(84, 113, 145, 0.14)" },
        horzLines: { color: "rgba(84, 113, 145, 0.14)" },
      },
      crosshair: {
        mode: LC.CrosshairMode.Normal,
        vertLine: { color: "rgba(25, 217, 255, 0.48)", labelBackgroundColor: "#0c7087" },
        horzLine: { color: "rgba(25, 217, 255, 0.34)", labelBackgroundColor: "#0c7087" },
      },
      rightPriceScale: { borderColor: "rgba(72, 105, 139, 0.48)", minimumWidth: 86 },
      timeScale: {
        borderColor: "rgba(72, 105, 139, 0.48)",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: 7,
      },
      localization: { locale: "es-CL" },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    });
    this.series = this.chart.addSeries(LC.CandlestickSeries, {
      upColor: "#16d9a6",
      downColor: "#ff3d62",
      borderVisible: false,
      wickUpColor: "#2af0bd",
      wickDownColor: "#ff5574",
      priceLineColor: "#22d3ee",
      priceLineWidth: 1,
    });
    this.smcPrimitive = new NexuxSmcPrimitive();
    this.series.attachPrimitive(this.smcPrimitive);
    this.volume = this.chart.addSeries(LC.HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    this.volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    this.#buildIndicatorControls();
    this.#rebuildIndicators();
    this.chart.subscribeCrosshairMove((parameter) => {
      if (!parameter?.time) return this.#renderLegend();
      const candle = parameter.seriesData?.get(this.series);
      const volume = parameter.seriesData?.get(this.volume);
      if (candle) this.#renderLegend({ ...candle, v: volume?.value ?? 0 });
    });
    this.chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      root.querySelector(".nexux-chart-now").classList.toggle(
        "visible",
        Boolean(range && this.candles.length && range.to < this.candles.length - 3),
      );
      if (range && range.from < 12 && this.hasMore) this.#loadOlder().catch(() => {});
    });
    root.querySelector(".nexux-chart-now").addEventListener("click", () => {
      this.chart.timeScale().scrollToRealTime();
    });
  }

  async #requestPage(endTime = null, symbolId = this.symbol, interval = this.interval) {
    const symbol = SYMBOLS[symbolId];
    const spec = intervalSpec(interval);
    const query = new URLSearchParams({
      instrument: symbol.local,
      timeframe: spec.source,
      limit: String(MAX_PAGE),
    });
    // El llamador conserva la convención histórica endTime=primera_t-1.
    // El endpoint canónico pagina con before exclusivo.
    if (endTime != null) query.set("before", String(Number(endTime) + 1));
    const response = await this.fetcher(`/m/trading/api/candles?${query}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      throw new NexuxChartError("nexux-chart.source-http", `NexUX Trading respondió HTTP ${response.status}.`);
    }
    const payload = await response.json();
    if (!Array.isArray(payload?.candles) || !payload.candles.length) {
      throw new NexuxChartError("nexux-chart.empty-history", "NexUX Trading no devolvió historial.");
    }
    return {
      candles: payload.candles.map((candle) => ({
        t: finite(candle.t, "time"), o: finite(candle.o, "open"),
        h: finite(candle.h, "high"), l: finite(candle.l, "low"),
        c: finite(candle.c, "close"), v: finite(candle.v, "volume"),
      })),
      hasMore: Boolean(payload.has_more),
      source: payload.fuente || "unknown",
      stream: payload.stream_vivo || null,
    };
  }

  async #loadInitial() {
    this.#setFeed("loading", "Cargando NexUX Trading");
    const page = await this.#requestPage();
    this.rawCandles = page.candles;
    this.candles = aggregateCandles(page.candles, this.interval);
    this.hasMore = page.hasMore;
    this.#adoptSource(page);
    this.#paint(true);
    this.#refreshStructure({ clear: true });
    this.metrics.candlesLoaded = this.candles.length;
    this.#setFeed("current", this.sourceLabel);
  }

  async #refresh() {
    if (!this.series || !this.symbol) return;
    const page = await this.#requestPage();
    this.rawCandles = mergeCandles(this.rawCandles, page.candles);
    this.candles = aggregateCandles(this.rawCandles, this.interval);
    this.#adoptSource(page);
    this.#paint(false);
  }

  async #reload() {
    this.#closeSocket();
    this.rawCandles = [];
    this.candles = [];
    this.hasMore = false;
    await this.#loadInitial();
    this.#connectLive();
  }

  async #loadOlder() {
    if (this.loadingOlder || !this.rawCandles.length || !this.hasMore) return;
    this.loadingOlder = true;
    const previousRange = this.chart.timeScale().getVisibleLogicalRange();
    try {
      const page = await this.#requestPage(this.rawCandles[0].t - 1);
      const before = this.candles.length;
      this.rawCandles = mergeCandles(page.candles, this.rawCandles);
      this.candles = aggregateCandles(this.rawCandles, this.interval);
      this.hasMore = page.hasMore;
      this.#paint(false);
      const added = this.candles.length - before;
      if (previousRange && added > 0) {
        this.chart.timeScale().setVisibleLogicalRange({
          from: previousRange.from + added,
          to: previousRange.to + added,
        });
      }
    } finally {
      this.loadingOlder = false;
    }
  }

  #paint(frame) {
    const bars = this.candles.map((candle) => ({
      time: Math.floor(candle.t / 1000),
      open: candle.o,
      high: candle.h,
      low: candle.l,
      close: candle.c,
    }));
    const volumes = this.candles.map((candle) => ({
      time: Math.floor(candle.t / 1000),
      value: candle.v,
      color: candle.c >= candle.o ? "rgba(22, 217, 166, 0.42)" : "rgba(255, 61, 98, 0.42)",
    }));
    this.series.setData(bars);
    this.volume.setData(volumes);
    this.volume.applyOptions({ visible: this.indicatorState.volume });
    const last = this.candles.at(-1);
    if (last) {
      const magnitude = Math.abs(last.c);
      const precision = magnitude >= 100 ? 1 : magnitude >= 10 ? 2 : magnitude >= 1 ? 4 : 6;
      this.series.applyOptions({
        priceFormat: { type: "price", precision, minMove: 10 ** -precision },
      });
      this.#emitPrice(last.c);
    }
    this.#renderLegend();
    this.#paintIndicators(true);
    if (frame) {
      const count = bars.length;
      this.chart.timeScale().setVisibleLogicalRange({
        from: Math.max(0, count - 190),
        to: count + 6,
      });
    }
  }

  #renderLegend(candle = this.candles.at(-1)) {
    if (!this.legend || !candle) return;
    const change = candle.o ? ((candle.c - candle.o) / candle.o) * 100 : 0;
    this.legend.innerHTML = `
      <strong>${SYMBOLS[this.symbol].label}</strong>
      <span>O <b>${formatPrice(candle.o)}</b></span>
      <span>H <b>${formatPrice(candle.h)}</b></span>
      <span>L <b>${formatPrice(candle.l)}</b></span>
      <span>C <b>${formatPrice(candle.c)}</b></span>
      <span class="${change >= 0 ? "up" : "down"}">${change >= 0 ? "+" : ""}${change.toFixed(2)}%</span>
      <span>Vol <b>${formatVolume(candle.v || 0)}</b></span>`;
  }

  #connectLive() {
    if (!this.WebSocketClass) return this.#setFeed("degraded", "Sin WebSocket");
    this.#closeSocket();
    if (!this.liveStream) {
      this.#setFeed("current", this.sourceLabel);
      return;
    }
    const kline = this.liveStream;
    const symbol = kline.split("@")[0];
    const ticker = `${symbol}@bookTicker`;
    const socket = new this.WebSocketClass(`${BINANCE_WS}${kline}/${ticker}`);
    this.socket = socket;
    socket.onopen = () => {
      this.reconnectAttempt = 0;
      this.#setFeed("loading", "Sincronizando en vivo");
    };
    socket.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch (_error) { return; }
      const data = message.data || message;
      this.lastFrameAt = this.now();
      if (data.k) {
        const klineData = {
          t: Number(data.k.t), o: Number(data.k.o), h: Number(data.k.h),
          l: Number(data.k.l), c: Number(data.k.c), v: Number(data.k.v),
        };
        this.#applyLiveCandle(klineData);
      } else if (data.e === "bookTicker" && data.b && data.a) {
        const now = this.now();
        if (now - this.lastBookPaintAt >= 120) {
          this.lastBookPaintAt = now;
          this.#extendLivePrice((Number(data.b) + Number(data.a)) / 2);
        }
      }
      this.#setFeed("live", `${this.sourceLabel} · en vivo`);
    };
    socket.onerror = () => this.#setFeed("degraded", "Reconectando feed");
    socket.onclose = () => {
      if (this.lifecycle === "destroyed") return;
      this.#setFeed("degraded", "Reconectando feed");
      const delay = Math.min(60_000, 2000 * (2 ** this.reconnectAttempt));
      this.reconnectAttempt += 1;
      this.metrics.websocketReconnects += 1;
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = setTimeout(() => this.#connectLive(), delay);
    };
  }

  #applyLiveCandle(candle) {
    this.rawCandles = mergeCandles(this.rawCandles, [candle]);
    const aggregated = aggregateCandles(this.rawCandles.slice(-Math.max(8, intervalSpec(this.interval).aggregate * 3)), this.interval);
    const live = aggregated.at(-1);
    if (!live) return;
    this.candles = mergeCandles(this.candles, [live]);
    this.#updateLast(live);
  }

  #extendLivePrice(price) {
    const last = this.candles.at(-1);
    if (!last || !Number.isFinite(price)) return;
    const updated = { ...last, h: Math.max(last.h, price), l: Math.min(last.l, price), c: price };
    this.candles[this.candles.length - 1] = updated;
    this.#updateLast(updated);
  }

  #updateLast(candle) {
    const time = Math.floor(candle.t / 1000);
    this.series.update({ time, open: candle.o, high: candle.h, low: candle.l, close: candle.c });
    this.volume.update({
      time,
      value: candle.v,
      color: candle.c >= candle.o ? "rgba(22, 217, 166, 0.42)" : "rgba(255, 61, 98, 0.42)",
    });
    this.#renderLegend(candle);
    this.#paintIndicators(false);
    this.#emitPrice(candle.c);
  }

  #closeSocket() {
    if (!this.socket) return;
    try {
      this.socket.onclose = null;
      this.socket.close();
    } catch (_error) {
      // Destruir debe ser idempotente incluso si WebKit ya cerró el socket.
    }
    this.socket = null;
  }

  #adoptSource(page) {
    this.liveStream = page.stream;
    this.sourceLabel = page.source === "binance_vps" ? "Binance Futuros"
      : page.source === "cryptocom" ? "Crypto.com · vía NexUX"
      : "NexUX Trading";
  }

  #setFeed(state, label) {
    if (!this.feedState) return;
    this.feedState.dataset.state = state;
    this.feedState.querySelector("span").textContent = label;
  }

  #emitPrice(price) {
    if (!this.onPrice || !Number.isFinite(price)) return;
    this.onPrice(Object.freeze({
      symbol: this.symbol,
      price,
      observedAt: this.now(),
      source: this.source,
    }));
  }

  #buildIndicatorControls() {
    const definitions = [
      ["volume", "Volumen", "Actividad negociada por vela"],
      ["structure", "Estructura NexUX", "Strong High, Weak Low y equilibrio"],
      ["fvg", "FVG", "Desequilibrios vigentes del precio"],
      ["ob", "Order Blocks", "POI válidos y zonas mitigadas"],
      ["cdc", "CDC", "Cambios de carácter confirmados"],
      ["ema", "EMA 21 / 55", "Cinta de tendencia sobre el precio"],
      ["rsi", "RSI 14", "Momento relativo en panel independiente"],
      ["adx", "ADX 14", "Fuerza de tendencia en panel independiente"],
    ];
    for (const [key, label, description] of definitions) {
      const control = document.createElement("label");
      control.className = "nexux-chart-indicator-option";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = Boolean(this.indicatorState[key]);
      checkbox.dataset.indicator = key;
      const copy = document.createElement("span");
      copy.innerHTML = `<strong>${label}</strong><small>${description}</small>`;
      checkbox.addEventListener("change", () => {
        this.indicatorState[key] = checkbox.checked;
        try {
          globalThis.localStorage?.setItem(INDICATOR_STORAGE_KEY, JSON.stringify(this.indicatorState));
        } catch (_error) {
          // La preferencia visual no debe degradar el gráfico si el storage está bloqueado.
        }
        this.#rebuildIndicators();
        this.#paintIndicators(true);
        if (["structure", "fvg", "ob", "cdc"].includes(key)) {
          this.#applyStructureLines();
          this.#pushSmcOverlay();
          this.#renderIndicatorSummary();
          if (checkbox.checked && !this.structureAnalysis) this.#refreshStructure();
        } else {
          this.#applyStructureLines();
          this.#pushSmcOverlay();
        }
      });
      control.append(checkbox, copy);
      this.indicatorMenu.append(control);
    }
    const trigger = this.root.querySelector(".nexux-chart-indicator-trigger");
    trigger.addEventListener("click", () => {
      const open = this.indicatorMenu.hidden;
      this.indicatorMenu.hidden = !open;
      trigger.setAttribute("aria-expanded", String(open));
    });
    this.root.addEventListener("pointerdown", (event) => {
      if (event.target.closest(".nexux-chart-indicators")) return;
      this.indicatorMenu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    });
    this.#renderIndicatorSummary();
  }

  #rebuildIndicators() {
    const LC = globalThis.LightweightCharts;
    const remove = (name) => {
      if (!this[name]) return;
      try { this.chart.removeSeries(this[name]); } catch (_error) { /* already removed */ }
      this[name] = null;
    };
    ["emaFast", "emaSlow", "rsi", "adx"].forEach(remove);
    this.volume?.applyOptions({ visible: this.indicatorState.volume });
    if (this.indicatorState.ema) {
      this.emaFast = this.chart.addSeries(LC.LineSeries, {
        color: "#22d3ee", lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
      });
      this.emaSlow = this.chart.addSeries(LC.LineSeries, {
        color: "#b45cff", lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
      });
    }
    let pane = 1;
    if (this.indicatorState.rsi) {
      this.rsi = this.chart.addSeries(LC.LineSeries, {
        color: "#b98cff", lineWidth: 2, priceLineVisible: false,
        priceFormat: { type: "price", precision: 1, minMove: 0.1 },
      }, pane);
      [[70, "rgba(255,61,98,0.55)"], [50, "rgba(154,169,189,0.28)"], [30, "rgba(22,217,166,0.55)"]]
        .forEach(([price, color]) => this.rsi.createPriceLine({
          price, color, lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true,
        }));
      pane += 1;
    }
    if (this.indicatorState.adx) {
      this.adx = this.chart.addSeries(LC.LineSeries, {
        color: "#ffba3b", lineWidth: 2, priceLineVisible: false,
        priceFormat: { type: "price", precision: 1, minMove: 0.1 },
      }, pane);
      this.adx.createPriceLine({
        price: 25, color: "rgba(154,169,189,0.4)", lineWidth: 1,
        lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true,
      });
    }
    queueMicrotask(() => {
      const panes = this.chart?.panes?.() || [];
      for (let index = 1; index < panes.length; index += 1) {
        try { panes[index].setHeight(105); } catch (_error) { /* older engine */ }
      }
    });
    this.#renderIndicatorSummary();
  }

  #paintIndicators(force) {
    const now = this.now();
    if (!force && now - this.indicatorPaintAt < 500) return;
    this.indicatorPaintAt = now;
    if (!this.candles.length) return;
    const times = this.candles.map((candle) => Math.floor(candle.t / 1000));
    const closes = this.candles.map((candle) => candle.c);
    if (this.emaFast && this.emaSlow) {
      const fast = emaValues(closes, 21);
      const slow = emaValues(closes, 55);
      this.emaFast.setData(times.map((time, index) => ({ time, value: fast[index] })));
      this.emaSlow.setData(times.map((time, index) => ({ time, value: slow[index] })));
    }
    if (this.rsi) {
      const values = rsiValues(closes, 14);
      this.rsi.setData(times.flatMap((time, index) => (
        values[index] == null ? [] : [{ time, value: values[index] }]
      )));
    }
    if (this.adx) {
      const values = adxValues(this.candles, 14);
      this.adx.setData(times.flatMap((time, index) => (
        values[index] == null ? [] : [{ time, value: values[index] }]
      )));
    }
  }

  #refreshStructure({ clear = false } = {}) {
    const revision = ++this.structureRevision;
    if (clear) {
      this.structureAnalysis = null;
      this.#applyStructureLines();
      this.#pushSmcOverlay();
      this.#renderIndicatorSummary();
    }
    this.#loadStructure(revision).catch(() => {});
  }

  async #loadStructure(revision) {
    const requested = ["structure", "fvg", "ob", "cdc"]
      .some((key) => this.indicatorState[key]);
    if (!requested || !SMC_INTERVALS.has(this.interval)) {
      return;
    }
    const symbol = SYMBOLS[this.symbol];
    const interval = this.interval;
    const query = new URLSearchParams({ instrument: symbol.local, timeframe: interval });
    let analysis = null;
    try {
      const response = await this.fetcher(`/m/trading/api/smc?${query}`, {
        headers: { Accept: "application/json" }, cache: "no-store",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      analysis = await response.json();
    } catch (_error) {
      analysis = null;
    }
    if (
      revision !== this.structureRevision ||
      this.lifecycle === "destroyed" ||
      this.symbol !== symbol.binance ||
      this.interval !== interval
    ) return;
    this.structureAnalysis = analysis;
    this.#applyStructureLines();
    this.#pushSmcOverlay();
    this.#renderIndicatorSummary();
  }

  #applyStructureLines() {
    for (const line of this.structureLines) {
      try { this.series?.removePriceLine(line); } catch (_error) { /* already removed */ }
    }
    this.structureLines = [];
    if (!this.indicatorState.structure || !this.structureAnalysis?.range || !this.series) return;
    const LC = globalThis.LightweightCharts;
    const range = this.structureAnalysis.range;
    const definitions = [
      [range.strong_high, "#ff3d62", "Strong High", "#be2340"],
      [range.eq, "#b45cff", "EQ 50%", "#6f35a4"],
      [range.weak_low, "#16d9a6", "Weak Low", "#087e62"],
    ];
    for (const [price, color, title, axisLabelColor] of definitions) {
      if (!Number.isFinite(Number(price))) continue;
      this.structureLines.push(this.series.createPriceLine({
        price: Number(price), color, title, axisLabelColor, axisLabelTextColor: "#ffffff",
        lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true,
      }));
    }
  }

  #renderIndicatorSummary() {
    if (!this.indicatorSummary) return;
    const active = [];
    const smcRequested = ["structure", "fvg", "ob", "cdc"]
      .some((key) => this.indicatorState[key]);
    const contract = this.structureAnalysis?.visual_contract;
    const legacySmc = Boolean(
      contract && contract.validated === false && contract.bot3_compatible === false,
    );
    const smcLabel = legacySmc ? "SMC legado" : "SMC";
    if (this.indicatorState.structure && SMC_INTERVALS.has(this.interval)) {
      active.push(smcLabel);
    }
    if (this.indicatorState.ema) active.push("EMA 21/55");
    if (SMC_INTERVALS.has(this.interval)) {
      if (this.indicatorState.fvg) active.push("FVG");
      if (this.indicatorState.ob) active.push("OB");
      if (this.indicatorState.cdc) active.push("CDC");
    } else if (smcRequested) active.push(`${smcLabel} no disponible`);
    if (this.indicatorState.rsi) active.push("RSI");
    if (this.indicatorState.adx) active.push("ADX");
    if (this.indicatorState.volume) active.push("VOL");
    this.indicatorSummary.textContent = active.join(" · ") || "Sin capas";
    this.indicatorSummary.dataset.degraded = String(
      smcRequested && !SMC_INTERVALS.has(this.interval),
    );
  }

  #pushSmcOverlay() {
    this.smcPrimitive?.setData({
      analysis: this.structureAnalysis,
      show: {
        fvg: this.indicatorState.fvg,
        ob: this.indicatorState.ob,
        cdc: this.indicatorState.cdc,
      },
    });
  }
}
