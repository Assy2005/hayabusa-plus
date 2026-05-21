/* SVG chart helpers — no library deps.
 *
 * Two charts live here:
 *   - donut(container, {level: count}) : 重要度ドーナツ
 *   - stackedBars(container, buckets, levels) : 時系列のレベル別積み上げ棒
 *
 * Horizontal bar lists (Top rules / Top hosts) are rendered as plain HTML
 * in app.js — they don't need SVG and using DOM elements keeps them
 * accessible (selectable text, copy, etc.).
 */
(function (global) {
  "use strict";

  // Level → color, kept in sync with style.css.
  const LEVEL_COLOR = {
    critical: "#ff1744",
    high: "#ff5252",
    medium: "#ffb300",
    low: "#42a5f5",
    informational: "#5a6378",
    unknown: "#7e8aa1",
  };
  const LEVEL_ORDER = ["critical", "high", "medium", "low", "informational", "unknown"];

  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function svg(tag, attrs, parent) {
    const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  /**
   * Donut chart. data: object mapping level → count.
   * Center label shows total. Hovering a slice shows level+count.
   */
  function donut(container, data) {
    clear(container);
    const w = container.clientWidth || 240, h = 200;
    const cx = w / 2, cy = h / 2, r = Math.min(w, h) * 0.4, rIn = r * 0.6;
    const root = svg("svg", { viewBox: `0 0 ${w} ${h}` }, container);
    const total = Object.values(data).reduce((a, b) => a + b, 0);
    if (!total) {
      svg("text", {
        x: cx, y: cy, "text-anchor": "middle", "dominant-baseline": "middle",
        fill: "#7d869c", "font-size": "14"
      }, root).textContent = "データなし";
      return;
    }
    let angle = -Math.PI / 2;
    LEVEL_ORDER.forEach(lv => {
      const v = data[lv];
      if (!v) return;
      const sweep = (v / total) * Math.PI * 2;
      const a2 = angle + sweep;
      const large = sweep > Math.PI ? 1 : 0;
      const p1 = [cx + Math.cos(angle) * r, cy + Math.sin(angle) * r];
      const p2 = [cx + Math.cos(a2) * r, cy + Math.sin(a2) * r];
      const p3 = [cx + Math.cos(a2) * rIn, cy + Math.sin(a2) * rIn];
      const p4 = [cx + Math.cos(angle) * rIn, cy + Math.sin(angle) * rIn];
      const d = [
        `M ${p1[0]} ${p1[1]}`,
        `A ${r} ${r} 0 ${large} 1 ${p2[0]} ${p2[1]}`,
        `L ${p3[0]} ${p3[1]}`,
        `A ${rIn} ${rIn} 0 ${large} 0 ${p4[0]} ${p4[1]}`,
        "Z"
      ].join(" ");
      const path = svg("path", { d, fill: LEVEL_COLOR[lv] || "#888",
        "stroke": "#0b0d12", "stroke-width": "1" }, root);
      const title = svg("title", {}, path);
      title.textContent = `${lv}: ${v.toLocaleString()} 件 (${(v / total * 100).toFixed(1)}%)`;
      angle = a2;
    });
    svg("text", {
      x: cx, y: cy - 6, "text-anchor": "middle",
      fill: "#d8def0", "font-size": "22", "font-weight": "700"
    }, root).textContent = total.toLocaleString();
    svg("text", {
      x: cx, y: cy + 14, "text-anchor": "middle",
      fill: "#7d869c", "font-size": "10",
      "letter-spacing": "0.5"
    }, root).textContent = "DETECTIONS";
  }

  /**
   * Stacked bars over time.
   * buckets: {bucketLabel: {level: n}}, sorted ascending by key.
   * Returns the levels actually present so the caller can render a legend.
   */
  function stackedBars(container, buckets) {
    clear(container);
    const keys = Object.keys(buckets).sort();
    const w = container.clientWidth || 600, h = 220;
    const pad = { l: 32, r: 12, t: 12, b: 28 };
    const root = svg("svg", { viewBox: `0 0 ${w} ${h}` }, container);
    if (!keys.length) {
      svg("text", { x: w/2, y: h/2, "text-anchor": "middle", fill: "#7d869c",
        "font-size": "13" }, root).textContent = "時系列データがありません";
      return [];
    }
    const present = new Set();
    let maxTotal = 0;
    keys.forEach(k => {
      const row = buckets[k];
      let t = 0;
      for (const lv in row) { present.add(lv); t += row[lv]; }
      if (t > maxTotal) maxTotal = t;
    });
    const innerW = w - pad.l - pad.r, innerH = h - pad.t - pad.b;
    const bw = Math.max(2, Math.floor(innerW / keys.length) - 1);
    const xStep = innerW / keys.length;

    // Y axis: 4 gridlines, max-rounded.
    const yMax = Math.max(1, Math.ceil(maxTotal * 1.05));
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + innerH * (1 - i / 4);
      const val = Math.round(yMax * i / 4);
      svg("line", { x1: pad.l, x2: w - pad.r, y1: y, y2: y,
        stroke: "#1f2533", "stroke-dasharray": i ? "2 4" : "0" }, root);
      svg("text", { x: pad.l - 4, y: y + 3, "text-anchor": "end",
        fill: "#7d869c", "font-size": "10" }, root).textContent = val;
    }

    const levelsByPriority = LEVEL_ORDER.filter(l => present.has(l));
    keys.forEach((k, i) => {
      const x = pad.l + xStep * i + (xStep - bw) / 2;
      let stacked = 0;
      // Stack bottom→top: informational at bottom, critical on top.
      [...levelsByPriority].reverse().forEach(lv => {
        const v = buckets[k][lv] || 0;
        if (!v) return;
        const hPx = (v / yMax) * innerH;
        const y = pad.t + innerH - stacked - hPx;
        const rect = svg("rect", { x, y, width: bw, height: hPx,
          fill: LEVEL_COLOR[lv] }, root);
        const title = svg("title", {}, rect);
        title.textContent = `${k} — ${lv}: ${v} 件`;
        stacked += hPx;
      });
    });

    // X axis labels — sample evenly to avoid overlap.
    const labelEvery = Math.max(1, Math.ceil(keys.length / 8));
    keys.forEach((k, i) => {
      if (i % labelEvery !== 0) return;
      const x = pad.l + xStep * i + xStep / 2;
      svg("text", { x, y: h - 8, "text-anchor": "middle",
        fill: "#7d869c", "font-size": "10" }, root).textContent = shortLabel(k);
    });

    return levelsByPriority;
  }

  function shortLabel(b) {
    // 'YYYY-MM-DDTHH' → 'MM-DD HH:00', 'YYYY-MM-DD' → 'MM-DD',
    // 'YYYY-MM-DDTHH:MM' → 'HH:MM'
    if (b.length === 16) return b.slice(11);             // minute
    if (b.length === 13) return b.slice(5).replace("T", " ") + ":00";  // hour
    if (b.length === 10) return b.slice(5);              // day
    return b;
  }

  function legend(container, levels) {
    container.innerHTML = "";
    levels.forEach(lv => {
      const span = document.createElement("span");
      span.className = "item";
      span.innerHTML = `<span class="swatch" style="background:${LEVEL_COLOR[lv]}"></span>${lv}`;
      container.appendChild(span);
    });
  }

  global.HayCharts = { donut, stackedBars, legend, LEVEL_COLOR, LEVEL_ORDER };
})(window);
