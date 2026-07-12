const state = {
  data: null,
  activeDate: null,
  activeStock: null,
  manualStock: null,
  trendRising: true,
  capitalMin: null,
  capitalMax: null,
  signalsCache: {},
  seriesCache: {},
  chartView: null,
  renderToken: 0,
};

const els = {
  generatedAt: document.getElementById("generatedAt"),
  dateSelect: document.getElementById("dateSelect"),
  stockSelect: document.getElementById("stockSelect"),
  stockQuery: document.getElementById("stockQuery"),
  stockQueryButton: document.getElementById("stockQueryButton"),
  trendFilter: document.getElementById("trendFilter"),
  capitalMin: document.getElementById("capitalMin"),
  capitalMax: document.getElementById("capitalMax"),
  signalCount: document.getElementById("signalCount"),
  currentStock: document.getElementById("currentStock"),
  distance: document.getElementById("distance"),
  currentCapital: document.getElementById("currentCapital"),
  signalList: document.getElementById("signalList"),
  chart: document.getElementById("chart"),
  chartPrevious: document.getElementById("chartPrevious"),
  chartNext: document.getElementById("chartNext"),
  chartZoomOut: document.getElementById("chartZoomOut"),
  chartZoomIn: document.getElementById("chartZoomIn"),
  chartLatest: document.getElementById("chartLatest"),
};

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function fmtVolume(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("zh-TW").format(Math.round(number)) : "-";
}

function hasNumericValue(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function isMa20Rising(row) {
  if (typeof row.ma20_rising === "boolean") return row.ma20_rising;
  return Number.isFinite(Number(row.ma20)) && Number.isFinite(Number(row.prev_ma20)) && Number(row.ma20) > Number(row.prev_ma20);
}

function filterSignals(signals) {
  return signals.filter((item) => {
    if (state.trendRising && !isMa20Rising(item)) return false;
    if (state.capitalMin === null && state.capitalMax === null) return true;
    if (!hasNumericValue(item.capital_billion)) return false;
    const capital = Number(item.capital_billion);
    if (state.capitalMin !== null && capital < state.capitalMin) return false;
    if (state.capitalMax !== null && capital > state.capitalMax) return false;
    return true;
  });
}

function updateCapitalFilters() {
  const minValue = els.capitalMin.value === "" ? null : Number(els.capitalMin.value);
  const maxValue = els.capitalMax.value === "" ? null : Number(els.capitalMax.value);
  els.capitalMax.setCustomValidity("");
  if (minValue !== null && maxValue !== null && minValue > maxValue) {
    els.capitalMax.setCustomValidity("最高資本額不可小於最低資本額");
    els.capitalMax.reportValidity();
    return;
  }
  state.capitalMin = minValue;
  state.capitalMax = maxValue;
  state.chartView = null;
  render();
}

function stockLabel(stockId) {
  const meta = state.data.meta[stockId] || {};
  return meta.stock_name ? `${stockId} ${meta.stock_name}` : stockId;
}

async function loadSignals(date) {
  if (!date) return [];
  if (state.signalsCache[date]) return state.signalsCache[date];
  const file = state.data.signal_files?.[date];
  if (!file) return [];
  const response = await fetch(`../data/processed/${file}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const rows = await response.json();
  state.signalsCache[date] = rows;
  return rows;
}

async function loadSeries(stockId) {
  if (!stockId) return [];
  if (state.seriesCache[stockId]) return state.seriesCache[stockId];
  const file = state.data.series_files?.[stockId];
  if (!file) return [];
  const response = await fetch(`../data/processed/${file}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const rows = await response.json();
  state.seriesCache[stockId] = rows;
  return rows;
}

function submitStockQuery() {
  const stockId = els.stockQuery.value.trim().toUpperCase();
  if (!stockId || !state.data.series_files?.[stockId]) {
    els.stockQuery.setCustomValidity(stockId ? `找不到股票代號 ${stockId} 的圖表資料` : "請輸入股票代號");
    els.stockQuery.reportValidity();
    return;
  }

  els.stockQuery.setCustomValidity("");
  els.stockQuery.value = stockId;
  state.manualStock = stockId;
  state.activeStock = stockId;
  state.chartView = null;
  render();
}

function updateChartView(action) {
  const fullSeries = state.seriesCache[state.activeStock];
  const view = state.chartView;
  if (!fullSeries?.length || !view) return;

  const length = fullSeries.length;
  const count = view.end - view.start;
  const minCount = Math.min(20, length);
  let nextCount = count;
  let nextStart = view.start;

  if (action === "zoom-in") {
    nextCount = Math.max(minCount, Math.round(count * 0.72));
  } else if (action === "zoom-out") {
    nextCount = Math.min(length, Math.ceil(count * 1.4));
  } else if (action === "previous") {
    nextStart -= Math.max(1, Math.round(count * 0.5));
  } else if (action === "next") {
    nextStart += Math.max(1, Math.round(count * 0.5));
  } else if (action === "latest") {
    nextStart = length - count;
  }

  if (action === "zoom-in" || action === "zoom-out") {
    const activeIndex = fullSeries.findIndex((row) => row.date === state.activeDate);
    const activeIsVisible = activeIndex >= view.start && activeIndex < view.end;
    const anchor = activeIsVisible ? activeIndex : (view.start + view.end - 1) / 2;
    const ratio = activeIsVisible ? (activeIndex - view.start) / Math.max(1, count - 1) : 0.5;
    nextStart = Math.round(anchor - ratio * Math.max(1, nextCount - 1));
  }

  nextStart = Math.max(0, Math.min(length - nextCount, nextStart));
  state.chartView = { ...view, start: nextStart, end: nextStart + nextCount };
  renderChart(state.activeStock, fullSeries);
}

function setupControls() {
  const dates = state.data.dates || [];
  els.dateSelect.innerHTML = dates.map((date) => `<option value="${date}">${date}</option>`).join("");
  state.activeDate = dates[dates.length - 1] || null;
  els.dateSelect.value = state.activeDate;

  els.dateSelect.addEventListener("change", () => {
    state.activeDate = els.dateSelect.value;
    state.activeStock = state.manualStock;
    state.chartView = null;
    render();
  });

  els.stockSelect.addEventListener("change", () => {
    state.activeStock = els.stockSelect.value;
    state.manualStock = null;
    els.stockQuery.value = "";
    state.chartView = null;
    render();
  });

  els.stockQuery.addEventListener("input", () => els.stockQuery.setCustomValidity(""));
  els.stockQuery.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submitStockQuery();
    }
  });
  els.stockQueryButton.addEventListener("click", submitStockQuery);
  els.trendFilter.addEventListener("change", () => {
    state.trendRising = els.trendFilter.checked;
    state.chartView = null;
    render();
  });
  els.capitalMin.addEventListener("input", updateCapitalFilters);
  els.capitalMax.addEventListener("input", updateCapitalFilters);

  els.chartPrevious.addEventListener("click", () => updateChartView("previous"));
  els.chartNext.addEventListener("click", () => updateChartView("next"));
  els.chartZoomOut.addEventListener("click", () => updateChartView("zoom-out"));
  els.chartZoomIn.addEventListener("click", () => updateChartView("zoom-in"));
  els.chartLatest.addEventListener("click", () => updateChartView("latest"));
}

function renderSignalList(signals) {
  els.signalCount.textContent = signals.length;
  const signalIds = new Set(signals.map((item) => String(item.stock_id)));
  const manualOption = state.manualStock && !signalIds.has(state.manualStock)
    ? `<option value="${state.manualStock}">${stockLabel(state.manualStock)}（查詢）</option>`
    : "";
  els.stockSelect.innerHTML = manualOption + signals
    .map((item) => `<option value="${item.stock_id}">${stockLabel(String(item.stock_id))}</option>`)
    .join("");

  if (!state.activeStock && signals[0]) state.activeStock = String(signals[0].stock_id);
  if (state.activeStock) els.stockSelect.value = state.activeStock;

  els.signalList.innerHTML = signals.map((item) => {
    const stockId = String(item.stock_id);
    const active = stockId === state.activeStock ? " is-active" : "";
    const capital = Number(item.capital_billion);
    const capitalText = hasNumericValue(item.capital_billion) ? ` / 股本 ${fmt(capital, 1)} 億` : "";
    return `<button class="signal-button${active}" data-stock="${stockId}">
      ${stockLabel(stockId)}
      <span>收盤 ${fmt(item.close)} / MA20 ${fmt(item.ma20)} / 距離 ${fmt(item.ma20_distance_pct)}%${capitalText}</span>
    </button>`;
  }).join("");

  els.signalList.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeStock = button.dataset.stock;
      state.manualStock = null;
      els.stockQuery.value = "";
      state.chartView = null;
      render();
    });
  });
}

function scaleLinear(domainMin, domainMax, rangeMin, rangeMax) {
  const span = domainMax - domainMin || 1;
  return (value) => rangeMin + ((value - domainMin) / span) * (rangeMax - rangeMin);
}

function pathFrom(points) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"}${point[0].toFixed(1)},${point[1].toFixed(1)}`).join(" ");
}

function signalArrowPath(cx, tipY) {
  return [
    `M ${cx.toFixed(1)} ${tipY.toFixed(1)}`,
    `L ${(cx - 9).toFixed(1)} ${(tipY + 12).toFixed(1)}`,
    `L ${(cx - 4).toFixed(1)} ${(tipY + 12).toFixed(1)}`,
    `L ${(cx - 4).toFixed(1)} ${(tipY + 24).toFixed(1)}`,
    `L ${(cx + 4).toFixed(1)} ${(tipY + 24).toFixed(1)}`,
    `L ${(cx + 4).toFixed(1)} ${(tipY + 12).toFixed(1)}`,
    `L ${(cx + 9).toFixed(1)} ${(tipY + 12).toFixed(1)}`,
    "Z",
  ].join(" ");
}

function renderChart(stockId, fullSeries) {
  const svg = els.chart;
  const width = svg.clientWidth || 900;
  const height = svg.clientHeight || 720;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = "";

  if (!fullSeries.length) {
    svg.innerHTML = `<text x="24" y="40" fill="currentColor">這檔股票沒有圖表資料</text>`;
    return;
  }

  const viewKey = `${stockId}:${state.activeDate}`;
  if (!state.chartView || state.chartView.key !== viewKey) {
    const signalIndex = Math.max(0, fullSeries.findIndex((row) => row.date === state.activeDate));
    const defaultCount = Math.min(108, fullSeries.length);
    let start = Math.max(0, signalIndex - 80);
    let end = Math.min(fullSeries.length, start + defaultCount);
    start = Math.max(0, end - defaultCount);
    state.chartView = { key: viewKey, start, end };
  }
  const start = Math.max(0, Math.min(fullSeries.length - 1, state.chartView.start));
  const end = Math.max(start + 1, Math.min(fullSeries.length, state.chartView.end));
  state.chartView = { key: viewKey, start, end };
  const series = fullSeries.slice(start, end);

  els.chartPrevious.disabled = start === 0;
  els.chartNext.disabled = end === fullSeries.length;
  els.chartZoomIn.disabled = series.length <= Math.min(20, fullSeries.length);
  els.chartZoomOut.disabled = series.length === fullSeries.length;
  els.chartLatest.disabled = end === fullSeries.length;

  const margin = { top: 18, right: 64, bottom: 34, left: 58 };
  const volumeHeight = Math.round(height * 0.24);
  const priceBottom = height - margin.bottom - volumeHeight - 22;
  const volumeTop = priceBottom + 24;
  const plotWidth = width - margin.left - margin.right;
  const candleWidth = Math.max(3, Math.min(12, plotWidth / series.length * 0.58));

  const lows = series.map((d) => Number(d.low));
  const highs = series.map((d) => Number(d.high));
  const maValues = series.map((d) => Number(d.ma20)).filter(Number.isFinite);
  const minPrice = Math.min(...lows, ...maValues) * 0.94;
  const maxPrice = Math.max(...highs, ...maValues) * 1.02;
  const maxVolume = Math.max(...series.map((d) => Number(d.volume) || 0), 1);

  const x = (index) => margin.left + (series.length === 1 ? plotWidth / 2 : index * (plotWidth / (series.length - 1)));
  const y = scaleLinear(maxPrice, minPrice, margin.top, priceBottom);
  const vy = scaleLinear(0, maxVolume, height - margin.bottom, volumeTop);

  const ns = "http://www.w3.org/2000/svg";
  const add = (name, attrs, parent = svg) => {
    const el = document.createElementNS(ns, name);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
    parent.appendChild(el);
    return el;
  };

  const grid = add("g", { class: "grid" });
  for (let i = 0; i <= 4; i++) {
    const yy = margin.top + i * ((priceBottom - margin.top) / 4);
    add("line", { x1: margin.left, x2: width - margin.right, y1: yy, y2: yy }, grid);
    const price = maxPrice - i * ((maxPrice - minPrice) / 4);
    add("text", { x: width - margin.right + 8, y: yy + 4, fill: "currentColor", "font-size": "12" }, grid).textContent = fmt(price);
  }

  series.forEach((d, index) => {
    const cx = x(index);
    const open = Number(d.open);
    const close = Number(d.close);
    const high = Number(d.high);
    const low = Number(d.low);
    const isUp = close >= open;
    const color = isUp ? "var(--up)" : "var(--down)";
    const bodyTop = y(Math.max(open, close));
    const bodyHeight = Math.max(1, Math.abs(y(open) - y(close)));

    add("rect", { class: "volume", x: cx - candleWidth / 2, y: vy(Number(d.volume) || 0), width: candleWidth, height: height - margin.bottom - vy(Number(d.volume) || 0) });
    add("line", { x1: cx, x2: cx, y1: y(high), y2: y(low), stroke: color, "stroke-width": 1.4 });
    add("rect", { x: cx - candleWidth / 2, y: bodyTop, width: candleWidth, height: bodyHeight, fill: color });

    if (d.cross_above_ma20 && (!state.trendRising || isMa20Rising(d))) {
      const tipY = Math.min(priceBottom - 30, y(low) + 10);
      const activeClass = d.date === state.activeDate ? " is-active" : "";
      add("path", { class: `signal-arrow${activeClass}`, d: signalArrowPath(cx, tipY) });
    }
  });

  const maPoints = series.map((d, index) => [x(index), y(Number(d.ma20)), d.ma20]).filter((point) => Number.isFinite(Number(point[2])));
  if (maPoints.length > 1) add("path", { class: "ma-line", d: pathFrom(maPoints) });

  const axis = add("g", { class: "axis" });
  const tickCount = Math.min(7, series.length);
  for (let i = 0; i < tickCount; i++) {
    const index = Math.round(i * (series.length - 1) / Math.max(1, tickCount - 1));
    add("text", { x: x(index), y: height - 10, "text-anchor": "middle" }, axis).textContent = series[index].date.slice(2, 7);
  }
  add("text", { x: margin.left, y: volumeTop - 8, fill: "currentColor", "font-size": "12" }).textContent = "成交量";
  add("text", { x: margin.left, y: margin.top + 4, fill: "currentColor", "font-size": "12" }).textContent = "週K + MA20";

  const crosshair = add("g", { class: "crosshair", visibility: "hidden" });
  const crosshairX = add("line", { class: "crosshair-line", y1: margin.top, y2: height - margin.bottom }, crosshair);
  const crosshairY = add("line", { class: "crosshair-line", x1: margin.left, x2: width - margin.right }, crosshair);
  const focusDot = add("circle", { class: "crosshair-dot", r: 3.5 }, crosshair);
  const tooltip = add("g", { class: "chart-tooltip" }, crosshair);
  const tooltipWidth = 250;
  const tooltipHeight = 112;
  add("rect", { width: tooltipWidth, height: tooltipHeight, rx: 4 }, tooltip);
  const tooltipLines = Array.from({ length: 4 }, (_, index) => add("text", { x: 12, y: 22 + index * 25 }, tooltip));

  const interactionLayer = add("rect", {
    class: "chart-interaction",
    x: margin.left,
    y: margin.top,
    width: plotWidth,
    height: height - margin.bottom - margin.top,
    fill: "transparent",
  });

  interactionLayer.addEventListener("pointermove", (event) => {
    const bounds = svg.getBoundingClientRect();
    const pointerX = (event.clientX - bounds.left) * (width / bounds.width);
    const pointerY = (event.clientY - bounds.top) * (height / bounds.height);
    const step = series.length > 1 ? plotWidth / (series.length - 1) : plotWidth;
    const index = Math.max(0, Math.min(series.length - 1, Math.round((pointerX - margin.left) / step)));
    const row = series[index];
    const cx = x(index);
    const cy = Math.max(margin.top, Math.min(height - margin.bottom, pointerY));
    const closeY = y(Number(row.close));

    crosshair.setAttribute("visibility", "visible");
    crosshairX.setAttribute("x1", cx);
    crosshairX.setAttribute("x2", cx);
    crosshairY.setAttribute("y1", cy);
    crosshairY.setAttribute("y2", cy);
    focusDot.setAttribute("cx", cx);
    focusDot.setAttribute("cy", closeY);

    tooltipLines[0].textContent = row.date;
    tooltipLines[1].textContent = `開 ${fmt(row.open)}　高 ${fmt(row.high)}　低 ${fmt(row.low)}`;
    tooltipLines[2].textContent = `收 ${fmt(row.close)}　MA20 ${fmt(row.ma20)}`;
    tooltipLines[3].textContent = `成交量 ${fmtVolume(row.volume)}`;

    const tooltipX = cx + tooltipWidth + 18 <= width - margin.right ? cx + 14 : cx - tooltipWidth - 14;
    const tooltipY = Math.max(margin.top + 6, Math.min(cy - tooltipHeight / 2, height - margin.bottom - tooltipHeight));
    tooltip.setAttribute("transform", `translate(${tooltipX}, ${tooltipY})`);
  });

  const hideCrosshair = () => {
    crosshair.setAttribute("visibility", "hidden");
  };
  svg.onpointerleave = hideCrosshair;
  svg.onpointerout = (event) => {
    if (!svg.contains(event.relatedTarget)) hideCrosshair();
  };
  document.onpointermove = (event) => {
    if (!svg.contains(event.target)) hideCrosshair();
  };

  svg.onwheel = (event) => {
    event.preventDefault();
    const count = end - start;
    const minCount = Math.min(20, fullSeries.length);
    const nextCount = Math.max(minCount, Math.min(fullSeries.length, Math.round(count * (event.deltaY > 0 ? 1.2 : 0.8))));
    if (nextCount === count) return;

    const bounds = svg.getBoundingClientRect();
    const pointerX = (event.clientX - bounds.left) * (width / bounds.width);
    const ratio = Math.max(0, Math.min(1, (pointerX - margin.left) / plotWidth));
    const anchor = start + ratio * Math.max(1, count - 1);
    let nextStart = Math.round(anchor - ratio * Math.max(1, nextCount - 1));
    nextStart = Math.max(0, Math.min(fullSeries.length - nextCount, nextStart));
    state.chartView = { key: viewKey, start: nextStart, end: nextStart + nextCount };
    renderChart(stockId, fullSeries);
  };
}

async function render() {
  const token = ++state.renderToken;
  els.chart.innerHTML = `<text x="24" y="40" fill="currentColor">載入選股清單...</text>`;
  let signals = [];
  try {
    signals = filterSignals(await loadSignals(state.activeDate));
  } catch (error) {
    if (token === state.renderToken) els.chart.innerHTML = `<text x="24" y="40" fill="currentColor">讀取選股清單失敗：${error.message}</text>`;
    return;
  }
  if (token !== state.renderToken) return;

  if (state.manualStock) {
    state.activeStock = state.manualStock;
  } else if (!signals.some((item) => String(item.stock_id) === state.activeStock)) {
    state.activeStock = signals[0] ? String(signals[0].stock_id) : null;
  }
  renderSignalList(signals);

  const activeSignal = signals.find((item) => String(item.stock_id) === state.activeStock);
  els.currentStock.textContent = state.activeStock ? stockLabel(state.activeStock) : "-";
  els.distance.textContent = activeSignal ? `${fmt(activeSignal.ma20_distance_pct)}%` : "-";
  els.currentCapital.textContent = hasNumericValue(activeSignal?.capital_billion) ? `${fmt(activeSignal.capital_billion, 1)} 億` : "-";

  if (!state.activeStock) {
    els.chart.innerHTML = `<text x="24" y="40" fill="currentColor">沒有符合篩選條件的股票</text>`;
    return;
  }
  els.chart.innerHTML = `<text x="24" y="40" fill="currentColor">載入 ${stockLabel(state.activeStock)} 週K...</text>`;
  try {
    const rows = await loadSeries(state.activeStock);
    if (token === state.renderToken) {
      const activeRow = rows.find((row) => row.date === state.activeDate);
      if (!activeSignal && activeRow) els.distance.textContent = `${fmt(activeRow.ma20_distance_pct)}%`;
      if (!activeSignal && activeRow) {
        els.currentCapital.textContent = hasNumericValue(activeRow.capital_billion) ? `${fmt(activeRow.capital_billion, 1)} 億` : "-";
      }
      renderChart(state.activeStock, rows);
    }
  } catch (error) {
    if (token === state.renderToken) els.chart.innerHTML = `<text x="24" y="40" fill="currentColor">讀取週K失敗：${error.message}</text>`;
  }
}

async function boot() {
  try {
    const response = await fetch("../data/processed/chart_index.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
    els.generatedAt.textContent = `資料產生時間：${state.data.generated_at}`;
    setupControls();
    render();
    window.addEventListener("resize", () => {
      if (state.activeStock && state.seriesCache[state.activeStock]) renderChart(state.activeStock, state.seriesCache[state.activeStock]);
    });
  } catch (error) {
    els.generatedAt.textContent = "找不到 data/processed/chart_index.json，請先執行 Python pipeline。";
    els.chart.innerHTML = `<text x="24" y="40" fill="currentColor">${error.message}</text>`;
  }
}

boot();
