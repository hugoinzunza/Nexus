import { TradingViewWidgetAdapter } from "./tradingview-spike.js?v=20260815-chart-clock";
import { NexuxChartProvider } from "./nexux-chart-provider.js?v=20260816-chart-stability-v3";

export const CONTRACT_VERSION = 1;
export const CONTRACT_FINGERPRINT =
  "b0a8a7efa623a1aae4b681c3cfc42790d36a6a14fbc689688026c523f2e49b46";

const SNAPSHOT_URL = "/m/command-center/api/snapshot";
const MACRO_URL = "/m/trading/api/dashboard?translate=0";
const MARKET_RIBBON_URL = "/m/command-center/api/market-ribbon";
const AI_CONTEXT_URL = "/m/command-center/api/ai-context";
const POSITIONS_CONTEXT_URL = "/m/command-center/api/positions-context";
const MACOS_CONTEXT_URL = "/m/command-center/api/macos-context";
const BOT_CONTEXT_URL = "/m/command-center/api/bot-context";
const MEDIA_CONTEXT_URL = "/m/command-center/api/media-context";
const MEDIA_COMMAND_URL = "/m/command-center/api/media-command";
const HEALTH_URL = "/health";
const WS_PATH = "/m/command-center/ws";
const RECONNECT_DELAYS = [1000, 2000, 5000, 10000, 15000];
const TRADING_DEGRADED_AFTER_MS = 60_000;
const TRADING_FAILED_AFTER_MS = 120_000;
const FIXTURE_STATES = new Set([
  "ready",
  "degraded",
  "stale",
  "expired",
  "disconnected",
]);

export function mergePatch(target, patch) {
  if (patch === null || typeof patch !== "object" || Array.isArray(patch)) {
    return structuredClone(patch);
  }
  const output =
    target && typeof target === "object" && !Array.isArray(target)
      ? structuredClone(target)
      : {};
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) {
      delete output[key];
    } else {
      output[key] = mergePatch(output[key], value);
    }
  }
  return output;
}

export function projectionFreshness(envelope, now = Date.now()) {
  if (!envelope) return "unknown";
  if (now >= envelope.expires_at) return "expired";
  if (now >= envelope.stale_at) return "stale";
  return envelope.payload?.state?.freshness || "unknown";
}

export function selectNextHighImpact(calendar, nowSeconds = Date.now() / 1000) {
  return (Array.isArray(calendar) ? calendar : [])
    .filter(
      (event) =>
        String(event?.impact || "").toLowerCase() === "high" &&
        Number.isFinite(Number(event?.ts)) &&
        Number(event.ts) >= nowSeconds,
    )
    .sort((left, right) => Number(left.ts) - Number(right.ts))[0] || null;
}

export function formatMacroCountdown(eventTimestamp, now = Date.now()) {
  const remainingSeconds = Math.max(
    0,
    Math.round(Number(eventTimestamp) - now / 1000),
  );
  if (remainingSeconds < 60) return "ahora";
  const minutes = Math.ceil(remainingSeconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} h ${remainder} min` : `${hours} h`;
}

export class MacroContextClient {
  constructor({
    dashboardUrl = MACRO_URL,
    fetcher = (...args) => fetch(...args),
    onChange = () => {},
    now = () => Date.now(),
  } = {}) {
    this.dashboardUrl = dashboardUrl;
    this.fetcher = fetcher;
    this.onChange = onChange;
    this.now = now;
    this.status = "loading";
    this.event = null;
    this.events = [];
    this.generatedAt = null;
    this.error = null;
    this.refreshTimer = null;
    this.countdownTimer = null;
  }

  state() {
    return {
      status: this.status,
      event: this.event,
      events: this.events,
      generatedAt: this.generatedAt,
      error: this.error,
      now: this.now(),
    };
  }

  async start() {
    await this.refresh();
    this.refreshTimer = setInterval(() => {
      this.refresh().catch(() => {});
    }, 60_000);
    this.countdownTimer = setInterval(() => this.onChange(this.state()), 1000);
  }

  stop() {
    clearInterval(this.refreshTimer);
    clearInterval(this.countdownTimer);
    this.refreshTimer = null;
    this.countdownTimer = null;
  }

  async refresh() {
    try {
      const response = await this.fetcher(this.dashboardUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`dashboard HTTP ${response.status}`);
      const dashboard = await response.json();
      this.events = Array.isArray(dashboard?.calendar)
        ? dashboard.calendar.filter((event) => Number.isFinite(Number(event?.ts)))
        : [];
      this.event = selectNextHighImpact(
        this.events,
        this.now() / 1000,
      );
      this.generatedAt = Number.isFinite(Number(dashboard?.generated_at_ms))
        ? Number(dashboard.generated_at_ms)
        : this.now();
      this.status = this.event ? "ready" : "empty";
      this.error = null;
    } catch (error) {
      this.status = "degraded";
      this.error = error?.message || "calendario no disponible";
    }
    this.onChange(this.state());
  }
}

export function calendarMonthCells(year, month) {
  const first = new Date(year, month, 1);
  const mondayOffset = (first.getDay() + 6) % 7;
  const start = new Date(year, month, 1 - mondayOffset);
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return {
      key: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`,
      timestampMs: date.getTime(),
      day: date.getDate(),
      currentMonth: date.getMonth() === month,
    };
  });
}

export function formatCalendarMonth(year, month, locale = "es-CL") {
  const monthName = new Intl.DateTimeFormat(locale, { month: "long" })
    .format(new Date(year, month, 1))
    .replace(/^./, (value) => value.toUpperCase());
  return `${monthName} ${year}`;
}

export function localCalendarDateKey(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function formatCalendarEventTime(event, locale = "es-CL") {
  if (event?.all_day === true) return "Todo el día";
  const timestampMs = Number(event?.start_ms ?? Number(event?.ts) * 1000);
  if (!Number.isFinite(timestampMs)) return "Hora pendiente";
  return new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(timestampMs));
}

export function formatCalendarEventLabel(event, locale = "es-CL") {
  return `${formatCalendarEventTime(event, locale)} · ${String(event?.title || "Evento")}`;
}

class CalendarSurface {
  constructor() {
    const now = new Date();
    this.year = now.getFullYear();
    this.month = now.getMonth();
    this.todayKey = localCalendarDateKey(now);
    this.selectedDateKey = this.todayKey;
    this.personalEvents = [];
    this.macroEvents = [];
    this.requestGeneration = 0;
    this.retryTimer = null;
    this.native = Boolean(window.webkit?.messageHandlers?.commandCenter);
  }

  start() {
    window.__nexuxCalendarReceive = (payload) => {
      if (Number(payload?.year) !== this.year || Number(payload?.month) !== this.month + 1) return;
      this.requestGeneration += 1;
      clearTimeout(this.retryTimer);
      this.personalEvents = Array.isArray(payload?.events) ? payload.events : [];
      const status = document.querySelector("#calendar-status");
      status.textContent = payload?.status === "ready"
        ? `${this.personalEvents.length} evento${this.personalEvents.length === 1 ? "" : "s"}`
        : payload?.message || "Calendar no disponible";
      this.render();
    };
    document.querySelector("#calendar-previous").addEventListener("click", () => this.move(-1));
    document.querySelector("#calendar-next").addEventListener("click", () => this.move(1));
    document.querySelector("#calendar-today").addEventListener("click", () => {
      const now = new Date();
      this.year = now.getFullYear();
      this.month = now.getMonth();
      this.selectedDateKey = localCalendarDateKey(now);
      this.request();
    });
    this.render();
    setTimeout(() => this.request(), this.native ? 750 : 0);
    this.dayTimer = setInterval(() => this.syncCalendarDay(), 30_000);
  }

  syncCalendarDay(now = new Date()) {
    const nextKey = localCalendarDateKey(now);
    if (nextKey === this.todayKey) return;
    this.todayKey = nextKey;
    this.selectedDateKey = nextKey;
    this.year = now.getFullYear();
    this.month = now.getMonth();
    this.personalEvents = [];
    this.request();
  }

  setMacroEvents(events) {
    this.macroEvents = Array.isArray(events) ? events : [];
    this.render();
  }

  move(delta) {
    const date = new Date(this.year, this.month + delta, 1);
    this.year = date.getFullYear();
    this.month = date.getMonth();
    this.selectedDateKey = null;
    this.personalEvents = [];
    this.request();
  }

  request(allowRetry = true) {
    this.render();
    if (!this.native) {
      document.querySelector("#calendar-status").textContent = "Disponible en la app NexUX";
      return;
    }
    const generation = ++this.requestGeneration;
    window.webkit.messageHandlers.commandCenter.postMessage({
      type: "calendarMonth", year: this.year, month: this.month + 1,
    });
    clearTimeout(this.retryTimer);
    if (allowRetry) {
      this.retryTimer = setTimeout(() => {
        if (this.requestGeneration === generation) this.request(false);
      }, 2500);
    }
  }

  render() {
    document.querySelector("#calendar-title").textContent = formatCalendarMonth(
      this.year,
      this.month,
    );
    const personalByDay = new Map();
    for (const event of this.personalEvents) {
      const date = new Date(Number(event.start_ms));
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
      if (!personalByDay.has(key)) personalByDay.set(key, []);
      personalByDay.get(key).push(event);
    }
    const macroByDay = new Map();
    for (const event of this.macroEvents) {
      const date = new Date(Number(event.ts) * 1000);
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
      if (!macroByDay.has(key)) macroByDay.set(key, []);
      macroByDay.get(key).push(event);
    }
    const todayKey = localCalendarDateKey();
    const grid = document.querySelector("#calendar-grid");
    grid.replaceChildren(...calendarMonthCells(this.year, this.month).map((cell) => {
      const personal = personalByDay.get(cell.key) || [];
      const macro = macroByDay.get(cell.key) || [];
      const dayButton = document.createElement("button");
      dayButton.type = "button";
      dayButton.className = "calendar-day";
      dayButton.dataset.outside = String(!cell.currentMonth);
      dayButton.dataset.today = String(cell.key === todayKey);
      dayButton.dataset.selected = String(cell.key === this.selectedDateKey);
      dayButton.disabled = !personal.length && !macro.length;
      dayButton.title = [
        ...personal.map((event) => formatCalendarEventLabel(event)),
        ...macro.map((event) => formatCalendarEventLabel(event)),
      ].join(" · ");
      const number = document.createElement("span");
      number.textContent = String(cell.day);
      const dots = document.createElement("i");
      dots.className = "calendar-dots";
      if (personal.length) dots.append(Object.assign(document.createElement("b"), { className: "personal" }));
      if (macro.length) dots.append(Object.assign(document.createElement("b"), { className: "macro" }));
      dayButton.append(number, dots);
      dayButton.addEventListener("click", () => {
        this.selectedDateKey = cell.key;
        this.render();
        if (this.native) {
          window.webkit.messageHandlers.commandCenter.postMessage({
            type: "openCalendar", timestampMs: cell.timestampMs,
          });
        }
      });
      return dayButton;
    }));
    const selectedPersonal = personalByDay.get(this.selectedDateKey) || [];
    const selectedMacro = macroByDay.get(this.selectedDateKey) || [];
    const selectedEvents = [...selectedPersonal, ...selectedMacro]
      .sort((left, right) => Number(left.start_ms ?? Number(left.ts) * 1000) -
        Number(right.start_ms ?? Number(right.ts) * 1000));
    const selectedLabels = [...new Map(selectedEvents.map((event) => [
      formatCalendarEventLabel(event), event,
    ])).values()];
    const selection = document.querySelector("#calendar-selection");
    if (selectedLabels.length) {
      selection.replaceChildren(...selectedLabels.slice(0, 2).map((event) => {
        const row = document.createElement("span");
        row.className = "calendar-event-summary";
        const time = document.createElement("small");
        time.textContent = formatCalendarEventTime(event);
        const title = document.createElement("b");
        title.textContent = String(event.title || "Evento");
        row.append(time, title);
        return row;
      }));
    } else {
      selection.textContent = this.selectedDateKey === todayKey
        ? "Sin eventos para hoy"
        : "Selecciona un día con actividad";
    }
  }
}

const MARKET_ASSET_ORDER = [
  "spx",
  "vix",
  "dxy",
  "total",
  "btcusdt",
  "ethusdt",
  "solusdt",
  "xrpusdt",
];
const MARKET_FRESHNESS = new Set([
  "live",
  "current",
  "close",
  "stale",
  "unknown",
]);

export function normalizeMarketRibbon(payload) {
  const byId = new Map(
    (Array.isArray(payload?.assets) ? payload.assets : [])
      .filter((asset) => MARKET_ASSET_ORDER.includes(asset?.id))
      .map((asset) => [asset.id, asset]),
  );
  return MARKET_ASSET_ORDER.map((id) => {
    const source = byId.get(id) || {};
    const price =
      source.price === null || source.price === undefined || source.price === ""
        ? Number.NaN
        : Number(source.price);
    const change =
      source.change_pct === null ||
      source.change_pct === undefined ||
      source.change_pct === ""
        ? Number.NaN
        : Number(source.change_pct);
    return {
      id,
      symbol: String(source.symbol || id.toUpperCase()),
      chartSymbol: String(source.chart_symbol || ""),
      tvSymbol: String(source.tv_symbol || ""),
      chartMode: String(source.chart_mode || "tradingview"),
      price: Number.isFinite(price) ? price : null,
      priceDecimals: Number.isInteger(Number(source.price_decimals))
        ? Math.max(0, Math.min(8, Number(source.price_decimals)))
        : 2,
      changePct: Number.isFinite(change) ? change : null,
      observedAt: Number.isFinite(Number(source.observed_at_ms))
        ? Number(source.observed_at_ms)
        : null,
      freshness: MARKET_FRESHNESS.has(source.freshness)
        ? source.freshness
        : "unknown",
      source: source.source ? String(source.source) : null,
      kind: String(source.kind || "unknown"),
    };
  });
}

export function formatMarketPrice(asset) {
  if (!Number.isFinite(asset?.price)) return "--";
  if (asset.kind === "aggregate") {
    return `$${(asset.price / 1e12).toFixed(2)}T`;
  }
  const digits = Number.isInteger(asset.priceDecimals)
    ? asset.priceDecimals
    : 2;
  return new Intl.NumberFormat("es-CL", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(asset.price);
}

const CRYPTO_INSIGHT_IDS = new Set([
  "btcusdt",
  "ethusdt",
  "solusdt",
  "xrpusdt",
]);
const INSIGHT_FRESHNESS = new Set(["live", "current"]);

function median(values) {
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2
    ? ordered[middle]
    : (ordered[middle - 1] + ordered[middle]) / 2;
}

export function deriveMarketInsight(assets) {
  const eligible = (Array.isArray(assets) ? assets : []).filter(
    (asset) =>
      CRYPTO_INSIGHT_IDS.has(asset?.id) &&
      Number.isFinite(asset?.changePct) &&
      INSIGHT_FRESHNESS.has(asset?.freshness),
  );
  if (eligible.length < 3) {
    return Object.freeze({
      state: "unknown",
      text: "Contexto insuficiente",
      evidence: `${eligible.length}/4 activos cripto con lectura vigente`,
    });
  }

  const changes = eligible.map((asset) => asset.changePct);
  const positive = changes.filter((change) => change > 0).length;
  const negative = changes.filter((change) => change < 0).length;
  const center = median(changes);
  const evidence = `${positive} suben · ${negative} bajan · mediana ${formatMarketChange(center)}`;

  if (positive >= 3) {
    return Object.freeze({
      state: "positive",
      text: center >= 2
        ? "Cripto avanza con fuerza"
        : center >= 0.5
          ? "Cripto mantiene tono alcista"
          : "Cripto avanza con cautela",
      evidence,
    });
  }
  if (negative >= 3) {
    return Object.freeze({
      state: "negative",
      text: center <= -2
        ? "Cripto retrocede con fuerza"
        : center <= -0.5
          ? "Cripto mantiene tono bajista"
          : "Cripto retrocede con cautela",
      evidence,
    });
  }
  return Object.freeze({
    state: "neutral",
    text: "Cripto opera sin dirección común",
    evidence,
  });
}

export class MarketRibbonClient {
  constructor({
    ribbonUrl = MARKET_RIBBON_URL,
    fetcher = (...args) => fetch(...args),
    onChange = () => {},
  } = {}) {
    this.ribbonUrl = ribbonUrl;
    this.fetcher = fetcher;
    this.onChange = onChange;
    this.status = "loading";
    this.assets = normalizeMarketRibbon(null);
    this.generatedAt = null;
    this.error = null;
    this.refreshTimer = null;
  }

  state() {
    return {
      status: this.status,
      assets: this.assets,
      generatedAt: this.generatedAt,
      error: this.error,
    };
  }

  async start() {
    await this.refresh();
    this.refreshTimer = setInterval(() => {
      this.refresh().catch(() => {});
    }, 30_000);
  }

  stop() {
    clearInterval(this.refreshTimer);
    this.refreshTimer = null;
  }

  async refresh() {
    try {
      const response = await this.fetcher(this.ribbonUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`market ribbon HTTP ${response.status}`);
      const payload = await response.json();
      this.assets = normalizeMarketRibbon(payload);
      this.generatedAt = Number.isFinite(Number(payload?.generated_at_ms))
        ? Number(payload.generated_at_ms)
        : Date.now();
      this.status = this.assets.some((asset) => asset.price !== null)
        ? "ready"
        : "degraded";
      this.error = null;
    } catch (error) {
      this.status = this.assets.some((asset) => asset.price !== null)
        ? "degraded"
        : "failed";
      this.error = error?.message || "market ribbon no disponible";
    }
    this.onChange(this.state());
  }
}

export function normalizeAiContext(payload) {
  const allowedStates = new Set([
    "ready",
    "disabled",
    "degraded",
    "unknown",
  ]);
  const allowedSeverities = new Set([
    "normal",
    "info",
    "warning",
    "critical",
  ]);
  const state = allowedStates.has(payload?.state)
    ? payload.state
    : "unknown";
  const severity = allowedSeverities.has(payload?.severity)
    ? payload.severity
    : "normal";
  return {
    state,
    severity,
    summary:
      typeof payload?.summary === "string" && payload.summary.trim()
        ? payload.summary.trim().slice(0, 180)
        : null,
    lastEvaluationMs: Number.isFinite(Number(payload?.last_evaluation_ms))
      ? Number(payload.last_evaluation_ms)
      : null,
    freshness: String(payload?.freshness || "unknown"),
    source: payload?.source ? String(payload.source) : null,
  };
}

export class AiContextClient {
  constructor({
    contextUrl = AI_CONTEXT_URL,
    fetcher = (...args) => fetch(...args),
    onChange = () => {},
  } = {}) {
    this.contextUrl = contextUrl;
    this.fetcher = fetcher;
    this.onChange = onChange;
    this.context = normalizeAiContext(null);
    this.refreshTimer = null;
  }

  async start() {
    await this.refresh();
    this.refreshTimer = setInterval(() => {
      this.refresh().catch(() => {});
    }, 60_000);
  }

  stop() {
    clearInterval(this.refreshTimer);
    this.refreshTimer = null;
  }

  async refresh() {
    try {
      const response = await this.fetcher(this.contextUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`ai context HTTP ${response.status}`);
      this.context = normalizeAiContext(await response.json());
    } catch {
      this.context = normalizeAiContext({ state: "degraded" });
    }
    this.onChange(this.context);
  }
}

export function normalizePositionsContext(payload) {
  const normalizeNumber = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  };
  const accounts = new Map(
    (Array.isArray(payload?.accounts) ? payload.accounts : [])
      .filter((account) => ["principal", "bot"].includes(account?.id))
      .map((account) => [account.id, account]),
  );
  const normalizeAccount = (id, label) => {
    const account = accounts.get(id) || {};
    return {
      id,
      label: String(account.label || label).slice(0, 40),
      environment: String(account.environment || "unknown").slice(0, 20),
      state: ["ready", "stale", "failed", "unavailable"].includes(account.state)
        ? account.state
        : "unavailable",
      detail: account.detail ? String(account.detail).slice(0, 80) : null,
      ageSeconds: normalizeNumber(account.age_seconds),
      totalPnl: normalizeNumber(account.total_pnl) ?? 0,
      positions: (Array.isArray(account.positions) ? account.positions : [])
        .slice(0, 12)
        .map((position) => ({
          symbol: String(position?.symbol || "Activo").slice(0, 24),
          side: position?.side === "SHORT" ? "SHORT" : "LONG",
          entry: normalizeNumber(position?.entry),
          mark: normalizeNumber(position?.mark),
          pnl: normalizeNumber(position?.pnl),
          roe: normalizeNumber(position?.roe),
          leverage: normalizeNumber(position?.leverage),
        })),
    };
  };
  return {
    state: ["ready", "degraded"].includes(payload?.state)
      ? payload.state
      : "degraded",
    generatedAtMs: normalizeNumber(payload?.generated_at_ms),
    totalPositions: Math.max(0, Number(payload?.total_positions) || 0),
    readOnly: payload?.read_only === true,
    accounts: [
      normalizeAccount("principal", "Cuenta principal"),
      normalizeAccount("bot", "Cuenta Bot"),
    ],
  };
}

export class PositionsContextClient {
  constructor({
    contextUrl = POSITIONS_CONTEXT_URL,
    fetcher = (...args) => fetch(...args),
    onChange = () => {},
  } = {}) {
    this.contextUrl = contextUrl;
    this.fetcher = fetcher;
    this.onChange = onChange;
    this.context = normalizePositionsContext(null);
    this.refreshTimer = null;
  }

  async start() {
    await this.refresh();
    this.refreshTimer = setInterval(() => {
      if (document.visibilityState === "hidden") return;
      this.refresh().catch(() => {});
    }, 10_000);
  }

  stop() {
    clearInterval(this.refreshTimer);
    this.refreshTimer = null;
  }

  async refresh() {
    try {
      const response = await this.fetcher(this.contextUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`positions context HTTP ${response.status}`);
      this.context = normalizePositionsContext(await response.json());
    } catch {
      this.context = normalizePositionsContext({ state: "degraded" });
    }
    this.onChange(this.context);
  }
}

export function normalizeMacOSContext(payload) {
  const number = (value) => (
    value === null || value === undefined || value === ""
      ? null
      : Number.isFinite(Number(value))
        ? Math.max(0, Number(value))
        : null
  );
  return {
    state: ["ready", "degraded", "unavailable"].includes(payload?.state)
      ? payload.state
      : "degraded",
    generatedAtMs: number(payload?.generated_at_ms),
    device: String(payload?.device || "Mac local").slice(0, 60),
    osVersion: String(payload?.os_version || "macOS").slice(0, 30),
    loadPercent: number(payload?.load_percent),
    memoryPercent: number(payload?.memory_percent),
    memoryPressure: ["normal", "elevated", "critical", "unknown"].includes(
      payload?.memory_pressure,
    ) ? payload.memory_pressure : "unknown",
    memoryAvailablePercent: number(payload?.memory_available_percent),
    diskPercent: number(payload?.disk_percent),
    powerSource: String(payload?.power_source || "Sin lectura").slice(0, 30),
    batteryPercent: number(payload?.battery_percent),
    uptimeSeconds: number(payload?.uptime_seconds),
    detail: payload?.detail ? String(payload.detail).slice(0, 100) : null,
    readOnly: payload?.read_only === true,
  };
}

export class MacOSContextClient {
  constructor({
    contextUrl = MACOS_CONTEXT_URL,
    fetcher = (...args) => fetch(...args),
    onChange = () => {},
  } = {}) {
    this.contextUrl = contextUrl;
    this.fetcher = fetcher;
    this.onChange = onChange;
    this.context = normalizeMacOSContext(null);
    this.refreshTimer = null;
  }

  async start() {
    await this.refresh();
    this.refreshTimer = setInterval(() => {
      if (document.visibilityState === "hidden") return;
      this.refresh().catch(() => {});
    }, 15_000);
  }

  stop() {
    clearInterval(this.refreshTimer);
    this.refreshTimer = null;
  }

  async refresh() {
    try {
      const response = await this.fetcher(this.contextUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`macOS context HTTP ${response.status}`);
      this.context = normalizeMacOSContext(await response.json());
    } catch {
      this.context = normalizeMacOSContext({ state: "degraded" });
    }
    this.onChange(this.context);
  }
}

export function normalizeBotContext(payload) {
  const states = new Set(["ready", "paused", "degraded", "unknown"]);
  const severity = new Set(["normal", "info", "warning", "critical"]);
  const signal = payload?.latest_signal;
  return {
    state: states.has(payload?.state) ? payload.state : "unknown",
    mode: payload?.mode === "live" ? "live" : (
      payload?.mode === "dry-run" ? "dry-run" : "unknown"
    ),
    severity: severity.has(payload?.severity)
      ? payload.severity
      : "normal",
    sourceAgeSeconds: Number.isFinite(Number(payload?.source_age_seconds))
      ? Math.max(0, Number(payload.source_age_seconds))
      : null,
    latestSignal:
      signal && typeof signal === "object"
        ? {
            pair: String(signal.pair || "Activo"),
            direction: ["long", "short"].includes(signal.direction)
              ? signal.direction
              : "unknown",
            status: String(signal.status || "unknown"),
            mode: String(signal.mode || "unknown"),
            occurredAtMs: Number.isFinite(Number(signal.occurred_at_ms))
              ? Number(signal.occurred_at_ms)
              : null,
          }
        : null,
    readOnly: payload?.read_only === true,
  };
}

const ATTENTION_RANK = { critical: 3, warning: 2, info: 1 };

const TIMELINE_STATE_LABELS = Object.freeze({
  positive: "Alcista",
  negative: "Bajista",
  neutral: "Mixto",
  ready: "Estable",
  degraded: "Degradado",
  failed: "Crítico",
});

export class OperationalTimeline {
  constructor({ now = () => Date.now(), maxEntries = 24 } = {}) {
    this.now = now;
    this.maxEntries = Math.max(1, Number(maxEntries) || 24);
    this.startedAtMs = this.now();
    this.baselines = new Map();
    this.seenExternalEvents = new Set();
    this.events = [];
  }

  entries() {
    return this.events.map((event) => Object.freeze({ ...event }));
  }

  observe({ marketInsight = null, readiness = null, positions = null, bot = null } = {}) {
    const observedAtMs = this.now();
    this._observeTransition({
      source: "market-pulse",
      value: ["positive", "negative", "neutral"].includes(marketInsight?.state)
        ? marketInsight.state
        : null,
      observedAtMs,
      build: (before, after) => ({
        label: `Pulso: ${TIMELINE_STATE_LABELS[before]} → ${TIMELINE_STATE_LABELS[after]}`,
        detail: marketInsight.evidence,
        severity: "info",
      }),
    });
    this._observeTransition({
      source: "operational-health",
      value: ["ready", "degraded", "failed"].includes(readiness?.overall)
        ? readiness.overall
        : null,
      observedAtMs,
      build: (before, after) => ({
        label: `Sistema: ${TIMELINE_STATE_LABELS[before]} → ${TIMELINE_STATE_LABELS[after]}`,
        detail: "Estado global observado",
        severity: after === "failed" ? "critical" : (
          after === "degraded" ? "warning" : "info"
        ),
      }),
    });
    this._observeTransition({
      source: "positions",
      value: Number.isFinite(Number(positions?.totalPositions))
        ? Math.max(0, Number(positions.totalPositions))
        : null,
      observedAtMs,
      build: (before, after) => ({
        label: `Posiciones observadas: ${before} → ${after}`,
        detail: "Lectura consolidada de Binance",
        severity: "info",
      }),
    });
    this._observeBotSignal(bot?.latestSignal, observedAtMs);
    return this.entries();
  }

  _observeTransition({ source, value, observedAtMs, build }) {
    if (value === null || value === undefined) return;
    if (!this.baselines.has(source)) {
      this.baselines.set(source, value);
      return;
    }
    const previous = this.baselines.get(source);
    if (Object.is(previous, value)) return;
    this.baselines.set(source, value);
    this._append({
      id: `${source}:${observedAtMs}:${String(value)}`,
      source,
      occurredAtMs: observedAtMs,
      observedAtMs,
      ...build(previous, value),
    });
  }

  _observeBotSignal(signal, observedAtMs) {
    const occurredAtMs = Number(signal?.occurredAtMs);
    if (
      !signal ||
      !Number.isFinite(occurredAtMs) ||
      occurredAtMs < this.startedAtMs ||
      occurredAtMs > observedAtMs
    ) return;
    const eventId = [
      "bot-signal",
      occurredAtMs,
      signal.pair,
      signal.direction,
      signal.status,
    ].join(":");
    if (this.seenExternalEvents.has(eventId)) return;
    this.seenExternalEvents.add(eventId);
    this._append({
      id: eventId,
      source: "bot",
      occurredAtMs,
      observedAtMs,
      label: `${signal.pair} · ${String(signal.direction).toUpperCase()}`,
      detail: `Bot: ${signal.status}`,
      severity: "info",
    });
  }

  _append(event) {
    this.events.push(Object.freeze(event));
    this.events.sort((left, right) =>
      right.occurredAtMs - left.occurredAtMs ||
      right.observedAtMs - left.observedAtMs
    );
    this.events.length = Math.min(this.events.length, this.maxEntries);
  }
}

export function deriveImmediateAttention({
  readiness = null,
  macro = null,
  positions = null,
  bot = null,
  now = Date.now(),
} = {}) {
  const systemState = readiness?.overall === "failed" ? "critical" : (
    readiness?.overall === "degraded" ? "warning" : (
      readiness?.overall === "ready" ? "normal" : "unknown"
    )
  );
  const unavailableAccounts = (positions?.accounts || []).filter((account) =>
    ["stale", "failed", "unavailable"].includes(account.state),
  );
  const positionState = unavailableAccounts.length ? "warning" : (
    positions ? "normal" : "unknown"
  );
  const macroRemaining = macro?.status === "ready" && macro.event
    ? Number(macro.event.ts) * 1000 - now
    : null;
  const macroState = Number.isFinite(macroRemaining) && macroRemaining >= 0
    && macroRemaining <= 15 * 60_000
    ? "critical"
    : Number.isFinite(macroRemaining) && macroRemaining >= 0
      && macroRemaining <= 60 * 60_000
      ? "warning"
      : macro?.status === "degraded" ? "warning" : (
        macro ? "info" : "unknown"
      );
  const botState = bot?.severity === "critical" ? "critical" : (
    bot?.state === "degraded" || bot?.severity === "warning"
      ? "warning"
      : bot ? "info" : "unknown"
  );
  const items = [
    {
      label: "Sistema",
      detail: readiness?.overall === "ready" ? "Listo" : (
        readiness?.overall === "degraded" ? "Degradado" : (
          readiness?.overall === "failed" ? "Falló" : "Esperando"
        )
      ),
      state: systemState,
    },
    {
      label: "Binance",
      detail: unavailableAccounts.length
        ? `${unavailableAccounts.length} sin confirmar`
        : positions ? `${positions.totalPositions || 0} abiertas` : "Esperando",
      state: positionState,
    },
    {
      label: "Macro",
      detail: macro?.status === "ready" && macro.event
        ? formatMacroCountdown(macro.event.ts, now)
        : macro?.status === "empty" ? "Sin próximos" : "Esperando",
      state: macroState,
    },
    {
      label: "Bot",
      detail: bot?.mode === "live" ? "Live" : (
        bot?.mode === "dry-run" ? "Dry-run" : "Esperando"
      ),
      state: botState,
    },
  ];
  const available = [readiness, macro, positions, bot].filter(Boolean).length;
  if (available < 4) {
    return {
      state: "unknown",
      summary: "Reuniendo contexto operacional.",
      detail: `${available}/4 fuentes`,
      explanation: `Fuentes verificadas: ${available}/4.`,
      count: 0,
      items,
      evaluatedAtMs: now,
    };
  }

  const alerts = [];
  if (readiness.overall === "failed") {
    alerts.push({
      state: "critical",
      summary: "La plataforma no está preparada para trabajar.",
      source: "Sistema",
    });
  } else if (readiness.overall === "degraded") {
    alerts.push({
      state: "warning",
      summary: "Hay servicios esenciales degradados.",
      source: "Sistema",
    });
  }

  if (unavailableAccounts.length) {
    alerts.push({
      state: "warning",
      summary: "No se pueden confirmar todas las posiciones abiertas.",
      source: "Binance",
    });
  }

  if (macro.status === "ready" && macro.event) {
    const remaining = Number(macro.event.ts) * 1000 - now;
    if (Number.isFinite(remaining) && remaining >= 0 && remaining <= 60 * 60_000) {
      const critical = remaining <= 15 * 60_000;
      alerts.push({
        state: critical ? "critical" : "warning",
        summary: `${macro.event.title || "Evento macro"} · ${formatMacroCountdown(
          macro.event.ts,
          now,
        )}.`,
        source: "Macro",
      });
    }
  }

  if (bot.state === "degraded" || bot.severity === "critical") {
    alerts.push({
      state: bot.severity === "critical" ? "critical" : "warning",
      summary: "El estado del Bot requiere revisión.",
      source: "Bot",
    });
  } else if (bot.severity === "warning") {
    alerts.push({
      state: "warning",
      summary: "El Bot reportó una observación que requiere revisión.",
      source: "Bot",
    });
  }

  alerts.sort((left, right) => ATTENTION_RANK[right.state] - ATTENTION_RANK[left.state]);
  if (!alerts.length) {
    const macroDetail = macro.status === "ready" && macro.event
      ? `Macro: ${macro.event.title || "evento"} · ${formatMacroCountdown(
          macro.event.ts,
          now,
        )}`
      : macro.status === "empty"
        ? "Macro: sin eventos próximos"
        : "4 fuentes verificadas";
    return {
      state: "normal",
      summary: "Sin intervención inmediata.",
      detail: macroDetail,
      explanation: "Sistema, Binance, Macro y Bot no publican una alerta activa.",
      count: 0,
      items,
      evaluatedAtMs: now,
    };
  }
  const first = alerts[0];
  return {
    state: first.state,
    summary: first.summary,
    detail: alerts.length === 1
      ? first.source
      : `${first.source} · ${alerts.length} alertas`,
    explanation: alerts.map((alert) =>
      `${alert.source}: ${alert.summary}`
    ).join(" · "),
    count: alerts.length,
    items,
    evaluatedAtMs: now,
  };
}

export class BotContextClient {
  constructor({
    contextUrl = BOT_CONTEXT_URL,
    fetcher = (...args) => fetch(...args),
    onChange = () => {},
  } = {}) {
    this.contextUrl = contextUrl;
    this.fetcher = fetcher;
    this.onChange = onChange;
    this.context = normalizeBotContext(null);
    this.refreshTimer = null;
  }

  async start() {
    await this.refresh();
    this.refreshTimer = setInterval(() => {
      this.refresh().catch(() => {});
    }, 30_000);
  }

  stop() {
    clearInterval(this.refreshTimer);
    this.refreshTimer = null;
  }

  async refresh() {
    try {
      const response = await this.fetcher(this.contextUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`bot context HTTP ${response.status}`);
      this.context = normalizeBotContext(await response.json());
    } catch {
      this.context = normalizeBotContext({ state: "degraded" });
    }
    this.onChange(this.context);
  }
}

const MEDIA_CAPABILITIES = new Set([
  "current_state",
  "play",
  "pause",
  "next",
  "previous",
  "set_volume",
  "open_app",
]);

export function normalizeMediaContext(payload) {
  const lifecycle = new Set([
    "ready",
    "degraded",
    "unavailable",
    "revoked",
    "closed",
    "unknown",
  ]);
  const freshness = new Set(["live", "current", "stale", "unknown"]);
  const capabilities = Array.isArray(payload?.capabilities)
    ? payload.capabilities.filter((item) => MEDIA_CAPABILITIES.has(item))
    : [];
  const providerIds = new Set(["apple-music", "qobuz", "tidal"]);
  const selectedProvider = providerIds.has(payload?.selected_provider)
    ? payload.selected_provider
    : "apple-music";
  return {
    provider: payload?.provider ? String(payload.provider) : null,
    lifecycle: lifecycle.has(payload?.lifecycle)
      ? payload.lifecycle
      : "unknown",
    playback: String(payload?.playback || "unknown"),
    freshness: freshness.has(payload?.freshness)
      ? payload.freshness
      : "unknown",
    observedAtMs: Number.isFinite(Number(payload?.observed_at_ms))
      ? Number(payload.observed_at_ms)
      : null,
    track: payload?.track ? String(payload.track).slice(0, 160) : null,
    artist: payload?.artist ? String(payload.artist).slice(0, 160) : null,
    album: payload?.album ? String(payload.album).slice(0, 160) : null,
    artworkUrl: payload?.artwork_url
      ? String(payload.artwork_url).slice(0, 240)
      : null,
    positionSeconds: Number.isFinite(Number(payload?.position_seconds))
      ? Math.max(0, Number(payload.position_seconds))
      : null,
    durationSeconds: Number.isFinite(Number(payload?.duration_seconds))
      ? Math.max(0, Number(payload.duration_seconds))
      : null,
    progress: Number.isFinite(Number(payload?.progress))
      ? Math.min(1, Math.max(0, Number(payload.progress)))
      : null,
    itemRef: payload?.item_ref ? String(payload.item_ref) : null,
    capabilities,
    commandsEnabled: payload?.commands_enabled === true,
    readOnly: payload?.read_only !== false,
    code: payload?.code ? String(payload.code) : null,
    simulated: payload?.simulated === true,
    selectedProvider,
    availableProviders: Array.isArray(payload?.available_providers)
      ? payload.available_providers.filter((item) => providerIds.has(item))
      : [],
  };
}

export class MediaContextClient {
  constructor({
    contextUrl = MEDIA_CONTEXT_URL,
    fetcher = (...args) => fetch(...args),
    onChange = () => {},
  } = {}) {
    this.contextUrl = contextUrl;
    this.fetcher = fetcher;
    this.onChange = onChange;
    this.context = normalizeMediaContext(null);
    this.provider = "apple-music";
    this.feedback = null;
    this.busy = false;
    this.refreshTimer = null;
    this.autoRefreshBusy = false;
    this.refreshSequence = 0;
    this.refreshPromise = null;
  }

  async start() {
    await this.refresh({ detectActive: true });
    this.refreshTimer = setInterval(() => {
      if (document.visibilityState === "hidden") return;
      if (this.busy || this.autoRefreshBusy) return;
      this.autoRefreshBusy = true;
      this.refresh({ detectActive: true })
        .catch(() => {})
        .finally(() => {
          this.autoRefreshBusy = false;
        });
    }, 5_000);
  }

  stop() {
    clearInterval(this.refreshTimer);
    this.refreshTimer = null;
  }

  async refresh({ detectActive = false } = {}) {
    const previousRefresh = this.refreshPromise;
    if (previousRefresh) await previousRefresh;
    const operation = this.performRefresh({ detectActive });
    this.refreshPromise = operation;
    try {
      await operation;
    } finally {
      if (this.refreshPromise === operation) this.refreshPromise = null;
    }
  }

  async performRefresh({ detectActive = false } = {}) {
    const sequence = ++this.refreshSequence;
    try {
      const url = new URL(this.contextUrl, location.origin);
      url.searchParams.set("provider", detectActive ? "auto" : this.provider);
      if (detectActive) url.searchParams.set("preferred", this.provider);
      const response = await this.fetcher(url, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`media context HTTP ${response.status}`);
      const nextContext = normalizeMediaContext(await response.json());
      if (sequence !== this.refreshSequence) return;
      if (detectActive && nextContext.selectedProvider !== this.provider) {
        this.provider = nextContext.selectedProvider;
        this.feedback = null;
      }
      this.context = nextContext;
    } catch {
      if (sequence !== this.refreshSequence) return;
      this.context = normalizeMediaContext({
        lifecycle: "degraded",
        selected_provider: this.provider,
      });
    }
    this.onChange({ ...this.context, feedback: this.feedback, busy: this.busy });
  }

  async execute(action) {
    if (this.busy) return;
    this.busy = true;
    this.feedback = "Enviando";
    this.onChange({ ...this.context, feedback: this.feedback, busy: true });
    const suffix =
      globalThis.crypto?.randomUUID?.() ||
      `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    try {
      // Accessibility reads and transport commands must not overlap. Qobuz can
      // otherwise reject a valid command while its player tree is being read.
      const pendingRefresh = this.refreshPromise;
      if (pendingRefresh) await pendingRefresh;
      const response = await this.fetcher(MEDIA_COMMAND_URL, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          command_id: `cc-media-${suffix}`,
          action,
          provider: this.provider,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.code || `HTTP ${response.status}`);
      const labels = {
        applied: "Aplicado",
        rejected: "Rechazado",
        unknown: "Resultado incierto",
      };
      const reconciledPlayback = payload?.reconciled_state?.playback;
      this.feedback =
        action === "play" &&
        payload.status === "applied" &&
        payload.reconciled_state &&
        reconciledPlayback !== "playing"
          ? "Sin pista cargada"
          : labels[payload.status] || "Confirmado";
      await this.refresh();
    } catch (error) {
      this.feedback = error?.message || "No disponible";
    } finally {
      this.busy = false;
      this.onChange({
        ...this.context,
        feedback: this.feedback,
        busy: false,
      });
    }
  }

  async selectProvider(provider) {
    if (this.busy) return;
    if (!["apple-music", "qobuz", "tidal"].includes(provider)) return;
    this.provider = provider;
    this.feedback = null;
    await this.refresh();
    if (this.context.track && !this.context.artworkUrl) {
      setTimeout(() => {
        if (this.provider === provider) this.refresh().catch(() => {});
      }, 5_000);
    }
  }
}

export class OperationalHealthClient {
  constructor({
    healthUrl = HEALTH_URL,
    fetcher = (...args) => fetch(...args),
    onChange = () => {},
    now = () => Date.now(),
  } = {}) {
    this.healthUrl = healthUrl;
    this.fetcher = fetcher;
    this.onChange = onChange;
    this.now = now;
    this.status = "loading";
    this.health = null;
    this.checkedAt = null;
    this.error = null;
    this.refreshTimer = null;
    this.confirmationTimer = null;
    this.consecutiveFailures = 0;
  }

  state() {
    return {
      status: this.status,
      health: this.health,
      checkedAt: this.checkedAt,
      error: this.error,
    };
  }

  async start() {
    await this.refresh();
    this.refreshTimer = setInterval(() => {
      this.refresh().catch(() => {});
    }, 15_000);
  }

  stop() {
    clearInterval(this.refreshTimer);
    clearTimeout(this.confirmationTimer);
    this.refreshTimer = null;
    this.confirmationTimer = null;
  }

  async refresh() {
    try {
      const response = await this.fetcher(this.healthUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`health HTTP ${response.status}`);
      this.health = await response.json();
      this.status = "ready";
      this.checkedAt = this.now();
      this.error = null;
      this.consecutiveFailures = 0;
      clearTimeout(this.confirmationTimer);
      this.confirmationTimer = null;
    } catch (error) {
      this.consecutiveFailures += 1;
      this.status = this.health && this.consecutiveFailures === 1
        ? "ready"
        : this.health ? "degraded" : "failed";
      this.error = error?.message || "health no disponible";
      if (this.health && this.consecutiveFailures === 1) {
        clearTimeout(this.confirmationTimer);
        this.confirmationTimer = setTimeout(() => {
          this.confirmationTimer = null;
          this.refresh().catch(() => {});
        }, 2_500);
      }
    }
    this.onChange(this.state());
  }
}

const READINESS_LABELS = {
  ready: "Listo",
  degraded: "Degradado",
  failed: "Falló",
  unknown: "Sin datos",
};

const OPERATIONAL_HEALTH_LABELS = Object.freeze({
  stable: "Estable",
  degraded: "Degradado",
  critical: "Crítico",
  unknown: "Desconocido",
});

const REQUIRED_READINESS_IDS = new Set([
  "gateway",
  "event-bus",
  "snapshot",
  "internet",
  "trading",
]);
const GATEWAY_RECONNECT_GRACE_MS = 8_000;

function normalizeServiceState(value) {
  if (value === "ready" || value === "ok") return "ready";
  if (value === "degraded" || value === "degradado") return "degraded";
  if (value === "failed" || value === "closed" || value === "error") {
    return "failed";
  }
  return "unknown";
}

function moduleBySlug(health, slug) {
  return (Array.isArray(health?.modules) ? health.modules : []).find(
    (module) => module?.slug === slug,
  );
}

export function deriveOperationalReadiness({
  commandState,
  healthState,
  online = true,
  now = Date.now(),
}) {
  const health = healthState?.health;
  const commandCenter = moduleBySlug(health, "command-center");
  const trading = moduleBySlug(health, "trading");
  const registryModules = commandCenter?.module_registry?.modules || [];
  const media = registryModules.find(
    (module) => module?.module_id === "media.controller",
  );

  const freshness = worstFreshness(commandState?.readModel || {}, now);
  const snapshot = !commandState?.snapshotAt
    ? "unknown"
    : freshness === "expired"
      ? "failed"
      : freshness === "stale"
        ? "degraded"
        : "ready";
  const gatewayReconnectIsTransient = commandState?.connection === "degraded" &&
    Number.isFinite(commandState?.connectionDegradedAt) &&
    now - commandState.connectionDegradedAt < GATEWAY_RECONNECT_GRACE_MS &&
    freshness !== "expired";
  const gateway = gatewayReconnectIsTransient ? "ready" : ({
    ready: "ready",
    degraded: "degraded",
    stale: "degraded",
    expired: "failed",
    disconnected: "failed",
    loading: "unknown",
  }[commandState?.connection] || "unknown");

  let tradingState = normalizeServiceState(trading?.status);
  if (trading?.upstream_ok === false) tradingState = "degraded";
  if (trading?.upstream_ok === true && tradingState === "ready") {
    const age = now - Number(trading?.last_update_ms || 0);
    if (!Number.isFinite(age) || age > TRADING_FAILED_AFTER_MS) {
      tradingState = "failed";
    } else if (age > TRADING_DEGRADED_AFTER_MS) {
      tradingState = "degraded";
    }
  }

  const healthAvailable = healthState?.status === "ready";
  const services = [
    {
      id: "gateway",
      name: "Gateway",
      state: gateway,
      evidence: gatewayReconnectIsTransient
        ? "Conexión: reconectando dentro de tolerancia"
        : `Conexión: ${commandState?.connection || "sin lectura"}`,
    },
    {
      id: "event-bus",
      name: "EventBus",
      state: normalizeServiceState(commandCenter?.event_bus?.status),
      evidence: `Health: ${commandCenter?.event_bus?.status || "sin lectura"}`,
    },
    {
      id: "snapshot",
      name: "Snapshot",
      state: snapshot,
      evidence: commandState?.snapshotAt
        ? `Frescura: ${freshness}`
        : "Snapshot: sin lectura",
    },
    {
      id: "internet",
      name: "Internet",
      state:
        online === false
          ? "failed"
          : healthAvailable && trading?.upstream_ok === true
            ? "ready"
            : healthState?.status === "degraded"
              ? "degraded"
              : "unknown",
      evidence: online === false
        ? "Navegador sin conexión"
        : `Upstream trading: ${trading?.upstream_ok === true ? "disponible" : (
          trading?.upstream_ok === false ? "degradado" : "sin lectura"
        )}`,
    },
    {
      id: "trading",
      name: "Trading",
      state: tradingState,
      evidence: `Módulo: ${trading?.status || "sin lectura"} · upstream: ${
        trading?.upstream_ok === true ? "disponible" : (
          trading?.upstream_ok === false ? "degradado" : "sin lectura"
        )
      }`,
    },
    { id: "agent", name: "Agente macOS", state: "unknown" },
    {
      id: "music",
      name: "Apple Music",
      state: media?.factory_attached
        ? normalizeServiceState(media.lifecycle)
        : "unknown",
    },
    { id: "ai", name: "IA", state: "unknown" },
  ];
  const required = services.filter((service) =>
    REQUIRED_READINESS_IDS.has(service.id),
  );
  const overall = required.some((service) => service.state === "failed")
    ? "failed"
    : required.some(
        (service) => service.state === "degraded",
      )
      ? "degraded"
      : required.some((service) => service.state === "unknown")
        ? "unknown"
        : "ready";
  return { overall, services };
}

export function deriveOperationalHealth(readiness) {
  const required = (Array.isArray(readiness?.services) ? readiness.services : [])
    .filter((service) => REQUIRED_READINESS_IDS.has(service.id));
  const failures = required.filter((service) => service.state === "failed");
  const degraded = required.filter((service) => service.state === "degraded");
  const unknown = required.filter((service) => service.state === "unknown");
  const state = failures.length
    ? "critical"
    : degraded.length
      ? "degraded"
      : unknown.length || required.length !== REQUIRED_READINESS_IDS.size
        ? "unknown"
        : "stable";
  const affected = state === "critical"
    ? failures
    : state === "degraded"
      ? degraded
      : state === "unknown"
        ? unknown
        : [];
  const reasons = affected.map((service) => Object.freeze({
    service: service.name,
    state: service.state,
    evidence: service.evidence || "Sin evidencia adicional",
  }));
  const explanation = state === "stable"
    ? `${required.length} servicios esenciales verificados.`
    : reasons.length
      ? reasons.map((reason) =>
          `${reason.service}: ${reason.evidence}`
        ).join(" · ")
      : `${required.length}/${REQUIRED_READINESS_IDS.size} servicios esenciales observados.`;
  return Object.freeze({
    state,
    label: OPERATIONAL_HEALTH_LABELS[state],
    explanation,
    reasons,
    requiredCount: REQUIRED_READINESS_IDS.size,
    observedCount: required.length,
  });
}

export function reduceEnvelope(readModel, cursors, envelope) {
  const topic = envelope?.topic;
  if (!topic || !Number.isInteger(envelope.seq)) {
    return { status: "invalid", readModel, cursors };
  }
  const cursor = cursors[topic];
  if (Number.isInteger(cursor) && envelope.seq <= cursor) {
    return { status: "duplicate", readModel, cursors };
  }
  if (Number.isInteger(cursor) && envelope.seq > cursor + 1) {
    return { status: "gap", readModel, cursors };
  }
  if (!Number.isInteger(cursor) && envelope.kind !== "snapshot") {
    return { status: "gap", readModel, cursors };
  }

  const nextModel = { ...readModel };
  if (envelope.kind === "snapshot") {
    nextModel[topic] = structuredClone(envelope);
  } else if (envelope.kind === "patch") {
    const previous = nextModel[topic];
    if (!previous) return { status: "gap", readModel, cursors };
    nextModel[topic] = {
      ...structuredClone(previous),
      ...structuredClone(envelope),
      payload: mergePatch(previous.payload, envelope.payload),
    };
  }
  return {
    status: "applied",
    readModel: nextModel,
    cursors: { ...cursors, [topic]: envelope.seq },
  };
}

export class CommandCenterClient {
  constructor({
    snapshotUrl = SNAPSHOT_URL,
    socketFactory = (url) => new WebSocket(url),
    fetcher = (...args) => fetch(...args),
    onChange = () => {},
    now = () => Date.now(),
  } = {}) {
    this.snapshotUrl = snapshotUrl;
    this.socketFactory = socketFactory;
    this.fetcher = fetcher;
    this.onChange = onChange;
    this.now = now;
    this.socket = null;
    this.readModel = {};
    this.cursors = {};
    this.subject = null;
    this.snapshotAt = null;
    this.connection = "loading";
    this.connectionDegradedAt = null;
    this.lastError = null;
    this.reconnectAttempt = 0;
    this.reconnectTimer = null;
    this.freshnessTimer = null;
    this.manualClose = false;
    this.resyncing = false;
  }

  state() {
    return {
      readModel: this.readModel,
      cursors: this.cursors,
      subject: this.subject,
      snapshotAt: this.snapshotAt,
      connection: this.connection,
      connectionDegradedAt: this.connectionDegradedAt,
      lastError: this.lastError,
      resyncing: this.resyncing,
      now: this.now(),
    };
  }

  async start() {
    this.manualClose = false;
    await this.#loadSnapshot();
    this.#connect();
  }

  stop() {
    this.manualClose = true;
    clearTimeout(this.reconnectTimer);
    clearTimeout(this.freshnessTimer);
    this.reconnectTimer = null;
    this.freshnessTimer = null;
    this.socket?.close(1000, "client shutdown");
    this.socket = null;
  }

  resync() {
    clearTimeout(this.freshnessTimer);
    this.freshnessTimer = null;
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.resyncing = true;
      this.connection = "loading";
      this.#emit();
      this.socket.send(JSON.stringify({ gateway_v: 1, op: "resync" }));
      return;
    }
    this.connection = "loading";
    this.#emit();
    this.#loadSnapshot()
      .then(() => this.#connect())
      .catch(() => this.#scheduleReconnect());
  }

  async #loadSnapshot() {
    try {
      const response = await this.fetcher(this.snapshotUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`snapshot HTTP ${response.status}`);
      const snapshot = await response.json();
      this.#acceptSnapshot(snapshot);
      this.connection =
        this.socket?.readyState === WebSocket.OPEN ? "ready" : "degraded";
      this.connectionDegradedAt = this.connection === "degraded"
        ? (this.connectionDegradedAt ?? this.now())
        : null;
      this.lastError = null;
      this.#emit();
    } catch (error) {
      this.connection = Object.keys(this.readModel).length
        ? "degraded"
        : "disconnected";
      this.connectionDegradedAt = this.connection === "degraded" ? this.now() : null;
      this.lastError = error?.message || "snapshot unavailable";
      this.#emit();
      throw error;
    }
  }

  #connect() {
    if (this.manualClose || this.socket?.readyState === WebSocket.OPEN) return;
    clearTimeout(this.reconnectTimer);
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${scheme}//${location.host}${WS_PATH}`;
    const socket = this.socketFactory(url);
    this.socket = socket;

    socket.addEventListener("message", (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        this.#fail("gateway.invalid-json");
        return;
      }
      this.#handleMessage(message);
    });
    socket.addEventListener("close", () => {
      if (this.socket === socket) this.socket = null;
      if (this.manualClose) return;
      this.connection = Object.keys(this.readModel).length
        ? "degraded"
        : "disconnected";
      this.connectionDegradedAt = this.connection === "degraded" ? this.now() : null;
      this.#emit();
      this.#scheduleReconnect();
    });
    socket.addEventListener("error", () => {
      this.lastError = "gateway.connection-failed";
    });
  }

  #handleMessage(message) {
    if (message?.op === "ready" && message.gateway_v === 1) {
      if (
        message.contract_v !== CONTRACT_VERSION ||
        message.fingerprint !== CONTRACT_FINGERPRINT
      ) {
        this.#fail("gateway.contract-mismatch");
        this.socket?.close(4400, "contract mismatch");
        return;
      }
      const topics = Array.isArray(message.available_topics)
        ? message.available_topics
        : [];
      this.socket.send(
        JSON.stringify({
          gateway_v: 1,
          op: "subscribe",
          contract_v: CONTRACT_VERSION,
          fingerprint: CONTRACT_FINGERPRINT,
          topics,
        }),
      );
      return;
    }
    if (message?.op === "ping") {
      this.socket?.send(JSON.stringify({ gateway_v: 1, op: "pong" }));
      return;
    }
    if (message?.contract === "nexux.command-center.snapshot") {
      this.#acceptSnapshot(message);
      this.connection = "ready";
      this.connectionDegradedAt = null;
      this.resyncing = false;
      this.reconnectAttempt = 0;
      this.lastError = null;
      this.#emit();
      return;
    }
    if (message?.contract === "nexux.command-center.event") {
      const reduced = reduceEnvelope(
        this.readModel,
        this.cursors,
        message,
      );
      if (reduced.status === "gap") {
        this.resync();
        return;
      }
      if (reduced.status === "applied") {
        this.readModel = reduced.readModel;
        this.cursors = reduced.cursors;
        this.#emit();
      }
      return;
    }
    if (message?.contract === "nexux.command-center.error") {
      this.lastError = message.code;
      if (message.code === "gateway.resync-required") this.resync();
      else this.#emit();
    }
  }

  #acceptSnapshot(snapshot) {
    if (
      snapshot?.contract !== "nexux.command-center.snapshot" ||
      snapshot.v !== CONTRACT_VERSION ||
      snapshot.contract_fingerprint !== CONTRACT_FINGERPRINT
    ) {
      throw new Error("snapshot contract mismatch");
    }
    const nextModel = {};
    const nextCursors = {};
    for (const [topic, incoming] of Object.entries(snapshot.topics || {})) {
      const incomingCursor = snapshot.cursors?.[topic];
      const current = this.readModel[topic];
      const currentCursor = this.cursors[topic];
      const preserveCurrent =
        current &&
        (currentCursor > incomingCursor ||
          (currentCursor === incomingCursor &&
            current.observed_at > incoming.observed_at));
      nextModel[topic] = structuredClone(
        preserveCurrent ? current : incoming,
      );
      nextCursors[topic] = preserveCurrent
        ? currentCursor
        : incomingCursor;
    }
    this.readModel = nextModel;
    this.cursors = nextCursors;
    this.subject = snapshot.subject;
    this.snapshotAt = snapshot.generated_at;
    this.#scheduleFreshnessRefresh();
  }

  #fail(code) {
    this.lastError = code;
    this.connection = Object.keys(this.readModel).length
      ? "degraded"
      : "disconnected";
    this.connectionDegradedAt = this.connection === "degraded" ? this.now() : null;
    this.#emit();
  }

  #scheduleReconnect() {
    if (this.manualClose || this.reconnectTimer) return;
    const index = Math.min(
      this.reconnectAttempt,
      RECONNECT_DELAYS.length - 1,
    );
    const delay = RECONNECT_DELAYS[index];
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.#loadSnapshot()
        .catch(() => {})
        .finally(() => this.#connect());
    }, delay);
  }

  #scheduleFreshnessRefresh() {
    clearTimeout(this.freshnessTimer);
    this.freshnessTimer = null;
    const deadlines = Object.values(this.readModel)
      .map((envelope) => envelope?.stale_at)
      .filter((value) => Number.isFinite(value));
    if (!deadlines.length || this.manualClose) return;
    const nextDeadline = Math.min(...deadlines);
    const delay = Math.max(1000, nextDeadline - this.now() - 1000);
    this.freshnessTimer = setTimeout(() => {
      this.freshnessTimer = null;
      this.#loadSnapshot().catch(() => this.#scheduleReconnect());
    }, delay);
  }

  #emit() {
    this.onChange(this.state());
  }
}

function fixtureState(name) {
  const now = Date.now();
  const staleOffset =
    name === "expired" ? -2000 : name === "stale" ? -1000 : 30_000;
  const expiryOffset = name === "expired" ? -1000 : 60_000;
  const health = name === "degraded" ? "degraded" : "healthy";
  const degradation =
    name === "degraded"
      ? {
          category: "source-unavailable",
          code: "fixture.provider-delayed",
          retryable: true,
          since: now - 60_000,
        }
      : null;
  const envelope = (topic, source, data) => ({
    contract: "nexux.command-center.event",
    v: 1,
    topic,
    kind: "snapshot",
    subject: "user:local",
    seq: 0,
    observed_at: now - 2000,
    received_at: now,
    stale_at: now + staleOffset,
    expires_at: now + expiryOffset,
    severity: health === "degraded" ? "warning" : "normal",
    source,
    payload: {
      state: {
        health,
        freshness:
          name === "expired" ? "expired" : name === "stale" ? "stale" : "live",
        mode: "not_applicable",
        severity: health === "degraded" ? "warning" : "normal",
        source,
        as_of: now - 2000,
        availability: health === "degraded" ? "degraded" : "available",
        degradation,
      },
      data,
    },
  });
  return {
    readModel: {
      "system.session": envelope("system.session", "nexux:auth", {
        authenticated: true,
        role: "admin",
        synthetic: true,
      }),
      "system.modules": envelope("system.modules", "nexux:config", {
        modules: [
          { slug: "trading", enabled: true, access: "authenticated" },
          { slug: "coinglass", enabled: true, access: "authenticated" },
          { slug: "journal", enabled: true, access: "authenticated" },
          { slug: "bot", enabled: false, access: "admin" },
          { slug: "command-center", enabled: true, access: "authenticated" },
        ],
      }),
    },
    cursors: { "system.session": 0, "system.modules": 0 },
    subject: "user:local",
    snapshotAt: now,
    connection: name === "disconnected" ? "disconnected" : name,
    lastError:
      name === "disconnected" ? "fixture.gateway-unavailable" : null,
    resyncing: false,
    now,
  };
}

function fixtureMacroState() {
  const now = Date.now();
  return {
    status: "ready",
    event: {
      title: "Decisión de tasas · fixture",
      country: "USD",
      impact: "High",
      ts: Math.round(now / 1000) + 42 * 60,
    },
    generatedAt: now,
    error: null,
    now,
  };
}

function fixtureAiContext() {
  return {
    state: "ready",
    severity: "warning",
    summary: "La observación contractual requiere revisión manual.",
    lastEvaluationMs: Date.now() - 4 * 60_000,
    freshness: "current",
    source: "Fixture contractual",
  };
}

function fixturePositionsContext() {
  return normalizePositionsContext({
    state: "ready",
    generated_at_ms: Date.now(),
    total_positions: 2,
    read_only: true,
    accounts: [
      {
        id: "principal", label: "Cuenta principal", environment: "live",
        state: "ready", total_pnl: 18.42,
        positions: [{
          symbol: "BTCUSDT", side: "LONG", entry: 64120.4, mark: 64502.1,
          pnl: 18.42, roe: 6.8, leverage: 5,
        }],
      },
      {
        id: "bot", label: "Cuenta Bot", environment: "testnet",
        state: "ready", total_pnl: -2.15,
        positions: [{
          symbol: "SOLUSDT", side: "SHORT", entry: 77.2, mark: 77.36,
          pnl: -2.15, roe: -1.4, leverage: 5,
        }],
      },
    ],
  });
}

function fixtureMacOSContext() {
  return normalizeMacOSContext({
    state: "ready",
    generated_at_ms: Date.now(),
    device: "Mac de Hugo",
    os_version: "26.0",
    load_percent: 24,
    memory_percent: 58,
    memory_pressure: "normal",
    memory_available_percent: 42,
    disk_percent: 41,
    power_source: "Corriente",
    uptime_seconds: 86_400,
    read_only: true,
  });
}

function fixtureBotContext() {
  return {
    state: "ready",
    mode: "dry-run",
    severity: "info",
    sourceAgeSeconds: 8,
    latestSignal: {
      pair: "BTC",
      direction: "short",
      status: "abierta",
      mode: "dry",
      occurredAtMs: Date.now() - 7 * 60_000,
    },
    readOnly: true,
  };
}

function fixtureMediaContext() {
  return normalizeMediaContext({
    provider: "apple-music",
    lifecycle: "ready",
    playback: "playing",
    freshness: "live",
    observed_at_ms: Date.now(),
    track: "Midnight City",
    artist: "M83",
    album: "Hurry Up, We're Dreaming",
    position_seconds: 92,
    duration_seconds: 267,
    progress: 92 / 267,
    item_ref: "music:fixture",
    capabilities: [
      "current_state",
      "play",
      "pause",
      "next",
      "previous",
      "set_volume",
      "open_app",
    ],
    commands_enabled: true,
    read_only: false,
    simulated: true,
  });
}

function fixtureMarketRibbonState() {
  const now = Date.now();
  const definitions = [
    ["spx", "SPX", "SPX", "SP:SPX", 7437.63, 0.396, "index"],
    ["vix", "VIX", "VIX", "TVC:VIX", 17.09, -8.019, "index"],
    ["dxy", "DXY", "DXY", "TVC:DXY", 100.225, -1.266, "index"],
    ["total", "TOTAL", "TOTAL", "CRYPTOCAP:TOTAL", 2.28e12, 0.37, "aggregate"],
    ["btcusdt", "BTCUSDT.P", "BTCUSDT", "BINANCE:BTCUSDT.P", 64375, 0.204, "futures"],
    ["ethusdt", "ETHUSDT.P", "ETHUSDT", "BINANCE:ETHUSDT.P", 3318.2, 0.86, "futures"],
    ["solusdt", "SOLUSDT.P", "SOLUSDT", "BINANCE:SOLUSDT.P", 158.42, -0.72, "futures"],
    ["xrpusdt", "XRPUSDT.P", "XRPUSDT", "BINANCE:XRPUSDT.P", 1.78, 1.14, "futures"],
  ];
  return {
    status: "ready",
    generatedAt: now,
    error: null,
    assets: definitions.map(
      ([id, symbol, chartSymbol, tvSymbol, price, changePct, kind]) => ({
        id,
        symbol,
        chartSymbol,
        tvSymbol,
        price,
        changePct,
        observedAt: now,
        freshness: kind === "index" ? "close" : "live",
        source:
          kind === "index"
            ? "Yahoo Finance"
            : kind === "aggregate"
              ? "CoinGecko"
              : "Binance Futures",
        kind,
      }),
    ),
  };
}

function fixtureHealthState(name) {
  const coreState =
    name === "disconnected" || name === "expired" ? "closed" : "ready";
  return {
    status: name === "disconnected" ? "failed" : "ready",
    health: {
      status: name === "disconnected" ? "error" : "ok",
      modules: [
        {
          slug: "trading",
          status: name === "degraded" ? "degradado" : "ok",
          upstream_ok: name !== "degraded",
          last_update_ms: Date.now(),
        },
        {
          slug: "command-center",
          event_bus: { status: coreState },
          module_registry: {
            modules: [
              {
                module_id: "media.controller",
                factory_attached: false,
                lifecycle: "declared",
              },
            ],
          },
        },
      ],
    },
    checkedAt: Date.now(),
    error: null,
  };
}

function worstFreshness(readModel, now) {
  const rank = { live: 0, current: 0, unknown: 1, stale: 2, expired: 3 };
  return Object.values(readModel).reduce((worst, envelope) => {
    const next = projectionFreshness(envelope, now);
    return rank[next] > rank[worst] ? next : worst;
  }, "live");
}

function worstSeverity(readModel) {
  const rank = { normal: 0, info: 1, unknown: 2, warning: 3, critical: 4 };
  return Object.values(readModel).reduce((worst, envelope) => {
    const next = envelope?.severity || "unknown";
    return rank[next] > rank[worst] ? next : worst;
  }, "normal");
}

function label(value) {
  const labels = {
    loading: "Sincronizando",
    ready: "Conectado",
    degraded: "Degradado",
    stale: "Desactualizado",
    expired: "Expirado",
    disconnected: "Desconectado",
    live: "En vivo",
    current: "Actual",
    unknown: "Desconocida",
  };
  return labels[value] || value;
}

function render(state) {
  const now = Date.now();
  const readModel = state.readModel || {};
  const freshness = worstFreshness(readModel, now);
  let operational = state.connection;
  if (state.connection === "ready" && freshness === "stale") operational = "stale";
  if (freshness === "expired") operational = "expired";

  const connection = document.querySelector("#connection-state");
  connection.dataset.state = operational;
  connection.querySelector("span").textContent = label(operational);

  const modules =
    readModel["system.modules"]?.payload?.data?.modules || [];
  document.querySelector("#subject-state").textContent = state.subject
    ? `Sesión ${state.subject.replace("user:", "")}`
    : "Sesión pendiente";

  const cursorValues = Object.values(state.cursors || {});
  document.querySelector("#sequence-state").textContent = cursorValues.length
    ? `${modules.length} módulos · ${cursorValues.length} cursores · seq ${Math.max(...cursorValues)}`
    : `${modules.length} módulos · sin cursor`;
  document.querySelector("#last-update").textContent = state.snapshotAt
    ? `Snapshot ${new Date(state.snapshotAt).toLocaleTimeString("es-CL", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })}`
    : "Sin lectura todavía";

  document.querySelector("#resync-button").disabled =
    state.resyncing || state.connection === "loading";
}

function renderOperationalReadiness(readiness) {
  document.querySelector(".status-footer").dataset.state = readiness.overall;
  const health = deriveOperationalHealth(readiness);
  const overall = document.querySelector("#readiness-overall");
  overall.dataset.state = readiness.overall;
  overall.textContent = health.label;
  overall.title = health.explanation;
  overall.setAttribute("aria-label", `${health.label}. ${health.explanation}`);
  document.querySelector("#readiness-answer").textContent = health.explanation;
  const list = document.querySelector("#readiness-list");
  list.replaceChildren(
    ...readiness.services
      .filter((service) => REQUIRED_READINESS_IDS.has(service.id))
      .map((service) => {
        const item = document.createElement("li");
        item.className = "readiness-item";
        item.title = service.evidence || "Sin evidencia adicional";
        const name = document.createElement("span");
        name.className = "readiness-name";
        name.textContent = service.name;
        const state = document.createElement("span");
        state.className = "readiness-state";
        state.dataset.state = service.state;
        state.textContent = READINESS_LABELS[service.state];
        item.append(name, state);
        return item;
      }),
  );
}

function renderMacro(state) {
  const badge = document.querySelector("#macro-impact");
  if (!badge) return;
  badge.dataset.state = state.status;
  const event = state.event;
  if (state.status === "ready" && event) {
    badge.textContent = "Alto";
    document.querySelector("#macro-countdown").textContent =
      formatMacroCountdown(event.ts, state.now);
    document.querySelector("#macro-country").textContent =
      event.country || "Global";
    document.querySelector("#macro-event").textContent =
      event.title || "Evento sin título";
  } else {
    const copies = {
      loading: ["Esperando", "--", "Calendario", "Consultando calendario real."],
      empty: ["Sin próximos", "--", "Calendario", "No hay eventos futuros publicados esta semana."],
      degraded: ["No disponible", "--", "Calendario", "La última consulta del calendario falló."],
    };
    const [status, countdown, country, message] =
      copies[state.status] || copies.degraded;
    badge.textContent = status;
    document.querySelector("#macro-countdown").textContent = countdown;
    document.querySelector("#macro-country").textContent = country;
    document.querySelector("#macro-event").textContent = message;
  }
  document.querySelector("#macro-updated").textContent = state.generatedAt
    ? `Leído ${new Date(state.generatedAt).toLocaleTimeString("es-CL", {
        hour: "2-digit",
        minute: "2-digit",
      })}`
    : "Sin lectura";
}

function renderAiContext(context) {
  const badge = document.querySelector("#ai-severity");
  const summary = document.querySelector("#ai-summary");
  const visualState =
    context.state === "ready" ? context.severity : context.state;
  badge.dataset.state = visualState;
  const labels = {
    normal: "Normal",
    info: "Info",
    warning: "Atención",
    critical: "Crítica",
    disabled: "Inactiva",
    degraded: "Degradada",
    unknown: "Unknown",
  };
  badge.textContent = labels[visualState] || "Unknown";
  summary.dataset.state = context.state;
  summary.textContent =
    context.summary || (
      context.state === "disabled"
        ? "La IA está inactiva y no existe una observación vigente."
        : context.state === "degraded"
          ? "No fue posible verificar una observación de IA."
          : "Sin observación contractual vigente."
    );
  document.querySelector("#ai-source").textContent =
    context.source || (
      context.state === "disabled" ? "IA inactiva" : "Sin proveedor"
    );
  document.querySelector("#ai-updated").textContent =
    context.lastEvaluationMs
      ? `Evaluado ${new Date(context.lastEvaluationMs).toLocaleTimeString(
          "es-CL",
          { hour: "2-digit", minute: "2-digit" },
        )}`
      : "Sin evaluación";
}

function formatPositionNumber(value, { signed = false, suffix = "" } = {}) {
  if (!Number.isFinite(value)) return "--";
  const magnitude = Math.abs(value);
  const digits = magnitude >= 1000 ? 1 : magnitude >= 10 ? 2 : 3;
  const formatted = new Intl.NumberFormat("es-CL", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
    signDisplay: signed ? "always" : "auto",
  }).format(value);
  return `${formatted}${suffix}`;
}

function renderPositionsContext(context) {
  const badge = document.querySelector("#positions-state");
  badge.dataset.state = context.state === "ready" ? "ready" : "degraded";
  badge.textContent = context.totalPositions
    ? `${context.totalPositions} abierta${context.totalPositions === 1 ? "" : "s"}`
    : (context.state === "ready" ? "Sin posiciones" : "Revisar fuente");

  for (const account of context.accounts) {
    const root = document.querySelector(`#positions-${account.id}`);
    if (!root) continue;
    root.dataset.state = account.state;
    const title = root.querySelector("strong");
    title.textContent = account.label;
    title.dataset.environment = account.environment;
    const pnl = root.querySelector("[data-account-pnl]");
    pnl.textContent = `${formatPositionNumber(account.totalPnl, { signed: true })} USDT`;
    pnl.dataset.sign = account.totalPnl > 0 ? "positive" : (
      account.totalPnl < 0 ? "negative" : "flat"
    );
    const list = root.querySelector("[data-account-positions]");
    list.replaceChildren();
    if (!account.positions.length) {
      const empty = document.createElement("span");
      empty.className = "position-empty";
      empty.textContent = account.state === "ready"
        ? `Sin operaciones · ${account.environment}`
        : (account.detail || "Fuente no disponible");
      list.append(empty);
      continue;
    }
    for (const position of account.positions) {
      const row = document.createElement("div");
      row.className = "position-row";
      const identity = document.createElement("div");
      identity.className = "position-identity";
      const symbol = document.createElement("strong");
      symbol.textContent = position.symbol.replace(/USDT$/, "");
      const side = document.createElement("span");
      side.dataset.side = position.side.toLowerCase();
      side.textContent = `${position.side === "LONG" ? "Long" : "Short"}${
        position.leverage ? ` ${formatPositionNumber(position.leverage)}x` : ""
      }`;
      identity.append(symbol, side);
      const prices = document.createElement("span");
      prices.className = "position-prices";
      prices.textContent = `E ${formatPositionNumber(position.entry)} · M ${formatPositionNumber(position.mark)}`;
      const performance = document.createElement("div");
      performance.className = "position-performance";
      const positionPnl = document.createElement("strong");
      positionPnl.dataset.sign = position.pnl > 0 ? "positive" : (
        position.pnl < 0 ? "negative" : "flat"
      );
      positionPnl.textContent = `${formatPositionNumber(position.pnl, { signed: true })} USDT`;
      const roe = document.createElement("span");
      roe.textContent = `ROE ${formatPositionNumber(position.roe, { signed: true, suffix: "%" })}`;
      performance.append(positionPnl, roe);
      row.append(identity, prices, performance);
      list.append(row);
    }
  }
  document.querySelector("#positions-detail").textContent = context.readOnly
    ? "Principal + Bot · solo lectura"
    : "Fuente no confirmada";
  document.querySelector("#positions-updated").textContent = context.generatedAtMs
    ? `Leído ${new Date(context.generatedAtMs).toLocaleTimeString("es-CL", {
        hour: "2-digit", minute: "2-digit",
      })}`
    : "Sin lectura";
}

function formatMacUptime(seconds) {
  if (!Number.isFinite(seconds)) return "Sin lectura";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3600);
  if (days) return `Activo ${days} d ${hours} h`;
  return `Activo ${hours} h`;
}

function renderMacOSContext(context) {
  const badge = document.querySelector("#macos-state");
  badge.dataset.state = context.state;
  const labels = {
    ready: "Listo",
    degraded: "Revisar",
    unavailable: "Solo local",
  };
  badge.textContent = badge.classList.contains("macos-compact-state")
    ? "macOS"
    : labels[context.state] || "Sin datos";
  badge.title = labels[context.state] || "Sin datos";
  document.querySelector("#macos-answer").textContent = context.detail || (
    context.state === "ready"
      ? "El equipo local está listo para operar."
      : context.state === "degraded"
        ? "Una lectura del equipo requiere revisión."
        : "La telemetría está disponible solo en este Mac."
  );
  const percent = (value) => Number.isFinite(value)
    ? `${value.toLocaleString("es-CL", { maximumFractionDigits: 1 })}%`
    : "--";
  document.querySelector("#macos-load").textContent = percent(context.loadPercent);
  const memoryPressure = document.querySelector("#macos-memory-pressure");
  const pressureLabels = {
    normal: "Normal",
    elevated: "Elevada",
    critical: "Crítica",
    unknown: "Sin lectura",
  };
  memoryPressure.dataset.state = context.memoryPressure;
  memoryPressure.textContent = pressureLabels[context.memoryPressure] || "Sin lectura";
  memoryPressure.title = Number.isFinite(context.memoryAvailablePercent)
    ? `${percent(context.memoryAvailablePercent)} disponible · ${percent(context.memoryPercent)} ocupado`
    : `${percent(context.memoryPercent)} ocupado`;
  document.querySelector("#macos-memory").textContent = percent(context.memoryPercent);
  document.querySelector("#macos-disk").textContent = percent(context.diskPercent);
  document.querySelector("#macos-power").textContent = context.batteryPercent === null
    ? context.powerSource
    : `${context.batteryPercent.toLocaleString("es-CL")}%`;
  document.querySelector("#macos-device").textContent =
    `${context.device} · ${context.osVersion}`;
  document.querySelector("#macos-uptime").textContent =
    formatMacUptime(context.uptimeSeconds);
}

function renderImmediateAttention(attention, timelineEntries = []) {
  const attentionMode = {
    normal: "calm",
    info: "calm",
    warning: "elevated",
    critical: "focused",
    unknown: "unknown",
  }[attention.state] || "unknown";
  document.querySelector(".app-shell").dataset.attentionMode = attentionMode;
  document.querySelector(".attention-panel").dataset.attentionMode = attentionMode;
  const badge = document.querySelector("#attention-state");
  document.querySelector("#calendar-alert").dataset.state = attention.state;
  badge.dataset.state = attention.state;
  const labels = {
    normal: "Sin alertas",
    info: "Información",
    warning: "Atención",
    critical: "Crítico",
    unknown: "Esperando",
  };
  badge.textContent = labels[attention.state] || labels.unknown;
  const summary = document.querySelector("#attention-summary");
  summary.dataset.state = attention.state;
  summary.textContent = attention.summary;
  summary.title = attention.explanation || attention.detail;
  const list = document.querySelector("#attention-list");
  const alertItems = (attention.items || []).filter((source) =>
    source.state === "warning" ||
    source.state === "critical" ||
    source.state === "unknown"
  );
  const visibleTimeline = selectTimelineForAttention(
    attention,
    timelineEntries,
  );
  list.dataset.timelineActive = String(visibleTimeline.length > 0);
  const sources = [
    ...alertItems,
    ...visibleTimeline.map((event) => ({
      label: new Date(event.occurredAtMs).toLocaleTimeString("es-CL", {
        hour: "2-digit",
        minute: "2-digit",
      }),
      detail: event.label,
      state: event.severity,
      evidence: event.detail,
    })),
  ];
  list.replaceChildren(...sources.map((source) => {
    const item = document.createElement("div");
    item.className = "attention-item";
    item.dataset.state = source.state;
    if (source.evidence) item.title = source.evidence;
    const name = document.createElement("strong");
    name.textContent = source.label;
    const detail = document.createElement("span");
    detail.textContent = source.detail;
    item.append(name, detail);
    return item;
  }));
  document.querySelector("#attention-detail").textContent = attention.detail;
  document.querySelector("#attention-updated").textContent =
    attention.evaluatedAtMs
      ? `Evaluado ${new Date(attention.evaluatedAtMs).toLocaleTimeString(
          "es-CL",
          { hour: "2-digit", minute: "2-digit" },
        )}`
      : "Sin lectura";
}

export function selectTimelineForAttention(
  attention,
  timelineEntries,
  now = attention?.evaluatedAtMs || Date.now(),
) {
  if (attention?.state === "critical" || attention?.state === "unknown") {
    return [];
  }
  const recent = (Array.isArray(timelineEntries) ? timelineEntries : [])
    .filter((event) => {
      const age = now - Number(event?.occurredAtMs);
      return Number.isFinite(age) && age >= 0 && age <= 15 * 60_000;
    });
  return recent.slice(0, attention?.state === "warning" ? 1 : 2);
}

function renderMediaContext(context) {
  const providerLabels = {
    "apple-music": "Apple Music",
    qobuz: "Qobuz",
    tidal: "TIDAL",
  };
  document.querySelectorAll("[data-media-provider]").forEach((button) => {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.mediaProvider === context.selectedProvider),
    );
  });
  const badge = document.querySelector("#music-state");
  const stateLabels = {
    ready: "Lista",
    degraded: "Degradada",
    unavailable: "No disponible",
    revoked: "Sin permiso",
    closed: "Cerrada",
    unknown: "Sin datos",
  };
  const capabilities = new Set(context.capabilities);
  const hasPlaybackControls =
    capabilities.has("play") && capabilities.has("pause");
  badge.dataset.state =
    context.lifecycle === "ready" ? "ready" : context.lifecycle;
  badge.textContent =
    context.lifecycle === "ready" && context.playback === "playing"
      ? "Reproduciendo"
      : context.lifecycle === "unavailable"
        ? "Cerrada"
        : stateLabels[context.lifecycle] || "Sin datos";
  const selectedLabel = providerLabels[context.selectedProvider] || "Música";
  document.querySelector("#music-provider-label").textContent =
    context.provider || selectedLabel;
  document.querySelector("#music-track").textContent =
    context.track || (
      context.itemRef
        ? "Pista identificada"
        : context.lifecycle === "ready"
          ? "Sin reproducción disponible"
          : `Abrir ${selectedLabel}`
    );
  const details = [context.artist, context.album].filter(Boolean);
  document.querySelector("#music-detail").textContent =
    details.length
      ? details.join(" · ")
      : hasPlaybackControls
        ? `${selectedLabel} · reproductor local`
        : context.provider || `${selectedLabel} · integración local inactiva`;

  const artworkImage = document.querySelector("#music-artwork-image");
  if (context.artworkUrl) {
    artworkImage.src = context.artworkUrl;
    artworkImage.hidden = false;
  } else {
    artworkImage.removeAttribute("src");
    artworkImage.hidden = true;
  }

  const canControl =
    context.commandsEnabled &&
    context.lifecycle === "ready" &&
    context.busy !== true;
  const canStart =
    context.commandsEnabled &&
    context.lifecycle === "unavailable" &&
    context.busy !== true &&
    capabilities.has("play") &&
    capabilities.has("open_app");
  const controls = {
    open: document.querySelector("#music-open"),
    previous: document.querySelector("#music-previous"),
    toggle: document.querySelector("#music-toggle"),
    next: document.querySelector("#music-next"),
  };
  controls.open.disabled =
    !context.commandsEnabled ||
    context.busy === true ||
    !capabilities.has("open_app");
  controls.previous.disabled =
    !canControl || !capabilities.has("previous");
  controls.next.disabled = !canControl || !capabilities.has("next");
  controls.previous.hidden = !hasPlaybackControls;
  controls.toggle.hidden = !hasPlaybackControls;
  controls.next.hidden = !hasPlaybackControls;
  const toggleAction =
    context.playback === "playing" ? "pause" : "play";
  controls.toggle.disabled =
    !(canStart || (canControl && capabilities.has(toggleAction)));
  controls.toggle.dataset.action = toggleAction;
  controls.toggle.title =
    toggleAction === "pause" ? "Pausar" : "Reproducir";
  controls.toggle.setAttribute("aria-label", controls.toggle.title);
  document.querySelector("#music-toggle-icon").setAttribute(
    "d",
    toggleAction === "pause" ? "M8 5v14M16 5v14" : "M8 5v14l11-7z",
  );
  document.querySelector("#music-feedback").textContent =
    context.feedback || (
      context.simulated
      ? "Fixture sin efectos"
      : context.commandsEnabled
        ? FRESHNESS_LABELS[context.freshness] || "Estado leído"
        : "Solo lectura"
    );

  const duration = context.durationSeconds > 0
    ? context.durationSeconds
    : null;
  const position = context.positionSeconds !== null
    ? context.positionSeconds
    : null;
  const progress = context.progress !== null
    ? context.progress
    : duration && position !== null
      ? Math.min(1, position / duration)
      : null;
  const progressRoot = document.querySelector("#music-progress");
  progressRoot.dataset.known = String(progress !== null);
  document.querySelector("#music-progress-value").style.width =
    `${Math.round((progress || 0) * 1000) / 10}%`;
  document.querySelector("#music-elapsed").textContent =
    position !== null ? formatMediaTime(position) : "--:--";
  document.querySelector("#music-duration").textContent =
    duration !== null ? formatMediaTime(duration) : "--:--";
}

function formatMediaTime(value) {
  if (!Number.isFinite(value) || value < 0) return "--:--";
  const seconds = Math.floor(value);
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function wireMediaControls(onAction) {
  document.querySelectorAll(".music-control, .music-open").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.id === "music-toggle"
        ? button.dataset.action
        : button.id === "music-open"
          ? "open_app"
          : button.id.replace("music-", "");
      onAction(action);
    });
  });
}

function wireMediaProviderSelector(onSelect) {
  document.querySelectorAll("[data-media-provider]").forEach((button) => {
    button.addEventListener("click", () => {
      onSelect(button.dataset.mediaProvider);
    });
  });
}

const FRESHNESS_LABELS = {
  live: "En vivo",
  current: "Actual",
  close: "Último cierre",
  stale: "Desactualizado",
  unknown: "Sin lectura",
};
const ZAPPING_URL = "https://app.zapping.com/";
const STREAMING_PROVIDERS = Object.freeze({
  disney: { label: "Disney+", url: "https://www.disneyplus.com/" },
  apple_tv: { label: "Apple TV", url: "https://tv.apple.com/" },
  max: { label: "HBO Max", url: "https://www.hbomax.com/" },
  youtube: { label: "YouTube", url: "https://www.youtube.com/" },
});
let selectedMarketAssetId = "btcusdt";
let lastMarketRibbonState = null;
let activeChartAdapter = null;
let chartQueue = Promise.resolve();
let lastChartFailureDetail = null;
let primaryView = "market";
const CHART_INTERVAL_STORAGE_KEY = "nexux.command-center.chart-interval.v1";
let selectedChartInterval = (() => {
  try {
    const saved = localStorage.getItem(CHART_INTERVAL_STORAGE_KEY);
    return ["1m", "3m", "5m", "15m", "30m", "45m", "1h", "2h", "3h", "4h", "1D", "1W"]
      .includes(saved) ? saved : "1h";
  } catch (_error) {
    return "1h";
  }
})();
let candleCountdownTimer = null;
let chartIntervalRevision = 0;

const CHART_INTERVAL_SECONDS = Object.freeze({
  "1m": 60,
  "3m": 3 * 60,
  "5m": 5 * 60,
  "15m": 15 * 60,
  "30m": 30 * 60,
  "45m": 45 * 60,
  "1h": 60 * 60,
  "2h": 2 * 60 * 60,
  "3h": 3 * 60 * 60,
  "4h": 4 * 60 * 60,
  "1D": 24 * 60 * 60,
  "1W": 7 * 24 * 60 * 60,
});

const AURORA_PREVIEW_STATES = Object.freeze({
  listening: ["Escuchando", "Conversación local"],
  thinking: ["Procesando", "Evidencia local"],
  responding: ["Respondiendo", "Conversación local"],
  waiting: ["En espera", "Sesión disponible"],
});

export function configureAuroraPreview(parameters = new URLSearchParams()) {
  const panel = document.querySelector("#aurora-preview");
  const app = document.querySelector("#app");
  const state = parameters.get("aurora_preview");
  const copy = AURORA_PREVIEW_STATES[state];
  if (!panel || !app || !copy) {
    if (panel) panel.hidden = true;
    if (app) delete app.dataset.auroraPreviewActive;
    return false;
  }
  document.querySelector("#aurora-preview-title").textContent = copy[0];
  document.querySelector("#aurora-preview-detail").textContent = copy[1];
  panel.dataset.state = state;
  panel.hidden = false;
  app.dataset.auroraPreviewActive = "true";
  return true;
}

function syncNativeTV(view) {
  const handler = window.webkit?.messageHandlers?.commandCenter;
  if (!handler) return false;
  const rect = document.querySelector("#zapping-target").getBoundingClientRect();
  handler.postMessage({
    type: "primaryView",
    view,
    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
  });
  return true;
}

function selectedMarketAsset() {
  return lastMarketRibbonState?.assets?.find(
    (asset) => asset.id === selectedMarketAssetId,
  ) || {
    id: "btcusdt",
    symbol: "BTCUSDT.P",
    chartSymbol: "BTCUSDT",
    tvSymbol: "BINANCE:BTCUSDT.P",
  };
}

export function openStreamingProvider(provider) {
  const definition = STREAMING_PROVIDERS[provider];
  if (!definition) return false;
  const handler = window.webkit?.messageHandlers?.commandCenter;
  if (handler) {
    const rect = document.querySelector("#streaming-target").getBoundingClientRect();
    handler.postMessage({
      type: "openStreaming",
      provider,
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
    });
  } else {
    window.open(definition.url, "_blank", "noopener,noreferrer");
  }
  return true;
}

export function setPrimaryView(view) {
  if (!(["market", "tv", "streaming"].includes(view))) return false;
  primaryView = view;
  const chartTarget = document.querySelector("#chart-target");
  const zappingTarget = document.querySelector("#zapping-target");
  const streamingTarget = document.querySelector("#streaming-target");
  const zappingFrame = document.querySelector("#zapping-frame");
  const source = document.querySelector("#primary-source-label");
  const external = document.querySelector("#full-analysis-link");
  const externalLabel = document.querySelector("#full-analysis-label");
  const chartTimeControls = document.querySelector("#chart-time-controls");

  document.querySelectorAll("[data-primary-view]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.primaryView === view));
  });
  chartTarget.hidden = view !== "market";
  zappingTarget.hidden = view !== "tv";
  streamingTarget.hidden = view !== "streaming";
  external.hidden = view === "streaming";
  chartTimeControls.hidden = view !== "market";

  if (view === "tv") {
    document.querySelector("#market-symbol-title").textContent = "Zapping TV";
    document.querySelector("#market-interval-title").textContent = "· En vivo";
    source.textContent = "Zapping · señal oficial";
    external.href = ZAPPING_URL;
    externalLabel.textContent = "Abrir Zapping";
    const nativeTV = syncNativeTV("tv");
    zappingFrame.hidden = nativeTV;
    if (!nativeTV && !zappingFrame.src) zappingFrame.src = zappingFrame.dataset.src;
  } else if (view === "streaming") {
    syncNativeTV("streaming");
    document.querySelector("#market-symbol-title").textContent = "Streaming";
    document.querySelector("#market-interval-title").textContent = "· fútbol";
    source.textContent = "Entretenimiento · sesión local";
  } else {
    syncNativeTV("market");
    setChartLabels(selectedMarketAsset());
    source.textContent = chartProviderPreference() === "tradingview"
      ? "TradingView · reversión"
      : "NexUX Chart · fuente declarada";
    externalLabel.textContent = "Análisis completo";
  }
  try {
    localStorage.setItem("nexux.primary-view", view);
  } catch (_error) {
    // La preferencia es conveniente, no necesaria para operar.
  }
  return true;
}

function wirePrimaryViewSelector() {
  document.querySelectorAll("[data-primary-view]").forEach((button) => {
    button.addEventListener("click", () => setPrimaryView(button.dataset.primaryView));
  });
  let saved = "market";
  try {
    saved = localStorage.getItem("nexux.primary-view") || "market";
  } catch (_error) {
    saved = "market";
  }
  setPrimaryView(["tv", "streaming"].includes(saved) ? saved : "market");
  window.addEventListener("resize", () => {
    if (primaryView === "tv") syncNativeTV("tv");
  });
}

function wireStreamingProviders() {
  document.querySelectorAll("[data-streaming-provider]").forEach((button) => {
    button.addEventListener("click", () => {
      openStreamingProvider(button.dataset.streamingProvider);
    });
  });
}

function marketChangeDirection(change) {
  if (!Number.isFinite(change) || change === 0) return "flat";
  return change > 0 ? "up" : "down";
}

function formatMarketChange(change) {
  if (!Number.isFinite(change)) return "--";
  return `${change > 0 ? "+" : ""}${change.toFixed(2)}%`;
}

export function describeChartFallback(asset, detail = null) {
  const hasPrice = Number.isFinite(asset?.price);
  return {
    title: "Gráfico no disponible",
    explanation: detail ||
      "El proveedor gráfico no respondió. El resto del Command Center continúa disponible.",
    reading: hasPrice
      ? `${asset.symbol} ${formatMarketPrice(asset)} · ${formatMarketChange(asset.changePct)}`
      : "Sin una lectura de precio confirmada.",
    provenance: hasPrice
      ? `Última lectura fiable · ${FRESHNESS_LABELS[asset.freshness] || "Sin lectura"}${
          asset.observedAt
            ? ` · ${new Date(asset.observedAt).toLocaleTimeString("es-CL", {
                hour: "2-digit", minute: "2-digit",
              })}`
            : ""
        }`
      : "Use Análisis completo para continuar en TradingView.",
  };
}

export function chartProviderPreference(parameters = new URLSearchParams(location.search)) {
  return parameters.get("provider") === "tradingview" ? "tradingview" : "nexux";
}

function renderChartFallback(target, asset, detail = null) {
  const copy = describeChartFallback(asset, detail);
  const root = document.createElement("div");
  root.className = "chart-placeholder chart-placeholder-context";
  const title = document.createElement("span");
  title.textContent = copy.title;
  const explanation = document.createElement("small");
  explanation.textContent = copy.explanation;
  const reading = document.createElement("strong");
  reading.textContent = copy.reading;
  const provenance = document.createElement("small");
  provenance.textContent = copy.provenance;
  root.append(title, explanation, reading, provenance);
  target.replaceChildren(root);
}

function renderMarketRibbon(state) {
  lastMarketRibbonState = state;
  const insight = deriveMarketInsight(state.assets);
  const insightNode = document.querySelector("#market-ribbon-insight");
  insightNode.dataset.state = insight.state;
  insightNode.textContent = insight.text;
  insightNode.title = insight.evidence;
  const selectedAsset = state.assets.find(
    (asset) => asset.id === selectedMarketAssetId,
  );
  const chartTarget = document.querySelector("#chart-target");
  if (
    selectedAsset &&
    (chartTarget?.dataset.chartState === "degraded" ||
      chartTarget?.dataset.chartState === "omitted")
  ) {
    renderChartFallback(chartTarget, selectedAsset, lastChartFailureDetail);
  }
  const list = document.querySelector("#market-ribbon-list");
  list.replaceChildren(
    ...state.assets.map((asset) => {
      const external = asset.chartMode === "external_only";
      const control = document.createElement(external ? "a" : "button");
      control.className = "market-asset";
      if (external) {
        control.href = tradingViewAnalysisUrl(asset);
        control.target = "_blank";
        control.rel = "noopener noreferrer";
      } else {
        control.type = "button";
      }
      control.dataset.assetId = asset.id;
      control.dataset.destination =
        asset.chartMode === "external_only" ? "tradingview" : "embedded";
      control.setAttribute(
        "aria-pressed",
        String(
          asset.chartMode !== "external_only" &&
          asset.id === selectedMarketAssetId,
        ),
      );
      control.title = [
        asset.chartMode === "external_only"
          ? "Abrir análisis completo en TradingView"
          : "Mostrar gráfico en Command Center",
        asset.source || "Fuente no disponible",
        FRESHNESS_LABELS[asset.freshness],
        asset.observedAt
          ? new Date(asset.observedAt).toLocaleString("es-CL")
          : "sin timestamp",
      ].join(" · ");

      const symbol = document.createElement("span");
      symbol.className = "market-symbol";
      symbol.textContent = asset.symbol;
      const freshness = document.createElement("span");
      freshness.className = "market-freshness";
      freshness.dataset.state = asset.freshness;
      freshness.setAttribute(
        "aria-label",
        `Frescura: ${FRESHNESS_LABELS[asset.freshness]}`,
      );
      const price = document.createElement("span");
      price.className = "market-price";
      price.textContent = formatMarketPrice(asset);
      const change = document.createElement("span");
      change.className = "market-change";
      change.dataset.direction = marketChangeDirection(asset.changePct);
      change.textContent = formatMarketChange(asset.changePct);
      control.append(symbol, freshness, price, change);
      if (!external) {
        control.addEventListener("click", () => selectMarketAsset(asset));
      }
      return control;
    }),
  );
}

export function tradingViewAnalysisUrl(asset) {
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(
    asset.tvSymbol,
  )}`;
}

export function openTradingViewAnalysis(asset) {
  if (!asset?.tvSymbol) return false;
  window.open(
    tradingViewAnalysisUrl(asset),
    "_blank",
    "noopener,noreferrer",
  );
  return true;
}

function setChartLabels(asset) {
  if (primaryView !== "market") return;
  document.querySelector("#market-symbol-title").textContent = asset.symbol;
  document.querySelector("#market-interval-title").textContent =
    `· ${selectedChartInterval}`;
  const fullAnalysis = document.querySelector("#full-analysis-link");
  fullAnalysis.href = tradingViewAnalysisUrl(asset);
}

function synchronizeRibbonWithChart(reading) {
  const asset = lastMarketRibbonState?.assets?.find(
    (candidate) => candidate.chartSymbol === reading?.symbol,
  );
  if (!asset || asset.id !== selectedMarketAssetId || !Number.isFinite(reading.price)) return;
  asset.price = reading.price;
  asset.observedAt = reading.observedAt;
  asset.freshness = "live";
  const control = document.querySelector(`[data-asset-id="${asset.id}"]`);
  if (!control) return;
  control.querySelector(".market-price").textContent = formatMarketPrice(asset);
  const freshness = control.querySelector(".market-freshness");
  freshness.dataset.state = "live";
  freshness.setAttribute("aria-label", `Frescura: ${FRESHNESS_LABELS.live}`);
}

async function remountChart(asset) {
  const target = document.querySelector("#chart-target");
  setChartLabels(asset);
  if (new URLSearchParams(location.search).get("chart") === "0") {
    target.dataset.chartState = "omitted";
    lastChartFailureDetail = "Validación sin red externa.";
    renderChartFallback(target, asset, lastChartFailureDetail);
    document.querySelector("#chart-health").textContent = "Proveedor omitido";
    document.querySelector("#chart-latency").textContent =
      "Validación sin red externa";
    return;
  }
  if (activeChartAdapter) await activeChartAdapter.destroy();
  target.dataset.chartState = "mounting";
  const provider = chartProviderPreference();
  const providerLabel = provider === "tradingview" ? "TradingView" : "NexUX Chart";
  target.innerHTML =
    `<div class="chart-placeholder"><span>${providerLabel}</span>` +
    `<small>Montando ${asset.symbol}</small></div>`;
  const adapter = provider === "tradingview"
    ? new TradingViewWidgetAdapter()
    : new NexuxChartProvider();
  activeChartAdapter = adapter;
  window.__nexuxCommandCenterChart = adapter;
  try {
    await adapter.mount(target, {
      targetRef: "command-center:market",
      symbol: asset.chartSymbol,
      interval: selectedChartInterval,
      themeRef: "dark",
      onPrice: synchronizeRibbonWithChart,
    });
    const stats = adapter.stats();
    target.dataset.chartState = "ready";
    lastChartFailureDetail = null;
    document.querySelector("#chart-health").textContent =
      provider === "tradingview" ? "TradingView disponible" : "NexUX Chart en vivo";
    document.querySelector("#chart-latency").textContent =
      `Montaje ${stats.lastMountLatencyMs} ms`;
  } catch (error) {
    target.dataset.chartState = "degraded";
    lastChartFailureDetail = `${providerLabel} no respondió. El resto del Command Center continúa disponible.`;
    const latestAsset = lastMarketRibbonState?.assets?.find(
      (candidate) => candidate.id === selectedMarketAssetId,
    ) || asset;
    renderChartFallback(target, latestAsset, lastChartFailureDetail);
    document.querySelector("#chart-health").textContent =
      "Proveedor degradado";
    document.querySelector("#chart-latency").textContent =
      error?.code || "Montaje fallido";
  }
}

export function selectMarketAsset(asset) {
  if (!asset?.chartSymbol || !asset?.tvSymbol) return Promise.resolve(false);
  if (asset.chartMode === "external_only") {
    return Promise.resolve(openTradingViewAnalysis(asset));
  }
  selectedMarketAssetId = asset.id;
  if (lastMarketRibbonState) renderMarketRibbon(lastMarketRibbonState);
  document
    .querySelectorAll("button.market-asset")
    .forEach((button) => { button.disabled = true; });
  chartQueue = chartQueue
    .catch(() => {})
    .then(() => remountChart(asset))
    .finally(() => {
      document
        .querySelectorAll("button.market-asset")
        .forEach((button) => { button.disabled = false; });
    });
  return chartQueue.then(() => true);
}

export function formatCandleCountdown(interval, now = Date.now()) {
  const duration = CHART_INTERVAL_SECONDS[interval];
  if (!duration) return "--:--";
  let remaining;
  if (interval === "1W") {
    const current = new Date(now);
    const midnightUtc = Date.UTC(
      current.getUTCFullYear(),
      current.getUTCMonth(),
      current.getUTCDate(),
    );
    const daysSinceMonday = (current.getUTCDay() + 6) % 7;
    const nextMonday = midnightUtc - daysSinceMonday * 86_400_000 + 7 * 86_400_000;
    remaining = Math.max(1, Math.ceil((nextMonday - now) / 1000));
  } else {
    const epochSeconds = Math.floor(now / 1000);
    remaining = duration - (epochSeconds % duration);
  }
  const days = Math.floor(remaining / 86_400);
  const hours = Math.floor((remaining % 86_400) / 3600);
  const minutes = Math.floor((remaining % 3600) / 60);
  const seconds = remaining % 60;
  const clock = `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  if (days) return `${days}d ${clock}`;
  if (hours) return clock;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function renderChartTimeControls(now = Date.now()) {
  document.querySelector("#chart-interval-select").value = selectedChartInterval;
  document.querySelector("#candle-countdown").textContent =
    `Próxima vela ${formatCandleCountdown(selectedChartInterval, now)}`;
  if (primaryView === "market") {
    document.querySelector("#market-interval-title").textContent =
      `· ${selectedChartInterval}`;
  }
}

function wireChartTimeControls() {
  document.querySelector("#chart-interval-select").addEventListener("change", (event) => {
    const interval = event.currentTarget.value;
    if (!CHART_INTERVAL_SECONDS[interval] || interval === selectedChartInterval) {
      return;
    }
    const previousInterval = selectedChartInterval;
    const revision = ++chartIntervalRevision;
    selectedChartInterval = interval;
    renderChartTimeControls();
    const adapter = activeChartAdapter;
    if (!adapter || adapter.providerId === "tradingview" || typeof adapter.setInterval !== "function") {
      chartQueue = chartQueue
        .catch(() => {})
        .then(() => remountChart(selectedMarketAsset()));
      return;
    }
    event.currentTarget.disabled = true;
    adapter.setInterval(interval)
      .then(() => {
        if (revision !== chartIntervalRevision || adapter !== activeChartAdapter) return;
        try { localStorage.setItem(CHART_INTERVAL_STORAGE_KEY, interval); } catch (_error) {
          // La selección continúa funcionando aunque el almacenamiento esté restringido.
        }
        document.querySelector("#chart-health").textContent = "NexUX Chart en vivo";
        document.querySelector("#chart-latency").textContent = `Temporalidad ${interval}`;
      })
      .catch(() => {
        if (revision !== chartIntervalRevision || adapter !== activeChartAdapter) return;
        selectedChartInterval = previousInterval;
        renderChartTimeControls();
        document.querySelector("#chart-health").textContent = "Temporalidad no disponible";
      })
      .finally(() => {
        if (revision === chartIntervalRevision) {
          document.querySelector("#chart-interval-select").disabled = false;
        }
      });
  });
  renderChartTimeControls();
  candleCountdownTimer = setInterval(() => renderChartTimeControls(), 1000);
}

function startClock() {
  const tick = () => {
    document.querySelector("#clock").textContent =
      new Date().toLocaleTimeString("es-CL", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
  };
  tick();
  setInterval(tick, 1000);
}

export function bootstrap() {
  startClock();
  wirePrimaryViewSelector();
  wireChartTimeControls();
  wireStreamingProviders();
  document.querySelector("#music-artwork-image").addEventListener("error", (event) => {
    event.currentTarget.hidden = true;
  });
  remountChart({
    id: "btcusdt",
    symbol: "BTCUSDT.P",
    chartSymbol: "BTCUSDT",
    tvSymbol: "BINANCE:BTCUSDT.P",
  });

  const parameters = new URLSearchParams(location.search);
  configureAuroraPreview(parameters);
  const calendarSurface = new CalendarSurface();
  calendarSurface.start();
  const fixture = parameters.get("fixture");
  if (
    FIXTURE_STATES.has(fixture) &&
    parameters.get("fixture_mode") === "1"
  ) {
    const origin = document.querySelector("#data-origin");
    origin.textContent = "Fixture contractual";
    origin.classList.add("fixture");
    const state = fixtureState(fixture);
    const macroState = fixtureMacroState();
    const positionsState = fixturePositionsContext();
    const macosState = fixtureMacOSContext();
    const botState = fixtureBotContext();
    const readinessState = deriveOperationalReadiness({
      commandState: state,
      healthState: fixtureHealthState(fixture),
      online: fixture !== "disconnected",
    });
    render(state);
    renderMacro(macroState);
    calendarSurface.setMacroEvents(macroState.events);
    renderMarketRibbon(fixtureMarketRibbonState());
    renderPositionsContext(positionsState);
    renderMacOSContext(macosState);
    renderImmediateAttention(deriveImmediateAttention({
      readiness: readinessState,
      macro: macroState,
      positions: positionsState,
      bot: botState,
    }));
    renderMediaContext(fixtureMediaContext());
    wireMediaControls((action) => {
      document.querySelector("#music-feedback").textContent =
        `${action} · fake ACK`;
    });
    wireMediaProviderSelector((provider) => {
      document.querySelector("#music-feedback").textContent =
        `${provider} · fixture`;
    });
    renderOperationalReadiness(readinessState);
    document.querySelector("#resync-button").disabled = true;
    return;
  }

  let commandState = null;
  let operationalHealthState = {
    status: "loading",
    health: null,
    checkedAt: null,
    error: null,
  };
  const attentionInputs = {
    readiness: null,
    macro: null,
    positions: null,
    bot: null,
    market: null,
  };
  const operationalTimeline = new OperationalTimeline();
  window.__nexuxOperationalTimeline = operationalTimeline;
  const paintAttention = () => {
    const timelineEntries = operationalTimeline.observe({
      marketInsight: attentionInputs.market
        ? deriveMarketInsight(attentionInputs.market.assets)
        : null,
      readiness: attentionInputs.readiness,
      positions: attentionInputs.positions,
      bot: attentionInputs.bot,
    });
    renderImmediateAttention(
      deriveImmediateAttention(attentionInputs),
      timelineEntries,
    );
  };
  const paintReadiness = () => {
    attentionInputs.readiness = deriveOperationalReadiness({
      commandState,
      healthState: operationalHealthState,
      online: navigator.onLine,
    });
    renderOperationalReadiness(attentionInputs.readiness);
    paintAttention();
  };
  const client = new CommandCenterClient({
    onChange: (state) => {
      commandState = state;
      render(state);
      paintReadiness();
    },
  });
  const macroClient = new MacroContextClient({
    onChange: (state) => {
      attentionInputs.macro = state;
      calendarSurface.setMacroEvents(state.events);
      renderMacro(state);
      paintAttention();
    },
  });
  const marketRibbonClient = new MarketRibbonClient({
    onChange: (state) => {
      attentionInputs.market = state;
      renderMarketRibbon(state);
      paintAttention();
    },
  });
  const positionsContextClient = new PositionsContextClient({
    onChange: (state) => {
      attentionInputs.positions = state;
      renderPositionsContext(state);
      paintAttention();
    },
  });
  const macosContextClient = new MacOSContextClient({
    onChange: renderMacOSContext,
  });
  const botContextClient = new BotContextClient({
    onChange: (state) => {
      attentionInputs.bot = state;
      paintAttention();
    },
  });
  const mediaContextClient = new MediaContextClient({
    onChange: renderMediaContext,
  });
  const healthClient = new OperationalHealthClient({
    onChange: (state) => {
      operationalHealthState = state;
      paintReadiness();
    },
  });
  window.__nexuxCommandCenter = client;
  window.__nexuxCommandCenterMacro = macroClient;
  window.__nexuxCommandCenterMarketRibbon = marketRibbonClient;
  window.__nexuxCommandCenterPositions = positionsContextClient;
  window.__nexuxCommandCenterMacOS = macosContextClient;
  window.__nexuxCommandCenterBot = botContextClient;
  window.__nexuxCommandCenterMedia = mediaContextClient;
  window.__nexuxCommandCenterHealth = healthClient;
  wireMediaControls((action) => {
    mediaContextClient.execute(action).catch(() => {});
  });
  wireMediaProviderSelector((provider) => {
    mediaContextClient.selectProvider(provider).catch(() => {});
  });
  document
    .querySelector("#resync-button")
    .addEventListener("click", () => client.resync());
  client.start().catch(() => {});
  macroClient.start().catch(() => {});
  marketRibbonClient.start().catch(() => {});
  positionsContextClient.start().catch(() => {});
  macosContextClient.start().catch(() => {});
  botContextClient.start().catch(() => {});
  mediaContextClient.start().catch(() => {});
  healthClient.start().catch(() => {});
  setInterval(() => {
    commandState = client.state();
    render(commandState);
    paintReadiness();
  }, 1000);
  window.addEventListener("online", paintReadiness);
  window.addEventListener("offline", paintReadiness);
  window.addEventListener("beforeunload", () => {
    client.stop();
    macroClient.stop();
    marketRibbonClient.stop();
    positionsContextClient.stop();
    macosContextClient.stop();
    botContextClient.stop();
    mediaContextClient.stop();
    healthClient.stop();
  });
}

if (typeof document !== "undefined") bootstrap();
