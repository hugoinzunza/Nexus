const $ = (id) => document.getElementById(id);
const API = "/m/bot2/api";
const LABELS = {
  teacher_2close: "Profesor · 2 cierres",
  first_close: "Primer cierre",
  structure_break: "Quiebre estructural",
};
let chart;
let candles;
let phaseSeries = [];
let tradeMarkers;
let tradeLines = [];

const fmt = (v, d = 2) => v == null || !Number.isFinite(Number(v)) ? "—"
  : Number(v).toLocaleString("es-CL", {maximumFractionDigits:d, minimumFractionDigits:d});
const unix = (ms) => Math.floor(Number(ms) / 1000);
const date = (ms) => new Date(Number(ms)).toLocaleDateString("es-CL");

function initChart() {
  chart = LightweightCharts.createChart($("chart"), {
    layout:{background:{color:"#11151d"},textColor:"#8f9aaa"},
    grid:{vertLines:{color:"#171d27"},horzLines:{color:"#171d27"}},
    timeScale:{borderColor:"#252c38",timeVisible:true},
    rightPriceScale:{borderColor:"#252c38"},
  });
  candles = chart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor:"#36c98e",downColor:"#ef6673",wickUpColor:"#36c98e",
    wickDownColor:"#ef6673",borderVisible:false,
  });
  new ResizeObserver(() => chart.applyOptions({width:$("chart").clientWidth})).observe($("chart"));
}

function drawPhases(phases) {
  phaseSeries.forEach((s) => { try { chart.removeSeries(s); } catch (_) {} });
  phaseSeries = [];
  const colors = {I:"#36c98e",II:"#e5b653","III?":"#9e8cff",III:"#9e8cff"};
  phases.forEach((phase) => {
    const segments = [...(phase.segments || [])];
    if (phase.phase_iii) segments.push(phase.phase_iii);
    segments.forEach((seg) => {
      const s = chart.addSeries(LightweightCharts.LineSeries, {
        color:colors[seg.label] || "#9e8cff",lineWidth:3,
        lineStyle:seg.candidate ? 2 : 0,priceLineVisible:false,lastValueVisible:false,
      });
      s.setData([{time:unix(seg.start_t),value:Number(seg.start_price)},
                 {time:unix(seg.end_t),value:Number(seg.end_price)}]);
      LightweightCharts.createSeriesMarkers(s,[{
        time:unix(seg.end_t),position:phase.side === "long" ? "belowBar":"aboveBar",
        color:colors[seg.label] || "#9e8cff",shape:"circle",text:seg.label,
      }]);
      phaseSeries.push(s);
    });
  });
}

function drawTrades(trades, visibleCandles, watchlist) {
  const first = visibleCandles.length ? Number(visibleCandles[0].t) : Infinity;
  const last = visibleCandles.length ? Number(visibleCandles.at(-1).t) : -Infinity;
  const visible = trades.filter(t => Number(t.entry_t) >= first && Number(t.entry_t) <= last);
  const markers = [];
  visible.forEach(t => {
    markers.push({time:unix(t.entry_t),position:t.side==="long"?"belowBar":"aboveBar",
      color:t.side==="long"?"#36c98e":"#ef6673",shape:t.side==="long"?"arrowUp":"arrowDown",
      text:`${t.side} · ${fmt(t.net_rr,1)}R`});
    if(t.exit_t) markers.push({time:unix(t.exit_t),position:t.side==="long"?"aboveBar":"belowBar",
      color:t.status==="win"?"#36c98e":"#ef6673",shape:"circle",text:`${t.status} ${fmt(t.result_r,1)}R`});
  });
  const watched = (watchlist || [])[0];
  if (watched && visibleCandles.length) {
    markers.push({time:unix(visibleCandles.at(-1).t),
      position:watched.side==="long"?"belowBar":"aboveBar",
      color:"#e5b653",shape:"circle",text:`VIG · ${watched.side}`});
  }
  if (tradeMarkers?.setMarkers) tradeMarkers.setMarkers(markers);
  else tradeMarkers = LightweightCharts.createSeriesMarkers(candles, markers);
  tradeLines.forEach(line => { try { candles.removePriceLine(line); } catch (_) {} });
  tradeLines = [];
  const latest = watched || visible.at(-1);
  if (!latest) return;
  const levels = watched
    ? [["trigger","#e5b653","VIG gatillo"],["stop","#ef6673","VIG SL"],["target","#36c98e","VIG TP"]]
    : [["entry","#42c7d9","entrada"],["stop","#ef6673","SL"],["target","#36c98e","TP"]];
  levels.forEach(([key,color,title])=>{
    if (latest[key] == null) return;
    tradeLines.push(candles.createPriceLine({price:Number(latest[key]),color,lineWidth:1,lineStyle:2,title,axisLabelVisible:true}));
  });
}

function metric(label, value) {
  return `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`;
}

function render(data) {
  const s=data.summary;
  $("metrics").innerHTML=[
    metric("fases I-II",s.cycles),metric("trades",s.trades),
    metric("win rate",s.win_rate==null?"—":fmt(s.win_rate*100,1)+"%"),
    metric("avgR",fmt(s.avg_r,2)),metric("total R",fmt(s.total_r,2)),
    metric("drawdown",fmt(s.max_drawdown_r,2)+"R"),
  ].join("");
  candles.setData(data.candles.map(v=>({time:unix(v.t),open:+v.o,high:+v.h,low:+v.l,close:+v.c})));
  drawPhases(data.phases || []);
  drawTrades(data.trades || [], data.candles || [], data.watchlist || []);
  chart.timeScale().fitContent();
  $("chart-sub").textContent=`${data.symbol} · ${data.tf} · ${LABELS[data.variant]} · ${data.source}`;
  $("trades").innerHTML=(data.trades || []).slice().reverse().map(t=>`<tr>
    <td>${date(t.entry_t)}</td><td class="${t.side}">${t.side}</td>
    <td class="${t.status}">${t.status}</td><td>${fmt(t.net_rr,2)}</td>
    <td>${fmt(t.result_r,2)}</td><td>${t.context_label.replaceAll("_"," ")}</td></tr>`).join("")
    || `<tr><td colspan="6">Ninguna operación supera todavía todas las reglas.</td></tr>`;
  const watch = data.watchlist || [];
  $("watch-count").textContent = `${watch.length} activa${watch.length === 1 ? "" : "s"}`;
  $("watchlist").innerHTML = watch.map(w=>`<tr class="${w.eligible_next_open ? "ready" : ""}">
    <td><span class="watch-state">${w.status}</span></td>
    <td class="${w.side}">${w.side}</td><td>${fmt(w.trigger,2)}</td>
    <td>${w.distance_pct==null?"—":fmt(w.distance_pct,2)+"%"}</td>
    <td>${fmt(w.stop,2)}</td><td>${fmt(w.target,2)}</td>
    <td>${fmt(w.net_rr_estimate,2)}</td>
    <td>${w.context_label.replaceAll("_"," ")}</td></tr>`).join("")
    || `<tr><td colspan="8">No hay una fase vigente dentro de la ventana de vigilancia.</td></tr>`;
  $("rejections").innerHTML=Object.entries(data.rejected || {}).sort((a,b)=>b[1]-a[1])
    .map(([k,v])=>`<div class="reject"><span>${k}</span><strong>${v}</strong></div>`).join("");
  $("entry-rule").textContent = data.variant === "teacher_2close" ? "dos cierres + apertura siguiente"
    : data.variant === "first_close" ? "primer cierre válido + apertura siguiente"
    : "quiebre del pivote + apertura siguiente";
}

async function load() {
  $("chart-sub").textContent="Calculando histórico causal…";
  const q=new URLSearchParams({symbol:$("symbol").value,tf:$("tf").value,variant:$("variant").value});
  const response=await fetch(`${API}/analysis?${q}`,{cache:"no-store"});
  const data=await response.json();
  if(!response.ok || data.error) throw new Error(data.error || "No fue posible calcular");
  render(data);
}

async function boot() {
  initChart();
  const state=await fetch(`${API}/state`).then(r=>r.json());
  $("symbol").innerHTML=state.pairs.map(x=>`<option>${x}</option>`).join("");
  $("tf").innerHTML=state.timeframes.map(x=>`<option value="${x}">${x.toUpperCase()}</option>`).join("");
  $("variant").innerHTML=state.variants.map(x=>`<option value="${x}">${LABELS[x]}</option>`).join("");
  [$("symbol"),$("tf"),$("variant")].forEach(el=>el.addEventListener("change",()=>load().catch(showError)));
  await load();
}
function showError(error){$("chart-sub").textContent=error.message;}
boot().catch(showError);
