/* Hayabusa GUI frontend — vanilla JS SPA. */
console.log("[app] app.js v2026-05-21-c executing");
(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));
  const fmtTime = (ts) => ts ? new Date(ts * 1000).toLocaleString("ja-JP") : "—";
  const fmtDur = (a, b) => {
    if (!a) return "—";
    const end = b || Date.now() / 1000;
    const s = Math.max(0, Math.round(end - a));
    if (s < 60) return s + "秒";
    if (s < 3600) return Math.floor(s / 60) + "分 " + (s % 60) + "秒";
    return Math.floor(s / 3600) + "時間 " + Math.floor((s % 3600) / 60) + "分";
  };
  // バックエンドの英語ステータスを日本語表示に置き換える。
  const STATUS_JA = {
    queued: "待機中", running: "実行中", done: "完了",
    failed: "失敗", cancelled: "中止", idle: "待機中",
  };
  const localizeStatus = (s) => STATUS_JA[s] || s;

  // -------- tabs --------
  // Switch to a tab by its data-tab name. Centralised so home-screen
  // shortcut cards and in-app pivots can reuse it.
  function switchTab(name) {
    // 公開(危険度ランキング)モードでは、ローカル専用タブ (結果/全体ビュー/さがす/
    // パソコン別) への遷移をすべてランキングへ振り替える。ナビは非表示でも、
    // ホームのカードや検知詳細リンク経由で抜け道になるのを防ぐ。
    if (document.body.classList.contains("public-mode")) {
      const t = document.querySelector('.tab[data-tab="' + name + '"]');
      if (t && t.classList.contains("local-only")) name = "ranking";
    }
    $$(".tab").forEach(x => x.classList.toggle("active", x.dataset.tab === name));
    const id = "tab-" + name;
    $$(".tab-panel").forEach(p => p.classList.toggle("active", p.id === id));
    // タブを URL ハッシュに反映 → 共有・ブックマーク・直リンクが効く
    if (("#" + name) !== location.hash) {
      try { history.replaceState(null, "", "#" + name); } catch { location.hash = name; }
    }
    if (name === "results") refreshJobs();
    if (name === "rules") { loadRules(); loadFeedback(); loadSuppressions(); loadLookups(); }
    if (name === "dashboard") loadDashboard();
    if (name === "hunt") initHunt();
    if (name === "hosts") loadHosts();
    if (name === "ranking") loadRanking();
  }
  $$(".tab").forEach(t => t.onclick = () => switchTab(t.dataset.tab));

  // 起動時に URL ハッシュ (#dashboard 等) があればそのタブを開く
  const _hashTab = (location.hash || "").replace(/^#/, "");
  if (_hashTab && document.getElementById("tab-" + _hashTab)) {
    switchTab(_hashTab);
  }

  // 公開(危険度ランキング)モードの判定。サーバが 0.0.0.0 で待受しているとき
  // network_mode=true。ローカル専用機能を隠し、ランキングを入口にする。
  fetch("/api/config").then(r => r.json()).then(cfg => {
    // 運営者(localhost)だけに「安全としてマーク」等の管理操作を見せる。
    document.body.classList.toggle("is-admin", !!(cfg && cfg.is_admin));
    if (cfg && cfg.network_mode) {
      document.body.classList.add("public-mode");
      // 入口はランキング。直リンク (#results 等) でローカル専用タブを開いた場合も振り替える。
      const cur = document.querySelector(".tab.active");
      if (!_hashTab || (cur && cur.classList.contains("local-only"))) switchTab("ranking");
      loadRankingStats();   // スキャン画面の大会ダッシュボードを初期表示
    }
  }).catch(() => {});

  // ホーム画面の 3 ステップカード → 該当タブへ
  $$(".home-step").forEach(step => {
    step.onclick = () => { const g = step.dataset.goto; if (g) switchTab(g); };
  });
  // 空状態などからの「○○へ」ボタン (data-goto-tab) を委譲で拾う
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-goto-tab]");
    if (el) { e.preventDefault(); switchTab(el.dataset.gotoTab); }
  });

  // -------- health --------
  async function health() {
    try {
      const r = await fetch("/api/health");
      const d = await r.json();
      $("#ver").textContent = (d.version || "").replace(/^Hayabusa\s*/, "");
      $("#health").classList.add("ok");
      $("#health").title = "Hayabusa 正常\n" + d.hayabusa;
    } catch (e) {
      $("#health").classList.add("bad");
      $("#health").title = "Hayabusa との通信に失敗しました";
    }
  }

  // -------- workspace listing (clickable cards) --------
  const fmtSize = (n) => {
    if (n == null) return "";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KiB";
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MiB";
    return (n / 1024 / 1024 / 1024).toFixed(2) + " GiB";
  };

  async function refreshWorkspace() {
    try {
      const r = await fetch("/api/workspace");
      const d = await r.json();
      const root = $("#workspace-listing");
      root.innerHTML = "";
      const items = (d.uploads || []).concat(d.results || []);
      // Filter to .evtx and directories — those are the only valid scan
      // targets, and showing analysis output as a "scannable file" is
      // misleading.
      const usable = items.filter(it =>
        it.type === "dir" || /\.evtx$/i.test(it.name));
      if (!usable.length) {
        root.innerHTML = `<div class="ws-empty">
          まだ EVTX がありません。<br/>
          上のドロップゾーンにファイルを投げ込むと、ここに現れます。
        </div>`;
        return;
      }
      // Directories first, then files; alphabetical within each.
      usable.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name)
                              : (a.type === "dir" ? -1 : 1)));
      const selected = $("#target-path").value;
      usable.forEach(it => {
        const card = document.createElement("div");
        card.className = "ws-item" + (it.rel === selected ? " selected" : "");
        const dirMark = it.type === "dir" ? `<span class="dir-mark">▸</span>` : "";
        card.innerHTML = `
          <div class="name" title="${it.rel}">${dirMark}${it.name}${it.type === "dir" ? "/" : ""}</div>
          <div class="size">${it.type === "dir" ? "—" : fmtSize(it.size)}</div>
          <div class="kind">${it.type === "dir" ? "DIR" : "EVTX"}</div>`;
        card.onclick = () => selectTarget(it);
        root.appendChild(card);
      });
    } catch (e) { /* ignore */ }
  }

  // -------- "このパソコン" カード --------
  // We hold the latest /api/system/info response so the modal can reuse it
  // without a second fetch. Refresh is cheap so we re-pull on each open.
  let systemInfo = null;
  // Channels currently selected for live scan. Empty = "all readable".
  let selectedChannels = [];

  async function loadSystemInfo() {
    try {
      const r = await fetch("/api/system/info", { cache: "no-store" });
      systemInfo = await r.json();
      console.log("[app] system info: " + (systemInfo.channels?.length || 0)
        + " channels, admin=" + systemInfo.admin);
    } catch (e) {
      systemInfo = null;
      console.error("[app] loadSystemInfo failed:", e);
    }
    renderThisPc();
    // Pre-render the modal contents so opening the modal is purely a
    // visibility toggle — no async, no race conditions, no chance for the
    // user to see an empty list.
    renderChannelsList();
  }

  // Detached from openChannelsModal so we can call it eagerly at boot.
  // The modal stays hidden; only its INNER content is populated.
  function renderChannelsList() {
    const host = document.querySelector("#channels-list");
    if (!host) {
      console.error("[channels] #channels-list element missing");
      return;
    }
    host.innerHTML = "";
    if (!systemInfo) {
      host.innerHTML = `<div class="muted small" style="padding:14px">
        <strong>システム情報の取得に失敗しました。</strong><br/>
        サーバ <code>/api/system/info</code> が応答していません。
      </div>`;
      return;
    }
    if (systemInfo.platform !== "win32") {
      host.innerHTML = `<div class="muted small" style="padding:14px">
        Windows 上でのみ動作します (現在: ${escapeHtml(String(systemInfo.platform))})。
      </div>`;
      return;
    }
    if (!Array.isArray(systemInfo.channels) || systemInfo.channels.length === 0) {
      host.innerHTML = `<div class="muted small" style="padding:14px">
        EVTX チャネルが見つかりません: <code>${escapeHtml(String(systemInfo.evtx_root || ""))}</code>
      </div>`;
      return;
    }
    const sorted = [...systemInfo.channels].sort((a, b) => {
      const pa = a.priority ? 1 : 0, pb = b.priority ? 1 : 0;
      if (pa !== pb) return pb - pa;
      const ra = a.readable ? 1 : 0, rb = b.readable ? 1 : 0;
      if (ra !== rb) return rb - ra;
      return (b.size || 0) - (a.size || 0);
    });
    try {
      const frag = document.createDocumentFragment();
      sorted.forEach(c => {
        const row = document.createElement("div");
        row.className = "row" + (c.priority ? " priority" : "")
          + (c.readable ? "" : " unreadable");
        const checked = c.priority && c.readable;
        row.innerHTML = `
          <input type="checkbox" data-name="${escapeHtml(c.name)}" ${checked ? "checked" : ""}
                 ${c.readable ? "" : "disabled"} />
          <div class="name" title="${escapeHtml(c.name)}">${escapeHtml(c.channel || c.name)}</div>
          <div class="size">${c.size != null ? fmtSize(c.size) : "—"}</div>
          <div class="badge">${c.priority ? "PRIORITY" : (c.readable ? "" : "DENIED")}</div>`;
        frag.appendChild(row);
      });
      host.appendChild(frag);
      console.log("[channels] pre-rendered " + sorted.length + " rows");
    } catch (e) {
      console.error("[channels] render failed:", e);
      host.innerHTML = `<div class="muted small" style="padding:14px;color:#ef5350">
        描画エラー: <code>${escapeHtml(String(e))}</code></div>`;
    }
  }

  function renderThisPc() {
    const summary = $("#this-pc-summary");
    const status = $("#this-pc-status");
    const btnScan = $("#pc-scan-btn");
    const btnImport = $("#pc-import-btn");
    const btnCh = $("#pc-channels-btn");
    if (!systemInfo) {
      summary.textContent = "情報取得に失敗";
      status.textContent = "/api/system/info が応答していません。";
      [btnScan, btnImport, btnCh].forEach(b => b.disabled = true);
      return;
    }
    if (systemInfo.platform !== "win32") {
      summary.textContent = systemInfo.platform;
      status.textContent = "この機能は Windows でのみ動作します。";
      [btnScan, btnImport, btnCh].forEach(b => b.disabled = true);
      return;
    }
    const total = systemInfo.total_size || 0;
    const readable = systemInfo.channels.filter(c => c.readable).length;
    const unread = systemInfo.unreadable_count;
    summary.textContent = `${systemInfo.channels.length} チャネル / 読取可 ${readable}`;
    if (systemInfo.admin) {
      status.className = "this-pc-status ok";
      status.innerHTML = `✓ 管理者権限あり &nbsp; ・ &nbsp; 読み取り可能ログ: ${fmtSize(total)}`
        + (unread ? `<span class="muted small"> (${unread} 件 アクセス不可)</span>` : "");
    } else {
      status.className = "this-pc-status warn";
      status.innerHTML = `⚠ サーバプロセスが管理者権限で動いていません。 <span class="muted small">`
        + `PowerShell を「管理者として実行」で開き直して <code>.\\start.ps1</code> を起動してください。`
        + `現状でも Application / PowerShell 等の一部チャネルは読めるので、`
        + `そのままスキャンしても部分的な結果は得られます。</span>`;
    }
    // We keep all three buttons clickable regardless of admin status —
    // Hayabusa itself returns a clean error when it can't read a file,
    // and disabling buttons silently leaves users wondering why nothing
    // happens. The buttons surface real failures faster than guessing
    // ahead of time.
    [btnScan, btnImport, btnCh].forEach(b => b.disabled = false);
  }

  // --- buttons ---
  $("#pc-scan-btn").onclick = async () => {
    // One-click live scan: set the form fields, update the visible
    // selection summary, then immediately kick off the same scan flow
    // that the main run-button uses. Skipping the extra click matches
    // the user's mental model ("I pressed scan, scan something").
    $("#target-type").value = "live";
    $("#allow-live").checked = true;
    $("#target-path").value = "";
    const label = $("#selection-label");
    label.textContent = "ライブ解析 (このパソコン)";
    label.classList.remove("selection-empty");
    refreshWorkspace();
    updateScanButton();
    // Programmatically invoke the main scan button. Going through
    // .click() keeps a single source of truth for the scan path
    // (validation, summary update, live-feed binding all live there).
    if (!$("#scan-btn").disabled) {
      $("#scan-btn").click();
    } else {
      alert("スキャン開始ボタンが無効です。コンソール (F12) のエラーを確認してください。");
    }
  };

  $("#pc-import-btn").onclick = async () => {
    // Default import = priority channels with readable=true.
    const names = (systemInfo?.channels || [])
      .filter(c => c.priority && c.readable)
      .map(c => c.name);
    if (!names.length) {
      alert("読み取り可能な優先チャネルがありません。管理者権限で再起動してください。");
      return;
    }
    if (!confirm(`${names.length} 個のチャネル(優先のみ)を workspace/uploads/system-snapshot/ にコピーします。よろしいですか?`)) return;
    const btn = $("#pc-import-btn");
    btn.disabled = true;
    btn.textContent = "コピー中…";
    try {
      const r = await fetch("/api/system/import", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({channels: names}),
      });
      const d = await r.json();
      if (d.error) { alert("エラー: " + d.error); return; }
      const errMsg = d.errors.length ? `\n失敗: ${d.errors.length} 件` : "";
      alert(`${d.saved.length} 個のファイルを取り込みました → ${d.snapshot_dir}/${errMsg}`);
      refreshWorkspace();
    } catch (e) {
      alert("通信エラー: " + e);
    } finally {
      btn.disabled = false;
      btn.textContent = "EVTX を取り込む";
    }
  };

  // --- channel picker modal ---
  // Open is JS-side because it has to populate / refresh content.
  $("#pc-channels-btn").onclick = () => openChannelsModal();
  // Close handlers are EXCLUSIVELY in HTML inline onclick (see index.html).
  // We deliberately do NOT register a JS-side handler for #channels-close
  // because `.onclick = ...` would overwrite the inline attribute, and any
  // hiccup in the JS arrow function would silently dead-end the close.
  // Escape key handling is the one JS-side close we keep — there is no
  // sensible inline equivalent.
  document.addEventListener("keydown", (e) => {
    const modal = $("#channels-modal");
    if (e.key === "Escape" && modal && !modal.classList.contains("is-hidden")) {
      modal.classList.add("is-hidden");
    }
  });
  $("#ch-select-priority").onclick = () => setChannelSelection(c => c.priority && c.readable);
  $("#ch-select-all").onclick = () => setChannelSelection(c => c.readable);
  $("#ch-select-none").onclick = () => setChannelSelection(() => false);

  // We attach the change listener exactly once at boot; the rows that
  // come and go inside #channels-list are caught via event delegation.
  $("#channels-list").addEventListener("change", updateChannelsSummary);

  function openChannelsModal() {
    // Contents are pre-rendered at boot inside loadSystemInfo →
    // renderChannelsList. Opening is now a pure DOM toggle — no async, no
    // race conditions, no chance of an empty list.
    console.log("[channels] open modal");
    // If the list is still empty (loadSystemInfo never completed), kick
    // off a synchronous re-render based on the current cached state. The
    // user will see whatever the latest fetch produced.
    const host = document.querySelector("#channels-list");
    if (host && host.children.length === 0) {
      renderChannelsList();
    }
    $("#channels-modal").classList.remove("is-hidden");
    updateChannelsSummary();
  }
  function setChannelSelection(pred) {
    document.querySelectorAll("#channels-list input[type=checkbox]").forEach(cb => {
      cb.checked = !cb.disabled && pred({
        name: cb.dataset.name,
        priority: cb.closest(".row").classList.contains("priority"),
        readable: !cb.disabled,
      });
    });
    updateChannelsSummary();
  }
  function getCheckedChannels() {
    return Array.from(document.querySelectorAll("#channels-list input[type=checkbox]:checked"))
      .map(cb => cb.dataset.name);
  }
  function updateChannelsSummary() {
    const names = getCheckedChannels();
    let bytes = 0;
    const byName = new Map((systemInfo?.channels || []).map(c => [c.name, c]));
    names.forEach(n => bytes += byName.get(n)?.size || 0);
    $("#channels-summary").textContent =
      `${names.length} 個選択中 (計 ${fmtSize(bytes)})`;
  }
  $("#channels-confirm").onclick = async () => {
    const names = getCheckedChannels();
    if (!names.length) { alert("少なくとも 1 つのチャネルを選んでください"); return; }
    $("#channels-modal").classList.add("is-hidden");
    // Import the selected channels into workspace and then point the
    // target there. This lets us use directory-mode scan (no admin
    // needed after the import) and lets the user re-scan the same
    // snapshot multiple times.
    const btn = $("#channels-confirm");
    btn.disabled = true; btn.textContent = "取込中…";
    try {
      const r = await fetch("/api/system/import", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({channels: names}),
      });
      const d = await r.json();
      if (d.error) { alert("エラー: " + d.error); return; }
      // Point the scan target at the snapshot dir.
      $("#target-type").value = "directory";
      $("#allow-live").checked = false;
      $("#target-path").value = d.snapshot_dir;
      const label = $("#selection-label");
      label.textContent = `${d.snapshot_dir}/  (${d.saved.length} ファイル、計 ${fmtSize(d.saved.reduce((s,x)=>s+x.size,0))})`;
      label.classList.remove("selection-empty");
      updateScanButton();
      refreshWorkspace();
    } finally {
      btn.disabled = false; btn.textContent = "この選択でスキャン";
    }
  };

  // -------- target selection --------
  function selectTarget(item) {
    $("#target-path").value = item.rel;
    $("#target-type").value = item.type === "dir" ? "directory" : "file";
    const label = $("#selection-label");
    label.textContent = item.rel + (item.type === "dir"
      ? "  (ディレクトリ)"
      : "  (" + fmtSize(item.size) + ")");
    label.classList.remove("selection-empty");
    refreshWorkspace();      // re-highlights the selected card
    updateScanButton();
  }

  // -------- upload (with drag-and-drop) --------
  const dropZone = $("#drop-zone");
  const uploadInput = $("#upload-input");

  // Clicking the drop zone is a sensible alternative to picking the
  // file input directly — it's a noticeably larger hit target.
  dropZone.addEventListener("click", (e) => {
    if (e.target.closest("label,input")) return;  // don't double-trigger
    uploadInput.click();
  });
  ["dragenter", "dragover"].forEach(evt =>
    dropZone.addEventListener(evt, e => {
      e.preventDefault(); e.stopPropagation();
      dropZone.classList.add("over");
    }));
  ["dragleave", "drop"].forEach(evt =>
    dropZone.addEventListener(evt, e => {
      e.preventDefault(); e.stopPropagation();
      dropZone.classList.remove("over");
    }));
  dropZone.addEventListener("drop", e => uploadFiles(e.dataTransfer.files));
  uploadInput.addEventListener("change", () => uploadFiles(uploadInput.files));

  async function uploadFiles(fileList) {
    // .evtx をそのまま、または .zip (収集ツールの出力) をまとめて受け付ける。
    const files = Array.from(fileList || []).filter(f => /\.(evtx|zip)$/i.test(f.name));
    if (!files.length) {
      $("#upload-status").textContent = ".evtx または .zip ファイルを入れてください";
      return;
    }
    let lastSaved = null;
    for (const f of files) {
      const fd = new FormData(); fd.append("file", f);
      $("#upload-status").textContent =
        /\.zip$/i.test(f.name)
          ? `アップロード中…（ZIP を展開します） ${f.name} (${fmtSize(f.size)})`
          : `アップロード中… ${f.name} (${fmtSize(f.size)})`;
      try {
        const r = await fetch("/api/upload", { method: "POST", body: fd });
        const d = await r.json();
        if (d.error) {
          $("#upload-status").textContent = "エラー: " + d.error;
          return;
        }
        const entry = (d.saved || [])[0];
        if (entry && entry.error) {   // 例: ZIP 内に .evtx が無い
          $("#upload-status").textContent = "エラー: " + entry.error;
          return;
        }
        lastSaved = entry;
      } catch (e) {
        $("#upload-status").textContent = "通信エラー: " + e;
        return;
      }
    }
    if (lastSaved && lastSaved.kind === "dir") {
      $("#upload-status").textContent =
        `ZIP を展開しました → ${lastSaved.count} 個の .evtx（まとめてスキャンします）`;
    } else {
      $("#upload-status").textContent =
        files.length === 1
          ? `保存しました → ${lastSaved.rel}`
          : `${files.length} 個のファイルを保存しました`;
    }
    await refreshWorkspace();
    if (lastSaved) {
      // 直近のアップロードを自動選択（ZIP 展開ならフォルダ=ディレクトリ対象）。
      selectTarget({ ...lastSaved, type: lastSaved.kind === "dir" ? "dir" : "file" });
    }
  }

  // -------- presets --------
  const PRESETS = {
    standard: {
      min_level: "medium", eid_filter: false, enable_all: false,
      proven_only: false, dedupe: true,
    },
    fast: {
      min_level: "medium", eid_filter: true, enable_all: false,
      proven_only: true, dedupe: true,
    },
    deep: {
      min_level: "informational", eid_filter: false, enable_all: true,
      proven_only: false, dedupe: false,
    },
  };
  function applyPreset(name) {
    if (name === "custom") { updateScanButton(); return; }
    const p = PRESETS[name]; if (!p) return;
    $("#min-level").value = p.min_level;
    $("#eid-filter").checked = p.eid_filter;
    $("#enable-all").checked = p.enable_all;
    $("#proven-only").checked = p.proven_only;
    $("#dedupe").checked = p.dedupe;
    updateScanButton();
  }
  document.querySelectorAll(".preset-btn").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll(".preset-btn").forEach(b =>
        b.classList.toggle("active", b === btn));
      applyPreset(btn.dataset.preset);
    };
  });
  // Any manual change to settings switches the preset to "custom".
  ["min-level", "eid-filter", "enable-all", "proven-only", "dedupe",
   "include-tags", "exclude-tags", "ts-start", "ts-end"
  ].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("change", () => {
      document.querySelectorAll(".preset-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.preset === "custom");
      });
      updateScanButton();
    });
  });

  // -------- scan summary + enable/disable --------
  function updateScanButton() {
    const btn = $("#scan-btn");
    const summary = $("#scan-summary");
    const path = $("#target-path").value.trim();
    const type = $("#target-type").value;
    const live = $("#allow-live").checked && type === "live";
    const hasTarget = live || path.length > 0;
    btn.disabled = !hasTarget;
    if (!hasTarget) {
      summary.textContent = "先にステップ 1 で対象を選んでください";
      return;
    }
    const level = $("#min-level").value;
    const flags = [];
    if ($("#eid-filter").checked)  flags.push("EIDフィルタ");
    if ($("#enable-all").checked)  flags.push("全ルール");
    if ($("#proven-only").checked) flags.push("実績ルールのみ");
    if ($("#dedupe").checked)      flags.push("重複排除");
    const targetLabel = live ? "ライブ解析" : path;
    summary.textContent =
      `${targetLabel} ・ 最小レベル: ${level}` +
      (flags.length ? ` ・ ${flags.join(" / ")}` : "");
  }

  // Hooks that should also recompute the summary.
  $("#target-type").addEventListener("change", updateScanButton);
  $("#allow-live").addEventListener("change", updateScanButton);

  // -------- scan submission --------
  let liveES = null;

  // ニックネームはブラウザに記憶。値が "" でも「キーが存在する=入力済み」と扱い、
  // 2回目以降はモーダルを出さずにその名前でランキング更新する。
  const NICK_KEY = "hayabusa_nickname";
  // localStorage が無音失敗する環境 (プライベートモード等) でも、セッション内は
  // メモリに保持して二度と聞かれないようにする。
  let _nick = null;
  const storedNick = () => {
    if (_nick !== null) return _nick;
    try { _nick = localStorage.getItem(NICK_KEY); } catch { _nick = null; }
    return _nick;
  };
  const setStoredNick = (v) => { _nick = v; try { localStorage.setItem(NICK_KEY, v); } catch {} };
  { const n = storedNick(); if (n != null && $("#nickname")) $("#nickname").value = n; }

  function buildScanParams() {
    const targetType = $("#target-type").value;
    // 公開モードは記憶済みニックネームを使用。ローカルは入力欄(あれば)。
    const nick = (storedNick() ?? ($("#nickname")?.value || "")).trim();
    return {
      target: { type: targetType, path: $("#target-path").value.trim() },
      nickname: nick,
      allow_live: $("#allow-live").checked,
      min_level: $("#min-level").value,
      eid_filter: $("#eid-filter").checked,
      enable_all_rules: $("#enable-all").checked,
      proven_rules: $("#proven-only").checked,
      remove_duplicates: $("#dedupe").checked,
      include_tags: $("#include-tags").value.split(",").map(s => s.trim()).filter(Boolean),
      exclude_tags: $("#exclude-tags").value.split(",").map(s => s.trim()).filter(Boolean),
      timeline_start: $("#ts-start").value.trim() || null,
      timeline_end: $("#ts-end").value.trim() || null,
    };
  }

  async function startScan() {
    const r = await fetch("/api/scan", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildScanParams())
    });
    const d = await r.json();
    if (d.error) { alert("スキャンを開始できませんでした: " + d.error); return; }
    bindLive(d.job_id);
  }

  function openNicknameModal(startAfter) {
    const m = $("#nickname-modal"); if (!m) { startScan(); return; }
    const n = storedNick(); if (n != null && $("#nickname")) $("#nickname").value = n;
    m.dataset.startAfter = startAfter ? "1" : "";
    m.classList.remove("is-hidden");
    setTimeout(() => $("#nickname")?.focus(), 50);
  }

  $("#scan-btn").onclick = () => {
    if ($("#scan-btn").disabled) return;
    // 公開モードで未入力なら、初回だけ名前入力モーダルを出してから開始。
    if (document.body.classList.contains("public-mode") && storedNick() === null) {
      openNicknameModal(true);
      return;
    }
    startScan();
  };

  {
    const confirmNick = () => {
      const m = $("#nickname-modal");
      setStoredNick(($("#nickname")?.value || "").trim());
      m.classList.add("is-hidden");
      if (m.dataset.startAfter === "1") { m.dataset.startAfter = ""; startScan(); }
    };
    $("#nickname-confirm")?.addEventListener("click", confirmNick);
    $("#nickname")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); confirmNick(); }
    });
    $("#nickname-edit")?.addEventListener("click", () => openNicknameModal(false));
  }

  // Refresh button on the workspace panel.
  $("#ws-refresh").onclick = refreshWorkspace;

  // Job id whose stream is currently being shown in the live feed.
  // Detection rows in the feed key off this when fetching detail.
  let liveJobId = null;

  function bindLive(jobId) {
    liveJobId = jobId;
    // スキャン中は公開モードの大会ダッシュを隠し、進捗を前面に出す。
    document.body.classList.add("scanning");
    $("#live-card").hidden = false;
    $("#live-jobid").textContent = "#" + jobId;
    $("#live-feed").innerHTML = "";
    $("#m-count").textContent = "0";
    $("#m-status").textContent = localizeStatus("queued");
    $("#m-elapsed").textContent = "0秒";
    // 進捗バー + 中止ボタンを表示
    $("#scan-progress").hidden = false;
    $("#progress-note").textContent = "スキャンの準備をしています…";
    // バーをリセット: 推定 % が来るまでは流れるストライプ (indeterminate)
    const progFill = $("#scan-progress .progress-fill");
    progFill.classList.add("indeterminate");
    progFill.style.width = "";
    // 進捗表示用のローカル状態 (note に % と件数を合成する)
    let totalFilesSeen = null, lastPct = 0, lastEta = null;
    const fmtDur = (s) => s >= 60 ? `${Math.floor(s / 60)}分${s % 60}秒` : `${s}秒`;
    const renderNote = () => {
      if (lastPct >= 100) {  // 完了直前のスナップ表示
        const tail = totalFilesSeen
          ? `（${totalFilesSeen.toLocaleString()} 件のログ）` : "";
        $("#progress-note").textContent = `解析完了 ✓ 100%${tail}`;
        return;
      }
      const parts = [];
      if (lastPct > 0) parts.push(`${Math.round(lastPct)}%`);
      if (totalFilesSeen) parts.push(`${totalFilesSeen.toLocaleString()} 件のログ`);
      let s = parts.length ? `${parts.join(" ・ ")} を解析中…` : "解析中…";
      if (lastEta != null && lastPct > 0) {
        s += `（残り 約${fmtDur(lastEta)}）`;
      }
      $("#progress-note").textContent = s;
    };
    const setProgress = (pct, etaSec) => {
      lastPct = pct;
      lastEta = (etaSec == null) ? lastEta : etaSec;
      progFill.classList.remove("indeterminate");  // 確定バーに切替
      progFill.style.width = Math.max(0, Math.min(100, pct)) + "%";
      renderNote();
    };
    const cancelBtn = $("#cancel-scan-btn");
    cancelBtn.hidden = false;
    cancelBtn.disabled = false;
    cancelBtn.textContent = "■ 中止";
    cancelBtn.onclick = () => cancelScan(jobId, cancelBtn);

    if (liveES) liveES.close();
    const startedAt = Date.now();
    const tick = setInterval(() => {
      $("#m-elapsed").textContent = Math.round((Date.now() - startedAt) / 1000) + "秒";
    }, 1000);

    // スキャン終了時に進捗 UI を片付ける共通処理
    const finishUI = (statusText) => {
      clearInterval(tick);
      document.body.classList.remove("scanning");   // 大会ダッシュを戻す
      cancelBtn.hidden = true;
      if (statusText) $("#progress-note").textContent = statusText;
      // 100% を一瞬見せてから片付ける (完了が伝わるように)。
      setTimeout(() => { $("#scan-progress").hidden = true; }, 450);
    };

    liveES = new EventSource(`/api/jobs/${jobId}/stream`);
    liveES.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "state") {
        $("#m-status").textContent = localizeStatus(msg.job.status);
        $("#m-status").className = "status-" + msg.job.status;
        if (msg.job.status === "running") {
          if (msg.job.total_files) totalFilesSeen = msg.job.total_files;
          renderNote();
        }
        if (["done", "failed", "cancelled"].includes(msg.job.status)) {
          finishUI();
        }
      } else if (msg.type === "meta") {
        // 規模 (総ログ件数) が分かったら note に反映
        if (msg.total_files != null) {
          totalFilesSeen = Number(msg.total_files);
          renderNote();
        }
      } else if (msg.type === "progress") {
        // サーバが入力サイズ × 経過時間から推定した完了率
        setProgress(Number(msg.pct), msg.eta_sec);
      } else if (msg.type === "detection") {
        $("#m-count").textContent = msg.n;
        appendDetection(msg.event, msg.n);
      } else if (msg.type === "complete") {
        liveES.close(); liveES = null;
        finishUI();
        refreshJobs();
        // 公開(ランキング)モードでは、スキャンが終わるたびに順位を更新する。
        if (document.body.classList.contains("public-mode")) { loadRanking(); loadRankingStats(); }
      } else if (msg.type === "error") {
        const row = document.createElement("div");
        row.className = "row"; row.style.color = "var(--bad)";
        row.textContent = `[エラー/${msg.stage}] ${msg.msg}`;
        $("#live-feed").appendChild(row);
      }
    };
    liveES.onerror = () => { finishUI(); };
  }

  // スキャンを中止する。サーバ側で subprocess を terminate/kill する。
  async function cancelScan(jobId, btn) {
    if (!confirm("実行中のスキャンを中止しますか?\n(ここまでに見つかった結果は残ります)")) return;
    btn.disabled = true;
    btn.textContent = "中止中…";
    $("#progress-note").textContent = "中止しています…";
    try {
      const r = await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
      const d = await r.json();
      if (d.error) {
        $("#progress-note").textContent = "中止できませんでした: " + d.error;
        btn.disabled = false; btn.textContent = "■ 中止";
      }
      // 成功時は SSE の complete / state(cancelled) が UI を片付ける
    } catch (e) {
      $("#progress-note").textContent = "通信エラー: " + e;
      btn.disabled = false; btn.textContent = "■ 中止";
    }
  }

  function appendDetection(ev, lineNo) {
    // Sanitise to letters only — Level feeds an innerHTML class/text below, so
    // never trust it raw (defence-in-depth against crafted detection output).
    const lvl = ((ev.Level || "info").toLowerCase().match(/[a-z]+/) || ["info"])[0];
    const row = document.createElement("div");
    row.className = "row clickable";
    row.dataset.jobId = liveJobId || "";
    row.dataset.lineNo = String(lineNo || 0);
    const ts = document.createElement("div"); ts.textContent = ev.Timestamp || "";
    const lv = document.createElement("div");
    lv.innerHTML = `<span class="lvl lvl-${lvl}">${lvl.slice(0,4)}</span>`;
    const title = document.createElement("div");
    title.innerHTML = `${escapeHtml(ev.RuleTitle || ev.Title || "(タイトル無し)")} `
                    + `<span class="muted small">▾</span>`;
    const meta = document.createElement("div"); meta.className = "muted";
    meta.textContent = [ev.Computer, ev.Channel, ev.EventID].filter(Boolean).join(" · ");
    row.append(ts, lv, title, meta);
    row.addEventListener("click", () => toggleExplain(row, ev));
    const feed = $("#live-feed");
    feed.appendChild(row);
    while (feed.children.length > 1600) feed.removeChild(feed.firstChild);
    feed.scrollTop = feed.scrollHeight;
  }

  // -------- 検知解説 (ライブフィード行の展開) --------

  // ATT&CK technique → 日本語要約 + 攻撃者が「何を狙っているか」の説明。
  // tNNNN.NNN 形式 (Hayabusa の tag) を小文字キーで持つ。
  const ATTACK_INFO = {
    "t1003":     ["認証情報ダンプ", "メモリやレジストリからパスワード/ハッシュを抜き取り、横展開や成りすましに使う。"],
    "t1003.001": ["LSASS メモリ", "Windows の認証プロセス lsass.exe からハッシュやパスワードを抜き取る。Mimikatz・comsvcs.dll 経由が定番。"],
    "t1003.002": ["SAM データベース", "ローカルアカウントのハッシュを SAM レジストリから取り出す。"],
    "t1027":     ["難読化", "ペイロードを base64 や暗号化で隠して検知を回避する。"],
    "t1036":     ["なりすまし", "正規ファイル名や場所を装って実行する (例: System32 に偽 svchost.exe)。"],
    "t1055":     ["プロセスインジェクション", "他の正規プロセスにコードを注入して身を隠しつつ実行する。"],
    "t1059":     ["コマンド・スクリプト実行", "シェル経由で攻撃者のコマンドを走らせる。"],
    "t1059.001": ["PowerShell", "PowerShell を使った攻撃。難読化・メモリ実行・AMSI bypass を伴うことが多い。"],
    "t1059.003": ["コマンドプロンプト", "cmd.exe / batch 経由のコマンド実行。"],
    "t1068":     ["権限昇格", "脆弱性やドライバを悪用して管理者・SYSTEM 権限を得る。BYOVD が増加中。"],
    "t1070":     ["証拠の隠蔽", "ログを消したり、ファイルを削除したりして痕跡を消す。"],
    "t1070.001": ["Windows イベントログのクリア", "wevtutil cl や Clear-EventLog でログを消去。攻撃直後に行われる。"],
    "t1071":     ["C2 通信", "HTTP/DNS など正常に見えるプロトコルで指令サーバと通信。"],
    "t1078":     ["有効なアカウント悪用", "盗んだ正規アカウントでログイン。検知をすり抜けやすい。"],
    "t1082":     ["システム情報収集", "OS バージョン・ユーザー名・ドメインなどを集めて偵察する。"],
    "t1083":     ["ファイル/ディレクトリ偵察", "dir, Get-ChildItem などで価値のあるファイルを探す。"],
    "t1105":     ["外部からの追加ツール持込み", "certutil / curl / bitsadmin で C2 から追加 malware を落とす。"],
    "t1112":     ["レジストリ改変", "永続化や設定改ざんのためレジストリを操作。"],
    "t1218":     ["署名済みバイナリ悪用 (LOLBin)", "Microsoft 署名済みツール (rundll32, mshta 等) を悪用して防御を回避。"],
    "t1486":     ["データ暗号化 (ランサム)", "ファイルを暗号化して身代金を要求する。"],
    "t1490":     ["復元の阻害", "vssadmin delete shadows / wbadmin で復元手段を破壊。ランサム実行の直前。"],
    "t1543":     ["サービス/プロセス作成", "新しいサービスやプロセスを永続化目的で登録。"],
    "t1543.003": ["Windows サービス", "新規 Windows サービスとして malware を登録。再起動後も動き続ける。SYSTEM 権限になることも。"],
    "t1546":     ["イベントトリガ永続化", "WMI / イベントに紐づけて永続化。"],
    "t1546.003": ["WMI イベント購読", "__EventFilter + __EventConsumer の組合せでイベント発生時に自動実行。"],
    "t1547":     ["ブート/ログオン永続化", "Run キー、Startup フォルダ、スケジュールタスク等で起動時に実行。"],
    "t1547.001": ["Run キー / Startup", "HKLM/HKCU の Run キーや Startup フォルダにエントリ追加。"],
    "t1548":     ["UAC バイパス", "管理者承認を出さずに高権限プロセスを起動。"],
    "t1562":     ["防御機構の無効化", "セキュリティ製品・ログ・監査ポリシを止めて検知を逃れる。"],
    "t1562.001": ["セキュリティツールの停止", "Defender / EDR / Sysmon を停止・除外。"],
    "t1562.002": ["イベントログの無効化", "EventLog サービスを止めるか監査ポリシを下げる。"],
    "t1566":     ["フィッシング", "メール添付・リンクから初期侵入。"],
  };

  // 重要度の意味 + 推奨アクション。
  const SEVERITY_INFO = {
    critical:      { ja: "重大", desc: "実害が出ている / 出る寸前。即時調査と封じ込めが必要です。", urgency: "今すぐ確認" },
    high:          { ja: "高",   desc: "攻撃の強い兆候。本日中に確認してください。", urgency: "本日中" },
    medium:        { ja: "中",   desc: "怪しいが正規利用と区別しにくい場合あり。コンテキストで判断。", urgency: "週内に確認" },
    low:           { ja: "低",   desc: "補助情報。他の検知と組み合わせて意味を持つことが多い。", urgency: "コンテキストで参照" },
    informational: { ja: "情報", desc: "通常運用の記録。攻撃の前後関係を追うときに参照。", urgency: "ログとして保管" },
    info:          { ja: "情報", desc: "通常運用の記録。攻撃の前後関係を追うときに参照。", urgency: "ログとして保管" },
  };

  function attackBadge(tag) {
    // tag は "attack.t1543.003" 形式。先頭の "attack." を除いて lookup。
    const key = tag.toLowerCase().replace(/^attack\./, "");
    const info = ATTACK_INFO[key];
    const tNum = key.toUpperCase();
    const ja = info ? info[0] : "";
    const desc = info ? info[1] : "";
    const url = "https://attack.mitre.org/techniques/" + tNum.replace(".", "/") + "/";
    return `<a class="attack-tag" href="${url}" target="_blank" rel="noopener"
      title="${escapeHtml(desc || tNum)}">${tNum}${ja ? " · " + escapeHtml(ja) : ""}</a>`;
  }

  function suggestNextSteps(detail, ev) {
    const tags = (detail.attack_tags || []).map(t => t.toLowerCase());
    const steps = [];
    if (tags.some(t => t.startsWith("attack.t1003"))) {
      steps.push("lsass.exe にアクセスしたプロセスの **親系統** を Sysmon EID 1 / Security 4688 で確認。");
      steps.push("そのプロセスが **RDP / WMI / PsExec 経由で起動された** なら、横展開のシグナル。");
    }
    if (tags.some(t => t.startsWith("attack.t1543"))) {
      steps.push("登録されたサービスバイナリの **署名・SHA256** を確認 (LOLDrivers でないか)。");
      steps.push("**ImagePath が C:\\Users\\, C:\\Temp\\, %ProgramData%** ならほぼ確実に malicious。");
    }
    if (tags.some(t => t.startsWith("attack.t1059.001"))) {
      steps.push("PowerShell 4104 の **ScriptBlockText** を読み、難読化 / IEX / DownloadString を確認。");
      steps.push("**親プロセス** が explorer.exe (人手起動) か wscript.exe (添付ファイル経由) かで侵入経路が分かる。");
    }
    if (tags.some(t => t.startsWith("attack.t1070") || t.startsWith("attack.t1562"))) {
      steps.push("**直前** に動いたプロセスを優先確認。攻撃者は痕跡を消す前に本命の操作をしている。");
      steps.push("WEC / Sysmon 別チャネルに **同時刻のイベント** があれば、それが「消されなかった真実」。");
    }
    if (tags.some(t => t.startsWith("attack.t1490") || t.startsWith("attack.t1486"))) {
      steps.push("**ランサム実行直前** の可能性。直ちにネットワーク隔離を検討。");
      steps.push("同じホストで **大量のファイル変更 (Sysmon EID 11)** が出ていないか確認。");
    }
    if (tags.some(t => t.startsWith("attack.t1105") || t.startsWith("attack.t1218"))) {
      steps.push("外部通信先 (URL / IP) を確認。**Microsoft 系以外** なら C2 の可能性。");
      steps.push("ダウンロード後の **子プロセス** が何を実行したかを系統で追う。");
    }
    if (!steps.length) {
      steps.push("「結果」タブで **同じホストの ±5 分以内の他検知** を確認してコンテキストを掴む。");
      steps.push("ルールの **誤検知例 (falsepositives)** を確認し、業務での正規利用と一致しないか比較。");
    }
    return steps;
  }

  async function toggleExplain(row, ev) {
    // Toggle: if an explain row already follows this row, remove it.
    const next = row.nextElementSibling;
    if (next && next.classList.contains("explain-row")) {
      next.remove();
      return;
    }
    // Collapse any other open explain panel — keep the feed tidy.
    document.querySelectorAll(".explain-row").forEach(e => e.remove());

    const explain = document.createElement("div");
    explain.className = "explain-row";
    explain.innerHTML = `<div class="muted small" style="padding:10px">読込中…</div>`;
    row.parentNode.insertBefore(explain, row.nextSibling);

    const jobId = row.dataset.jobId;
    const lineNo = row.dataset.lineNo;
    let detail = null;
    try {
      const r = await fetch(`/api/detections/${jobId}/${lineNo}/detail`);
      detail = await r.json();
    } catch (e) {
      explain.innerHTML = `<div class="muted small" style="padding:10px;color:#ef5350">
        詳細取得に失敗しました: <code>${escapeHtml(String(e))}</code></div>`;
      return;
    }

    const lvl = (ev.Level || "info").toLowerCase();
    const sev = SEVERITY_INFO[lvl] || SEVERITY_INFO.info;
    const desc = detail?.rule?.description?.trim()
      || "(このルールには詳細な説明が登録されていません)";
    const attackHtml = (detail?.attack_tags?.length)
      ? detail.attack_tags.map(attackBadge).join(" ")
      : `<span class="muted small">ATT&CK タグ未指定</span>`;
    const steps = suggestNextSteps(detail || {}, ev);
    const fpHtml = (detail?.rule?.falsepositives?.length)
      ? "<ul>" + detail.rule.falsepositives.map(s => `<li>${escapeHtml(s)}</li>`).join("") + "</ul>"
      : `<span class="muted small">記載なし</span>`;
    const ruleFile = detail?.rule?.filename || "";
    const ruleId = detail?.detection?._rule_id || ev._rule_id || "";
    const ruleTitle = ev.RuleTitle || detail?.rule?.title || detail?.detection?.RuleTitle || "";

    explain.innerHTML = `
      <div class="explain-block">
        <div class="explain-grid">
          <div class="explain-col">
            <h4>なにを検知している?</h4>
            <p>${escapeHtml(desc)}</p>
            <h4>誤検知の例</h4>
            <div>${fpHtml}</div>
          </div>
          <div class="explain-col">
            <h4>重要度 — ${sev.ja} (${escapeHtml(lvl)})</h4>
            <p>${escapeHtml(sev.desc)} <span class="urgency">対応目安: ${escapeHtml(sev.urgency)}</span></p>
            <h4>ATT&amp;CK 技術</h4>
            <div class="attack-tags">${attackHtml}</div>
            <h4>次にすべきこと</h4>
            <ol>${steps.map(s => `<li>${s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")}</li>`).join("")}</ol>
          </div>
        </div>
        <div class="explain-log">
          <h4>📄 検知したログの中身 <span class="muted small">このルールに引っかかった実際のログ</span></h4>
          <div class="explain-log-meta muted small">
            チャネル: <code>${escapeHtml(ev.Channel || "—")}</code>
            &nbsp;・&nbsp; EventID: <b>${escapeHtml(String(ev.EventID != null ? ev.EventID : "—"))}</b>
            ${ev.RecordID != null ? `&nbsp;・&nbsp; RecordID: ${escapeHtml(String(ev.RecordID))}` : ""}
          </div>
          <div class="explain-log-details kv-lines"></div>
          ${ev.ExtraFieldInfo != null
            ? `<details class="explain-log-raw"><summary class="muted small">生イベントデータ (ExtraFieldInfo)</summary><div class="explain-log-extra kv-lines"></div></details>`
            : ""}
        </div>
        <div class="explain-foot muted small">
          ${ruleFile ? "ルールファイル: <code>" + escapeHtml(ruleFile) + "</code>" : ""}
          &nbsp; &nbsp;
          <a href="#" data-job="${jobId}" data-line="${lineNo}" class="open-in-results">結果タブで詳細を見る →</a>
        </div>
        ${ruleId ? `<div class="explain-admin is-admin-only">
          <button type="button" class="btn btn-ghost mark-safe-btn"
                  data-rule-id="${escapeHtml(ruleId)}" data-rule-title="${escapeHtml(ruleTitle)}">
            🛡 このルールを安全としてマーク（スコアから除外）
          </button>
          <span class="mark-safe-status muted small"></span>
          <div class="muted small" style="margin-top:4px">
            運営者だけに表示。無害と判断した検知をスコア計算から外します（検知一覧には残ります）。
          </div>
        </div>` : ""}
      </div>`;

    // 検知したログの中身を描画 (Hayabusa の Details / ExtraFieldInfo を再利用)。
    const logHost = explain.querySelector(".explain-log-details");
    if (logHost) {
      const has = renderDetailsString(logHost, ev.Details);
      if (!has) logHost.innerHTML = `<span class="muted small">（このログには追加の詳細フィールドがありません）</span>`;
    }
    const extraHost = explain.querySelector(".explain-log-extra");
    if (extraHost) renderDetailsString(extraHost, ev.ExtraFieldInfo);

    // Wire the "open in results tab" link to actually navigate + select.
    const link = explain.querySelector(".open-in-results");
    if (link) link.addEventListener("click", (e) => {
      e.preventDefault();
      const tabBtn = document.querySelector('.tab[data-tab="results"]');
      if (tabBtn) tabBtn.click();
      // Give the tab a tick to render, then open the job detail.
      setTimeout(() => openDetail(jobId), 80);
    });

    // 運営者向け「安全としてマーク」ボタン。ルール単位で抑制を登録し、
    // 全体ビューとランキングを再計算する。
    const safeBtn = explain.querySelector(".mark-safe-btn");
    if (safeBtn) safeBtn.addEventListener("click", () => markRuleSafe(safeBtn));
  }

  async function markRuleSafe(btn) {
    const ruleId = btn.dataset.ruleId;
    const title = btn.dataset.ruleTitle || ruleId;
    const status = btn.parentNode.querySelector(".mark-safe-status");
    if (!ruleId) return;
    if (!confirm(`「${title}」を安全なルールとして扱い、危険度スコアの計算から外します。\n`
        + "（検知一覧・全体ビューには引き続き表示されます。ルールタブの「安全リスト」からいつでも解除できます）\n\nよろしいですか？")) return;
    btn.disabled = true;
    if (status) status.textContent = "登録中…";
    try {
      const r = await fetch("/api/suppressions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rule_id: ruleId, computer: null,
          reason: `運営が安全と判断: ${title}`, created_by: "operator",
        }),
      });
      const res = await r.json();
      if (!r.ok || res.error) {
        if (status) status.textContent = "エラー: " + (res.error || r.status);
        btn.disabled = false;
        return;
      }
      if (status) status.textContent = "✓ 安全リストに追加しました。スコアを再計算しました。";
      btn.textContent = "✓ 安全としてマーク済み";
      // 全体ビュー・ランキング・安全リストを更新して即座に反映。
      if (document.getElementById("tab-dashboard")?.classList.contains("active")) loadDashboard();
      if (document.body.classList.contains("public-mode")) { loadRanking?.(); loadRankingStats?.(); }
      if (typeof loadSuppressions === "function") loadSuppressions();
    } catch (e) {
      if (status) status.textContent = "エラー: " + String(e);
      btn.disabled = false;
    }
  }

  // -------- jobs / results tab --------
  async function refreshJobs() {
    const r = await fetch("/api/jobs");
    const jobs = await r.json();
    const tb = $("#jobs-table tbody"); tb.innerHTML = "";
    if (!jobs.length) {
      tb.innerHTML = `<tr><td colspan="6">
        <div class="empty-state">
          <div class="icon">📋</div>
          <div class="title">まだスキャン結果がありません</div>
          まずはログを読み込んでスキャンしてみましょう。
          <div class="cta"><button class="primary" data-goto-tab="scan">🔍 スキャンへ進む</button></div>
        </div></td></tr>`;
      return;
    }
    const running = (s) => s === "running" || s === "queued";
    jobs.forEach(j => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td><code>${j.id}</code></td>
        <td class="status-${j.status}">${localizeStatus(j.status)}</td>
        <td>${fmtTime(j.started_at)}</td>
        <td>${fmtDur(j.started_at, j.finished_at)}</td>
        <td>${j.detection_count}</td>
        <td class="row-actions">
          <button class="open-btn" data-id="${j.id}">開く</button>
          <button class="del-btn" data-id="${j.id}" ${running(j.status) ? "disabled title='実行中は削除できません'" : ""}>削除</button>
        </td>`;
      tr.querySelector(".open-btn").onclick = (e) => { e.stopPropagation(); openDetail(j.id); };
      tr.querySelector(".del-btn").onclick = (e) => { e.stopPropagation(); deleteJob(j.id, j.detection_count); };
      tb.appendChild(tr);
    });
  }

  // 単一ジョブの削除。検知・結果ファイルごと消える。
  async function deleteJob(jobId, detCount) {
    if (!confirm(`ジョブ #${jobId} を削除しますか?\n` +
                 `この検知データ ${detCount} 件と結果ファイルが完全に消えます (元に戻せません)。`)) return;
    try {
      const r = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
      const d = await r.json();
      if (d.error) { alert("削除できませんでした: " + d.error); return; }
      // 開いている詳細がこのジョブなら閉じる
      if (currentDetection && currentDetection._job_id === jobId) {
        currentDetection = null;
        const dc = $("#detection-card"); if (dc) dc.hidden = true;
      }
      refreshJobs();
    } catch (e) { alert("通信エラー: " + e); }
  }

  // すべてのスキャン履歴を消去 (抑制ルールは残る)。
  async function clearAllJobs() {
    if (!confirm("すべてのスキャン結果を消去しますか?\n" +
                 "全ジョブ・全検知データ・結果ファイルが完全に消えます (元に戻せません)。\n" +
                 "※ 抑制ルールは残ります。")) return;
    try {
      const r = await fetch("/api/jobs/clear", { method: "POST" });
      const d = await r.json();
      if (d.error) { alert("消去できませんでした: " + d.error +
        (d.running ? `\n実行中: ${d.running.join(", ")}` : "")); return; }
      currentDetection = null;
      const dc = $("#detection-card"); if (dc) dc.hidden = true;
      refreshJobs();
    } catch (e) { alert("通信エラー: " + e); }
  }

  // Selected detection — set when the user clicks a row. Verdict buttons act on this.
  let currentDetection = null;

  const VERDICT_LABEL = { tp: "TP (本物)", fp: "FP (誤検知)", null: "未判定" };

  function verdictCellHtml(v) {
    if (v === "tp") return `<span class="verdict-cell tp">TP</span>`;
    if (v === "fp") return `<span class="verdict-cell fp">FP</span>`;
    return `<span class="verdict-cell none">—</span>`;
  }

  function setVerdictButtons(v) {
    $("#verdict-tp").classList.toggle("active", v === "tp");
    $("#verdict-fp").classList.toggle("active", v === "fp");
    $("#verdict-clear").classList.toggle("active", !v);
  }

  async function postVerdict(verdict) {
    if (!currentDetection) return;
    const { _job_id, _line_no } = currentDetection;
    if (!_job_id || _line_no == null) {
      alert("この検知は SQLite に未登録のためフィードバックできません。"); return;
    }
    const body = JSON.stringify({ verdict });
    const r = await fetch(`/api/detections/${_job_id}/${_line_no}/feedback`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body
    });
    const res = await r.json();
    if (res.error) { $("#verdict-status").textContent = "エラー: " + res.error; return; }
    currentDetection._verdict = verdict || null;
    setVerdictButtons(currentDetection._verdict);
    $("#verdict-status").textContent =
      `登録しました — このルール累計: TP ${res.tp} / FP ${res.fp}`;
    // Refresh the row in-place and the feedback summary
    const row = document.querySelector(
      `#detections-table tbody tr[data-line="${_line_no}"]`);
    if (row) row.querySelector(".verdict-cell-host").innerHTML = verdictCellHtml(currentDetection._verdict);
    if ($("#tab-rules").classList.contains("active")) loadFeedback();
  }

  $("#verdict-tp").onclick = () => postVerdict("tp");
  $("#verdict-fp").onclick = () => postVerdict("fp");
  $("#verdict-clear").onclick = () => postVerdict(null);

  const clearAllBtn = $("#clear-all-jobs");
  if (clearAllBtn) clearAllBtn.onclick = clearAllJobs;

  async function addSuppression(opts) {
    if (!currentDetection) return;
    const reason = prompt("抑制の理由 (省略可):", opts.defaultReason || "") || null;
    const body = {
      rule_id: opts.rule ? currentDetection._rule_id : null,
      computer: opts.host ? currentDetection.Computer : null,
      reason,
    };
    const r = await fetch("/api/suppressions", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const res = await r.json();
    if (res.error) { $("#suppress-status").textContent = "エラー: " + res.error; return; }
    $("#suppress-status").textContent = `抑制を登録しました (#${res.id})`;
    // Reload the detection list so newly-hidden rows disappear (or get
    // greyed out when "include suppressed" is on).
    if (lastJobId) openDetail(lastJobId);
    if ($("#tab-rules").classList.contains("active")) loadSuppressions();
  }

  $("#suppress-host-rule").onclick = () => addSuppression({ rule: true, host: true });
  $("#suppress-rule").onclick = () => addSuppression({ rule: true, host: false });
  $("#suppress-host").onclick = () => addSuppression({ rule: false, host: true });

  let lastJobId = null;

  // -------- detection detail (structured view) --------

  // Sub-tab routing inside the detail pane.
  document.addEventListener("click", (e) => {
    const t = e.target.closest(".subtab");
    if (!t) return;
    document.querySelectorAll(".subtab").forEach(x => x.classList.toggle("active", x === t));
    const id = "sub-" + t.dataset.sub;
    document.querySelectorAll(".subpanel").forEach(p => p.classList.toggle("active", p.id === id));
    // Lazy-load the process tree when its subtab is opened.
    if (t.dataset.sub === "ptree") loadProcessTree();
  });

  // Re-fetch the tree when the window-size dropdown changes.
  document.addEventListener("change", (e) => {
    if (e.target && e.target.id === "ptree-window") loadProcessTree();
  });

  let currentDetectionForTree = null;
  async function loadProcessTree() {
    if (!currentDetection) return;
    currentDetectionForTree = currentDetection;
    const host = $("#ptree-host");
    const summary = $("#ptree-summary");
    host.innerHTML = `<div class="ptree-empty">読込中…</div>`;
    summary.textContent = "";
    const win = $("#ptree-window")?.value || "10";
    try {
      const r = await fetch(`/api/detections/${currentDetection._job_id}/`
        + `${currentDetection._line_no}/process_tree?window=${win}`);
      const t = await r.json();
      // The user may have switched detections while we were waiting;
      // bail if so to avoid clobbering the new tree's render.
      if (currentDetectionForTree !== currentDetection) return;
      if (t.error) {
        host.innerHTML = `<div class="ptree-empty">エラー: ${escapeHtml(t.error)}</div>`;
        return;
      }
      summary.textContent = `${t.host} ・ 検出ノード ${t.nodes_seen}`
        + (t.truncated ? ` ・ 上限到達 (一部省略)` : "")
        + ` ・ キー: ${t.key_mode}`;
      if (!t.roots || !t.roots.length) {
        host.innerHTML = `<div class="ptree-empty">
          このホストの ±${win} 分以内に Sysmon EID 1 (プロセス作成) ログが
          見つかりませんでした。<br/>
          <span class="small">対象ホストで Sysmon が動いていないか、
          このスキャンに該当チャネルが含まれていない可能性があります。</span>
        </div>`;
        return;
      }
      host.innerHTML = "";
      const ul = document.createElement("ul");
      t.roots.forEach(n => ul.appendChild(renderPtreeNode(n)));
      host.appendChild(ul);
      // Scroll the focal node into view if any.
      const focal = host.querySelector(".pnode.focal");
      if (focal) focal.scrollIntoView({ block: "center", behavior: "smooth" });
    } catch (e) {
      host.innerHTML = `<div class="ptree-empty">取得に失敗しました: ${escapeHtml(String(e))}</div>`;
    }
  }

  function renderPtreeNode(n) {
    const li = document.createElement("li");
    const div = document.createElement("div");
    const imgName = (n.image || "").split("\\").pop() || "(unknown)";
    const lvl = n.detection?.level || "";
    const cls = ["pnode"];
    if (n.is_focal) cls.push("focal");
    if (n.detection) { cls.push("has-detection"); if (lvl) cls.push("lvl-" + lvl); }
    div.className = cls.join(" ");
    const detBadge = n.detection
      ? `<span class="lvl lvl-${lvl}">${lvl.slice(0,4)}</span>
         <span class="muted" style="display:block;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(n.detection.rule_title || "")}</span>`
      : "";
    div.innerHTML = `
      <div class="pname">
        <span class="img">${escapeHtml(imgName)}</span>
        <span class="muted">  pid=${escapeHtml(n.pid || "")}</span>
        <span class="cmd" title="${escapeHtml(n.cmdline || "")}">${escapeHtml(n.cmdline || "")}</span>
      </div>
      <div class="pmeta">${escapeHtml(n.user || "")}${n.integrity ? "  ·  " + escapeHtml(n.integrity) : ""}
        <br/><span style="color:var(--muted)">${escapeHtml((n.ts || "").slice(0, 19))}</span></div>
      <div class="pdet">${detBadge}</div>`;
    if (n.detection) {
      div.style.cursor = "pointer";
      div.addEventListener("click", (ev) => {
        ev.stopPropagation();
        // Pivot to this process's own detection without leaving the tab.
        fetch(`/api/detections/${n.detection.job_id}/${n.detection.line_no}/detail`)
          .then(r => r.json()).then(d => { if (d.detection) renderDetail(d.detection); });
      });
    }
    li.appendChild(div);
    if (n.children && n.children.length) {
      const ul = document.createElement("ul");
      n.children.forEach(c => ul.appendChild(renderPtreeNode(c)));
      li.appendChild(ul);
    }
    return li;
  }

  // Hayabusa's "Details" field is a free-text string that nevertheless
  // tends to contain k: v ¦ k: v segments. This makes it readable as a
  // table. Fields like "ExtraFieldInfo" are nested dicts that we render
  // recursively as a definition list.
  function renderDetailsString(host, val) {
    host.innerHTML = "";
    if (val == null) return false;
    if (typeof val !== "string") {
      host.textContent = JSON.stringify(val, null, 2);
      return true;
    }
    // Split on the unicode broken-bar that Hayabusa uses as a field
    // separator inside the Details field. Fall back to newline split.
    const sep = val.includes("¦") ? "¦" : (val.includes("\n") ? "\n" : null);
    if (!sep) { host.textContent = val; return !!val; }
    val.split(sep).map(s => s.trim()).filter(Boolean).forEach(seg => {
      const m = seg.match(/^([^:]{1,40}):\s*(.*)$/s);
      const line = document.createElement("div");
      if (m) {
        line.innerHTML = `<span class="muted small">${m[1]}: </span>${escapeHtml(m[2])}`;
      } else {
        line.textContent = seg;
      }
      host.appendChild(line);
    });
    return true;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }

  function kvPair(label, value, mono = false) {
    const cell = document.createElement("div");
    const cls = mono ? "v mono" : "v";
    cell.innerHTML = `<label>${escapeHtml(label)}</label>
      <div class="${cls}">${value == null || value === ""
        ? '<span class="muted small">—</span>'
        : escapeHtml(String(value))}</div>`;
    return cell;
  }

  async function renderDetail(ev) {
    // Header — title, level chip, attack tags.
    const lvl = (ev.Level || "info").toLowerCase();
    $("#dt-level").className = "lvl lvl-" + lvl;
    $("#dt-level").textContent = lvl;
    $("#dt-title").textContent = ev.RuleTitle || ev.Title || "(タイトル無し)";
    $("#dt-meta").textContent = `#${ev._job_id} / line ${ev._line_no}`;

    // Overview tab — the high-signal fields in a compact grid.
    const kv = $("#dt-kv"); kv.innerHTML = "";
    kv.appendChild(kvPair("時刻", ev.Timestamp));
    kv.appendChild(kvPair("コンピュータ", ev.Computer));
    kv.appendChild(kvPair("チャネル", ev.Channel, true));
    kv.appendChild(kvPair("EventID", ev.EventID));
    kv.appendChild(kvPair("RecordID", ev.RecordID));
    kv.appendChild(kvPair("RuleID", ev._rule_id, true));

    // Details / ExtraFieldInfo (when present).
    const hasDetails = renderDetailsString($("#dt-details"), ev.Details);
    $("#dt-details-card").hidden = !hasDetails;
    const hasExtra = renderDetailsString($("#dt-extra"), ev.ExtraFieldInfo);
    $("#dt-extra-card").hidden = !hasExtra;

    // Raw JSON — strip injected meta fields starting with _.
    const display = Object.fromEntries(
      Object.entries(ev).filter(([k]) => !k.startsWith("_")));
    $("#detail-pane").textContent = JSON.stringify(display, null, 2);

    // Reset placeholder content for async-loaded tabs so a fast clicker
    // doesn't see stale data from the previous detection.
    $("#dt-attack").innerHTML = "";
    $("#dt-rule-card").hidden = true;
    $("#dt-rule-empty").hidden = true;
    $("#related-table tbody").innerHTML =
      `<tr><td colspan="5" class="muted small">読込中…</td></tr>`;
    $("#history-table tbody").innerHTML =
      `<tr><td colspan="5" class="muted small">読込中…</td></tr>`;
    $("#dt-related-cnt").textContent = "";
    $("#dt-hist-cnt").textContent = "";

    // Asynchronously fetch enriched detail.
    try {
      const r = await fetch(`/api/detections/${ev._job_id}/${ev._line_no}/detail`);
      const d = await r.json();

      // ATT&CK tags as small chips.
      d.attack_tags.forEach(t => {
        const chip = document.createElement("span");
        chip.className = "attack-tag";
        chip.textContent = t.replace(/^attack\./, "");
        $("#dt-attack").appendChild(chip);
      });

      // Rule tab.
      if (d.rule) {
        $("#dt-rule-empty").hidden = true;
        $("#dt-rule-card").hidden = false;
        $("#dtr-title").textContent = d.rule.title || "—";
        $("#dtr-id").textContent = d.rule.id || ev._rule_id || "—";
        $("#dtr-level").textContent = d.rule.level || "—";
        $("#dtr-file").textContent = d.rule.filename || "";
        $("#dtr-desc").textContent = d.rule.description || "(説明なし)";
        const fp = $("#dtr-fp"); fp.innerHTML = "";
        (d.rule.falsepositives || []).forEach(s => {
          const li = document.createElement("li"); li.textContent = s; fp.appendChild(li);
        });
        if (!fp.children.length) fp.innerHTML = `<li class="muted small">記載なし</li>`;
        const refs = $("#dtr-refs"); refs.innerHTML = "";
        (d.rule.references || []).forEach(s => {
          const li = document.createElement("li");
          if (/^https?:\/\//.test(s)) {
            li.innerHTML = `<a href="${escapeHtml(s)}" target="_blank" rel="noopener">${escapeHtml(s)}</a>`;
          } else { li.textContent = s; }
          refs.appendChild(li);
        });
        if (!refs.children.length) refs.innerHTML = `<li class="muted small">記載なし</li>`;
        $("#dtr-yaml").textContent = d.rule.raw_yaml || "";
      } else {
        $("#dt-rule-empty").hidden = false;
        $("#dt-rule-card").hidden = true;
      }

      // Related table.
      const rt = $("#related-table tbody"); rt.innerHTML = "";
      $("#dt-related-cnt").textContent = `(${d.related.length})`;
      if (!d.related.length) {
        rt.innerHTML = `<tr><td colspan="5" class="muted small">±5分以内に他の検知はありません。</td></tr>`;
      } else {
        d.related.forEach(r2 => {
          const tr = document.createElement("tr");
          const l = (r2.level || "info").toLowerCase();
          tr.innerHTML = `<td>${r2.ts || ""}</td>
            <td><span class="lvl lvl-${l}">${l.slice(0,4)}</span></td>
            <td>${escapeHtml(r2.rule_title || "")}</td>
            <td>${escapeHtml(r2.channel || "")}</td>
            <td>${r2.event_id || ""}</td>`;
          tr.onclick = () => {
            // Pivot: re-open the host job's detail with this detection
            // selected. We approximate that by fetching the row.
            currentDetection = null;
            fetch(`/api/detections/${r2.job_id}/${r2.line_no}/detail`)
              .then(r => r.json()).then(d2 => {
                if (d2.detection) renderDetail(d2.detection);
              });
          };
          rt.appendChild(tr);
        });
      }

      // History (other fires of the same rule).
      const ht = $("#history-table tbody"); ht.innerHTML = "";
      $("#dt-hist-cnt").textContent = `(${d.rule_history.total})`;
      const sample = d.rule_history.sample || [];
      if (!sample.length) {
        ht.innerHTML = `<tr><td colspan="5" class="muted small">他に発火例はありません。</td></tr>`;
      } else {
        sample.forEach(r2 => {
          const tr = document.createElement("tr");
          const l = (r2.level || "info").toLowerCase();
          tr.innerHTML = `<td>${r2.ts || ""}</td>
            <td><span class="lvl lvl-${l}">${l.slice(0,4)}</span></td>
            <td>${escapeHtml(r2.computer || "")}</td>
            <td>${escapeHtml(r2.channel || "")}</td>
            <td>${r2.event_id || ""}</td>`;
          tr.onclick = () => {
            fetch(`/api/detections/${r2.job_id}/${r2.line_no}/detail`)
              .then(r => r.json()).then(d2 => {
                if (d2.detection) renderDetail(d2.detection);
              });
          };
          ht.appendChild(tr);
        });
      }
    } catch (e) {
      console.error("detail fetch failed", e);
    }
  }

  async function openDetail(id) {
    lastJobId = id;
    $("#detection-card").hidden = false;
    $("#detail-jobid").textContent = "#" + id;
    $("#detail-wrap").hidden = true;
    currentDetection = null;

    const filterText = $("#filter-text"); const filterLevel = $("#filter-level");
    const showSuppressed = $("#filter-show-suppressed");
    let cache = [];

    async function load() {
      const qs = new URLSearchParams({ offset: "0", limit: "500" });
      if (filterLevel.value) qs.set("level", filterLevel.value);
      if (filterText.value.trim()) qs.set("q", filterText.value.trim());
      if (showSuppressed.checked) qs.set("include_suppressed", "1");
      const r = await fetch(`/api/jobs/${id}?${qs}`);
      const d = await r.json();
      cache = d;
      render();
      $("#summary-btn").onclick = () => {
        if (d.summary_available) window.open(`/api/jobs/${id}/summary`, "_blank");
        else alert("このジョブにはまだ HTML サマリがありません。");
      };
    }

    function render() {
      const tb = $("#detections-table tbody"); tb.innerHTML = "";
      cache.detections.forEach(ev => {
        const lvl = (ev.Level || "info").toLowerCase();
        const tr = document.createElement("tr");
        tr.dataset.line = ev._line_no;
        if (ev._suppressed) tr.classList.add("suppressed");
        const supTag = ev._suppressed ? ` <span class="muted small">[抑制]</span>` : "";
        tr.innerHTML = `<td>${ev.Timestamp || ""}</td>
          <td><span class="lvl lvl-${lvl}">${lvl.slice(0,4)}</span></td>
          <td>${ev.RuleTitle || ev.Title || ""}${supTag}</td>
          <td>${ev.Computer || ""}</td>
          <td>${ev.Channel || ""}</td>
          <td>${ev.EventID || ""}</td>
          <td class="verdict-cell-host">${verdictCellHtml(ev._verdict)}</td>`;
        tr.onclick = () => {
          currentDetection = ev;
          $("#detail-wrap").hidden = false;
          $("#verdict-status").textContent = "現在の判定: " + (VERDICT_LABEL[ev._verdict] || "未判定");
          $("#suppress-status").textContent = ev._suppressed
            ? "この検知は抑制されています: " + (ev._suppression_reason || "(理由なし)")
            : "";
          setVerdictButtons(ev._verdict);
          renderDetail(ev);
        };
        tb.appendChild(tr);
      });
    }
    filterText.oninput = load; filterLevel.onchange = load;
    showSuppressed.onchange = load;
    await load();
  }

  // -------- suppressions table (rules tab) --------
  async function loadSuppressions() {
    try {
      const r = await fetch("/api/suppressions");
      const rows = await r.json();
      const tb = $("#suppressions-table tbody"); tb.innerHTML = "";
      if (!rows.length) {
        tb.innerHTML = `<tr><td colspan="7" class="muted small">抑制ルールはまだ登録されていません。検知詳細から「抑制」ボタンで登録できます。</td></tr>`;
        return;
      }
      rows.forEach(row => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${row.id}</td>
          <td><code>${row.scope}</code></td>
          <td>${row.rule_id ? `<code>${row.rule_id}</code>` : "—"}</td>
          <td>${row.computer ? `<code>${row.computer}</code>` : "—"}</td>
          <td>${row.reason || ""}</td>
          <td>${fmtTime(row.created_at)}</td>
          <td><button data-id="${row.id}">解除</button></td>`;
        tr.querySelector("button").onclick = async () => {
          if (!confirm("この抑制を解除しますか?")) return;
          await fetch(`/api/suppressions/${row.id}`, { method: "DELETE" });
          loadSuppressions();
          if (lastJobId) openDetail(lastJobId);
        };
        tb.appendChild(tr);
      });
    } catch { /* ignore */ }
  }

  // -------- rule feedback (rules tab) --------
  async function loadFeedback() {
    try {
      const r = await fetch("/api/rule_feedback");
      const rows = await r.json();
      const tb = $("#feedback-table tbody"); tb.innerHTML = "";
      if (!rows.length) {
        tb.innerHTML = `<tr><td colspan="6" class="muted small">まだフィードバックがありません。検知をクリックして TP / FP を登録してください。</td></tr>`;
        return;
      }
      rows.forEach(row => {
        const tot = row.tp_count + row.fp_count;
        const rate = tot ? ((row.fp_count / tot) * 100).toFixed(1) + "%" : "—";
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${row.rule_title || ""}</td>
          <td><code>${row.rule_id}</code></td>
          <td>${row.tp_count}</td>
          <td>${row.fp_count}</td>
          <td>${rate}</td>
          <td>${row.last_at ? fmtTime(row.last_at) : ""}</td>`;
        tb.appendChild(tr);
      });
    } catch { /* ignore */ }
  }

  // -------- rules tab --------
  async function loadRules() {
    const r = await fetch("/api/rules");
    const d = await r.json();
    $("#rules-summary").textContent = `${d.total} 件のルールを読み込み済み`;
    const lvl = $("#rules-levels"); lvl.innerHTML = "";
    Object.entries(d.by_level).sort((a,b) => b[1]-a[1]).forEach(([k,v]) => {
      const c = document.createElement("span"); c.className = "chip";
      c.innerHTML = `<b>${v}</b>${k}`; lvl.appendChild(c);
    });
    const cats = $("#rules-cats"); cats.innerHTML = "";
    Object.entries(d.by_category).sort((a,b) => b[1]-a[1]).slice(0,40).forEach(([k,v]) => {
      const c = document.createElement("span"); c.className = "chip";
      c.innerHTML = `<b>${v}</b>${k}`; cats.appendChild(c);
    });
  }

  // -------- lookup tables (rules tab) --------
  async function loadLookups() {
    try {
      const r = await fetch("/api/lookups");
      const d = await r.json();
      const tb = $("#lookups-table tbody"); tb.innerHTML = "";
      if (!d.lookups.length) {
        tb.innerHTML = `<tr><td colspan="5" class="muted small">
          lookups/ ディレクトリに表が見つかりません。<code>name.txt</code>
          形式のファイルを置き、ルールから <code>lookup:</code> ブロックで
          参照してください。</td></tr>`;
        return;
      }
      d.lookups.forEach(it => {
        const tr = document.createElement("tr");
        const refs = it.referenced_by && it.referenced_by.length
          ? it.referenced_by.length + " 件"
          : `<span class="muted small">参照なし</span>`;
        // Feed metadata column: when the lookup is fed by feeds.yml, show
        // last-fetch timestamp; otherwise show '—' (e.g. for the manually
        // curated sample files).
        let feedCell = `<span class="muted small">手動管理</span>`;
        if (it.feed_meta) {
          const at = it.feed_meta.fetched_at;
          const when = at ? new Date(at * 1000).toLocaleString("ja-JP") : "?";
          if (it.feed_meta.error) {
            feedCell = `<span class="feed-error" title="${escapeHtml(it.feed_meta.error)}">⚠ ${escapeHtml(it.feed_meta.error.slice(0, 30))}</span><br/>
              <span class="feed-fetch-time">${when}</span>`;
          } else {
            feedCell = `<span class="feed-ok">✓ ${it.feed_meta.entries} 件</span><br/>
              <span class="feed-fetch-time">${when}</span>`;
          }
        }
        tr.innerHTML = `<td><code>${it.name}</code></td>
          <td class="mono"><span title="${it.rel}">${it.filename}</span></td>
          <td>${it.entries.toLocaleString()}</td>
          <td>${feedCell}</td>
          <td>${refs}</td>`;
        if (it.referenced_by && it.referenced_by.length) {
          tr.title = "参照しているルール:\n" + it.referenced_by.join("\n");
        }
        tb.appendChild(tr);
      });
    } catch { /* ignore */ }
  }

  // Wire the "フィードを更新" button. Hits the server's refresh endpoint
  // which forwards to feed_fetcher.fetch_all() synchronously. For huge
  // feeds (URLhaus is ~4 MB / 78k entries) this can take a few seconds —
  // we disable the button and show progress text.
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("#refresh-feeds-btn");
    if (!btn) return;
    const status = $("#refresh-feeds-status");
    btn.disabled = true;
    btn.textContent = "取得中…";
    status.textContent = "全フィードを順次取得しています…";
    try {
      const r = await fetch("/api/lookups/refresh", { method: "POST" });
      const d = await r.json();
      if (d.error) {
        status.innerHTML = `<span class="feed-error">エラー: ${escapeHtml(d.error)}</span>`;
      } else {
        const ok = d.ok || 0, fail = d.fail || 0;
        const detail = (d.results || []).map(r => {
          if (r.error) return `${r.name || r.output}: ✗ ${r.error}`;
          return `${r.name || r.output}: ${r.entries} 件 (${r.elapsed_sec}s)`;
        }).join(" / ");
        status.innerHTML = `<span class="feed-ok">完了: ${ok} 成功 / ${fail} 失敗</span> ・ <span class="muted small">${escapeHtml(detail)}</span>`;
      }
      // Re-render with new metadata.
      loadLookups();
    } catch (e) {
      status.innerHTML = `<span class="feed-error">通信エラー: ${escapeHtml(String(e))}</span>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "フィードを更新";
    }
  });

  // -------- ハント (threat hunting) --------
  // We split this out of the dashboard / results paths because the
  // mental model is genuinely different: results = one job at a time,
  // dashboard = aggregate trends, hunt = arbitrary cross-job queries.

  // Quick-hypothesis presets. Each preset returns the same shape as the
  // form, so applying a preset = filling form fields + running the search.
  const HUNT_PRESETS = {
    recent_crit: {
      label: "直近 24h の重大",
      apply: (f) => { f.window = "24h"; f.levels = ["critical", "high"]; }
    },
    anti_forensic: {
      label: "痕跡隠蔽行為",
      // We can't filter on ATT&CK tag directly without a rule index join,
      // so we approximate via free-text against rule_title.
      apply: (f) => { f.q = "clear|wevtutil|vssadmin|shadow|policy|EventLog|Audit"; }
    },
    lsass: {
      label: "認証情報窃取",
      apply: (f) => { f.q = "lsass|comsvcs|MiniDump|Credential|Mimikatz"; }
    },
    persistence: {
      label: "永続化",
      apply: (f) => { f.q = "Service|WMI|EventConsumer|Run|Startup|Scheduled"; }
    },
    cross_host: {
      label: "横展開兆候 (同一ルールが複数ホスト)",
      apply: (f) => { f.view = "by_rule"; /* the pivot view answers this directly */ }
    },
    noisy: {
      label: "最多発火ルール",
      apply: (f) => { f.view = "by_rule"; }
    },
  };

  let huntInitialised = false;
  let huntState = {  // current form state
    host: "", window: "", from: "", to: "",
    levels: [], channel: "", eid: "", q: "", verdict: "",
    include_suppressed: false,
    view: "list",
  };

  async function initHunt() {
    if (!huntInitialised) {
      try {
        const r = await fetch("/api/hunt/facets");
        const facets = await r.json();
        // Populate the channel dropdown.
        const sel = $("#hunt-channel"); sel.innerHTML = '<option value="">(指定なし)</option>';
        facets.channels.forEach(c => {
          const o = document.createElement("option");
          o.value = c.name; o.textContent = `${c.name} (${c.count})`;
          sel.appendChild(o);
        });
        // Build the level chip group.
        const lvlHost = $("#hunt-levels"); lvlHost.innerHTML = "";
        ["critical", "high", "medium", "low", "informational"].forEach(lv => {
          const b = document.createElement("button");
          b.type = "button";
          b.className = `chip-btn lvl-${lv}`;
          b.dataset.level = lv;
          b.textContent = lv;
          b.onclick = () => {
            b.classList.toggle("active");
          };
          lvlHost.appendChild(b);
        });
      } catch (e) { console.error("[hunt] facets fetch failed:", e); }
      wireHunt();
      renderSavedHunts();
      huntInitialised = true;
    }
    runHunt();  // show initial result (all detections, recent first)
  }

  function wireHunt() {
    $("#hunt-run").onclick = () => runHunt();
    $("#hunt-reset").onclick = () => resetHuntForm();
    $("#hunt-save").onclick = () => saveCurrentHunt();
    $("#hunt-export").onclick = () => exportHuntCSV();
    $("#hunt-window").onchange = () => {
      $("#hunt-custom-range").hidden = $("#hunt-window").value !== "custom";
    };
    // Preset buttons.
    document.querySelectorAll(".hunt-presets .preset-btn").forEach(btn => {
      btn.onclick = () => {
        resetHuntForm();
        const preset = HUNT_PRESETS[btn.dataset.hunt];
        if (!preset) return;
        const f = {};
        preset.apply(f);
        // Apply to form
        if (f.window) $("#hunt-window").value = f.window;
        if (f.q) $("#hunt-q").value = f.q;
        if (f.levels) {
          document.querySelectorAll("#hunt-levels .chip-btn").forEach(c => {
            c.classList.toggle("active", f.levels.includes(c.dataset.level));
          });
        }
        if (f.view) {
          document.querySelectorAll(".hunt-tab").forEach(t => {
            t.classList.toggle("active", t.dataset.view === f.view);
          });
          huntState.view = f.view;
        }
        runHunt();
      };
    });
    // View tabs
    document.querySelectorAll(".hunt-tab").forEach(t => {
      t.onclick = () => {
        document.querySelectorAll(".hunt-tab").forEach(x => x.classList.toggle("active", x === t));
        huntState.view = t.dataset.view;
        renderHuntView();
      };
    });
  }

  function resetHuntForm() {
    $("#hunt-host").value = "";
    $("#hunt-window").value = "";
    $("#hunt-from").value = ""; $("#hunt-to").value = "";
    $("#hunt-custom-range").hidden = true;
    $("#hunt-channel").value = "";
    $("#hunt-eid").value = "";
    $("#hunt-q").value = "";
    $("#hunt-verdict").value = "";
    $("#hunt-include-suppressed").checked = false;
    document.querySelectorAll("#hunt-levels .chip-btn").forEach(c => c.classList.remove("active"));
  }

  // Translate the form into URL search params + the current view.
  function buildHuntParams() {
    const params = new URLSearchParams();
    const host = $("#hunt-host").value.trim();
    if (host) params.set("host", host);

    const window = $("#hunt-window").value;
    const now = new Date();
    if (window && window !== "custom") {
      const ms = { "1h": 3.6e6, "24h": 8.64e7, "7d": 6.048e8, "30d": 2.592e9 }[window];
      if (ms) {
        params.set("from", new Date(now.getTime() - ms).toISOString());
      }
    } else if (window === "custom") {
      if ($("#hunt-from").value) params.set("from", $("#hunt-from").value);
      if ($("#hunt-to").value)   params.set("to",   $("#hunt-to").value);
    }

    document.querySelectorAll("#hunt-levels .chip-btn.active").forEach(c => {
      params.append("level", c.dataset.level);
    });
    const ch = $("#hunt-channel").value; if (ch) params.set("channel", ch);
    const eid = $("#hunt-eid").value.trim(); if (eid) params.set("eid", eid);
    const q = $("#hunt-q").value.trim(); if (q) params.set("q", q);
    const v = $("#hunt-verdict").value; if (v) params.set("verdict", v);
    if ($("#hunt-include-suppressed").checked) params.set("include_suppressed", "1");
    return params;
  }

  // Captured at the top so renderHuntView can re-render without re-fetching
  // when the user just switches tabs (one fetch per filter change).
  let huntLastSearch = null;
  let huntLastPivots = {};

  async function runHunt() {
    const params = buildHuntParams();
    const url = "/api/hunt/search?" + params + "&limit=500";
    $("#hunt-total").textContent = "…";
    $("#hunt-summary").textContent = "検索中";
    try {
      const r = await fetch(url);
      const d = await r.json();
      huntLastSearch = d;
      huntLastPivots = {};  // invalidate pivot cache
      $("#hunt-total").textContent = d.total.toLocaleString();
      const filt = [];
      if (params.get("host")) filt.push(`host=${params.get("host")}`);
      if (params.getAll("level").length) filt.push(`level=${params.getAll("level").join(",")}`);
      if (params.get("channel")) filt.push(`channel=${params.get("channel")}`);
      if (params.get("eid")) filt.push(`eid=${params.get("eid")}`);
      if (params.get("q")) filt.push(`q="${params.get("q")}"`);
      if (params.get("from")) filt.push(`from=${params.get("from").slice(0, 16)}`);
      $("#hunt-summary").textContent = filt.length
        ? "件 (" + filt.join(", ") + ")"
        : "件 (条件指定なし)";
      renderHuntView();
    } catch (e) {
      $("#hunt-total").textContent = "—";
      $("#hunt-summary").textContent = "検索エラー: " + e;
    }
  }

  async function renderHuntView() {
    const view = huntState.view;
    const host = $("#hunt-view");
    if (view === "list") return renderHuntList(host);
    // Pivot views — fetch once per filter set + dim.
    const dimMap = { by_rule: "rule_id", by_host: "computer",
                     by_hour: "hour", by_level: "level" };
    const dim = dimMap[view];
    if (!dim) return;
    if (!huntLastPivots[dim]) {
      const params = buildHuntParams();
      const r = await fetch(`/api/hunt/pivot?dim=${dim}&limit=200&` + params);
      huntLastPivots[dim] = await r.json();
    }
    renderHuntPivot(host, dim, huntLastPivots[dim]);
  }

  function renderHuntList(host) {
    if (!huntLastSearch || !huntLastSearch.detections.length) {
      // 検知データ自体が 0 件なのか、条件に合わないだけなのかで案内を変える
      const noDataAtAll = huntLastSearch && huntLastSearch.total === 0
        && !$("#hunt-host").value && !$("#hunt-q").value
        && !document.querySelector("#hunt-levels .chip-btn.active");
      if (noDataAtAll) {
        host.innerHTML = `<div class="empty-state">
          <div class="icon">🔎</div>
          <div class="title">まださがせるデータがありません</div>
          スキャンを実行すると、ここから過去の結果を自由にさがせます。
          <div class="cta"><button class="primary" data-goto-tab="scan">🔍 スキャンへ進む</button></div>
        </div>`;
      } else {
        host.innerHTML = `<div class="empty-state">
          <div class="icon">🔍</div>
          <div class="title">条件に合う項目がありませんでした</div>
          条件をゆるめるか、左の「リセット」を押してやり直してください。
        </div>`;
      }
      return;
    }
    const rows = huntLastSearch.detections;
    let html = `<table><thead><tr>
      <th>時刻</th><th>レベル</th><th>ルール</th><th>ホスト</th>
      <th>チャネル</th><th>EID</th><th>判定</th></tr></thead><tbody>`;
    rows.forEach(ev => {
      const lvl = (ev.Level || "info").toLowerCase();
      html += `<tr data-job="${escapeHtml(ev._job_id)}" data-line="${ev._line_no}">
        <td class="muted-cell">${escapeHtml(ev.Timestamp || "")}</td>
        <td><span class="lvl lvl-${lvl}">${lvl.slice(0,4)}</span></td>
        <td>${escapeHtml(ev.RuleTitle || "")}</td>
        <td>${escapeHtml(ev.Computer || "")}</td>
        <td class="muted-cell">${escapeHtml(ev.Channel || "")}</td>
        <td>${ev.EventID || ""}</td>
        <td>${verdictCellHtml(ev._verdict)}</td>
      </tr>`;
    });
    html += "</tbody></table>";
    if (rows.length < huntLastSearch.total) {
      html += `<div class="muted small" style="padding:8px">
        全 ${huntLastSearch.total.toLocaleString()} 件中、表示は ${rows.length} 件まで。
        条件を絞るか CSV 出力で全件を取り出してください。</div>`;
    }
    host.innerHTML = html;
    host.querySelectorAll("tbody tr").forEach(tr => {
      tr.onclick = () => {
        const tabBtn = document.querySelector('.tab[data-tab="results"]');
        if (tabBtn) tabBtn.click();
        setTimeout(() => openDetail(tr.dataset.job), 80);
      };
    });
  }

  function renderHuntPivot(host, dim, data) {
    if (!data || !data.rows || !data.rows.length) {
      host.innerHTML = `<div class="muted small" style="padding:14px">
        集計するデータがありません。</div>`;
      return;
    }
    const label = { rule_id: "ルール (RuleID)", computer: "ホスト",
                    hour: "時間 (1時間粒度)", level: "重要度" }[dim];
    const max = Math.max(...data.rows.map(r => r.n));
    let html = `<table><thead><tr>
      <th>${label}</th><th style="text-align:right">件数</th>
      <th>分布</th><th style="text-align:right">crit/high</th>
      </tr></thead><tbody>`;
    data.rows.forEach(r => {
      const pct = (r.n / max * 100).toFixed(1);
      const key = (dim === "rule_id")
        ? `<div>${escapeHtml(r.sample_title || "")}</div>
           <div class="muted-cell" style="font-size:10.5px"><code>${escapeHtml(r.k || "")}</code></div>`
        : `<code>${escapeHtml(r.k || "(空)")}</code>`;
      html += `<tr>
        <td>${key}</td>
        <td style="text-align:right;font-variant-numeric:tabular-nums">${r.n.toLocaleString()}</td>
        <td><div class="bar lvl-default" style="width:100%;height:10px;background:#1a1f2c;border-radius:3px;overflow:hidden">
          <div style="width:${pct}%;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent-2))"></div>
        </div></td>
        <td style="text-align:right;color:var(--high)">${r.sev_count || 0}</td>
      </tr>`;
    });
    html += "</tbody></table>";
    host.innerHTML = html;
  }

  // --- saved searches (localStorage) ---
  function loadSavedHunts() {
    try { return JSON.parse(localStorage.getItem("hayabusa_hunts") || "[]"); }
    catch { return []; }
  }
  function persistSavedHunts(list) {
    localStorage.setItem("hayabusa_hunts", JSON.stringify(list));
  }
  function saveCurrentHunt() {
    const name = prompt("この検索の名前を付けてください:", "");
    if (!name) return;
    const list = loadSavedHunts();
    list.push({
      name,
      params: buildHuntParams().toString(),
      view: huntState.view,
      at: Date.now(),
    });
    persistSavedHunts(list);
    renderSavedHunts();
  }
  function renderSavedHunts() {
    const host = $("#hunt-saved");
    const list = loadSavedHunts();
    if (!list.length) {
      host.innerHTML = `<span class="muted small">(まだありません)</span>`;
      return;
    }
    host.innerHTML = list.map((h, i) => `
      <div class="saved-row">
        <a class="name" data-i="${i}">${escapeHtml(h.name)}</a>
        <button class="del" data-i="${i}" title="削除">×</button>
      </div>
    `).join("");
    host.querySelectorAll("a.name").forEach(a => {
      a.onclick = (e) => {
        e.preventDefault();
        const h = loadSavedHunts()[a.dataset.i];
        applyHuntParams(new URLSearchParams(h.params));
        huntState.view = h.view || "list";
        document.querySelectorAll(".hunt-tab").forEach(t =>
          t.classList.toggle("active", t.dataset.view === huntState.view));
        runHunt();
      };
    });
    host.querySelectorAll("button.del").forEach(b => {
      b.onclick = () => {
        const list = loadSavedHunts();
        list.splice(b.dataset.i, 1);
        persistSavedHunts(list);
        renderSavedHunts();
      };
    });
  }
  function applyHuntParams(params) {
    resetHuntForm();
    if (params.get("host")) $("#hunt-host").value = params.get("host");
    if (params.get("channel")) $("#hunt-channel").value = params.get("channel");
    if (params.get("eid")) $("#hunt-eid").value = params.get("eid");
    if (params.get("q")) $("#hunt-q").value = params.get("q");
    if (params.get("verdict")) $("#hunt-verdict").value = params.get("verdict");
    if (params.get("include_suppressed") === "1") $("#hunt-include-suppressed").checked = true;
    const levels = params.getAll("level");
    document.querySelectorAll("#hunt-levels .chip-btn").forEach(c => {
      c.classList.toggle("active", levels.includes(c.dataset.level));
    });
    if (params.get("from") || params.get("to")) {
      $("#hunt-window").value = "custom";
      $("#hunt-custom-range").hidden = false;
      if (params.get("from")) $("#hunt-from").value = params.get("from");
      if (params.get("to"))   $("#hunt-to").value = params.get("to");
    }
  }

  function exportHuntCSV() {
    const params = buildHuntParams();
    // Trigger browser download by navigating to the export URL.
    const url = "/api/hunt/export?" + params + "&limit=50000";
    window.location.href = url;
  }

  // -------- dashboard --------
  async function populateJobSelector() {
    const sel = $("#dash-job");
    const r = await fetch("/api/jobs");
    const jobs = await r.json();
    const current = sel.value;
    sel.innerHTML = `<option value="">(全ジョブ)</option>`;
    jobs.forEach(j => {
      const opt = document.createElement("option");
      opt.value = j.id;
      opt.textContent = `${j.id}  —  ${fmtTime(j.started_at)}  (${j.detection_count}件)`;
      sel.appendChild(opt);
    });
    if (current && [...sel.options].some(o => o.value === current)) sel.value = current;
  }

  async function populateComputerSelector() {
    const sel = $("#dash-computer"); if (!sel) return;
    const current = sel.value;
    try {
      const r = await fetch("/api/hunt/facets");
      const f = await r.json();
      sel.innerHTML = `<option value="">全部</option>`;
      (f.computers || []).forEach(c => {
        const o = document.createElement("option");
        o.value = c.name; o.textContent = `${c.name} (${c.count})`;
        sel.appendChild(o);
      });
      if (current && [...sel.options].some(o => o.value === current)) sel.value = current;
    } catch (e) { /* facets 取得失敗時は「全部」のまま */ }
  }

  // 「いまの状況」を一文で。最悪の重要度でトーン(色)を決める。
  function renderDashSummary(d) {
    const el = $("#dash-summary"); if (!el) return;
    const bl = d.by_level || {};
    const crit = bl.critical || 0, high = bl.high || 0, med = bl.medium || 0, low = bl.low || 0;
    const hosts = (d.totals && d.totals.unique_computers) || 0;
    const worst = (d.top_computers || []).slice()
      .sort((a, b) => (b.sev_count || 0) - (a.sev_count || 0))[0];
    let tone, msg;
    if (crit > 0)      { tone = "crit"; msg = `🟥 <b>緊急レベルの危険</b>が <b>${crit.toLocaleString()}</b> 件 見つかりました。すぐ確認を。`; }
    else if (high > 0) { tone = "high"; msg = `🟧 <b>高レベルの危険</b>が <b>${high.toLocaleString()}</b> 件 見つかりました。`; }
    else if (med > 0)  { tone = "med";  msg = `🟨 中レベルの検知が <b>${med.toLocaleString()}</b> 件。緊急・高はありません。`; }
    else if (low > 0)  { tone = "ok";   msg = `🟩 低レベルの検知のみ（${low.toLocaleString()} 件）。目立った危険はありません。`; }
    else               { tone = "ok";   msg = `🟩 危険な検知は見つかっていません。`; }
    const worstTxt = (worst && (worst.sev_count || 0) > 0)
      ? ` 最も危険なPCは <b>${escapeHtml(worst.computer || "(不明)")}</b>。` : "";
    el.className = "dash-summary tone-" + tone;
    el.innerHTML = `🖥️ 調査したパソコン <b>${hosts.toLocaleString()}</b> 台。${msg}${worstTxt}`;
  }

  async function loadDashboard() {
    await populateJobSelector();
    await populateComputerSelector();
    const job = $("#dash-job").value;
    const computer = $("#dash-computer")?.value || "";
    const bucket = $("#dash-bucket").value;
    const incSup = $("#dash-suppressed").checked;
    const qs = new URLSearchParams();
    if (job) qs.set("job", job);
    if (computer) qs.set("computer", computer);
    qs.set("bucket", bucket);
    if (incSup) qs.set("include_suppressed", "1");
    const r = await fetch(`/api/stats?${qs}`);
    const d = await r.json();

    $("#kpi-total").textContent = d.totals.detections.toLocaleString();
    $("#kpi-hosts").textContent = d.totals.unique_computers.toLocaleString();
    $("#kpi-rules").textContent = d.totals.unique_rules.toLocaleString();

    // 信号色タイル（重要度別の件数）
    const bl = d.by_level || {};
    const setN = (id, v) => { const e = $(id); if (e) e.textContent = (v || 0).toLocaleString(); };
    setN("#st-crit", bl.critical); setN("#st-high", bl.high);
    setN("#st-med", bl.medium);    setN("#st-low", bl.low);

    // 状況ヒトコト
    renderDashSummary(d);

    const levels = HayCharts.stackedBars($("#chart-timeline"), d.timeline);
    HayCharts.legend($("#timeline-legend"), levels);
    const keys = Object.keys(d.timeline);
    if (keys.length) {
      $("#timeline-range").textContent = `${keys[0]} 〜 ${keys[keys.length-1]} (粒度: ${bucket})`;
    } else {
      $("#timeline-range").textContent = "";
    }

    renderBars($("#chart-rules"), d.top_rules.map(r => ({
      label: r.rule_title || r.rule_id,
      sublabel: r.level,
      level: r.level,
      count: r.n,
    })));
    renderBars($("#chart-hosts"), d.top_computers.map(c => ({
      label: c.computer || "(不明)",
      sublabel: `Critical+High: ${c.sev_count || 0}`,
      count: c.n,
    })));

    // 「いつ・どこで・何が」を一目で: 最近の重大イベント一覧。
    loadRecentEvents();

    // 運営者専用の安全リスト（スコア除外ルール）を描画。
    loadSafeList();

    // Run the anomaly analyser. It can be slow on huge corpora (it walks
    // the whole detection table) so fire it asynchronously without
    // blocking the rest of the dashboard render.
    loadAnomalies();
  }

  // 運営者専用: 「安全としてマーク」したルール一覧を描画し、解除できる。
  async function loadSafeList() {
    const host = $("#safe-list");
    if (!host || !document.body.classList.contains("is-admin")) return;
    let rows = [];
    try {
      const r = await fetch("/api/suppressions");
      rows = await r.json();
    } catch (e) {
      host.innerHTML = `<span class="muted small">一覧の取得に失敗しました。</span>`;
      return;
    }
    if (!Array.isArray(rows) || !rows.length) {
      host.innerHTML = `<span class="muted small">まだ安全リストは空です。検知の解説を開いて「安全としてマーク」を押すと、ここに登録されます。</span>`;
      return;
    }
    host.innerHTML = "";
    rows.forEach(row => {
      const div = document.createElement("div");
      div.className = "safe-list-row";
      const scope = row.computer_like
        ? `PC「${escapeHtml(row.computer_like)}」` : "全PC";
      const label = escapeHtml(row.reason || row.rule_id || "(理由なし)");
      div.innerHTML = `
        <span class="safe-rule" title="${escapeHtml(row.rule_id || "")}">
          🛡 ${label} <span class="muted small">(${scope})</span>
        </span>
        <button type="button" class="btn btn-ghost small safe-remove" data-id="${row.id}">解除</button>`;
      div.querySelector(".safe-remove").addEventListener("click", async () => {
        if (!confirm("このルールを安全リストから外し、再びスコアに数えるようにしますか？")) return;
        await fetch(`/api/suppressions/${row.id}`, { method: "DELETE" });
        loadSafeList();
        loadDashboard();
        if (document.body.classList.contains("public-mode")) { loadRanking?.(); loadRankingStats?.(); }
      });
      host.appendChild(div);
    });
  }

  // ISO/hayabusa のタイムスタンプを "MM/DD HH:MM" に整形 (失敗時は先頭16文字)。
  function fmtWhen(ts) {
    if (!ts) return "—";
    const d = new Date(ts);
    if (!isNaN(d)) {
      const p = n => String(n).padStart(2, "0");
      return `${p(d.getMonth()+1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
    }
    return String(ts).replace("T", " ").slice(0, 16);
  }

  async function loadRecentEvents() {
    const host = $("#recent-events"); if (!host) return;
    const job = $("#dash-job")?.value;
    const computer = $("#dash-computer")?.value || "";
    const incSup = $("#dash-suppressed")?.checked;
    const qs = new URLSearchParams();
    qs.set("level", "critical"); qs.append("level", "high");
    qs.set("order", "ts_desc"); qs.set("limit", "15");
    if (job) qs.set("job", job);
    if (computer) qs.set("computer", computer);
    if (incSup) qs.set("include_suppressed", "1");
    host.innerHTML = `<div class="muted small" style="padding:8px 2px">読込中…</div>`;
    try {
      const r = await fetch("/api/hunt/search?" + qs.toString());
      const d = await r.json();
      const evs = d.detections || [];
      if (!evs.length) {
        host.innerHTML = `<div class="muted small" style="padding:8px 2px">まだ重大な出来事（critical / high）はありません。</div>`;
        return;
      }
      host.innerHTML = evs.map((ev, i) => {
        const lv = ((ev.Level || "").toLowerCase().match(/[a-z]+/) || ["info"])[0];
        const ja = LEVEL_JA[lv] || ev.Level || "";
        const meta = [ev.Channel, ev.EventID].filter(Boolean).join(" · ");
        return `<div class="re-row clickable" data-i="${i}" role="button" tabindex="0"
                     title="クリックで解説（なにを検知したか）を表示">
          <span class="re-time">${escapeHtml(fmtWhen(ev.Timestamp))}</span>
          <span class="lvl lvl-${escapeHtml(lv)}">${escapeHtml(ja)}</span>
          <span class="re-pc" title="${escapeHtml(ev.Computer || "")}">💻 ${escapeHtml(ev.Computer || "(不明)")}</span>
          <span class="re-what">${escapeHtml(ev.RuleTitle || ev.Title || "(不明)")}${meta ? ` <span class="re-meta">${escapeHtml(meta)}</span>` : ""}</span>
          <span class="re-caret">▾</span>
        </div>`;
      }).join("");
      // 各行に detection を紐付け、クリックで既存の解説パネルを展開する。
      host.querySelectorAll(".re-row").forEach(rowEl => {
        const ev = evs[Number(rowEl.dataset.i)];
        rowEl.dataset.jobId = ev._job_id || "";
        rowEl.dataset.lineNo = (ev._line_no != null ? ev._line_no : "");
        rowEl.addEventListener("click", () => toggleExplain(rowEl, ev));
        rowEl.addEventListener("keydown", e => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleExplain(rowEl, ev); }
        });
      });
    } catch (e) {
      host.innerHTML = `<div class="muted small" style="padding:8px 2px">取得に失敗しました</div>`;
    }
  }

  async function loadAnomalies() {
    const tb = $("#anomalies-table tbody"); if (!tb) return;
    tb.innerHTML = `<tr><td colspan="6" class="muted small">分析中…</td></tr>`;
    try {
      const r = await fetch("/api/behavioral/anomalies?top=30");
      const d = await r.json();
      tb.innerHTML = "";
      if (d.error) {
        tb.innerHTML = `<tr><td colspan="6" class="muted small">エラー: ${escapeHtml(d.error)}</td></tr>`;
        return;
      }
      if (!d.anomalies.length) {
        tb.innerHTML = `<tr><td colspan="6" class="muted small">
          異常は検出されていません。検知データが少ない場合は数日分を取り込んでから再度試してください。
        </td></tr>`;
        return;
      }
      d.anomalies.forEach(a => {
        const tr = document.createElement("tr");
        const kindLabel = {
          burst: "バースト", spread: "拡散",
          silence: "沈黙",   off_hours: "時間外",
        }[a.kind] || a.kind;
        const target = a.rule_title
          ? escapeHtml(a.rule_title)
          : (a.host ? escapeHtml(a.host) : "—");
        let num = "—";
        if (a.kind === "burst")    num = `${a.observed} 件 (×${a.ratio})`;
        if (a.kind === "spread")   num = `${a.hosts_count} ホスト / ${a.observed} 件`;
        if (a.kind === "silence")  num = `${a.gap_hours}h 無音`;
        if (a.kind === "off_hours") num = a.ts ? a.ts.slice(11, 16) : "—";
        const lvl = (a.severity || "medium").toLowerCase();
        tr.innerHTML = `
          <td><span class="anom-kind ${a.kind}">${kindLabel}</span></td>
          <td><span class="lvl lvl-${lvl}">${lvl.slice(0,4)}</span></td>
          <td class="anom-target">${target}</td>
          <td class="anom-num">${num}</td>
          <td class="anom-desc">${escapeHtml(a.description)}</td>
          <td><a href="#" class="muted small">調査 →</a></td>`;
        tr.onclick = () => drillIntoAnomaly(a);
        tb.appendChild(tr);
      });
    } catch (e) {
      tb.innerHTML = `<tr><td colspan="6" class="muted small">
        通信エラー: ${escapeHtml(String(e))}
      </td></tr>`;
    }
  }

  // When the analyst clicks an anomaly row, jump into the Hunt tab with
  // a pre-applied filter that surfaces the underlying detections.
  function drillIntoAnomaly(a) {
    // Switch tab first so the form elements exist by the time we set them.
    const tabBtn = document.querySelector('.tab[data-tab="hunt"]');
    if (tabBtn) tabBtn.click();
    setTimeout(() => {
      resetHuntForm?.();
      const d = a.drill || {};
      if (d.host)    $("#hunt-host").value = d.host;
      if (d.from || d.to) {
        $("#hunt-window").value = "custom";
        $("#hunt-custom-range").hidden = false;
        if (d.from) $("#hunt-from").value = d.from;
        if (d.to)   $("#hunt-to").value = d.to;
      }
      if (a.rule_id && !d.host) {
        // For burst/spread the focus is on the rule; the hunt form takes
        // a free-text query that matches rule_title, so use that.
        $("#hunt-q").value = a.rule_title || "";
      }
      runHunt?.();
    }, 60);
  }

  function renderBars(container, items) {
    container.innerHTML = "";
    if (!items.length) {
      container.innerHTML = `<div class="muted small">データがありません。</div>`;
      return;
    }
    const max = Math.max(...items.map(i => i.count), 1);
    items.forEach(item => {
      const row = document.createElement("div");
      row.className = "bar-row";
      const cls = item.level ? `lvl-${item.level}` : "lvl-default";
      const sub = item.sublabel
        ? `<span class="muted small">${item.sublabel}</span>` : "";
      row.innerHTML =
        `<div class="label" title="${item.label}">${item.label} ${sub}</div>
         <div class="bar ${cls}"><div style="width:${(item.count/max*100).toFixed(1)}%"></div></div>
         <div class="count">${item.count.toLocaleString()}</div>`;
      container.appendChild(row);
    });
  }

  $("#dash-refresh").onclick = loadDashboard;
  $("#dash-job").onchange = loadDashboard;
  $("#dash-bucket").onchange = loadDashboard;
  { const dc = $("#dash-computer"); if (dc) dc.onchange = loadDashboard; }
  $("#dash-suppressed").onchange = loadDashboard;
  // Recompute bar widths if the panel resizes (e.g. window resize while open).
  window.addEventListener("resize", () => {
    if ($("#tab-dashboard").classList.contains("active")) loadDashboard();
  });

  // -------- ホスト資産ビュー (tab=hosts) --------

  // Map a risk score (0..100) onto a band + colour class. The thresholds
  // are calibrated so the table can be read at a glance: "anything above
  // 70 is somebody to investigate today".
  function riskBand(score) {
    if (score >= 70) return {label: "very-high", cls: "risk-very-high"};
    if (score >= 50) return {label: "high",      cls: "risk-high"};
    if (score >= 30) return {label: "med",       cls: "risk-med"};
    if (score >= 10) return {label: "low",       cls: "risk-low"};
    return {label: "info", cls: "risk-info"};
  }

  async function loadRanking() {
    const host = $("#ranking-list");
    if (!host) return;
    host.innerHTML = `<div class="muted small">読込中…</div>`;
    try {
      const r = await fetch("/api/ranking");
      const d = await r.json();
      if (d.error) { host.innerHTML = `<div class="muted small">エラー: ${escapeHtml(d.error)}</div>`; return; }
      const rows = d.ranking || [];
      const cnt = $("#ranking-count");
      if (cnt) cnt.textContent = rows.length ? `(${rows.length} エントリー)` : "";
      if (!rows.length) {
        host.innerHTML = `<div class="empty-state">
          <div class="icon">🏆</div>
          <div class="title">まだエントリーがありません</div>
          ログをアップロードしてスキャンすると、危険度スコアでここに並びます。
          <div class="cta"><button class="primary" data-goto-tab="scan">🔍 ログをアップロード</button></div>
        </div>`;
        return;
      }
      const maxScore = Math.max(...rows.map(x => x.risk_score || 0), 1);
      host.innerHTML = rows.map(x => {
        const top = x.rank <= 3 ? ` top${x.rank}` : "";
        const medal = x.rank === 1 ? "🥇" : x.rank === 2 ? "🥈" : x.rank === 3 ? "🥉" : x.rank;
        const src = x.is_named ? "" : ` <span class="name-src">(ログのPC名)</span>`;
        const w = Math.round(100 * (x.risk_score || 0) / maxScore);

        // --- 危険演出: critical/high を含む or 高スコアほど "感染" 度UP ---
        const crit = x.critical_n || 0, high = x.high_n || 0, score = x.risk_score || 0;
        let infect = 0;                         // 0=なし 1=軽 2=中 3=重
        if (crit > 0 || score >= 60) infect = 3;
        else if (high > 0 || score >= 35) infect = 2;
        else if (score >= 15) infect = 1;
        const champion = x.rank === 1 && infect > 0;   // 1位かつ危険なら主役演出
        const cls = ["rank-row" + top];
        if (infect) cls.push("infected", "infect-" + infect);
        if (champion) cls.push("champion");

        // 浮遊する 🦠 (重いほど数を増やす)。champion はさらに盛る。
        const bugN = champion ? 6 : infect === 3 ? 4 : infect === 2 ? 2 : 0;
        let bugs = "";
        for (let i = 0; i < bugN; i++) {
          const left = 6 + (i * 88 / Math.max(1, bugN - 1));   // 横位置を散らす
          const delay = (i * 0.5).toFixed(2), dur = (3 + (i % 3)).toFixed(1);
          const g = ["🦠", "☣️", "💀", "🐛"][i % 4];
          bugs += `<span class="vbug" style="left:${left}%;animation-delay:${delay}s;animation-duration:${dur}s">${g}</span>`;
        }
        const badge = champion
          ? `<span class="danger-badge">☣️ 最も危険なPC</span>`
          : (infect === 3 ? `<span class="danger-badge sm">感染の疑い</span>` : "");

        return `<div class="rank-item${champion ? " is-champion" : ""}" data-computer="${escapeHtml(x.computer || "")}">
          <div class="${cls.join(" ")}" role="button" tabindex="0" aria-expanded="false" title="クリックで危険の内訳を表示">
            ${bugs ? `<div class="vbug-layer" aria-hidden="true">${bugs}</div>` : ""}
            <div class="rank-no">${medal}</div>
            <div class="rank-main">
              <div class="rank-name">${escapeHtml(x.name || "(不明)")}${src}${badge}</div>
              <div class="rank-sev">
                <span class="rank-chip c">critical ${x.critical_n || 0}</span>
                <span class="rank-chip h">high ${x.high_n || 0}</span>
                <span class="rank-chip m">medium ${x.medium_n || 0}</span>
                <span class="rank-chip l">low ${x.low_n || 0}</span>
                <span class="rank-chip muted">検知 ${(x.total || 0).toLocaleString()} ・ ルール ${x.rules_seen || 0}種</span>
              </div>
              <div class="rank-bar"><i style="width:${w}%"></i></div>
            </div>
            <div class="rank-score"><div class="sv">${(x.risk_score || 0).toFixed(1)}</div><div class="sl">危険度</div></div>
            <div class="rank-caret">▾</div>
          </div>
          <div class="rank-detail" hidden></div>
        </div>`;
      }).join("");
    } catch (e) {
      host.innerHTML = `<div class="muted small">取得に失敗しました: ${escapeHtml(String(e))}</div>`;
    }
  }

  const LEVEL_JA = { critical: "緊急", high: "高", medium: "中", low: "低", informational: "情報" };

  // 行をクリック → そのPCの「危険の内訳」(検知ルール上位) を遅延ロードして展開。
  async function toggleRankingDetail(item) {
    const row = item.querySelector(".rank-row");
    const panel = item.querySelector(".rank-detail");
    if (!panel) return;
    const open = !panel.hidden;
    if (open) {
      panel.hidden = true;
      row.setAttribute("aria-expanded", "false");
      return;
    }
    row.setAttribute("aria-expanded", "true");
    panel.hidden = false;
    if (panel.dataset.loaded === "1") return;   // 既に取得済み
    panel.innerHTML = `<div class="muted small" style="padding:10px 14px">読込中…</div>`;
    const comp = item.dataset.computer || "";
    try {
      const r = await fetch(`/api/hosts/${encodeURIComponent(comp)}`);
      const d = await r.json();
      if (d.error) { panel.innerHTML = `<div class="muted small" style="padding:10px 14px">取得に失敗: ${escapeHtml(d.error)}</div>`; return; }
      const rules = d.top_rules || [];
      const chans = d.top_channels || [];
      if (!rules.length) {
        panel.innerHTML = `<div class="muted small" style="padding:10px 14px">表示できる検知がありません。</div>`;
        panel.dataset.loaded = "1";
        return;
      }
      const ruleRows = rules.map(rr => {
        const lv = (rr.level || "").toLowerCase();
        const ja = LEVEL_JA[lv] || rr.level || "";
        return `<div class="rd-rule">
          <span class="lvl lvl-${escapeHtml(lv)}">${escapeHtml(ja)}</span>
          <span class="rd-title">${escapeHtml(rr.rule_title || rr.rule_id || "(名称不明)")}</span>
          <span class="rd-count">${(rr.n || 0).toLocaleString()} 件</span>
        </div>`;
      }).join("");
      const chanLine = chans.length
        ? `<div class="rd-chans">記録源: ${chans.map(c => `${escapeHtml(c.channel)} (${c.n})`).join(" ・ ")}</div>`
        : "";
      panel.innerHTML = `<div class="rank-detail-inner">
          <div class="rd-head">このパソコンで見つかった“あやしい動き” 上位 ${rules.length} 件</div>
          ${ruleRows}
          ${chanLine}
          <div class="rd-note">数字は当てはまった回数です（回数はスコアに影響しません）。スコアは <b>緊急/高 の“異なる手口の数”</b>で決まります。</div>
        </div>`;
      panel.dataset.loaded = "1";
    } catch (e) {
      panel.innerHTML = `<div class="muted small" style="padding:10px 14px">取得に失敗: ${escapeHtml(String(e))}</div>`;
    }
  }

  { const rl = $("#ranking-list"); if (rl) {
      rl.addEventListener("click", (e) => {
        const item = e.target.closest(".rank-item");
        if (item && rl.contains(item)) toggleRankingDetail(item);
      });
      rl.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        const row = e.target.closest(".rank-row");
        if (!row) return;
        e.preventDefault();
        toggleRankingDetail(row.closest(".rank-item"));
      });
  } }
  { const _rb = $("#ranking-refresh"); if (_rb) _rb.onclick = loadRanking; }

  // -------- 公開モード: 大会の全体統計ダッシュボード --------
  async function loadRankingStats() {
    const host = $("#pub-stats");
    if (!host || !document.body.classList.contains("public-mode")) return;
    try {
      const r = await fetch("/api/ranking/stats");
      const d = await r.json();
      if (d.error) return;
      if (!d.entries) {
        host.innerHTML = `<div class="ps-head">📊 大会の状況</div>
          <div class="muted small" style="padding:6px 2px">まだ参戦PCがありません。最初の1台になろう！</div>`;
        return;
      }
      const champ = d.champion
        ? `<div class="ps-champ">👑 首位 <b>${escapeHtml(d.champion.name || "(不明)")}</b>
             <span class="ps-champ-score">${(d.champion.score || 0).toFixed(1)}</span></div>`
        : "";
      const tiles = [
        ["🖥️", d.entries, "参戦PC"],
        ["🦠", d.infected, "感染の疑い"],
        ["⚠️", d.high_plus, "高リスク"],
        ["🔎", (d.total_detections || 0).toLocaleString(), "総検知"],
      ].map(([ic, n, l]) =>
        `<div class="ps-tile"><div class="ps-ic">${ic}</div>
           <div class="ps-n">${n}</div><div class="ps-l">${l}</div></div>`).join("");
      const tech = (d.top_techniques || []).map(t => {
        const lv = (t.level || "").toLowerCase();
        const ja = LEVEL_JA[lv] || t.level || "";
        return `<div class="ps-tech">
            <span class="lvl lvl-${escapeHtml(lv)}">${escapeHtml(ja)}</span>
            <span class="ps-tech-title">${escapeHtml(t.title || "(名称不明)")}</span>
            <span class="ps-tech-pcs">${t.pcs}台</span>
          </div>`;
      }).join("");
      host.innerHTML = `<div class="ps-head">📊 大会の状況 <span class="muted small">(自動更新)</span></div>
        ${champ}
        <div class="ps-tiles">${tiles}</div>
        ${tech ? `<div class="ps-tech-head">よく出た“危険な手口”</div>${tech}` : ""}`;
    } catch (e) { /* 静かに無視 (ネットワーク瞬断など) */ }
  }
  // 公開モードでは定期的に更新して "ライブ感" を出す。
  setInterval(() => {
    if (document.body.classList.contains("public-mode")) loadRankingStats();
  }, 10000);

  async function loadHosts() {
    const tb = $("#hosts-table tbody");
    if (!tb) return;
    tb.innerHTML = `<tr><td colspan="10" class="muted small">読込中…</td></tr>`;
    try {
      const inc = $("#hosts-include-suppressed").checked ? "1" : "0";
      const r = await fetch(`/api/hosts?include_suppressed=${inc}`);
      const d = await r.json();
      tb.innerHTML = "";
      if (d.error) {
        tb.innerHTML = `<tr><td colspan="10" class="muted small">エラー: ${escapeHtml(d.error)}</td></tr>`;
        return;
      }
      if (!d.hosts.length) {
        tb.innerHTML = `<tr><td colspan="10">
          <div class="empty-state">
            <div class="icon">💻</div>
            <div class="title">まだパソコンの情報がありません</div>
            スキャンを実行すると、ここにパソコンごとの危険度が並びます。
            <div class="cta"><button class="primary" data-goto-tab="scan">🔍 スキャンへ進む</button></div>
          </div></td></tr>`;
        return;
      }
      d.hosts.forEach(h => {
        const band = riskBand(h.risk_score);
        const tr = document.createElement("tr");
        tr.dataset.host = h.host;
        tr.innerHTML = `
          <td class="host-name">${escapeHtml(h.host)}</td>
          <td><div class="risk-cell">
            <div class="risk-bar"><div class="${band.cls}-bar" style="width:${h.risk_score}%"></div></div>
            <span class="risk-score ${band.cls}">${h.risk_score.toFixed(1)}</span>
          </div></td>
          <td class="risk-score">${h.total.toLocaleString()}</td>
          <td><span class="lvl lvl-critical">${h.critical_n || 0}</span></td>
          <td><span class="lvl lvl-high">${h.high_n || 0}</span></td>
          <td><span class="lvl lvl-medium">${h.medium_n || 0}</span></td>
          <td>${h.jobs}</td>
          <td class="muted-cell">${escapeHtml((h.first_seen || "").slice(0, 16))}</td>
          <td class="muted-cell">${escapeHtml((h.last_seen || "").slice(0, 16))}</td>
          <td><button class="ghost-btn small" data-host="${escapeHtml(h.host)}">詳細 →</button></td>
        `;
        tr.querySelector("button").onclick = (e) => {
          e.stopPropagation();
          openHostDetail(h.host);
        };
        tr.onclick = () => openHostDetail(h.host);
        tb.appendChild(tr);
      });
    } catch (e) {
      tb.innerHTML = `<tr><td colspan="10" class="muted small">
        通信エラー: ${escapeHtml(String(e))}
      </td></tr>`;
    }
  }

  async function openHostDetail(host) {
    const card = $("#host-detail-card");
    card.hidden = false;
    $("#host-detail-name").textContent = host;
    $("#host-detail-summary").innerHTML = `<div class="muted small">読込中…</div>`;
    $("#host-detail-rules").innerHTML = "";
    $("#host-detail-channels").innerHTML = "";
    $("#host-detail-timeline").innerHTML = "";
    try {
      const r = await fetch(`/api/hosts/${encodeURIComponent(host)}`);
      const d = await r.json();
      if (d.error) {
        $("#host-detail-summary").innerHTML = `<div class="muted small">エラー: ${escapeHtml(d.error)}</div>`;
        return;
      }
      const s = d.summary;
      const last7d = s.last_seen ? new Date() - new Date(s.last_seen.slice(0, 19)) : null;
      const ageStr = last7d == null ? "—"
        : last7d < 86400000 ? "1日以内" :
          last7d < 86400000*7 ? Math.floor(last7d/86400000) + "日前" :
          Math.floor(last7d/86400000) + "日前";

      $("#host-detail-summary").innerHTML = `
        <div class="host-stat-row"><span>リスクスコア</span><span class="${riskBand(s.risk_score).cls}">${s.risk_score.toFixed(1)} / 100</span></div>
        <div class="host-stat-row lvl-critical"><span>critical</span><span>${s.critical_n || 0}</span></div>
        <div class="host-stat-row lvl-high"><span>high</span><span>${s.high_n || 0}</span></div>
        <div class="host-stat-row lvl-medium"><span>medium</span><span>${s.medium_n || 0}</span></div>
        <div class="host-stat-row lvl-low"><span>low</span><span>${s.low_n || 0}</span></div>
        <div class="host-stat-row lvl-informational"><span>info</span><span>${s.info_n || 0}</span></div>
        <div class="host-stat-row"><span>TP / FP 判定</span><span>${s.tp_n || 0} / ${s.fp_n || 0}</span></div>
        <div class="host-stat-row"><span>発火ルール種数</span><span>${s.rules_seen || 0}</span></div>
        <div class="host-stat-row"><span>スキャンジョブ数</span><span>${s.jobs || 0}</span></div>
        <div class="host-stat-row"><span>最終検知</span><span>${escapeHtml((s.last_seen || "—").slice(0, 19))} (${ageStr})</span></div>
        <div class="host-stat-row"><span>初検知</span><span>${escapeHtml((s.first_seen || "—").slice(0, 19))}</span></div>
      `;
      // TOP rules
      const rulesHost = $("#host-detail-rules");
      d.top_rules.forEach(r => {
        const row = document.createElement("div");
        row.className = "bar-row";
        const cls = r.level ? `lvl-${r.level}` : "lvl-default";
        row.innerHTML = `<div class="label" title="${escapeHtml(r.rule_title || r.rule_id)}">${escapeHtml(r.rule_title || r.rule_id)}</div>
          <div class="bar ${cls}"><div style="width:${(r.n / d.top_rules[0].n * 100).toFixed(1)}%"></div></div>
          <div class="count">${r.n.toLocaleString()}</div>`;
        rulesHost.appendChild(row);
      });
      // TOP channels
      const chHost = $("#host-detail-channels");
      d.top_channels.forEach(c => {
        const row = document.createElement("div");
        row.className = "bar-row";
        row.innerHTML = `<div class="label" title="${escapeHtml(c.channel || "")}">${escapeHtml((c.channel || "").replace(/^.+\//, ""))}</div>
          <div class="bar lvl-default"><div style="width:${(c.n / d.top_channels[0].n * 100).toFixed(1)}%"></div></div>
          <div class="count">${c.n.toLocaleString()}</div>`;
        chHost.appendChild(row);
      });
      // Timeline — reuse the existing stacked-bars helper.
      if (window.HayCharts && d.timeline) {
        HayCharts.stackedBars($("#host-detail-timeline"), d.timeline);
      }
      // Wire the "hunt for this host" pivot.
      $("#host-pivot-hunt").onclick = () => {
        const tabBtn = document.querySelector('.tab[data-tab="hunt"]');
        if (tabBtn) tabBtn.click();
        setTimeout(() => {
          resetHuntForm?.();
          $("#hunt-host").value = host;
          runHunt?.();
        }, 60);
      };
    } catch (e) {
      $("#host-detail-summary").innerHTML = `<div class="muted small">通信エラー: ${escapeHtml(String(e))}</div>`;
    }
  }

  // Close button on the host detail card.
  document.addEventListener("click", (e) => {
    if (e.target && e.target.id === "host-detail-close") {
      $("#host-detail-card").hidden = true;
    }
    if (e.target && e.target.id === "hosts-refresh") loadHosts();
    if (e.target && e.target.id === "hosts-include-suppressed") loadHosts();
  });

  // -------- フッタ ステータスバー --------
  // Refreshed periodically with backend health, store counts, feed status
  // and admin posture. This is a "you can see at a glance what's loaded"
  // surface — purely informational, no interactions.
  async function refreshStatusBar() {
    const set = (id, text, klass) => {
      const el = document.getElementById(id);
      if (!el) return;
      const span = el.querySelector("span:last-child") || el;
      span.textContent = text;
      if (klass) el.className = "group " + klass;
    };
    const setDot = (id, cls) => {
      const el = document.getElementById(id);
      if (!el) return;
      const dot = el.querySelector(".dot");
      if (dot) dot.className = "dot " + cls;
    };

    try {
      // Health is the cheapest probe — runs first to colour the conn dot.
      const h = await (await fetch("/api/health")).json();
      const ver = (h.version || "").replace(/^Hayabusa\s*/, "").slice(0, 40);
      document.querySelector("#sb-conn span:last-child").textContent = "接続中";
      setDot("sb-conn", "ok");
      document.querySelector("#sb-engine").textContent = "engine: " + (ver || "?");
    } catch {
      document.querySelector("#sb-conn span:last-child").textContent = "接続失敗";
      setDot("sb-conn", "bad");
      return;
    }

    try {
      // Detection count + latest job from a single jobs query.
      const jobs = await (await fetch("/api/jobs")).json();
      const total = jobs.reduce((s, j) => s + (j.detection_count || 0), 0);
      document.querySelector("#sb-store").textContent =
        "DB: " + total.toLocaleString() + " 検知 / " + jobs.length + " ジョブ";
      if (jobs[0]) {
        const t = jobs[0].started_at ? new Date(jobs[0].started_at * 1000)
          .toLocaleTimeString("ja-JP", {hour:"2-digit",minute:"2-digit"}) : "—";
        document.querySelector("#sb-job").textContent =
          "最終ジョブ: " + t + " · " + (jobs[0].status || "?");
      }
    } catch { /* keep prior text */ }

    try {
      // Feed meta + lookup count.
      const l = await (await fetch("/api/lookups")).json();
      const feeds = (l.feeds || []).filter(f => f && f.fetched_at);
      const ok = feeds.filter(f => !f.error).length;
      const total = (l.lookups || []).reduce((s, x) => s + (x.entries || 0), 0);
      document.querySelector("#sb-feeds").textContent =
        "IoC: " + total.toLocaleString() + " 件 / " + ok + " フィード";
    } catch { /* ignore */ }

    try {
      const s = await (await fetch("/api/system/info")).json();
      const isAdmin = !!s.admin;
      document.querySelector("#sb-admin").textContent =
        "権限: " + (isAdmin ? "管理者" : "通常ユーザ");
      // Re-style the admin badge subtly: warn colour when not elevated.
      const el = document.querySelector("#sb-admin");
      el.style.color = isAdmin ? "var(--ok)" : "var(--warn)";
    } catch { /* ignore */ }
  }

  // -------- 用語ツールチップ (専門用語に hover 解説) --------
  // 専門用語を含む本文を走査し、最初の 1 回だけ小さな解説ポップを付ける。
  // code / a / button / input などは触らないので表示は壊れない。
  const GLOSSARY = {
    "EVTX": "<b>EVTX</b><br>Windows があらゆる出来事を記録するログファイル。拡張子は .evtx。これを読んで攻撃の痕跡をさがします。",
    "Sigma": "<b>Sigma</b><br>「あやしい動き」の見つけ方を、世界共通の書式で書いた検出ルールのこと。",
    "ATT&CK": "<b>ATT&amp;CK (アタック)</b><br>世界共通の「攻撃の手口カタログ」。MITRE という団体が整理しています。",
    "IoC": "<b>IoC</b><br>すでに知られている「悪いもの」(ファイルのハッシュ・URL・IP 等) のリスト。",
    "Sysmon": "<b>Sysmon</b><br>Windows の動作を、より細かく記録してくれる追加ツール。",
    "DFIR": "<b>DFIR</b><br>サイバー攻撃を受けた「後」に、何が起きたかを調べる作業のこと。",
    "プロセスツリー": "<b>プロセスツリー</b><br>どのプログラムが、どのプログラムを起動したか、という親子関係のこと。",
  };

  function installGlossary() {
    const root = document.querySelector("main");
    if (!root) return;
    const used = new Set();
    // 走査対象から除外するタグ
    const SKIP = new Set(["CODE","A","BUTTON","INPUT","SELECT","OPTION",
                          "TEXTAREA","SCRIPT","STYLE","PRE"]);
    // 用語を長い順に (ATT&CK が AT より先に当たるように)
    const terms = Object.keys(GLOSSARY).sort((a,b)=>b.length-a.length);

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        let p = node.parentNode;
        while (p && p !== root) {
          if (p.nodeType === 1) {
            if (SKIP.has(p.tagName)) return NodeFilter.FILTER_REJECT;
            if (p.classList && p.classList.contains("term")) return NodeFilter.FILTER_REJECT;
          }
          p = p.parentNode;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const textNodes = [];
    let n; while ((n = walker.nextNode())) textNodes.push(n);

    for (const node of textNodes) {
      let text = node.nodeValue;
      // この text 内で最初に見つかる未使用の用語を 1 つだけ処理
      for (const term of terms) {
        if (used.has(term)) continue;
        const idx = text.indexOf(term);
        if (idx < 0) continue;
        // 前後がラテン英数字なら単語の一部とみなしてスキップ (日本語語中はOK)
        const before = text[idx-1] || "", after = text[idx+term.length] || "";
        if (/[A-Za-z0-9]/.test(before) || /[A-Za-z0-9]/.test(after)) continue;
        used.add(term);
        const span = document.createElement("span");
        span.className = "term";
        span.tabIndex = 0;
        span.appendChild(document.createTextNode(term));
        const q = document.createElement("span");
        q.className = "term-q"; q.textContent = "?";
        span.appendChild(q);
        const pop = document.createElement("span");
        pop.className = "term-pop"; pop.innerHTML = GLOSSARY[term];
        span.appendChild(pop);
        const after_node = node.splitText(idx);
        after_node.nodeValue = after_node.nodeValue.slice(term.length);
        node.parentNode.insertBefore(span, after_node);
        break; // この text ノードは 1 用語で打ち切り
      }
    }
  }

  // boot
  health(); refreshWorkspace(); refreshJobs(); updateScanButton(); loadSystemInfo();
  refreshStatusBar();
  installGlossary();
  setInterval(refreshWorkspace, 5000);
  setInterval(refreshStatusBar, 15000);   // status bar refresh
})();
