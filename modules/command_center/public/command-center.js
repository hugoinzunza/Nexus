import { TradingViewWidgetAdapter } from "./tradingview-spike.js";

export const CONTRACT_VERSION = 1;
export const CONTRACT_FINGERPRINT =
  "b0a8a7efa623a1aae4b681c3cfc42790d36a6a14fbc689688026c523f2e49b46";

const SNAPSHOT_URL = "/m/command-center/api/snapshot";
const MACRO_URL = "/m/trading/api/dashboard?translate=0";
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
  const severity = worstSeverity(readModel);
  let operational = state.connection;
  if (state.connection === "ready" && freshness === "stale") operational = "stale";
  if (freshness === "expired") operational = "expired";

  const connection = document.querySelector("#connection-state");
  connection.dataset.state = operational;
  connection.querySelector("span").textContent = label(operational);

  const band = document.querySelector("#attention-band");
  const effectiveSeverity =
    operational === "expired" || operational === "disconnected"
      ? "critical"
      : operational === "degraded" || operational === "stale"
        ? "warning"
        : severity;
  band.dataset.severity = effectiveSeverity;

  const messages = {
    ready: ["Sin alertas críticas", "Fuentes contractuales conectadas y vigentes."],
    loading: ["Sincronizando estado", "Reconstruyendo la sesión desde el snapshot."],
    degraded: ["Operación degradada", state.lastError || "El snapshot sigue disponible sin conexión incremental."],
    stale: ["Datos desactualizados", "Una o más fuentes superaron su ventana de frescura."],
    expired: ["Contexto expirado", "No use esta pantalla para tomar decisiones hasta resincronizar."],
    disconnected: ["NexUX desconectado", "No hay snapshot utilizable ni conexión incremental."],
  };
  const message = messages[operational] || messages.degraded;
  document.querySelector("#attention-title").textContent = message[0];
  document.querySelector("#attention-detail").textContent = message[1];

  const modules =
    readModel["system.modules"]?.payload?.data?.modules || [];
  document.querySelector("#primary-value").textContent =
    effectiveSeverity === "normal" ? "OK" : "—";
  document.querySelector("#primary-label").textContent =
    effectiveSeverity === "normal"
      ? "plataforma disponible"
      : "requiere atención";
  document.querySelector("#system-word").textContent =
    effectiveSeverity === "normal" ? "Estable" : label(operational);
  document.querySelector("#snapshot-state").textContent = state.snapshotAt
    ? "Disponible"
    : "Pendiente";
  document.querySelector("#gateway-state").textContent =
    state.connection === "ready" ? "Conectado" : label(state.connection);
  document.querySelector("#freshness-state").textContent = label(freshness);
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

function updateViewport() {
  document.querySelector("#viewport-size").textContent =
    `${window.innerWidth} × ${window.innerHeight}`;
  document.querySelector("#viewport-density").textContent =
    `DPR ${window.devicePixelRatio.toFixed(2)}`;
}

async function mountChart() {
  const target = document.querySelector("#chart-target");
  if (new URLSearchParams(location.search).get("chart") === "0") {
    target.querySelector(".chart-placeholder").innerHTML =
      "<span>Proveedor omitido</span><small>Validación sin red externa</small>";
    document.querySelector("#chart-health").textContent = "Proveedor omitido";
    document.querySelector("#chart-latency").textContent = "Validación sin red externa";
    return;
  }
  const adapter = new TradingViewWidgetAdapter();
  window.__nexuxCommandCenterChart = adapter;
  try {
    await adapter.mount(target, {
      targetRef: "command-center:market",
      symbol: "BTCUSDT",
      interval: "1h",
      themeRef: "dark",
    });
    const stats = adapter.stats();
    document.querySelector("#chart-health").textContent = "Proveedor disponible";
    document.querySelector("#chart-latency").textContent =
      `Montaje ${stats.lastMountLatencyMs} ms`;
  } catch (error) {
    document.querySelector("#chart-health").textContent = "Proveedor degradado";
    document.querySelector("#chart-latency").textContent =
      error?.code || "Montaje fallido";
  }
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
  updateViewport();
  startClock();
  window.addEventListener("resize", updateViewport);
  mountChart();

  const fixture = new URLSearchParams(location.search).get("fixture");
  if (FIXTURE_STATES.has(fixture)) {
    const origin = document.querySelector("#data-origin");
    origin.textContent = "Fixture contractual";
    origin.classList.add("fixture");
    const state = fixtureState(fixture);
    render(state);
    renderMacro(fixtureMacroState());
    document.querySelector("#resync-button").disabled = true;
    return;
  }

  const client = new CommandCenterClient({ onChange: render });
  const macroClient = new MacroContextClient({ onChange: renderMacro });
  window.__nexuxCommandCenter = client;
  window.__nexuxCommandCenterMacro = macroClient;
  document
    .querySelector("#resync-button")
    .addEventListener("click", () => client.resync());
  client.start().catch(() => {});
  macroClient.start().catch(() => {});
  setInterval(() => render(client.state()), 1000);
  window.addEventListener("beforeunload", () => {
    client.stop();
    macroClient.stop();
  });
}

if (typeof document !== "undefined") bootstrap();
