/* extra.js — log search + Elasticsearch screens.
 *
 * app.js owns navigation and the scan workflow. This file only listens for
 * the `hayfx:tab` event it dispatches and lazily initialises the two newer
 * screens, so neither file needs to know the other's internals.
 */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const esc = (v) => String(v ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  const shortTime = (ts) => {
    if (!ts) return "—";
    // "2019-02-16 19:02:21.934 +09:00" -> "2019-02-16 19:02:21"
    return String(ts).replace(/\.\d+\s*/, " ").replace(/\s+[+-]\d{2}:\d{2}$/, "").trim();
  };

  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await r.json(); } catch { /* empty body is fine */ }
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }

  async function getJSON(url) {
    const r = await fetch(url);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }

  const setBusy = (btn, busy, label) => {
    if (!btn) return;
    if (busy) {
      btn.dataset.old = btn.textContent;
      btn.textContent = label || "処理中…";
      btn.disabled = true;
    } else {
      btn.textContent = btn.dataset.old || btn.textContent;
      btn.disabled = false;
    }
  };

  /* ======================================================================
   * 1. Free log search
   * ==================================================================== */

  const logs = {
    ready: false,
    events: [],
    source: "",
    meta: null,
  };

  function logRow(ev, i) {
    const title = ev.Title || (ev.raw && ev.raw.EventTitle) || "";
    const detailKeys = Object.keys(ev.Details || {});
    const fields = detailKeys.length
      ? detailKeys.map((k) => {
          const v = ev.Details[k];
          const text = (v !== null && typeof v === "object")
            ? JSON.stringify(v) : String(v);
          return `<div class="kv"><span class="kv-k">${esc(k)}</span>`
            + `<span class="kv-v">${esc(text)}</span></div>`;
        }).join("")
      : `<div class="kv"><span class="kv-k">(no extra fields)</span><span class="kv-v"></span></div>`;

    return `<article class="logrow" data-i="${i}">
      <header class="logrow-head" role="button" tabindex="0">
        <span class="log-time">${esc(shortTime(ev.Timestamp))}</span>
        <span class="log-eid">${esc(ev.EventID ?? "—")}</span>
        <span class="log-chan">${esc(ev.Channel || "")}</span>
        <span class="log-host">${esc(ev.Computer || "")}</span>
        <span class="log-title">${esc(title)}</span>
        <span class="log-caret">＋</span>
      </header>
      <div class="logrow-body" hidden>
        <div class="kv-grid">${fields}</div>
        <div class="logrow-raw">
          <button class="ghost-btn small js-raw" data-i="${i}">生 JSON を表示</button>
          <pre class="raw-json" hidden>${esc(JSON.stringify(ev.raw, null, 2))}</pre>
        </div>
      </div>
    </article>`;
  }

  function renderLogResult() {
    const box = $("#log-result");
    if (!box) return;
    if (!logs.events.length) {
      box.innerHTML = `<div class="empty-state">
        <div class="empty-mark">∅</div>
        <p>条件に合うイベントはありませんでした。<br/>
        検索語を短くするか、Event ID の絞り込みを外してみてください。</p>
      </div>`;
      return;
    }
    box.innerHTML = `<div class="logrows">${logs.events.map(logRow).join("")}</div>`;
  }

  function logSourcesInto(select, sources) {
    select.innerHTML = "";
    if (!sources.length) {
      select.innerHTML = `<option value="">(EVTX がありません)</option>`;
      return;
    }
    const grouped = new Map();
    for (const s of sources) {
      const dir = s.dir || "uploads";
      if (!grouped.has(dir)) grouped.set(dir, []);
      grouped.get(dir).push(s);
    }
    for (const [dir, items] of grouped) {
      const og = document.createElement("optgroup");
      og.label = dir;
      for (const s of items) {
        const opt = document.createElement("option");
        opt.value = s.rel;
        opt.textContent = `${s.name} · ${s.size_h}`;
        og.appendChild(opt);
      }
      select.appendChild(og);
    }
    // Keep the previous selection when the file still exists.
    if (logs.source && sources.some((s) => s.rel === logs.source)) {
      select.value = logs.source;
    } else {
      logs.source = select.value;
    }
  }

  async function loadLogSources() {
    const select = $("#log-source");
    if (!select) return;
    try {
      const data = await getJSON("/api/logs/sources");
      logSourcesInto(select, data.sources || []);
      const hint = $("#log-source-hint");
      if (hint) {
        hint.textContent = `${(data.sources || []).length} ファイル · ${data.engine.split(/[\\/]/).pop()}`;
      }
    } catch (e) {
      select.innerHTML = `<option value="">(読み込み失敗)</option>`;
      const hint = $("#log-source-hint");
      if (hint) hint.textContent = e.message;
    }
  }

  function logParams() {
    return {
      source: $("#log-source").value,
      query: $("#log-query").value,
      regex: $("#log-regex").checked,
      ignore_case: $("#log-ignore-case").checked,
      and_logic: $("#log-and").checked,
      event_ids: $("#log-eid").value,
      channel: $("#log-channel").value,
      computer: $("#log-host").value,
      start: $("#log-start").value,
      end: $("#log-end").value,
      limit: parseInt($("#log-limit").value, 10) || 200,
    };
  }

  async function runLogSearch() {
    const btn = $("#log-run");
    const params = logParams();
    if (!params.source) {
      $("#log-meta").textContent = "先に対象ファイルを選んでください。";
      return;
    }
    logs.source = params.source;
    setBusy(btn, true, "検索中…");
    $("#log-meta").textContent = "エンジンを実行しています…";
    try {
      const data = await postJSON("/api/logs/search", params);
      logs.events = data.events || [];
      logs.meta = data;
      $("#log-count").textContent = data.matched.toLocaleString("ja-JP");
      const bits = [
        `${data.returned} / ${data.matched} 件を表示`,
        `${data.elapsed_ms} ms`,
        data.source.split("/").pop(),
      ];
      if (data.truncated) bits.push("上限到達（limit を上げるか条件を追加）");
      $("#log-meta").textContent = bits.join(" · ");
      $("#log-export").disabled = !logs.events.length;
      renderLogResult();
    } catch (e) {
      logs.events = [];
      $("#log-count").textContent = "—";
      $("#log-meta").textContent = e.message;
      $("#log-export").disabled = true;
      $("#log-result").innerHTML = `<div class="empty-state error">
        <div class="empty-mark">!</div><p>${esc(e.message)}</p></div>`;
    } finally {
      setBusy(btn, false);
    }
  }

  function exportLogCsv() {
    if (!logs.events.length) return;
    const head = ["Timestamp", "EventID", "Channel", "Computer", "Title", "Details"];
    const rows = logs.events.map((ev) => [
      ev.Timestamp, ev.EventID, ev.Channel, ev.Computer, ev.Title,
      JSON.stringify(ev.Details || {}),
    ]);
    const csv = [head, ...rows].map((r) => r.map((v) => {
      const s = String(v ?? "");
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(",")).join("\r\n");
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "hayabusa-log-search.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  function initLogs() {
    if (!logs.ready) {
      logs.ready = true;
      $("#log-refresh").onclick = loadLogSources;
      $("#log-run").onclick = runLogSearch;
      $("#log-clear").onclick = () => {
        ["#log-query", "#log-eid", "#log-channel", "#log-host", "#log-start", "#log-end"]
          .forEach((s) => { const el = $(s); if (el) el.value = ""; });
        logs.events = [];
        logs.meta = null;
        $("#log-count").textContent = "—";
        $("#log-meta").textContent = "条件を入れて検索してください";
        $("#log-export").disabled = true;
        $("#log-result").innerHTML = `<div class="empty-state">
          <div class="empty-mark">⌕</div>
          <p>検索結果はここに出ます。<br/>行をクリックすると全フィールドが開きます。</p></div>`;
      };
      $("#log-export").onclick = exportLogCsv;
      $("#log-source").onchange = (e) => { logs.source = e.target.value; };
      $("#log-query").addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); runLogSearch(); }
      });
      $("#log-result").addEventListener("click", (e) => {
        const rawBtn = e.target.closest(".js-raw");
        if (rawBtn) {
          e.stopPropagation();
          const pre = rawBtn.parentElement.querySelector(".raw-json");
          if (!pre) return;
          pre.hidden = !pre.hidden;
          rawBtn.textContent = pre.hidden ? "生 JSON を表示" : "生 JSON を閉じる";
          return;
        }
        const head = e.target.closest(".logrow-head");
        if (!head) return;
        const row = head.closest(".logrow");
        const body = row.querySelector(".logrow-body");
        const open = body.hidden;
        body.hidden = !open;
        row.classList.toggle("open", open);
      });
      $("#log-result").addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        const head = e.target.closest(".logrow-head");
        if (!head) return;
        e.preventDefault();
        head.click();
      });
      loadLogSources();
    } else {
      loadLogSources();
    }
  }

  /* ======================================================================
   * 2. Elasticsearch
   * ==================================================================== */

  const es = { ready: false, config: null };

  function esConn(text, kind) {
    const el = $("#es-conn");
    if (!el) return;
    el.textContent = text;
    el.className = "conn-state" + (kind ? " " + kind : "");
  }

  function kibanaUrl(url) {
    try {
      const u = new URL(url);
      // The common local layout is ES :9200 next to Kibana :5601. Only guess
      // in that case; a custom endpoint is not necessarily co-located.
      if (u.port !== "9200") return "";
      u.port = "5601";
      u.pathname = "/app/discover";
      u.search = "";
      return u.toString();
    } catch { return ""; }
  }

  async function loadElasticConfig() {
    try {
      const cfg = await getJSON("/api/elastic/config");
      es.config = cfg;
      $("#es-url").value = cfg.url || "";
      $("#es-index").value = cfg.index || "hayabusa-detections";
      $("#es-user").value = cfg.username || "";
      $("#es-tls").checked = cfg.verify_tls !== false;
      const bits = [];
      if (cfg.has_password) bits.push("password 保存済み");
      if (cfg.has_api_key) bits.push("API key 保存済み");
      esConn(cfg.configured ? `設定あり${bits.length ? " · " + bits.join(" / ") : ""}`
                            : "未設定 — URL を入れて保存してください",
             cfg.configured ? "ok" : "");
      const kib = $("#es-kibana");
      const link = cfg.url ? kibanaUrl(cfg.url) : "";
      if (link) { kib.href = link; kib.classList.remove("is-hidden"); }
      else kib.classList.add("is-hidden");
    } catch (e) {
      esConn(e.message, "bad");
    }
  }

  function elasticConfigFromForm() {
    return {
      url: $("#es-url").value.trim(),
      index: $("#es-index").value.trim(),
      username: $("#es-user").value.trim(),
      password: $("#es-pass").value,
      api_key: $("#es-key").value,
      verify_tls: $("#es-tls").checked,
    };
  }

  async function saveElasticConfig() {
    const btn = $("#es-save");
    setBusy(btn, true, "保存中…");
    try {
      const cfg = await postJSON("/api/elastic/config", elasticConfigFromForm());
      es.config = cfg;
      $("#es-pass").value = "";
      $("#es-key").value = "";
      esConn("設定を保存しました", "ok");
      const kib = $("#es-kibana");
      const link = kibanaUrl(cfg.url);
      if (link) { kib.href = link; kib.classList.remove("is-hidden"); }
      else kib.classList.add("is-hidden");
    } catch (e) {
      esConn(e.message, "bad");
    } finally {
      setBusy(btn, false);
    }
  }

  async function testElastic() {
    const btn = $("#es-test");
    setBusy(btn, true, "接続中…");
    try {
      // 画面の入力内容を保存してからテストする（保存済みの古い設定を
      // テストしてしまうと、URL を直したのに失敗して混乱するため）。
      const cfg = await postJSON("/api/elastic/config", elasticConfigFromForm());
      es.config = cfg;
      $("#es-pass").value = "";
      $("#es-key").value = "";
      const r = await getJSON("/api/elastic/test");
      esConn(`接続 OK · ${r.cluster_name || "cluster"} · v${r.version}`, "ok");
      $("#es-meta").textContent = `index: ${r.index}`;
      const kib = $("#es-kibana");
      const link = kibanaUrl(cfg.url);
      if (link) { kib.href = link; kib.classList.remove("is-hidden"); }
      else kib.classList.add("is-hidden");
    } catch (e) {
      esConn(e.message, "bad");
    } finally {
      setBusy(btn, false);
    }
  }

  async function elasticStatus() {
    const btn = $("#es-status");
    setBusy(btn, true, "確認中…");
    try {
      const r = await getJSON("/api/elastic/status");
      if (!r.configured) { esConn("未設定です", "bad"); return; }
      if (!r.exists) { esConn(`index "${r.index}" はまだありません`, ""); return; }
      esConn(`index "${r.index}" · ${r.count.toLocaleString("ja-JP")} docs`, "ok");
      $("#es-count").textContent = r.count.toLocaleString("ja-JP");
      $("#es-meta").textContent = `${r.index} のドキュメント数`;
    } catch (e) {
      esConn(e.message, "bad");
    } finally {
      setBusy(btn, false);
    }
  }

  async function loadElasticJobs() {
    const sel = $("#es-job");
    if (!sel) return;
    try {
      const jobs = await getJSON("/api/jobs");
      const keep = sel.value;
      sel.innerHTML = `<option value="">すべてのスキャン</option>`;
      (jobs || []).forEach((j) => {
        const opt = document.createElement("option");
        opt.value = j.id;
        const when = j.started_at ? new Date(j.started_at * 1000).toLocaleString("ja-JP") : "";
        opt.textContent = `${j.id} · ${when} · ${j.detection_count ?? 0} 件`;
        sel.appendChild(opt);
      });
      if (keep) sel.value = keep;
    } catch { /* jobs list is optional */ }
  }

  async function indexToElastic() {
    const btn = $("#es-index-btn");
    setBusy(btn, true, "投入中…");
    $("#es-index-note").textContent = "SQLite から読み出して _bulk で送信しています…";
    try {
      const r = await postJSON("/api/elastic/index", {
        job_id: $("#es-job").value,
        reset: $("#es-reset").checked,
      });
      const err = (r.errors && r.errors.length) ? ` / エラー ${r.errors.length} 件` : "";
      $("#es-index-note").textContent =
        `${r.indexed.toLocaleString("ja-JP")} 件を "${r.index}" に投入しました${err}`;
      if (r.errors && r.errors.length) {
        $("#es-index-note").textContent += " — " + r.errors.join(" | ");
      }
      await elasticStatus();
    } catch (e) {
      $("#es-index-note").textContent = e.message;
      esConn(e.message, "bad");
    } finally {
      setBusy(btn, false);
    }
  }

  function esHit(h) {
    const ev = h.event || {};
    const title = h.rule_title || ev.RuleTitle || "";
    // ES の highlight は <mark> を含む。本文は必ずエスケープしてから
    // <mark>/</mark> だけを戻す（ログ由来の HTML を実行しない）。
    const highlight = esc(Object.values(h.highlight || {}).flat().join(" … "))
      .replace(/&lt;(\/?)mark&gt;/gi, "<$1mark>");
    return `<article class="es-hit">
      <header class="es-hit-head">
        <span class="sev sev-${esc(String(h.level || "").toLowerCase())}">${esc(h.level || "—")}</span>
        <span class="es-rule">${esc(title)}</span>
        <span class="es-host">${esc(h.computer || "")}</span>
        <span class="es-time">${esc(shortTime(h["@timestamp"]))}</span>
      </header>
      ${highlight ? `<div class="es-hit-highlight">${highlight}</div>` : ""}
      <pre class="raw-json" hidden>${esc(JSON.stringify(h, null, 2))}</pre>
    </article>`;
  }

  async function runElasticSearch() {
    const btn = $("#es-run");
    setBusy(btn, true, "検索中…");
    try {
      const r = await postJSON("/api/elastic/search", {
        query: $("#es-q").value,
        level: $("#es-level").value,
        computer: $("#es-host").value,
        size: 100,
      });
      $("#es-count").textContent = r.total.toLocaleString("ja-JP");
      $("#es-meta").textContent =
        `${r.hits.length} 件を表示 · ${r.took} ms · ${r.index}`;
      if (!r.hits.length) {
        $("#es-result").innerHTML = `<div class="empty-state">
          <div class="empty-mark">∅</div><p>ヒットしませんでした。<br/>
          構文は Lucene（例 <code>rule_title:lsass</code>）です。</p></div>`;
        return;
      }
      $("#es-result").innerHTML = `<div class="es-hits">${r.hits.map(esHit).join("")}</div>`;
    } catch (e) {
      $("#es-result").innerHTML = `<div class="empty-state error">
        <div class="empty-mark">!</div><p>${esc(e.message)}</p></div>`;
    } finally {
      setBusy(btn, false);
    }
  }

  function initElastic() {
    if (!es.ready) {
      es.ready = true;
      $("#es-save").onclick = saveElasticConfig;
      $("#es-test").onclick = testElastic;
      $("#es-status").onclick = elasticStatus;
      $("#es-index-btn").onclick = indexToElastic;
      $("#es-run").onclick = runElasticSearch;
      $("#es-q").addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); runElasticSearch(); }
      });
      $("#es-result").addEventListener("click", (e) => {
        const hit = e.target.closest(".es-hit");
        if (!hit) return;
        const pre = hit.querySelector(".raw-json");
        if (pre) pre.hidden = !pre.hidden;
      });
      loadElasticConfig();
    }
    loadElasticJobs();
    elasticStatus();
  }

  /* ======================================================================
   * 3. Wiring
   * ==================================================================== */

  window.addEventListener("hayfx:tab", (e) => {
    const name = e.detail && e.detail.name;
    if (name === "logs") initLogs();
    if (name === "elastic") initElastic();
  });

  // The page loads on #home, but a deep link may point straight at a new tab.
  const hash = (location.hash || "").replace(/^#/, "");
  if (hash === "logs") initLogs();
  if (hash === "elastic") initElastic();
})();
