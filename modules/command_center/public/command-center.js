import { TradingViewWidgetAdapter } from "./tradingview-spike.js";

export const CONTRACT_VERSION = 1;
export const CONTRACT_FINGERPRINT =
  "b0a8a7efa623a1aae4b681c3cfc42790d36a6a14fbc689688026c523f2e49b46";

const SNAPSHOT_URL = "/m/command-center/api/snapshot";
const MACRO_URL = "/m/trading/api/dashboard?translate=0";
const MARKET_RIBBON_URL = "/m/command-center/api/market-ribbon";
const AI_CONTEXT_URL = "/m/command-center/api/ai-context";
const POSITIONS_CONTEXT_URL = "/m/command-center/api/positions-context";
const BOT_CONTEXT_URL = "/m/command-center/api/bot-context";
const MEDIA_CONTEXT_URL = "/m/command-center/api/media-context";
const MEDIA_COMMAND_URL = "/m/command-center/api/media-command";
const HEALTH_URL = "/health";
const WS_PATH = "/m/command-center/ws";
const RECONNECT_DELAYS = [1000, 2000, 5000, 10000, 15000];
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
    this.generatedAt = null;
    this.error = null;
    this.refreshTimer = null;
    this.countdownTimer = null;
  }

  state() {
    return {
      status: this.status,
      event: this.event,
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
      this.event = selectNextHighImpact(
        dashboard?.calendar,
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

export function deriveImmediateAttention({
  readiness = null,
  macro = null,
  positions = null,
  bot = null,
  now = Date.now(),
} = {}) {
  const available = [readiness, macro, positions, bot].filter(Boolean).length;
  if (available < 4) {
    return {
      state: "unknown",
      summary: "Reuniendo contexto operacional.",
      detail: `${available}/4 fuentes`,
      count: 0,
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

  const unavailableAccounts = positions.accounts.filter((account) =>
    ["stale", "failed", "unavailable"].includes(account.state),
  );
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
    return {
      state: "normal",
      summary: "Sin intervención inmediata.",
      detail: "4 fuentes verificadas",
      count: 0,
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
    count: alerts.length,
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
  }

  async start() {
    await this.refresh({ detectActive: true });
    this.refreshTimer = setInterval(() => {
      if (document.visibilityState === "hidden") return;
      if (this.autoRefreshBusy) return;
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
    this.refreshTimer = null;
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
    } catch (error) {
      this.status = this.health ? "degraded" : "failed";
      this.error = error?.message || "health no disponible";
    }
    this.onChange(this.state());
  }
}

const READINESS_LABELS = {
  ready: "Ready",
  degraded: "Degraded",
  failed: "Failed",
  unknown: "Unknown",
};

const REQUIRED_READINESS_IDS = new Set([
  "gateway",
  "event-bus",
  "snapshot",
  "internet",
  "trading",
]);

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
  const gateway = {
    ready: "ready",
    degraded: "degraded",
    stale: "degraded",
    expired: "failed",
    disconnected: "failed",
    loading: "unknown",
  }[commandState?.connection] || "unknown";

  let tradingState = normalizeServiceState(trading?.status);
  if (trading?.upstream_ok === false) tradingState = "degraded";
  if (trading?.upstream_ok === true && tradingState === "ready") {
    const age = now - Number(trading?.last_update_ms || 0);
    if (!Number.isFinite(age) || age > 120_000) tradingState = "failed";
    else if (age > 30_000) tradingState = "degraded";
  }

  const healthAvailable = healthState?.status === "ready";
  const services = [
    { id: "gateway", name: "Gateway", state: gateway },
    {
      id: "event-bus",
      name: "EventBus",
      state: normalizeServiceState(commandCenter?.event_bus?.status),
    },
    { id: "snapshot", name: "Snapshot", state: snapshot },
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
    },
    { id: "trading", name: "Trading", state: tradingState },
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
        (service) =>
          service.state === "degraded" || service.state === "unknown",
      )
      ? "degraded"
      : "ready";
  return { overall, services };
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
      this.lastError = null;
      this.#emit();
    } catch (error) {
      this.connection = Object.keys(this.readModel).length
        ? "degraded"
        : "disconnected";
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
  const overall = document.querySelector("#readiness-overall");
  overall.dataset.state = readiness.overall;
  overall.textContent = READINESS_LABELS[readiness.overall];
  const answers = {
    ready: "El núcleo necesario para analizar está disponible.",
    degraded: "Puede trabajar, pero hay servicios esenciales degradados.",
    failed: "La plataforma no está preparada para trabajar.",
    unknown: "Aún no hay evidencia suficiente para responder.",
  };
  document.querySelector("#readiness-answer").textContent =
    answers[readiness.overall];
  const list = document.querySelector("#readiness-list");
  list.replaceChildren(
    ...readiness.services.map((service) => {
      const item = document.createElement("li");
      item.className = "readiness-item";
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

function renderImmediateAttention(attention) {
  const badge = document.querySelector("#attention-state");
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
  document.querySelector("#attention-detail").textContent = attention.detail;
  document.querySelector("#attention-updated").textContent =
    attention.evaluatedAtMs
      ? `Evaluado ${new Date(attention.evaluatedAtMs).toLocaleTimeString(
          "es-CL",
          { hour: "2-digit", minute: "2-digit" },
        )}`
      : "Sin lectura";
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
    ready: "Ready",
    degraded: "Degradada",
    unavailable: "No disponible",
    revoked: "Sin permiso",
    closed: "Cerrada",
    unknown: "Unknown",
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
        : stateLabels[context.lifecycle] || "Unknown";
  const selectedLabel = providerLabels[context.selectedProvider] || "Música";
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
  const artworkPlaceholder = document.querySelector(
    "#music-artwork-placeholder",
  );
  if (context.artworkUrl) {
    artworkImage.src = context.artworkUrl;
    artworkImage.hidden = false;
    artworkPlaceholder.hidden = true;
  } else {
    artworkImage.removeAttribute("src");
    artworkImage.hidden = true;
    artworkPlaceholder.hidden = false;
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
let selectedMarketAssetId = "btcusdt";
let lastMarketRibbonState = null;
let activeChartAdapter = null;
let chartQueue = Promise.resolve();

function marketChangeDirection(change) {
  if (!Number.isFinite(change) || change === 0) return "flat";
  return change > 0 ? "up" : "down";
}

function formatMarketChange(change) {
  if (!Number.isFinite(change)) return "--";
  return `${change > 0 ? "+" : ""}${change.toFixed(2)}%`;
}

function renderMarketRibbon(state) {
  lastMarketRibbonState = state;
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
  document.querySelector("#market-symbol-title").textContent = asset.symbol;
  document.querySelector("#market-interval-title").textContent = "· 1H";
  const fullAnalysis = document.querySelector("#full-analysis-link");
  fullAnalysis.href = tradingViewAnalysisUrl(asset);
}

async function remountChart(asset) {
  const target = document.querySelector("#chart-target");
  setChartLabels(asset);
  if (new URLSearchParams(location.search).get("chart") === "0") {
    target.innerHTML =
      '<div class="chart-placeholder"><span>Proveedor omitido</span>' +
      "<small>Validación sin red externa</small></div>";
    document.querySelector("#chart-health").textContent = "Proveedor omitido";
    document.querySelector("#chart-latency").textContent =
      "Validación sin red externa";
    return;
  }
  if (activeChartAdapter) await activeChartAdapter.destroy();
  target.innerHTML =
    '<div class="chart-placeholder"><span>TradingView</span>' +
    `<small>Montando ${asset.symbol}</small></div>`;
  const adapter = new TradingViewWidgetAdapter();
  activeChartAdapter = adapter;
  window.__nexuxCommandCenterChart = adapter;
  try {
    await adapter.mount(target, {
      targetRef: "command-center:market",
      symbol: asset.chartSymbol,
      interval: "1h",
      themeRef: "dark",
    });
    const stats = adapter.stats();
    document.querySelector("#chart-health").textContent =
      "Proveedor disponible";
    document.querySelector("#chart-latency").textContent =
      `Montaje ${stats.lastMountLatencyMs} ms`;
  } catch (error) {
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
  document.querySelector("#music-artwork-image").addEventListener("error", (event) => {
    event.currentTarget.hidden = true;
    document.querySelector("#music-artwork-placeholder").hidden = false;
  });
  remountChart({
    id: "btcusdt",
    symbol: "BTCUSDT.P",
    chartSymbol: "BTCUSDT",
    tvSymbol: "BINANCE:BTCUSDT.P",
  });

  const parameters = new URLSearchParams(location.search);
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
    const botState = fixtureBotContext();
    const readinessState = deriveOperationalReadiness({
      commandState: state,
      healthState: fixtureHealthState(fixture),
      online: fixture !== "disconnected",
    });
    render(state);
    renderMacro(macroState);
    renderMarketRibbon(fixtureMarketRibbonState());
    renderPositionsContext(positionsState);
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
  };
  const paintAttention = () => {
    renderImmediateAttention(deriveImmediateAttention(attentionInputs));
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
      renderMacro(state);
      paintAttention();
    },
  });
  const marketRibbonClient = new MarketRibbonClient({
    onChange: renderMarketRibbon,
  });
  const positionsContextClient = new PositionsContextClient({
    onChange: (state) => {
      attentionInputs.positions = state;
      renderPositionsContext(state);
      paintAttention();
    },
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
    botContextClient.stop();
    mediaContextClient.stop();
    healthClient.stop();
  });
}

if (typeof document !== "undefined") bootstrap();
