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

  // Relationship-graph state is declared before switchTab so a direct
  // #graph deep-link can call initRelationshipGraph during boot.
  let _graphInited = false;
  let _graphData = null;
  let _graphSvg = null;
  let _graphSize = { w: 1200, h: 700 };
  let _graphZoom = 1;
  let _graphLayout = null;
  let _graphMatches = [];
  let _graphMatchIndex = 0;
  let _graphDragMoved = false;
  let _graphFocusId = null;

  // -------- tabs --------
  // サブ画面 → サイドバーの親グループ。グループ見出しは親で点灯させ、
  // サブ項目だけを完全一致で点灯させる。
  const TAB_PARENT = {
    dashboard: "results", hosts: "results", proctree: "results",
    cases: "results",
    hunt: "investigate", logs: "investigate", elastic: "investigate",
    graph: "investigate",
    rules: "settings", about: "settings",
  };

  // Switch to a tab by its data-tab name. Centralised so home-screen
  // shortcut cards and in-app pivots can reuse it.
  function switchTab(name) {
    // 公開(危険度ランキング)モードでは、ローカル専用グループへの遷移を
    // すべてランキングへ振り替える。ナビは非表示でも、ホームのカードや
    // 検知詳細リンク経由で抜け道になるのを防ぐ。
    if (document.body.classList.contains("public-mode")) {
      const el = document.querySelector('[data-tab="' + name + '"]');
      if (el && el.closest(".local-only")) name = "ranking";
    }
    if (!document.getElementById("tab-" + name)) return;
    if (name !== "graph") {
      document.querySelector(".graph-card")?.classList.remove("graph-fullscreen");
      document.body.classList.remove("graph-fullscreen-open");
      const fb = document.querySelector("#graph-fullscreen");
      if (fb) fb.textContent = "全画面";
    }
    const parent = TAB_PARENT[name] || name;

    $$(".nav-group").forEach(g => g.classList.toggle("is-active", g.dataset.group === parent));
    $$(".tab").forEach(x => {
      const g = x.closest(".nav-group");
      if (g) {
        x.classList.toggle("active", g.dataset.group === parent && x.classList.contains("group-lead"));
      } else {
        x.classList.toggle("active", x.dataset.tab === name);
      }
    });
    $$(".snav").forEach(x => x.classList.toggle("active", x.dataset.tab === name));

    const id = "tab-" + name;
    $$(".tab-panel").forEach(p => p.classList.toggle("active", p.id === id));
    // タブを URL ハッシュに反映 → 共有・ブックマーク・直リンクが効く
    if (("#" + name) !== location.hash) {
      try { history.replaceState(null, "", "#" + name); } catch { location.hash = name; }
    }
    if (name === "results") refreshJobs();
    if (name === "cases") loadCases();
    if (name === "rules") { loadRules(); loadFeedback(); loadSuppressions(); loadLookups(); }
    if (name === "dashboard") loadDashboard();
    if (name === "hunt") initHunt();
    if (name === "hosts") loadHosts();
    if (name === "ranking") loadRanking();
    if (name === "proctree") initProcessTree();
    if (name === "graph") initRelationshipGraph();
    // Extension point for the modules in extra.js (log search / Elastic).
    // A DOM event keeps app.js from having to know about them.
    window.dispatchEvent(new CustomEvent("hayfx:tab", { detail: { name } }));
  }
  $$(".tab, .snav").forEach(t => t.onclick = () => switchTab(t.dataset.tab));

  // -------- detection drawer --------
  // 検知詳細は右側のドロワー。テーブルを隠さずに読めるよう、背景と
  // 閉じるボタン・Esc を用意する。
  const _dw = $("#detail-wrap");
  const _db = $("#detail-backdrop");
  if (_dw && _db) {
    const syncDrawer = () => { _db.hidden = _dw.hidden; };
    new MutationObserver(syncDrawer).observe(_dw, { attributes: true, attributeFilter: ["hidden"] });
    syncDrawer();
    const closeDrawer = () => { _dw.hidden = true; };
    const closeBtn = $("#detail-close");
    if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
    _db.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !_dw.hidden) closeDrawer();
    });
  }

  // 起動時に URL ハッシュ (#dashboard 等) があればそのタブを開く
  const _hashTab = (location.hash || "").replace(/^#/, "");
  if (_hashTab && document.getElementById("tab-" + _hashTab)) {
    switchTab(_hashTab);
  }

  // 実行環境の表示。企業内運用では「どの解析ホストの、どのデータ領域を
  // 見ているか」が重要なので、設定 API の事実をそのまま出す。
  const RUNTIME_JA = {
    wsl: "WSL (解析用)", linux: "Linux (解析用)", windows: "Windows (互換)",
    macos: "macOS", darwin: "macOS",
  };
  function renderPosture(cfg) {
    const dep = (cfg && cfg.deployment) || {};
    const set = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };
    const runtime = RUNTIME_JA[dep.runtime] || dep.runtime || "—";
    set("post-runtime", dep.hostname ? `${runtime} · ${dep.hostname}` : runtime);
    set("post-bind", dep.bind_scope === "lan"
      ? "LAN 公開（認証なし・非推奨）"
      : `localhost のみ (${dep.bind_host || "127.0.0.1"})`);
    set("post-auth", dep.auth === "none"
      ? (dep.bind_scope === "lan" ? "なし（LAN 公開・危険）" : "なし（ローカル単独）")
      : (dep.auth || "—"));
    const ps = document.getElementById("home-posture");
    if (ps) ps.dataset.scope = dep.bind_scope || "loopback";
    // 設定画面とフッタでも同じ事実を参照できるように保持する。
    window.__hayabusaDeployment = dep;
  }

  // 公開(危険度ランキング)モードの判定。サーバが 0.0.0.0 で待受しているとき
  // network_mode=true。ローカル専用機能を隠し、ランキングを入口にする。
  fetch("/api/config").then(r => r.json()).then(cfg => {
    // 運営者(localhost)だけに「安全としてマーク」等の管理操作を見せる。
    document.body.classList.toggle("is-admin", !!(cfg && cfg.is_admin));
    renderPosture(cfg);
    if (cfg && cfg.network_mode) {
      document.body.classList.add("public-mode");
      // 入口はランキング。直リンク (#results 等) でローカル専用タブを開いた場合も振り替える。
      const cur = document.querySelector(".tab.active");
      if (!_hashTab || (cur && cur.closest(".local-only"))) switchTab("ranking");
      loadRankingStats();   // スキャン画面の大会ダッシュボードを初期表示
    }
  }).catch(() => {});

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
      $("#health").title = "Hayabusa 正常" + (d.hayabusa ? "\n" + d.hayabusa : "");
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
    const caseName = ($("#case-name")?.value || "").trim();
    for (const f of files) {
      const fd = new FormData(); fd.append("file", f);
      if (caseName) fd.append("case_name", caseName);
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
    const hashNote = lastSaved && lastSaved.sha256
      ? ` ・ SHA-256 ${lastSaved.sha256.slice(0, 16)}…` : "";
    if (lastSaved && lastSaved.kind === "dir") {
      $("#upload-status").textContent =
        `ZIP を展開しました → ${lastSaved.count} 個の .evtx（まとめてスキャンします）${hashNote}`;
    } else {
      $("#upload-status").textContent =
        files.length === 1
          ? `保存しました → ${lastSaved.rel}${hashNote}`
          : `${files.length} 個のファイルを保存しました${hashNote}`;
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
    const main = btn?.querySelector(".scan-go-main");
    if (scanRunning) {
      if (btn) btn.disabled = true;
      if (main) main.textContent = "スキャン中…";
      else if (btn) btn.textContent = "スキャン中…";
      if (summary) summary.textContent = "完了までお待ちください";
      return;
    }
    if (main) main.textContent = "スキャン開始";
    if (!btn) return;
    const path = $("#target-path").value.trim();
    const hasTarget = path.length > 0;
    btn.disabled = !hasTarget;
    if (!hasTarget) {
      if (summary) summary.textContent = "先にステップ 1 で対象を選んでください";
      return;
    }
    const level = $("#min-level").value;
    const flags = [];
    if ($("#eid-filter").checked)  flags.push("EIDフィルタ");
    if ($("#enable-all").checked)  flags.push("全ルール");
    if ($("#proven-only").checked) flags.push("実績ルールのみ");
    if ($("#dedupe").checked)      flags.push("重複排除");
    const targetLabel = path;
    const caseName = ($("#case-name")?.value || "").trim();
    if (summary) {
      summary.textContent =
        `${targetLabel} ・ 最小レベル: ${level}` +
        (caseName ? ` ・ 案件: ${caseName}` : " ・ 案件未指定") +
        (flags.length ? ` ・ ${flags.join(" / ")}` : "");
    }
  }

  // Hooks that should also recompute the summary.
  $("#target-type").addEventListener("change", updateScanButton);
  $("#case-name")?.addEventListener("input", updateScanButton);

  // -------- scan submission --------
  let liveES = null;
  let scanRunning = false;

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
      // Case is optional. A name is enough for first use; the server reuses
      // an existing open case with the same name.
      case_name: ($("#case-name")?.value || "").trim(),
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
    if (scanRunning) return;
    scanRunning = true;
    updateScanButton();
    let d;
    try {
      const params = buildScanParams();
      const r = await fetch("/api/scan", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params)
      });
      d = await r.json();
    } catch (e) {
      scanRunning = false;
      updateScanButton();
      alert("スキャンを開始できませんでした: " + e);
      return;
    }
    if (d.error) {
      scanRunning = false;
      updateScanButton();
      alert("スキャンを開始できませんでした: " + d.error);
      return;
    }
    bindLive(d.job_id, d.job_token);
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

  function bindLive(jobId, jobToken) {
    liveJobId = jobId;
    scanRunning = true;
    updateScanButton();
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
      if (lastPct >= 99) {
        const tail = totalFilesSeen
          ? `（${totalFilesSeen.toLocaleString()} 件のログ）` : "";
        $("#progress-note").textContent = `最終処理中… 99%${tail}（完了待ち）`;
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
    let finishedUI = false;
    const finishUI = (statusText, complete = false) => {
      if (finishedUI) return;
      finishedUI = true;
      clearInterval(tick);
      if (liveES) { liveES.close(); liveES = null; }
      document.body.classList.remove("scanning");   // 大会ダッシュを戻す
      cancelBtn.hidden = true;
      if (complete) setProgress(100, 0);
      if (statusText) $("#progress-note").textContent = statusText;
      scanRunning = false;
      updateScanButton();
      refreshJobs();
      // 完了表示を少し見せてから片付ける。
      setTimeout(() => { $("#scan-progress").hidden = true; }, 1200);
    };

    const streamUrl = `/api/jobs/${jobId}/stream` +
      (jobToken ? `?token=${encodeURIComponent(jobToken)}` : "");
    liveES = new EventSource(streamUrl);
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
        if (msg.job.status === "done") {
          finishUI("解析完了 ✓ 100%", true);
        } else if (msg.job.status === "failed") {
          finishUI("解析に失敗しました");
        } else if (msg.job.status === "cancelled") {
          finishUI("中止しました");
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
        finishUI("解析完了 ✓ 100%", true);
        // 公開(ランキング)モードでは、スキャンが終わるたびに順位を更新する。
        if (document.body.classList.contains("public-mode")) { loadRanking(); loadRankingStats(); }
      } else if (msg.type === "error") {
        const row = document.createElement("div");
        row.className = "row"; row.style.color = "var(--bad)";
        row.textContent = `[エラー/${msg.stage}] ${msg.msg}`;
        $("#live-feed").appendChild(row);
      }
    };
    liveES.onerror = () => {
      // EventSource reconnects automatically. Keep the scan button disabled;
      // otherwise the user can start a second scan while the first still runs.
      if (!finishedUI) {
        $("#progress-note").textContent =
          "サーバとの接続が切れました。自動再接続しています…";
      }
    };
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

  // 「何が実行したか」= 正規化した実行プログラム/コマンド/ユーザー を目立つ帯で。
  function renderActor(actor) {
    if (!actor) return "";
    const prog = actor.program_full || actor.program || actor.service || "";
    const hasAny = prog || actor.command || actor.user || actor.parent;
    if (!hasAny) return "";
    const rows = [];
    if (prog) {
      const svc = actor.service && actor.service !== actor.program
        ? ` <span class="muted small">(サービス: ${escapeHtml(actor.service)})</span>` : "";
      rows.push(`<div class="actor-row"><span class="actor-k">実行プログラム</span>
        <code class="actor-v">${escapeHtml(prog)}</code>${svc}</div>`);
    }
    if (actor.command && actor.command !== prog) {
      const cmd = actor.command.length > 400 ? actor.command.slice(0, 400) + "…" : actor.command;
      rows.push(`<div class="actor-row"><span class="actor-k">⌨ コマンド</span>
        <code class="actor-v cmd">${escapeHtml(cmd)}</code></div>`);
    }
    if (actor.parent) {
      rows.push(`<div class="actor-row"><span class="actor-k">↖ 親プロセス</span>
        <code class="actor-v">${escapeHtml(actor.parent)}</code></div>`);
    }
    const meta = [];
    if (actor.user) meta.push(`👤 ${escapeHtml(actor.user)}`);
    if (actor.pid) meta.push(`PID ${escapeHtml(actor.pid)}`);
    if (meta.length) rows.push(`<div class="actor-row muted small">${meta.join(" ・ ")}</div>`);
    return `<div class="actor-block">
      <div class="actor-head">何が実行したか</div>
      ${rows.join("")}
    </div>`;
  }

  // 「このアラートの前後のログ」= 同じPCの ±5分に出た検知を時系列で。
  // 攻撃はふつう単発でなく前後に痕跡が続くので、周辺を必ず確認できるように。
  function renderAround(related, ev) {
    const list = (related || []).slice();
    if (!list.length) return "";
    const focalTs = ev.Timestamp || "";
    // 焦点の時刻を差し込んで前後が分かるように並べる（サーバは時刻昇順）。
    const rowsHtml = list.slice(0, 20).map(r => {
      const lv = ((r.level || "").toLowerCase().match(/[a-z]+/) || ["info"])[0];
      const ja = LEVEL_JA[lv] || r.level || "";
      const before = focalTs && r.ts && r.ts < focalTs;
      const arrow = before ? "↑前" : "↓後";
      return `<div class="around-row" data-job="${escapeHtml(r.job_id || "")}" data-line="${escapeHtml(String(r.line_no != null ? r.line_no : ""))}" title="クリックで詳細">
          <span class="around-when">${escapeHtml(fmtWhen(r.ts))}</span>
          <span class="around-dir">${arrow}</span>
          <span class="lvl lvl-${escapeHtml(lv)}">${escapeHtml(ja)}</span>
          <span class="around-title">${escapeHtml(r.rule_title || r.rule_id || "(検知)")}</span>
          <span class="around-meta muted small">${escapeHtml([r.channel, r.event_id].filter(Boolean).join(" · "))}</span>
        </div>`;
    }).join("");
    return `<div class="explain-around">
        <h4>このアラートの前後のログ <span class="muted small">同じPCで ±5分に出た検知（クリックで移動）</span></h4>
        <div class="around-list">${rowsHtml}</div>
      </div>`;
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
    const actorHtml = renderActor(detail?.actor);
    const aroundHtml = renderAround(detail?.related, ev);
    // 「このログが実際に何をしたか」の平易な日本語1文（サーバ生成）。
    const narrHtml = detail?.narrative
      ? `<div class="explain-narr"><span class="en-k">このログがしたこと</span>
           <span class="en-v">${escapeHtml(detail.narrative)}</span></div>`
      : "";

    explain.innerHTML = `
      <div class="explain-block">
        ${narrHtml}
        ${actorHtml}
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
          <h4>検知したログの中身 <span class="muted small">このルールに引っかかった実際のログ</span></h4>
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
        ${aroundHtml}
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

    // 前後のログ行 → 結果タブでそのジョブを開く。
    explain.querySelectorAll(".around-row").forEach(ar => {
      ar.addEventListener("click", () => {
        const jid = ar.dataset.job;
        if (!jid) return;
        const tabBtn = document.querySelector('.tab[data-tab="results"]');
        if (tabBtn) tabBtn.click();
        setTimeout(() => openDetail(jid), 80);
      });
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
        + "（検知一覧・全体ビューには引き続き表示されます。ルールタブの「抑制 / 安全リスト」からいつでも解除できます）\n\nよろしいですか？")) return;
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
      $("#detection-card").hidden = true;
      tb.innerHTML = `<tr><td colspan="7">
        <div class="empty-state">
          <div class="icon">📋</div>
          <div class="title">まだスキャン結果がありません</div>
          まずは証跡を読み込んでスキャンしてみましょう。
          <div class="cta"><button class="primary" data-goto-tab="scan">🔍 スキャンへ進む</button></div>
        </div></td></tr>`;
      return;
    }
    const running = (s) => s === "running" || s === "queued";
    jobs.forEach(j => {
      const tr = document.createElement("tr");
      const caseCell = j.case_name
        ? `<span class="case-chip" title="${escapeHtml(j.case_reference || "")}">${escapeHtml(j.case_name)}</span>`
        : `<span class="muted">—</span>`;
      tr.innerHTML = `<td><code>${j.id}</code></td>
        <td>${caseCell}</td>
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

    // 初回表示で下半分が空にならないよう、まだ何も開いていなければ
    // 最新の完了ジョブを自動で開く。
    if ($("#detection-card").hidden) {
      const first = jobs.find(j => j.status === "done") || jobs[0];
      openDetail(first.id);
    }
  }

  // -------- cases / evidence / audit --------
  let lastCase = null;
  const AUDIT_ACTION_JA = {
    "case.open": "ケース作成",
    "scan.requested": "スキャン受付",
    "scan.start": "スキャン開始",
    "scan.finish": "スキャン完了",
    "evidence.hash": "証跡ハッシュ記録",
    "evidence.upload": "証跡アップロード",
    "evidence.link": "証跡をスキャンに紐付け",
    "job.delete": "ジョブ削除",
    "jobs.clear": "全ジョブ消去",
    "suppression.create": "抑制追加",
    "suppression.delete": "抑制解除",
  };

  function auditDetailText(detail) {
    if (!detail || typeof detail !== "object") return "";
    const bits = [];
    if (detail.case_id) bits.push("case " + detail.case_id);
    if (detail.filename) bits.push(detail.filename);
    if (detail.path) bits.push(detail.path);
    if (detail.sha256) bits.push("sha256 " + String(detail.sha256).slice(0, 16) + "…");
    if (detail.target && detail.target.path) bits.push(detail.target.path);
    if (detail.evidence_rows != null) bits.push(detail.evidence_rows + " 証跡");
    if (detail.status) bits.push(detail.status);
    if (detail.detections != null) bits.push(detail.detections + " 検知");
    if (detail.detections_removed != null) bits.push(detail.detections_removed + " 検知を削除");
    if (!bits.length) {
      const s = JSON.stringify(detail);
      return s.length > 140 ? s.slice(0, 140) + "…" : s;
    }
    return bits.join(" ・ ");
  }

  function auditListHtml(entries) {
    if (!entries || !entries.length) {
      return `<div class="muted small">監査イベントはまだありません。</div>`;
    }
    return entries.slice().reverse().map(e => {
      const action = AUDIT_ACTION_JA[e.action] || e.action || "—";
      const detail = auditDetailText(e.detail);
      return `<div class="audit-entry">
        <time>${fmtTime(e.ts)}</time>
        <span class="audit-action">${escapeHtml(action)}</span>
        <span class="audit-actor">${escapeHtml(e.actor || "")}</span>
        <span class="audit-object">${escapeHtml((e.object_type || "") + (e.object_id ? " / " + e.object_id : ""))}</span>
        ${detail ? `<span class="audit-detail">${escapeHtml(detail)}</span>` : ""}
      </div>`;
    }).join("");
  }

  async function loadAudit() {
    const list = $("#audit-list");
    if (!list) return;
    try {
      const r = await fetch("/api/audit?limit=200", { cache: "no-store" });
      const d = await r.json();
      const count = $("#audit-count");
      if (count) count.textContent = `${d.count || 0} 件`;
      list.innerHTML = auditListHtml(d.entries || []);
    } catch (e) {
      list.innerHTML = `<div class="muted small">監査ログを読めません: ${escapeHtml(String(e))}</div>`;
    }
  }

  async function verifyAudit() {
    const host = $("#audit-integrity");
    if (!host) return;
    host.className = "audit-integrity muted small";
    host.textContent = "検証中…";
    try {
      const r = await fetch("/api/audit/verify", { cache: "no-store" });
      const d = await r.json();
      host.classList.add(d.ok ? "ok" : "bad");
      host.textContent = (d.ok ? "✓ " : "✗ ") + (d.message || "") +
        (d.entries != null ? `（${d.entries} 件）` : "");
    } catch (e) {
      host.classList.add("bad");
      host.textContent = "✗ 検証できません: " + String(e);
    }
  }

  async function loadCases() {
    const tb = $("#cases-table tbody");
    if (!tb) return;
    loadAudit();
    try {
      const r = await fetch("/api/cases", { cache: "no-store" });
      const d = await r.json();
      const cases = d.cases || [];
      const count = $("#cases-count");
      if (count) count.textContent = `${cases.length} 件`;
      if (!cases.length) {
        tb.innerHTML = `<tr><td colspan="7" class="muted small">ケースはまだありません。スキャン画面で案件名を入力するか、左のフォームで作成してください。</td></tr>`;
        return;
      }
      tb.innerHTML = cases.map(c => `<tr data-case="${escapeHtml(c.id)}">
        <td><b>${escapeHtml(c.name)}</b></td>
        <td>${escapeHtml(c.reference || "—")}</td>
        <td>${c.job_count || 0}</td>
        <td>${c.detection_count || 0}</td>
        <td>${c.evidence_count || 0}</td>
        <td>${fmtTime(c.updated_at)}</td>
        <td class="row-actions"><button class="open-case-btn" data-case="${escapeHtml(c.id)}">開く</button></td>
      </tr>`).join("");
      tb.querySelectorAll(".open-case-btn").forEach(b => {
        b.onclick = () => openCase(b.dataset.case);
      });
    } catch (e) {
      tb.innerHTML = `<tr><td colspan="7" class="muted small">ケースを読めません: ${escapeHtml(String(e))}</td></tr>`;
    }
  }

  async function openCase(caseId) {
    const card = $("#case-detail");
    if (!card || !caseId) return;
    try {
      const r = await fetch(`/api/cases/${encodeURIComponent(caseId)}`, { cache: "no-store" });
      const d = await r.json();
      if (d.error) { alert("ケースを開けません: " + d.error); return; }
      const c = d.case || {};
      lastCase = { id: c.id, name: c.name || "" };
      const scanBtn = $("#case-scan-btn");
      if (scanBtn) scanBtn.hidden = false;
      $("#case-detail-name").textContent = c.name || "ケース詳細";
      $("#case-detail-meta").innerHTML = [
        c.id ? `ID: <code>${escapeHtml(c.id)}</code>` : "",
        c.reference ? `参照: ${escapeHtml(c.reference)}` : "",
        `状態: ${escapeHtml(c.status || "open")}`,
        `作成: ${fmtTime(c.created_at)}`,
        c.description ? escapeHtml(c.description) : "",
      ].filter(Boolean).join(" ・ ");

      const etb = $("#case-evidence-table tbody");
      const ev = d.evidence || [];
      etb.innerHTML = ev.length ? ev.map(e => `<tr>
        <td>${fmtTime(e.created_at)}</td>
        <td>${escapeHtml(e.filename || "")}</td>
        <td>${escapeHtml(e.source || "")}</td>
        <td>${e.size != null ? fmtSize(e.size) : "—"}</td>
        <td><code class="evidence-hash" title="${escapeHtml(e.sha256 || "")}">${escapeHtml((e.sha256 || "—").slice(0, 20))}${e.sha256 ? "…" : ""}</code></td>
        <td>${e.job_id ? `<code>${escapeHtml(e.job_id)}</code>` : "未割当"}</td>
      </tr>`).join("") : `<tr><td colspan="6" class="muted small">証跡はまだありません。</td></tr>`;

      const jtb = $("#case-jobs-table tbody");
      const jobs = d.jobs || [];
      jtb.innerHTML = jobs.length ? jobs.map(j => `<tr>
        <td><code>${escapeHtml(j.id)}</code></td>
        <td class="status-${escapeHtml(j.status || "")}">${escapeHtml(localizeStatus(j.status))}</td>
        <td>${fmtTime(j.started_at)}</td>
        <td>${j.detection_count || 0}</td>
        <td><code class="evidence-hash" title="${escapeHtml(j.evidence_sha256 || "")}">${escapeHtml((j.evidence_sha256 || "—").slice(0, 20))}${j.evidence_sha256 ? "…" : ""}</code></td>
        <td><button class="open-case-job" data-id="${escapeHtml(j.id)}">結果を開く</button></td>
      </tr>`).join("") : `<tr><td colspan="6" class="muted small">このケースのジョブはまだありません。</td></tr>`;
      jtb.querySelectorAll(".open-case-job").forEach(b => {
        b.onclick = () => { switchTab("results"); setTimeout(() => openDetail(b.dataset.id), 0); };
      });

      $("#case-audit").innerHTML = auditListHtml(d.audit || []);
      card.hidden = false;
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) {
      alert("ケースを読めません: " + e);
    }
  }

  $("#case-create-btn")?.addEventListener("click", async () => {
    const name = ($("#case-new-name")?.value || "").trim();
    const status = $("#case-create-status");
    if (!name) { if (status) status.textContent = "案件名を入力してください。"; return; }
    if (status) status.textContent = "作成中…";
    try {
      const r = await fetch("/api/cases", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          reference: ($("#case-new-ref")?.value || "").trim(),
          description: ($("#case-new-desc")?.value || "").trim(),
        }),
      });
      const d = await r.json();
      if (d.error) { if (status) status.textContent = "エラー: " + d.error; return; }
      if (status) status.textContent = "作成しました。";
      $("#case-new-name").value = "";
      $("#case-new-ref").value = "";
      $("#case-new-desc").value = "";
      await loadCases();
      if (d.case && d.case.id) openCase(d.case.id);
    } catch (e) {
      if (status) status.textContent = "通信エラー: " + e;
    }
  });
  $("#case-detail-close")?.addEventListener("click", () => {
    const card = $("#case-detail"); if (card) card.hidden = true;
  });
  $("#case-scan-btn")?.addEventListener("click", () => {
    if (!lastCase) return;
    const input = $("#case-name");
    if (input) {
      input.value = lastCase.name || "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    switchTab("scan");
    setTimeout(() => input?.focus(), 0);
  });
  $("#audit-refresh-btn")?.addEventListener("click", loadAudit);
  $("#audit-verify-btn")?.addEventListener("click", verifyAudit);

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
    if ($("#tab-dashboard").classList.contains("active")) loadDashboard();
    if (document.body.classList.contains("public-mode")) { loadRanking?.(); loadRankingStats?.(); }
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

  function renderJobEvidence(job) {
    const host = $("#job-evidence");
    if (!host) return;
    if (!job) { host.innerHTML = ""; return; }
    const bits = [];
    if (job.case_name) {
      bits.push(`<span class="case-chip">${escapeHtml(job.case_name)}</span>`);
    }
    if (job.evidence_kind === "live") {
      bits.push("旧方式: 直接読取（証跡ハッシュなし）");
    } else if (job.evidence_sha256) {
      const kind = job.evidence_kind === "directory" ? "ディレクトリ manifest" : "ファイル";
      bits.push(`${kind} SHA-256 <code class="evidence-hash">${escapeHtml(job.evidence_sha256)}</code>`);
      if (job.evidence_files != null) bits.push(`${job.evidence_files} ファイル`);
      if (job.evidence_bytes != null) bits.push(fmtSize(job.evidence_bytes));
    } else {
      bits.push("証跡ハッシュ未記録");
    }
    host.innerHTML = bits.join(" ・ ");
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
      renderJobEvidence(d.job);
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
          if ($("#tab-dashboard").classList.contains("active")) loadDashboard();
          if (document.body.classList.contains("public-mode")) { loadRanking?.(); loadRankingStats?.(); }
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
    const catEntries = Object.entries(d.by_category).sort((a,b) => b[1]-a[1]);
    catEntries.slice(0,16).forEach(([k,v]) => {
      const c = document.createElement("span"); c.className = "chip";
      c.innerHTML = `<b>${v}</b>${k}`; cats.appendChild(c);
    });
    if (catEntries.length > 16) {
      const c = document.createElement("span"); c.className = "chip";
      c.textContent = `他 ${catEntries.length - 16} 件`;
      cats.appendChild(c);
    }
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
    if (crit > 0)      { tone = "crit"; msg = `<b>緊急レベルの危険</b>が <b>${crit.toLocaleString()}</b> 件 見つかりました。すぐ確認を。`; }
    else if (high > 0) { tone = "high"; msg = `<b>高レベルの危険</b>が <b>${high.toLocaleString()}</b> 件 見つかりました。`; }
    else if (med > 0)  { tone = "med";  msg = `中レベルの検知が <b>${med.toLocaleString()}</b> 件。緊急・高はありません。`; }
    else if (low > 0)  { tone = "ok";   msg = `低レベルの検知のみ（${low.toLocaleString()} 件）。目立った危険はありません。`; }
    else               { tone = "ok";   msg = `危険な検知は見つかっていません。`; }
    const worstTxt = (worst && (worst.sev_count || 0) > 0)
      ? ` 最も危険なPCは <b>${escapeHtml(worst.computer || "(不明)")}</b>。` : "";
    el.className = "dash-summary tone-" + tone;
    el.innerHTML = `調査したパソコン <b>${hosts.toLocaleString()}</b> 台。${msg}${worstTxt}`;
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

    // Run the anomaly analyser. It can be slow on huge corpora (it walks
    // the whole detection table) so fire it asynchronously without
    // blocking the rest of the dashboard render.
    loadAnomalies();
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
          <span class="re-pc" title="${escapeHtml(ev.Computer || "")}">${escapeHtml(ev.Computer || "(不明)")}</span>
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
        // 実際の攻撃で確認された手口の数 (高信頼シグナル)。
        const hcBadge = (x.hc_count || 0) > 0
          ? `<span class="hc-badge" title="実際の攻撃サンプルで確認された手口">☣ 実攻撃 ${x.hc_count}</span>` : "";

        return `<div class="rank-item${champion ? " is-champion" : ""}" data-computer="${escapeHtml(x.computer || "")}">
          <div class="${cls.join(" ")}" role="button" tabindex="0" aria-expanded="false" title="クリックで危険の内訳を表示">
            ${bugs ? `<div class="vbug-layer" aria-hidden="true">${bugs}</div>` : ""}
            <div class="rank-no">${medal}</div>
            <div class="rank-main">
              <div class="rank-name">${escapeHtml(x.name || "(不明)")}${src}${badge}${hcBadge}</div>
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

  const SEV_RANK = { critical: 3, high: 2, medium: 1, low: 0, informational: -1 };

  // ★ 攻撃ストーリー（時系列タイムライン）= 主役ビュー。
  // 「いつ・誰が・何をしたか」を1文ずつ、時刻順に上から下へ読める形にする。
  // 同じ手口が複数の戦術にまたがって重複表示されるのを1つにまとめる。
  function renderAttackStory(story) {
    if (!story || !story.compromised || !(story.stages || []).length) return "";
    // 1. 全手口を1件ずつのイベントに展開し、説明文(なければ手口名)で重複排除。
    const byKey = new Map();
    story.stages.forEach(s => (s.techniques || []).forEach(t => {
      const key = (t.narrative || t.title || "").trim() || (t.techniques || []).join(",");
      const lv = (t.level || "").toLowerCase();
      const prev = byKey.get(key);
      const ev = {
        ts: t.first || "", tac: s.tactic_ja, order: s.order, level: lv,
        narrative: t.narrative || t.title || "(不明な手口)",
        title: t.title || "", ids: (t.techniques || []).join(", "),
        program: (t.programs || []).filter(Boolean)[0] || "",
        hc: !!t.high_confidence, count: t.count || 1, tacs: new Set([s.tactic_ja]),
      };
      if (!prev) { byKey.set(key, ev); return; }
      // まとめる: 最も早い時刻・最も重い重要度・件数合算・戦術を集約。
      if (ev.ts && (!prev.ts || ev.ts < prev.ts)) { prev.ts = ev.ts; prev.order = ev.order; }
      if ((SEV_RANK[ev.level] ?? -2) > (SEV_RANK[prev.level] ?? -2)) prev.level = ev.level;
      prev.count += ev.count; prev.hc = prev.hc || ev.hc;
      if (!prev.program && ev.program) prev.program = ev.program;
      prev.tacs.add(s.tactic_ja);
    }));
    const events = [...byKey.values()].sort((a, b) =>
      (a.ts && b.ts) ? String(a.ts).localeCompare(String(b.ts)) : (a.order - b.order));
    if (!events.length) return "";

    // 2. 冒頭サマリ: 戦術の流れ・時間帯・最悪の手口を1〜2文で。
    const tacSeq = [];
    events.forEach(e => { if (!tacSeq.includes(e.tac)) tacSeq.push(e.tac); });
    const times = events.map(e => e.ts).filter(Boolean).sort();
    const span = times.length
      ? (fmtWhen(times[0]) + (times.length > 1 ? " 〜 " + fmtWhen(times[times.length - 1]) : ""))
      : "";
    const worst = events.slice().sort((a, b) => (SEV_RANK[b.level] ?? -2) - (SEV_RANK[a.level] ?? -2))[0];
    const tone = worst && worst.level === "critical" ? "crit" : "high";
    const hcNote = story.hc_total ? `実際の攻撃で確認された手口が <b>${story.hc_total}</b> 件。` : "";
    const summary = `<div class="story-summary tone-${tone}">
        <div class="ss-title">⚠ このPCで攻撃の連鎖を検知しました</div>
        <div class="ss-flow">${tacSeq.map(escapeHtml).join(' <span class="ss-arrow">→</span> ')}</div>
        <div class="ss-sub muted small">${span ? "発生時間帯: <b>" + escapeHtml(span) + "</b>。 " : ""}${hcNote}
          いちばん危険: <b>${escapeHtml(worst ? worst.narrative : "")}</b></div>
      </div>`;

    // 3. 時系列タイムライン。各ステップ = 時刻＋日本語1文＋実行プログラム。
    const steps = events.map(e => {
      const ja = LEVEL_JA[e.level] || e.level || "";
      const hc = e.hc ? `<span class="st-hc" title="実際の攻撃で確認された手口">☣</span>` : "";
      const cnt = e.count > 1 ? `<span class="st-count">×${e.count}</span>` : "";
      const prog = e.program ? `<span class="st-prog">🖥 ${escapeHtml(e.program)}</span>` : "";
      const ids = e.ids ? `<span class="st-ids" title="${escapeHtml(e.title)}">${escapeHtml(e.ids)}</span>` : "";
      return `<li class="story-step lv-${escapeHtml(e.level)}">
          <div class="st-rail"><span class="st-dot"></span></div>
          <div class="st-body">
            <div class="st-top">
              <span class="st-time">🕒 ${escapeHtml(e.ts ? fmtWhen(e.ts) : "時刻不明")}</span>
              <span class="st-tac lv-${escapeHtml(e.level)}">${escapeHtml(e.tac)}</span>
              <span class="st-sev">${escapeHtml(ja)}</span>${hc}${cnt}
            </div>
            <div class="st-narr">${escapeHtml(e.narrative)}</div>
            <div class="st-meta">${prog}${ids}</div>
          </div>
        </li>`;
    }).join("");

    return `<div class="story">
        ${summary}
        <div class="story-head">🧭 攻撃の流れ（時系列）<span class="muted small"> — 上から下へ、起きた順に読めます</span></div>
        <ol class="story-timeline">${steps}</ol>
      </div>`;
  }

  // 行をクリック → そのPCの「危険の内訳」(検知ルール上位) を遅延ロードして展開。
  // 攻撃のキルチェーン図。侵害が疑われる (crit/high がある) 場合のみ、
  // 検知した手口を ATT&CK の段階順 (初期侵入→…→影響) に左から右へ並べ、
  // 「攻撃がどう進んだか」を1枚で見せる。攻撃が無ければ何も描かない。
  // mode: "stage" = ATT&CK 段階順（教科書的）, "time" = 実際の時刻順。
  function renderKillChain(story, mode) {
    if (!story || !story.compromised || !(story.stages || []).length) return "";
    mode = mode === "time" ? "time" : "stage";
    // 時系列順のときは stage を最初の時刻で並べ替える。
    const stages = story.stages.slice();
    if (mode === "time") {
      stages.sort((a, b) => String(a.first || "~").localeCompare(String(b.first || "~")));
    }
    const stageHtml = stages.map((s, idx) => {
      const techs = (s.techniques || []).map(t => {
        const lv = (t.level || "").toLowerCase();
        const hc = t.high_confidence
          ? `<span class="kc-hc" title="実際の攻撃で確認された手口">☣</span>` : "";
        // 技術ID は控えめに（タイトルの tooltip 兼、小さなグレー表記）。
        const idStr = (t.techniques || []).join(", ");
        const when = t.first
          ? `<span class="kc-when" title="最初に記録された時刻">🕒 ${escapeHtml(fmtWhen(t.first))}</span>` : "";
        // 主役 = 「誰が・何で・何をした」の平易な日本語説明。
        const narr = t.narrative
          ? `<div class="kc-narr">${escapeHtml(t.narrative)}</div>`
          : `<div class="kc-narr">${escapeHtml(t.title)}</div>`;
        // 実行プログラムだけ具体情報として残す（ユーザーは説明文に含まれる）。
        const progs = (t.programs || []).filter(Boolean);
        const progHtml = progs.length
          ? `<span class="kc-proc" title="実行プログラム">🖥 ${escapeHtml(progs.join(", "))}</span>` : "";
        return `<div class="kc-tech kc-${escapeHtml(lv)}" title="${escapeHtml(t.title)}${idStr ? " ("+idStr+")" : ""}">
            <div class="kc-tech-head">${hc}${when}</div>
            ${narr}
            <div class="kc-tech-meta">${progHtml}${idStr ? `<span class="kc-ids">${escapeHtml(idStr)}</span>` : ""}</div>
          </div>`;
      }).join("");
      const arrow = idx < stages.length - 1
        ? `<div class="kc-arrow" aria-hidden="true">➜</div>` : "";
      const stageWhen = (mode === "time" && s.first)
        ? ` <span class="kc-stage-when">🕒 ${escapeHtml(fmtWhen(s.first))}</span>` : "";
      return `<div class="kc-stage${s.hc ? " kc-stage-hc" : ""}">
          <div class="kc-stage-head"><span class="kc-num">${s.order}</span> ${escapeHtml(s.tactic_ja)}${stageWhen}</div>
          <div class="kc-techs">${techs}</div>
        </div>${arrow}`;
    }).join("");
    const hcBadge = story.hc_total
      ? `<span class="kc-hc-badge">☣ 実攻撃で確認された手口 ${story.hc_total} 件</span>` : "";
    // 並び順の意味を明記（「時系列が本当か」を検証できるように）。
    const orderNote = mode === "stage"
      ? "並び順 = 攻撃の<b>段階</b>（ATT&amp;CK の教科書的な順序）。実際の時刻は各手口の 🕒 で確認できます。"
      : "並び順 = <b>実際に記録された時刻</b>の順。これが本当の攻撃の流れです。";
    const matchNote = (story.timeline_matches_stage_order === false)
      ? `<div class="kc-warn">⚠ 実際の時刻の順序は、教科書的な段階順とは<b>一致していません</b>（🕒 の時刻で並びを確認してください）。</div>`
      : "";
    const toggle = `<button type="button" class="btn btn-ghost small kc-sort-toggle"
        data-mode="${mode}">${mode === "stage" ? "🕒 時系列順で見る" : "🧭 段階順で見る"}</button>`;
    return `<div class="killchain" data-mode="${mode}">
        <div class="kc-title">🧬 攻撃の流れ（ATT&amp;CK キルチェーン） ${hcBadge} ${toggle}</div>
        <div class="kc-ordernote muted small">${orderNote}</div>
        ${matchNote}
        <div class="kc-flow">${stageHtml}</div>
      </div>`;
  }

  // キルチェーンの並び替えトグル。押すたびに段階順 ⇄ 時系列順を切り替える。
  function wireKillChainToggle(scope, story) {
    const btn = scope.querySelector(".kc-sort-toggle");
    if (!btn) return;
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const kc = scope.querySelector(".killchain");
      if (!kc) return;
      const next = kc.dataset.mode === "time" ? "stage" : "time";
      kc.outerHTML = renderKillChain(story, next);
      wireKillChainToggle(scope, story);   // 再描画後に再配線
    });
  }

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
      const [r, sr] = await Promise.all([
        fetch(`/api/hosts/${encodeURIComponent(comp)}`),
        fetch(`/api/hosts/${encodeURIComponent(comp)}/attack_story`),
      ]);
      const d = await r.json();
      const story = await sr.json().catch(() => null);
      if (d.error) { panel.innerHTML = `<div class="muted small" style="padding:10px 14px">取得に失敗: ${escapeHtml(d.error)}</div>`; return; }
      const rules = d.top_rules || [];
      const chans = d.top_channels || [];
      if (!rules.length) {
        panel.innerHTML = `<div class="muted small" style="padding:10px 14px">表示できる検知がありません。</div>`;
        panel.dataset.loaded = "1";
        return;
      }
      // 各手口に平易な説明（サーバがルール説明を付与）を添える = ログごと説明。
      const ruleRows = rules.map(rr => {
        const lv = (rr.level || "").toLowerCase();
        const ja = LEVEL_JA[lv] || rr.level || "";
        const desc = (rr.description || "").trim();
        const tags = (rr.attack_tags || []).slice(0, 4)
          .map(t => `<span class="rd-attack">${escapeHtml(t)}</span>`).join(" ");
        return `<div class="rd-rule">
          <div class="rd-rule-head">
            <span class="lvl lvl-${escapeHtml(lv)}">${escapeHtml(ja)}</span>
            <span class="rd-title">${escapeHtml(rr.rule_title || rr.rule_id || "(名称不明)")}</span>
            <span class="rd-count">${(rr.n || 0).toLocaleString()} 件</span>
          </div>
          ${desc ? `<div class="rd-desc">${escapeHtml(desc)}</div>` : ""}
          ${tags ? `<div class="rd-attacks">${tags}</div>` : ""}
        </div>`;
      }).join("");
      const chanLine = chans.length
        ? `<div class="rd-chans">記録源: ${chans.map(c => `${escapeHtml(c.channel)} (${c.n})`).join(" ・ ")}</div>`
        : "";
      const storyHtml = renderAttackStory(story);
      panel.innerHTML = `<div class="rank-detail-inner">
          ${storyHtml || `<div class="muted small" style="margin-bottom:8px">緊急・高レベルの明確な攻撃連鎖は見つかりませんでした（下の一覧で個別の検知を確認できます）。</div>`}
          ${storyHtml ? `<details class="rd-more"><summary>🧬 ATT&amp;CK 段階マップで見る（上級者向け）</summary>
            <div style="margin-top:8px">${renderKillChain(story, "stage")}</div></details>` : ""}
          <details class="rd-more"${storyHtml ? "" : " open"}>
            <summary>検知した手口の一覧（${rules.length} 件）</summary>
            <div style="margin-top:8px">
              ${ruleRows}
              ${chanLine}
            </div>
          </details>
          <div class="rd-note">スコアは <b>緊急/高 の“異なる手口の数”</b>で決まり、<b>☣ 実攻撃で確認された手口</b>は特に重く数えます。</div>
        </div>`;
      panel.dataset.loaded = "1";
      // 段階マップを開いたときにトグルを配線（存在すれば）。
      wireKillChainToggle(panel, story);
    } catch (e) {
      panel.innerHTML = `<div class="muted small" style="padding:10px 14px">取得に失敗: ${escapeHtml(String(e))}</div>`;
    }
  }

  { const rl = $("#ranking-list"); if (rl) {
      rl.addEventListener("click", (e) => {
        // 展開パネル内のクリック（details の開閉・ボタン・リンク等）は
        // 親パネルを閉じない。トグルするのはヘッダ行だけ。
        if (e.target.closest(".rank-detail")) return;
        const row = e.target.closest(".rank-row");
        if (!row) return;
        const item = row.closest(".rank-item");
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

  // -------- プロセスツリー タブ --------
  let _proctreeInited = false;
  async function initProcessTree() {
    const sel = $("#proctree-computer");
    if (sel && !_proctreeInited) {
      _proctreeInited = true;
      // PC 一覧を用意（危険なPCを上に）。
      try {
        const r = await fetch("/api/ranking");
        const j = await r.json();
        const rows = Array.isArray(j) ? j : (j.ranking || []);
        const seen = new Set();
        rows.forEach(x => {
          const c = x.computer || "";
          if (!c || seen.has(c)) return;
          seen.add(c);
          const o = document.createElement("option");
          o.value = c; o.textContent = x.name && x.name !== c ? `${x.name}（${c}）` : c;
          sel.appendChild(o);
        });
        // 先頭のPCを自動選択。
        if (sel.options.length > 1) { sel.selectedIndex = 1; }
      } catch (e) {}
      await populateProctreeJobs(sel.value);
      // PC を変えたら、そのPCで「ツリーを描けるファイル」だけに絞り直す。
      sel.onchange = async () => { await populateProctreeJobs(sel.value); loadProcessTree(); };
      const jb = $("#proctree-job"); if (jb) jb.onchange = loadProcessTree;
      const rb = $("#proctree-refresh"); if (rb) rb.onclick = loadProcessTree;
      const sp = $("#proctree-suppressed"); if (sp) sp.onchange = loadProcessTree;
      // 検知プロセスのクリック → 結果タブでそのログを開く。
      const hostEl = $("#proctree-host");
      if (hostEl) hostEl.addEventListener("click", (e) => {
        const row = e.target.closest(".pt-clickable");
        if (!row) return;
        const jid = row.dataset.job, ln = row.dataset.line;
        if (!jid || ln === "") return;
        const tb = document.querySelector('.tab[data-tab="results"]');
        if (tb) tb.click();
        setTimeout(() => openDetail(jid), 80);
      });
    }
    loadProcessTree();
  }

  // 「対象ファイル(ジョブ)」候補を、選択中のPCで“プロセスツリーを描ける
  // ファイル”だけに絞って用意する（プロセス作成ログ EID1/4688 を含むもの）。
  // 件数はそのPCのプロセス作成ログ数。混ざり防止＋空振り防止。
  async function populateProctreeJobs(comp) {
    const jb = $("#proctree-job"); if (!jb) return;
    while (jb.options.length > 1) jb.remove(1);
    jb.options[0].textContent = "全ファイル";
    if (!comp) return;
    try {
      const d = await (await fetch(`/api/hosts/${encodeURIComponent(comp)}/process_jobs`)).json();
      const jobs = (d && d.jobs) || [];
      if (!jobs.length) {
        // 描けるファイルが無い → その旨を「全ファイル」に明示。
        jb.options[0].textContent = "（このPCにプロセス作成ログなし）";
        return;
      }
      jobs.forEach(j => {
        const o = document.createElement("option");
        o.value = j.job_id;
        const when = j.started_at ? fmtWhen(new Date(j.started_at * 1000).toISOString()) : j.job_id.slice(0,8);
        o.textContent = `${when}・プロセス${(j.count || 0).toLocaleString()}件`;
        jb.appendChild(o);
      });
    } catch (e) {}
  }

  async function loadProcessTree() {
    const host = $("#proctree-host"); if (!host) return;
    const comp = $("#proctree-computer")?.value || "";
    const cnt = $("#proctree-count");
    if (!comp) {
      host.innerHTML = `<div class="empty-state"><div class="icon">🌳</div>
        <div class="title">PC を選んでください</div>
        上の「PC」から対象のパソコンを選ぶと、プロセスの親子ツリーを表示します。</div>`;
      if (cnt) cnt.textContent = "";
      return;
    }
    host.innerHTML = `<div class="muted small" style="padding:10px">読込中…</div>`;
    const qs = new URLSearchParams();
    const job = $("#proctree-job")?.value || "";
    if (job) qs.set("job", job);
    if ($("#proctree-suppressed")?.checked) qs.set("include_suppressed", "1");
    let d;
    try {
      const r = await fetch(`/api/hosts/${encodeURIComponent(comp)}/process_tree?${qs}`);
      d = await r.json();
    } catch (e) {
      host.innerHTML = `<div class="muted small" style="padding:10px;color:#c0392b">取得に失敗しました: ${escapeHtml(String(e))}</div>`;
      return;
    }
    if (d.error) { host.innerHTML = `<div class="muted small" style="padding:10px">エラー: ${escapeHtml(d.error)}</div>`; return; }
    if (!d.has_data || !(d.roots || []).length) {
      // なぜ空なのかを説明する。件数はあるのにツリーが出ない＝そのログに
      // 「プロセス作成ログ(EID1/4688)」が含まれていない、という意味。
      const present = d.present || [];
      const total = d.total_detections || 0;
      const CH_JA = {
        "Microsoft-Windows-Sysmon/Operational": "Sysmon",
        "Security": "セキュリティ", "System": "システム",
        "Microsoft-Windows-PowerShell/Operational": "PowerShell",
        "Windows PowerShell": "PowerShell(旧)",
      };
      const presentHtml = present.length
        ? `<div class="pt-present"><div class="muted small" style="margin:8px 0 4px">このデータに含まれる検知（上位）:</div>
            <ul class="pt-present-list">${present.map(p =>
              `<li><b>${(CH_JA[p.channel] || escapeHtml(p.channel))}</b> ・ EventID ${escapeHtml(String(p.event_id))} <span class="muted small">— ${p.count.toLocaleString()}件</span></li>`
            ).join("")}</ul>
            <div class="muted small" style="margin-top:6px">この中に <b>プロセス作成（Sysmon EID 1 / Security 4688）</b> がありません。</div></div>`
        : "";
      host.innerHTML = `<div class="empty-state" style="text-align:left;max-width:640px;margin:0 auto">
        <div style="text-align:center"><div class="icon">🌳</div>
        <div class="title">このデータではプロセスの親子を描けません</div></div>
        <p>検知は <b>${total.toLocaleString()}件</b> ありますが、プロセスツリーには
        「<b>どのプロセスが、どのプロセスを起動したか</b>」が記録された
        <b>プロセス作成ログ</b>（Sysmon <b>EventID 1</b> または Windows セキュリティ <b>4688</b>）が必要です。
        今回のログはPowerShellやログオン等の<b>別種のイベント</b>で、親子関係の情報を持っていません。</p>
        ${presentHtml}
        <p class="muted small">ドロップダウンの「〇〇件」は<b>そのファイル全体</b>の検知数（このPC以外も含む）で、
        プロセス作成ログの数ではありません。プロセスツリーを見るには、Sysmonを有効にしたPCのログや、
        プロセス起動を含む攻撃サンプル（Webシェル・マルウェア実行など）が必要です。</p>
      </div>`;
      if (cnt) cnt.textContent = "";
      return;
    }
    if (cnt) cnt.textContent = `— ${d.nodes_seen} プロセス${d.truncated ? "（上限で一部省略）" : ""}・キー: ${d.key_mode === "guid" ? "Sysmon GUID" : "PID"}`;
    // 冒頭に「起動の連鎖」を1行で（最長パス）。何が何を起動したか一目で。
    const chain = procChainSummary(d.roots);
    const chainHtml = chain.length > 1
      ? `<div class="pt-summary">🔗 起動の連鎖：${chain.map((p, i) =>
          `<span class="pt-chain-item">${escapeHtml(p)}</span>`).join('<span class="pt-chain-arrow">→</span>')}</div>`
      : "";
    host.innerHTML = `${chainHtml}<ul class="ptree">${d.roots.map(renderProcNode).join("")}</ul>`;
  }

  function renderProcNode(node) {
    const img = node.image ? procBasename(node.image) : "(不明なプロセス)";
    const kids = (node.children || []).length
      ? `<ul class="ptree">${node.children.map(renderProcNode).join("")}</ul>` : "";
    const pidTxt = node.pid ? `PID ${escapeHtml(String(node.pid))}` : "";

    // 合成した親（記録外の起動元）: 系譜を示すためだけの控えめなノード。
    if (node.synthetic) {
      return `<li class="pt-node pt-synth">
          <div class="pt-row">
            <span class="pt-dot pt-dot-plain"></span>
            <span class="pt-img">${escapeHtml(img)}</span>
            <span class="pt-tag-parent">起動元</span>
            ${pidTxt ? `<span class="pt-pid">${pidTxt}</span>` : ""}
          </div>
          ${kids}
        </li>`;
    }

    const hit = node.detection;
    const cmd = node.cmdline && node.cmdline !== node.image
      ? `<div class="pt-cmd"><code>${escapeHtml(node.cmdline.length > 240 ? node.cmdline.slice(0,240) + "…" : node.cmdline)}</code></div>` : "";

    // 検知が無い中間プロセス（起動しただけ）: 控えめに。
    if (!hit) {
      const meta = [node.user ? "👤 " + escapeHtml(node.user) : "", node.ts ? "🕒 " + escapeHtml(fmtWhen(node.ts)) : "", pidTxt]
        .filter(Boolean).join(" ・ ");
      return `<li class="pt-node pt-clean">
          <div class="pt-row">
            <span class="pt-dot pt-dot-plain"></span>
            <span class="pt-img">${escapeHtml(img)}</span>
            ${meta ? `<span class="pt-meta muted small">${meta}</span>` : ""}
          </div>
          ${cmd}${kids}
        </li>`;
    }

    // 検知プロセス: プログラム名＋重要度、その下に「何をしたか」を日本語で。
    const lv = (hit.level || "").toLowerCase();
    const sev = `<span class="pt-sev lv-${escapeHtml(lv)}">${escapeHtml(LEVEL_JA[lv] || lv)}</span>`;
    const narr = `<div class="pt-narr">${escapeHtml(hit.narrative || hit.rule_title || "不審な動作")}</div>`;
    const meta = [node.user ? "👤 " + escapeHtml(node.user) : "", node.ts ? "🕒 " + escapeHtml(fmtWhen(node.ts)) : "", pidTxt]
      .filter(Boolean).join(" ・ ");
    const dataAttr = ` data-job="${escapeHtml(hit.job_id || "")}" data-line="${escapeHtml(String(hit.line_no != null ? hit.line_no : ""))}"`;
    return `<li class="pt-node pt-node-hit pt-lv-${escapeHtml(lv)}">
        <div class="pt-row pt-clickable"${dataAttr} title="クリックで詳細（結果タブ）">
          <span class="pt-dot"></span>
          <span class="pt-img">${escapeHtml(img)}</span>${sev}
          <span class="pt-rule muted small">${escapeHtml(hit.rule_title || "")}</span>
        </div>
        ${narr}
        ${meta ? `<div class="pt-meta muted small">${meta}</div>` : ""}
        ${cmd}
        ${kids}
      </li>`;
  }

  // ツリーの最長パス（起動元→…→末端）を「a.exe → b.exe → c.exe」でまとめる。
  function procChainSummary(roots) {
    let best = [];
    const walk = (n, path) => {
      const p = path.concat(n.image ? procBasename(n.image) : "(不明)");
      if (!(n.children || []).length) { if (p.length > best.length) best = p; }
      else (n.children || []).forEach(c => walk(c, p));
    };
    (roots || []).forEach(r => walk(r, []));
    return best;
  }

  function procBasename(p) {
    const s = String(p).replace(/^["']|["']$/g, "").replace(/\\/g, "/").replace(/\/+$/,"");
    return s.split("/").pop() || s;
  }

  // -------- プロセス / ファイル関係図 --------
  async function initRelationshipGraph() {
    const sel = $("#graph-computer");
    if (sel && !_graphInited) {
      _graphInited = true;
      try {
        const d = await (await fetch("/api/ranking")).json();
        const rows = Array.isArray(d) ? d : (d.ranking || []);
        const seen = new Set();
        rows.forEach(x => {
          const c = x.computer || "";
          if (!c || seen.has(c)) return;
          seen.add(c);
          const o = document.createElement("option");
          o.value = c;
          o.textContent = x.name && x.name !== c ? `${x.name}（${c}）` : c;
          sel.appendChild(o);
        });
        if (sel.options.length > 1) {
          let preferred = "";
          if (lastJobId) {
            try {
              const d = await (await fetch(`/api/jobs/${encodeURIComponent(lastJobId)}?limit=1`)).json();
              preferred = (d.detections && d.detections[0] && d.detections[0].computer) || "";
            } catch (e) { /* fall through to newest host */ }
          }
          if (!preferred) {
            const latest = rows.slice().sort((a, b) =>
              String(b.last_seen || "").localeCompare(String(a.last_seen || "")))[0];
            preferred = latest?.computer || "";
          }
          if (preferred && [...sel.options].some(o => o.value === preferred)) {
            sel.value = preferred;
          } else {
            sel.selectedIndex = 1;
          }
        }
      } catch (e) { /* ranking is optional */ }
      // Fallback: /api/hosts is independent of nickname/ranking data.
      if (sel.options.length <= 1) {
        try {
          const h = await (await fetch("/api/hosts")).json();
          const rows = Array.isArray(h) ? h : (h.hosts || []);
          const seen = new Set();
          rows.forEach(x => {
            const c = x.computer || "";
            if (!c || seen.has(c)) return;
            seen.add(c);
            const o = document.createElement("option");
            o.value = c;
            o.textContent = c;
            sel.appendChild(o);
          });
          if (sel.options.length > 1) sel.selectedIndex = 1;
        } catch (e) { /* leave the placeholder */ }
      }
      await populateGraphJobs(sel.value);
      sel.onchange = async () => {
        if ($("#graph-mode")?.value === "all") await populateGraphJobsAll();
        else await populateGraphJobs(sel.value);
        loadRelationshipGraph();
      };
      const jb = $("#graph-job");
      if (jb) jb.onchange = loadRelationshipGraph;
      const sp = $("#graph-suppressed");
      if (sp) sp.onchange = loadRelationshipGraph;
      const mode = $("#graph-mode");
      if (mode) mode.onchange = async () => {
        const all = mode.value === "all";
        const prevJob = $("#graph-job")?.value || "";
        if (sp) sp.disabled = all;
        if (sel) {
          sel.disabled = all;
          sel.title = all
            ? "ログ全体モードでは対象ファイルからホストを自動判定します"
            : "";
          const pcLabel = sel.closest("label");
          if (pcLabel) pcLabel.style.display = all ? "none" : "";
        }
        if (all) await populateGraphJobsAll();
        else await populateGraphJobs(sel.value);
        const jb = $("#graph-job");
        if (prevJob && jb && [...jb.options].some(o => o.value === prevJob)) {
          jb.value = prevJob;
        }
        loadRelationshipGraph();
      };
      const gen = $("#graph-generate");
      if (gen) gen.onclick = async () => {
        const all = $("#graph-mode")?.value === "all";
        const prevJob = $("#graph-job")?.value || "";
        if (all) await populateGraphJobsAll();
        else await populateGraphJobs(sel.value);
        const jb = $("#graph-job");
        if (prevJob && jb && [...jb.options].some(o => o.value === prevJob)) {
          jb.value = prevJob;
        }
        loadRelationshipGraph();
      };
      const center = $("#graph-center");
      if (center) center.onclick = () => { centerRelationshipGraph(); closeGraphMenus(); };
      const fit = $("#graph-fit");
      if (fit) fit.onclick = () => { fitGraphView(); closeGraphMenus(); };
      const full = $("#graph-fullscreen");
      if (full) full.onclick = () => { toggleGraphFullscreen(); closeGraphMenus(); };
      const viewBtn = $("#graph-view-btn");
      if (viewBtn) viewBtn.onclick = (e) => {
        e.stopPropagation();
        toggleGraphMenu("#graph-view-menu");
      };
      const saveBtn = $("#graph-save-btn");
      if (saveBtn) saveBtn.onclick = (e) => {
        e.stopPropagation();
        toggleGraphMenu("#graph-save-menu");
      };
      document.querySelectorAll("[data-save]").forEach(b => {
        b.onclick = () => {
          saveRelationshipGraph(b.dataset.save || "svg");
          closeGraphMenus();
        };
      });
      const filterBtn = $("#graph-filter-btn");
      if (filterBtn) filterBtn.onclick = (e) => {
        e.stopPropagation();
        closeGraphMenus();
        $("#graph-filter-pop")?.classList.toggle("is-hidden");
      };
      const filterApply = $("#graph-filter-apply");
      if (filterApply) filterApply.onclick = () => {
        $("#graph-filter-pop")?.classList.add("is-hidden");
        if (_graphData) renderRelationshipGraph(_graphData);
      };
      const filterReset = $("#graph-filter-reset");
      if (filterReset) filterReset.onclick = () => {
        document.querySelectorAll("[data-gtype]").forEach(c => { c.checked = true; });
        const f = $("#graph-from"); if (f) f.value = "";
        const t = $("#graph-to"); if (t) t.value = "";
        const n = $("#graph-hide-noise"); if (n) n.checked = false;
        updateGraphFilterBadge();
        if (_graphData) renderRelationshipGraph(_graphData);
      };
      document.addEventListener("click", (e) => {
        if (!e.target.closest(".graph-menu-wrap")) {
          document.querySelectorAll(".graph-menu").forEach(m => m.classList.add("is-hidden"));
        }
        if (!e.target.closest("#graph-filter-pop") && !e.target.closest("#graph-filter-btn")) {
          $("#graph-filter-pop")?.classList.add("is-hidden");
        }
      });
      const prev = $("#graph-prev");
      if (prev) prev.onclick = () => moveGraphMatch(-1);
      const next = $("#graph-next");
      if (next) next.onclick = () => moveGraphMatch(1);
      const focusClear = $("#graph-focus-clear");
      if (focusClear) focusClear.onclick = () => {
        _graphFocusId = null;
        if (_graphData) renderRelationshipGraph(_graphData);
      };
      const zin = $("#graph-zoom-in");
      if (zin) zin.onclick = () => setGraphZoom(_graphZoom + 0.2);
      const zout = $("#graph-zoom-out");
      if (zout) zout.onclick = () => setGraphZoom(_graphZoom - 0.2);
      const sbtn = $("#graph-search-btn");
      if (sbtn) sbtn.onclick = runGraphSearch;
      const sclear = $("#graph-search-clear");
      if (sclear) sclear.onclick = clearGraphSearch;
      const sinput = $("#graph-search");
      if (sinput) sinput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); runGraphSearch(); }
        if (e.key === "Escape") clearGraphSearch();
      });
      const gh = $("#graph-host");
      if (gh && !gh.dataset.panBound) {
        gh.dataset.panBound = "1";
        let panning = false, sx = 0, sy = 0, sl = 0, st = 0, pid = null;
        gh.addEventListener("wheel", (e) => {
          if (!_graphSvg) return;
          // Two-finger trackpad scrolling must not zoom the graph. Require a
          // deliberate Ctrl/Cmd + wheel gesture; normal wheel scrolls/pans.
          if (!(e.ctrlKey || e.metaKey)) return;
          e.preventDefault();
          const rect = gh.getBoundingClientRect();
          const px = e.clientX - rect.left;
          const py = e.clientY - rect.top;
          const rx = (gh.scrollLeft + px) / Math.max(1, gh.scrollWidth);
          const ry = (gh.scrollTop + py) / Math.max(1, gh.scrollHeight);
          setGraphZoom(_graphZoom * (e.deltaY < 0 ? 1.12 : 0.89));
          requestAnimationFrame(() => {
            gh.scrollLeft = Math.max(0, rx * gh.scrollWidth - px);
            gh.scrollTop = Math.max(0, ry * gh.scrollHeight - py);
          });
        }, { passive: false });
        gh.addEventListener("pointerdown", (e) => {
          if (e.button !== 0 || !_graphSvg) return;
          panning = true;
          _graphDragMoved = false;
          pid = e.pointerId;
          sx = e.clientX; sy = e.clientY;
          sl = gh.scrollLeft; st = gh.scrollTop;
        });
        gh.addEventListener("pointermove", (e) => {
          if (!panning) return;
          const dx = e.clientX - sx, dy = e.clientY - sy;
          if (!_graphDragMoved && Math.abs(dx) + Math.abs(dy) > 8) {
            _graphDragMoved = true;
            gh.classList.add("rg-panning");
            try { gh.setPointerCapture(pid); } catch {}
          }
          if (!_graphDragMoved) return;
          gh.scrollLeft = sl - dx;
          gh.scrollTop = st - dy;
        });
        const endPan = () => {
          if (!panning) return;
          panning = false;
          gh.classList.remove("rg-panning");
          try {
            if (pid != null && gh.hasPointerCapture(pid)) gh.releasePointerCapture(pid);
          } catch {}
          pid = null;
          setTimeout(() => { _graphDragMoved = false; }, 0);
        };
        gh.addEventListener("pointerup", endPan);
        gh.addEventListener("pointercancel", endPan);
      }
      const detail = $("#graph-detail");
      if (detail) detail.addEventListener("click", (e) => {
        const close = e.target.closest("[data-gd-close]");
        if (close) {
          detail.classList.remove("has-detail");
          detail.textContent = "ノードまたは線をクリックすると詳細を表示します。";
          clearGraphHighlight();
          return;
        }
        const fbtn = e.target.closest("[data-focus-id]");
        if (fbtn) {
          _graphFocusId = fbtn.dataset.focusId;
          if (_graphData) renderRelationshipGraph(_graphData);
          return;
        }
        const btn = e.target.closest("[data-open-job]");
        if (!btn) return;
        const jid = btn.dataset.openJob;
        if (!jid) return;
        switchTab("results");
        setTimeout(() => openDetail(jid), 80);
      });
    }
    if (sel) {
      if ($("#graph-mode")?.value === "all") await populateGraphJobsAll();
      else await populateGraphJobs(sel.value);
    }
    loadRelationshipGraph();
  }

  async function populateGraphJobs(comp) {
    const jb = $("#graph-job");
    if (!jb) return;
    while (jb.options.length > 1) jb.remove(1);
    jb.options[0].textContent = "全ファイル";
    if (!comp) return;
    const inc = $("#graph-suppressed")?.checked ? "1" : "0";
    try {
      const d = await (await fetch(
        `/api/hosts/${encodeURIComponent(comp)}/relationship_jobs?include_suppressed=${inc}`
      )).json();
      const jobs = (d && d.jobs) || [];
      if (!jobs.length) {
        jb.options[0].textContent = "（このPCに関係ログなし）";
        return;
      }
      jobs.forEach(j => {
        const o = document.createElement("option");
        o.value = j.job_id;
        const when = j.started_at
          ? fmtWhen(new Date(j.started_at * 1000).toISOString())
          : j.job_id.slice(0, 8);
        const file = String(j.evidence_path || "").split("/").pop();
        o.textContent = `${when}・${file ? `${file}・` : ""}${(j.count || 0).toLocaleString()}件`;
        if (j.evidence_path) o.title = j.evidence_path;
        jb.appendChild(o);
      });
      if (lastJobId && !jb.value &&
          [...jb.options].some(o => o.value === lastJobId)) {
        jb.value = lastJobId;
      }
      if ($("#graph-mode")?.value === "all" && jb.options.length > 1 && !jb.value) {
        jb.selectedIndex = 1;
      }
    } catch (e) { /* keep "全ファイル" */ }
  }

  async function populateGraphJobsAll() {
    const jb = $("#graph-job");
    if (!jb) return;
    while (jb.options.length > 1) jb.remove(1);
    jb.options[0].textContent = "対象ファイルを選択";
    try {
      const d = await (await fetch("/api/jobs")).json();
      const jobs = (Array.isArray(d) ? d : (d.jobs || []))
        .filter(j => j && j.evidence_path);
      jobs.forEach(j => {
        const o = document.createElement("option");
        o.value = j.id;
        const when = j.started_at
          ? fmtWhen(new Date(j.started_at * 1000).toISOString())
          : String(j.id).slice(0, 8);
        o.textContent = `${when}・${String(j.evidence_path).split("/").pop() || j.id}`;
        jb.appendChild(o);
      });
      if (jb.options.length > 1) {
        if (lastJobId && [...jb.options].some(o => o.value === lastJobId)) {
          jb.value = lastJobId;
        } else {
          jb.selectedIndex = 1;
        }
      } else {
        jb.options[0].textContent = "（証跡パス付きジョブなし）";
      }
    } catch (e) {
      jb.options[0].textContent = "（ジョブ一覧を取得できません）";
    }
  }

  async function loadRelationshipGraph() {
    const host = $("#graph-host");
    if (!host) return;
    const comp = $("#graph-computer")?.value || "";
    const count = $("#graph-count");
    const mode = $("#graph-mode")?.value || "detections";
    const jobSel = $("#graph-job");
    if (!comp && mode !== "all") {
      _graphData = null;
      _graphSvg = null;
      host.style.height = "";
      host.innerHTML = `<div class="empty-state"><div class="icon">🕸️</div>
        <div class="title">PC を選んで関係図を生成してください</div>
        プロセスの起動とファイル作成の検知から関係を復元します。</div>`;
      if (count) count.textContent = "";
      return;
    }
    if (mode === "all" && !(jobSel?.value || "")) {
      _graphData = null;
      _graphSvg = null;
      host.style.height = "";
      host.innerHTML = `<div class="empty-state"><div class="icon">🕸️</div>
        <div class="title">ログ全体モードでは対象ファイルを選んでください</div>
        検知だけでなく、そのログに含まれるプロセス作成・ファイル作成・接続を読みます。</div>`;
      if (count) count.textContent = "";
      return;
    }
    host.innerHTML = `<div class="muted small" style="padding:14px">関係図を生成中…${
      mode === "all" ? "（ログ全体を読み込むため時間がかかる場合があります）" : ""}</div>`;
    if (count) count.textContent = "";
    const qs = new URLSearchParams();
    if (mode === "all") qs.set("mode", "all");
    const job = jobSel?.value || "";
    if (job) qs.set("job", job);
    if (mode !== "all" && $("#graph-suppressed")?.checked) qs.set("include_suppressed", "1");
    let data;
    try {
      const endpoint = mode === "all"
        ? `/api/graph/relationship_graph?${qs}`
        : `/api/hosts/${encodeURIComponent(comp)}/relationship_graph?${qs}`;
      const r = await fetch(endpoint);
      data = await r.json();
    } catch (e) {
      host.innerHTML = `<div class="muted small" style="padding:14px;color:#c0392b">
        関係図の取得に失敗しました: ${escapeHtml(String(e))}</div>`;
      return;
    }
    if (data.error) {
      host.innerHTML = `<div class="muted small" style="padding:14px">エラー: ${escapeHtml(data.error)}</div>`;
      return;
    }
    _graphData = data;
    renderRelationshipGraph(data);
  }

  function graphEmptyHtml(data) {
    const notes = (data.notes || []).map(n => `<p>${escapeHtml(n)}</p>`).join("");
    const present = (data.present || []).map(p =>
      `<li><b>${escapeHtml(p.channel || "(不明)")}</b> ・ EventID ${escapeHtml(String(p.event_id))} <span class="muted small">— ${p.count.toLocaleString()}件</span></li>`
    ).join("");
    return `<div class="empty-state" style="text-align:left;max-width:700px;margin:0 auto">
      <div style="text-align:center"><div class="icon">🕸️</div>
      <div class="title">関係を描けるログがありません</div></div>
      ${notes || "<p>プロセス作成またはファイル作成の検知が必要です。</p>"}
      ${present ? `<div class="pt-present"><div class="muted small">このデータに含まれるイベント（上位）:</div>
        <ul class="pt-present-list">${present}</ul></div>` : ""}
    </div>`;
  }

  function graphFilterState() {
    const types = new Set();
    document.querySelectorAll("[data-gtype]").forEach(c => {
      if (c.checked) types.add(c.dataset.gtype);
    });
    const from = $("#graph-from")?.value || "";
    const to = $("#graph-to")?.value || "";
    const hideNoise = !!$("#graph-hide-noise")?.checked;
    return { types, from, to, hideNoise };
  }

  function updateGraphFilterBadge() {
    const s = graphFilterState();
    let n = 0;
    if (s.types.size < 5) n++;
    if (s.from || s.to) n++;
    if (s.hideNoise) n++;
    const b = $("#graph-filter-badge");
    if (b) b.textContent = n ? `(${n})` : "";
  }

  function filterGraphView(data) {
    const s = graphFilterState();
    const typeOk = (n) => s.types.has(n.type);
    const fromMs = s.from ? Date.parse(s.from) : NaN;
    const toMs = s.to ? Date.parse(s.to) : NaN;
    const timeOk = (n) => {
      const t0 = Date.parse(n.ts || "");
      const t1 = Date.parse(n.last_ts || n.ts || "");
      if (Number.isFinite(fromMs) && Number.isFinite(t1) && t1 < fromMs) return false;
      if (Number.isFinite(toMs) && Number.isFinite(t0) && t0 > toMs) return false;
      return true;
    };
    let nodes = (data.nodes || []).filter(n => typeOk(n) && timeOk(n));
    let allowed = new Set(nodes.map(n => n.id));
    let edges = (data.edges || []).filter(e => allowed.has(e.from) && allowed.has(e.to));

    if (_graphFocusId) {
      if (!allowed.has(_graphFocusId)) {
        _graphFocusId = null;
      } else {
        const keep = new Set([_graphFocusId]);
        edges.forEach(e => {
          if (e.from === _graphFocusId || e.to === _graphFocusId) {
            keep.add(e.from); keep.add(e.to);
          }
        });
        nodes = nodes.filter(n => keep.has(n.id));
        allowed = keep;
        edges = edges.filter(e => allowed.has(e.from) && allowed.has(e.to));
      }
    }

    if (s.hideNoise) {
      const degree = new Map();
      edges.forEach(e => {
        degree.set(e.from, (degree.get(e.from) || 0) + 1);
        degree.set(e.to, (degree.get(e.to) || 0) + 1);
      });
      nodes = nodes.filter(n => {
        if ((degree.get(n.id) || 0) === 0) return false;
        if (data.mode !== "all" && !n.detection
            && (n.type === "file" || n.type === "network" || n.type === "object")
            && (degree.get(n.id) || 0) <= 1) return false;
        return true;
      });
      allowed = new Set(nodes.map(n => n.id));
      edges = edges.filter(e => allowed.has(e.from) && allowed.has(e.to));
    }

    const countType = (t) => nodes.filter(n => n.type === t).length;
    return {
      nodes, edges,
      stats: {
        nodes: nodes.length,
        processes: countType("process"),
        identities: countType("identity"),
        files: countType("file"),
        objects: countType("object"),
        network: countType("network"),
        edges: edges.length,
        truncated: data.stats?.truncated || false,
      },
    };
  }

  function renderRelationshipGraph(data) {
    const host = $("#graph-host");
    if (!host) return;
    const count = $("#graph-count");
    if (!data.has_data) {
      _graphSvg = null;
      host.style.height = "";
      host.innerHTML = graphEmptyHtml(data);
      if (count) count.textContent = "";
      const detail = $("#graph-detail");
      if (detail) {
        detail.classList.remove("has-detail");
        const scope = data.mode === "all"
          ? "対象: このファイルの全イベント"
          : (data.job_id ? "対象: このファイルの検知" : "対象: ホスト全体の検知");
        detail.textContent = [scope, data.source ? `読込: ${data.source}` : "",
          (data.notes || []).join(" ")].filter(Boolean).join(" ・ ");
      }
      return;
    }
    const view = filterGraphView(data);
    if (!view.nodes.length) {
      _graphSvg = null;
      host.style.height = "";
      host.innerHTML = `<div class="empty-state"><div class="icon">🕸️</div>
        <div class="title">フィルタ条件に合うノードがありません</div>
        表示タイプ・時間範囲・「ノイズを隠す」を調整してください。</div>`;
      if (count) count.textContent = `0 / ${data.nodes.length} ノード`;
      return;
    }
    const layout = layoutRelationshipGraph(view.nodes, view.edges);
    _graphSize = { w: layout.width, h: layout.height };
    _graphLayout = layout;
    host.style.height = (layout.height > 620 ? "620px" : Math.max(330, layout.height + 18) + "px");
    const svg = svgEl("svg", {
      viewBox: `0 0 ${layout.width} ${layout.height}`,
      class: "rg-svg",
      role: "img",
      "aria-label": "プロセスとファイルの関係図",
    });
    const defs = svgEl("defs", {}, svg);
    [
      ["arrow-hit", "#b45309"],
      ["arrow-proc", "#2f6fb0"],
      ["arrow-file", "#7a8699"],
      ["arrow-net", "#7b4fa0"],
      ["arrow-audit", "#2e7d6b"],
    ].forEach(([id, color]) => {
      const marker = svgEl("marker", {
        id, viewBox: "0 0 10 10", refX: "9", refY: "5",
        markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse",
      }, defs);
      svgEl("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: color }, marker);
    });

    // Edges first so nodes sit on top.
    (layout.edges || []).forEach(edge => {
      const a = layout.pos.get(edge.from);
      const b = layout.pos.get(edge.to);
      if (!a || !b) return;
      const g = svgEl("g", { class: "rg-edge rg-edge-" + edge.type,
        "data-edge-from": edge.from, "data-edge-to": edge.to,
        "data-edge-label": edge.label || "",
        "data-edge-type": edge.type || "",
        "data-edge-count": String(edge.count || 1) }, svg);
      const path = edgePath(a, b, edge.type);
      const color = edge.inferred ? "#7a8699"
        : (edge.type === "spawn" ? "#2f6fb0"
          : (edge.type === "connect" || edge.type === "resolve" ? "#7b4fa0"
            : (edge.type === "audit" ? "#2e7d6b" : "#b45309")));
      const line = svgEl("path", {
        d: path.d, fill: "none", stroke: color,
        "stroke-width": edge.inferred ? "1.4" : "1.8",
        "stroke-dasharray": edge.inferred ? "5 4" : "",
        "marker-end": `url(#${edge.inferred ? "arrow-file" : (edge.type === "spawn" ? "arrow-proc" : (edge.type === "connect" || edge.type === "resolve" ? "arrow-net" : (edge.type === "audit" ? "arrow-audit" : "arrow-hit")))})`,
      }, g);
      const title = svgEl("title", {}, line);
      title.textContent = `${edge.label}${edge.count > 1 ? ` ×${edge.count}` : ""}`;
      if (view.edges.length <= 70) {
        const label = svgEl("text", {
          x: path.mx, y: path.my, class: "rg-edge-label",
          "text-anchor": "middle",
        }, g);
        label.textContent = edge.label;
      }
    });

    // Nodes.
    (view.nodes || []).forEach(node => {
      const p = layout.pos.get(node.id);
      if (!p) return;
      const hit = !!node.detection;
      const kind = node.type === "file" ? "rg-node-file"
        : node.type === "network" ? "rg-node-net"
          : node.type === "identity" ? "rg-node-identity"
            : node.type === "object" ? "rg-node-object" : "rg-node-proc";
      const cls = "rg-node " + kind
        + (hit ? " rg-node-hit" : "") + (node.synthetic ? " rg-node-synth" : "");
      const g = svgEl("g", {
        class: cls, "data-node-id": node.id,
        transform: `translate(${p.x},${p.y})`,
      }, svg);
      svgEl("rect", {
        x: 0, y: 0, width: p.w, height: p.h, rx: 8,
        class: "rg-box",
      }, g);
      const label = svgEl("text", { x: 10, y: 20, class: "rg-label" }, g);
      label.textContent = truncateText(node.label || node.path || "(不明)", 30);
      const sub = svgEl("text", { x: 10, y: 37, class: "rg-sub" }, g);
      if (node.type === "file") {
        sub.textContent = node.count > 1 ? `作成 ×${node.count}` : "作成されたファイル";
      } else if (node.type === "network") {
        const bits = [];
        if (node.protocol) bits.push(String(node.protocol).toUpperCase());
        if (node.port) bits.push("port " + node.port);
        if (node.ip && node.ip !== node.host) bits.push(node.ip);
        sub.textContent = truncateText(bits.join(" ・ ") || "通信先", 40);
      } else if (node.type === "identity") {
        sub.textContent = truncateText([node.domain, node.account].filter(Boolean).join(" ・ ") || "ユーザー / アカウント", 40);
      } else if (node.type === "object") {
        sub.textContent = truncateText(node.object_type || "対象オブジェクト", 40);
      } else {
        const bits = [];
        if (node.pid) bits.push("PID " + node.pid);
        if (node.user) bits.push(node.user);
        sub.textContent = truncateText(bits.join(" ・ ") || "プロセス", 40);
      }
      if (node.synthetic) {
        const s = svgEl("text", { x: p.w - 10, y: 20, class: "rg-synth-tag",
          "text-anchor": "end" }, g);
        s.textContent = "推定";
      }
      if (hit) {
        const h = svgEl("text", {
          x: p.w - 10, y: p.h - 9, class: "rg-hit-tag", "text-anchor": "end",
        }, g);
        h.textContent = "検知";
      }
      const title = svgEl("title", {}, g);
      const detail = node.type === "file"
        ? `${node.path || ""}\n作成プロセス: ${node.creator_image || "(不明)"}`
        : node.type === "network"
          ? `${node.label || ""}\n${node.ip || ""}${node.port ? ":" + node.port : ""}\n${node.protocol || ""}`
          : node.type === "identity"
            ? `${node.label || ""}\n${node.domain || ""}\\${node.account || ""}`
            : node.type === "object"
              ? `${node.label || ""}\n${node.path || ""}\n${node.object_type || ""}`
              : `${node.image || ""}\n${node.cmdline || ""}\n${node.ts || ""}`;
      title.textContent = detail.trim();
    });

    host.innerHTML = "";
    host.appendChild(svg);
    _graphSvg = svg;
    _graphZoom = 1;
    _graphMatches = [];
    _graphMatchIndex = 0;
    host.classList.remove("rg-searching");
    host.classList.toggle("rg-dense", (view.edges || []).length > 40);
    const sc = $("#graph-search-count");
    if (sc) sc.textContent = "";
    const si = $("#graph-search");
    if (si) si.value = "";
    updateGraphFilterBadge();
    const fb = $("#graph-focus-badge");
    if (fb) {
      fb.classList.toggle("is-hidden", !_graphFocusId);
      const fn = $("#graph-focus-name");
      if (fn && _graphFocusId) {
        const n = (data.nodes || []).find(x => x.id === _graphFocusId);
        fn.textContent = n?.label || n?.path || _graphFocusId;
      }
    }
    applyGraphZoom();
    if (count) {
      const s = view.stats || {};
      const parts = [`${s.processes || 0} プロセス`];
      if (s.identities) parts.push(`${s.identities} ユーザー`);
      if (s.objects) parts.push(`${s.objects} 対象`);
      parts.push(`${s.files || 0} ファイル`);
      parts.push(`${s.network || 0} ネットワーク`);
      parts.push(`${s.edges || 0} 関係`);
      const filtered = view.nodes.length !== (data.nodes || []).length
        || view.edges.length !== (data.edges || []).length;
      count.textContent = parts.join(" / ")
        + (filtered ? `（表示 ${view.nodes.length} / 全 ${(data.nodes || []).length} ノード）` : "")
        + (s.truncated ? "（上限で一部省略）" : "");
    }
    const detail = $("#graph-detail");
    if (detail) {
      detail.classList.remove("has-detail");
      const scope = data.mode === "all"
        ? "対象: このファイルの全イベント"
        : (data.job_id ? "対象: このファイルの検知" : "対象: ホスト全体の検知");
      const src = data.source ? `読込: ${data.source}` : "";
      detail.textContent = [scope, src, (data.notes || []).join(" ")]
        .filter(Boolean).join(" ・ ") || "ノードをクリックすると詳細を表示します。";
    }
    host.onclick = (e) => {
      if (_graphDragMoved) { _graphDragMoved = false; return; }
      const g = e.target.closest("[data-node-id]");
      if (g && _graphData) {
        graphShowNode(g.dataset.nodeId);
        highlightGraphNode(g.dataset.nodeId);
        return;
      }
      const edgeEl = e.target.closest(".rg-edge");
      if (edgeEl && _graphData) {
        graphShowEdge(edgeEl);
        return;
      }
      clearGraphHighlight();
      const detail = $("#graph-detail");
      if (detail) {
        detail.classList.remove("has-detail");
        detail.textContent = "";
      }
    };
  }

  function truncateText(s, n) {
    s = String(s || "");
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  function svgEl(tag, attrs, parent) {
    const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    if (attrs) {
      Object.entries(attrs).forEach(([k, v]) => {
        if (v !== undefined && v !== null) e.setAttribute(k, String(v));
      });
    }
    if (parent) parent.appendChild(e);
    return e;
  }

  function edgePath(a, b, type) {
    const acx = a.x + a.w / 2, acy = a.y + a.h / 2;
    const bcx = b.x + b.w / 2, bcy = b.y + b.h / 2;
    let sx, sy, tx, ty;
    if (type === "spawn") {
      sx = acx < bcx ? a.x + a.w : a.x;
      sy = acy;
      tx = acx < bcx ? b.x : b.x + b.w;
      ty = bcy;
    } else if (type === "create" || type === "connect" || type === "resolve"
      || type === "audit") {
      sx = acx; sy = a.y + a.h;
      tx = bcx; ty = b.y;
    } else {
      sx = acx; sy = a.y;
      tx = bcx; ty = b.y + b.h;
    }
    const dx = tx - sx, dy = ty - sy;
    const bend = Math.max(20, Math.min(70, Math.abs(dx) * 0.18 + Math.abs(dy) * 0.12));
    const c1x = sx + (type === "spawn" ? dx * 0.35 : 0);
    const c1y = sy + (type === "spawn" ? 0 : (dy < 0 ? -bend : bend));
    const c2x = tx - (type === "spawn" ? dx * 0.35 : 0);
    const c2y = ty - (type === "spawn" ? 0 : (dy < 0 ? -bend : bend));
    return {
      d: `M ${sx} ${sy} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${tx} ${ty}`,
      mx: (sx + tx) / 2,
      my: (sy + ty) / 2,
    };
  }

  function layoutRelationshipGraph(nodes, edges) {
    const byId = new Map((nodes || []).map(n => [n.id, n]));
    const procs = (nodes || []).filter(n => n.type === "process" || n.type === "identity");
    const leaves = (nodes || []).filter(n => n.type === "file" || n.type === "network" || n.type === "object");
    const spawn = (edges || []).filter(e => e.type === "spawn");
    const children = new Map();
    const hasParent = new Set();
    spawn.forEach(e => {
      if (!byId.has(e.from) || !byId.has(e.to)) return;
      if (!children.has(e.from)) children.set(e.from, []);
      children.get(e.from).push(e.to);
      hasParent.add(e.to);
    });
    const level = new Map();
    const queue = [];
    procs.forEach(n => {
      if (!hasParent.has(n.id)) { level.set(n.id, 0); queue.push(n.id); }
    });
    for (let qi = 0; qi < queue.length; qi++) {
      const id = queue[qi];
      const lv = level.get(id) || 0;
      (children.get(id) || []).forEach(cid => {
        const cand = lv + 1;
        if (!level.has(cid) || cand < (level.get(cid) || 0)) {
          level.set(cid, cand);
          queue.push(cid);
        }
      });
    }
    // Cycles / disconnected nodes: give every remaining process a level.
    procs.forEach(n => { if (!level.has(n.id)) level.set(n.id, 0); });
    const byLevel = new Map();
    procs.forEach(n => {
      const lv = level.get(n.id) || 0;
      if (!byLevel.has(lv)) byLevel.set(lv, []);
      byLevel.get(lv).push(n);
    });
    const pos = new Map();
    const procW = 200, procH = 54, fileW = 230, fileH = 46;
    let maxProcY = 0;
    [...byLevel.keys()].sort((a, b) => a - b).forEach(lv => {
      const list = byLevel.get(lv).sort((a, b) =>
        String(a.ts || "").localeCompare(String(b.ts || "")) ||
        String(a.label || "").localeCompare(String(b.label || "")));
      list.forEach((n, i) => {
        const x = 60 + lv * 280 + (n.type === "identity" ? i * 300 : 0);
        const y = 70 + (n.type === "identity" ? 0 : i * 110);
        pos.set(n.id, { x, y, w: procW, h: procH, node: n });
        maxProcY = Math.max(maxProcY, y + procH);
      });
    });

    // Files and network destinations are grouped under the process that
    // created / contacted them.
    const creatorOf = new Map();
    (edges || []).filter(e => e.type === "create" || e.type === "connect"
      || e.type === "resolve" || e.type === "audit").forEach(e => {
      if (!creatorOf.has(e.to)) creatorOf.set(e.to, e.from);
    });
    const groups = new Map();
    leaves.forEach(n => {
      const c = creatorOf.get(n.id) || "";
      if (!groups.has(c)) groups.set(c, []);
      groups.get(c).push(n);
    });
    const baseY = maxProcY + 90;
    const orderedGroups = [...groups.entries()].sort((a, b) => {
      const pa = pos.get(a[0]), pb = pos.get(b[0]);
      return (pa ? pa.x : 1e9) - (pb ? pb.x : 1e9);
    });
    orderedGroups.forEach(([cid, list], gi) => {
      const cp = pos.get(cid);
      const x = cp ? cp.x : 60 + (gi % 5) * 250;
      list.sort((a, b) => String(a.ts || "").localeCompare(String(b.ts || "")));
      list.forEach((n, i) => {
        const y = baseY + i * 66;
        pos.set(n.id, { x, y, w: fileW, h: fileH, node: n });
      });
    });
    // Any orphan leaves in a grid.
    const orphans = leaves.filter(n => !pos.has(n.id));
    const maxRows = Math.max(1, ...[...groups.values()].map(g => g.length));
    orphans.forEach((n, i) => {
      const x = 60 + (i % 5) * 250;
      const y = baseY + maxRows * 66 + Math.floor(i / 5) * 66;
      pos.set(n.id, { x, y, w: fileW, h: fileH, node: n });
    });

    let width = 1000, height = 600;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    pos.forEach(p => {
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + p.w);
      maxY = Math.max(maxY, p.y + p.h);
    });
    if (!Number.isFinite(minX)) { minX = 0; minY = 0; maxX = 0; maxY = 0; }
    const contentW = maxX - minX;
    const contentH = maxY - minY;
    const pad = 70;
    width = Math.max(900, contentW + pad * 2);
    height = Math.max(420, contentH + pad * 2);
    // Center small graphs instead of leaving everything in the top-left.
    const ox = (width - contentW) / 2 - minX;
    const oy = (height - contentH) / 2 - minY;
    pos.forEach(p => { p.x += ox; p.y += oy; });
    return { pos, edges: edges || [], width, height };
  }

  function graphShowNode(id) {
    const node = (_graphData?.nodes || []).find(n => n.id === id);
    const host = $("#graph-detail");
    if (!node || !host) return;
    const typeLabel = {
      process: "プロセス", file: "ファイル", network: "ネットワーク",
      identity: "ユーザー", object: "対象オブジェクト",
    }[node.type] || "ノード";
    const rows = [];
    const add = (k, v) => {
      if (v !== undefined && v !== null && String(v) !== "") {
        rows.push(`<div class="gd-k">${escapeHtml(k)}</div><div class="gd-v">${v}</div>`);
      }
    };
    const code = (v) => `<code>${escapeHtml(String(v))}</code>`;

    if (node.type === "file") {
      const path = String(node.path || "");
      const slash = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
      const dir = slash >= 0 ? path.slice(0, slash) : "";
      const name = slash >= 0 ? path.slice(slash + 1) : (node.label || path);
      add("ディレクトリ", dir ? code(dir) : "—");
      add("ファイル名", escapeHtml(name));
      add("フルパス", path ? code(path) : "—");
      if (node.creator_image) add("作成プロセス", code(node.creator_image));
      add("作成イベント", `${node.count || 0} 件`);
    } else if (node.type === "network") {
      add("接続先", escapeHtml(node.label || ""));
      if (node.host) add("ホスト", code(node.host));
      if (node.ip) add("IP", code(node.ip));
      if (node.port) add("ポート", escapeHtml(String(node.port)));
      if (node.protocol) add("プロトコル", escapeHtml(node.protocol));
      if (node.creator_image) add("接続元", code(node.creator_image));
      add("通信イベント", `${node.count || 0} 件`);
    } else if (node.type === "identity") {
      if (node.domain) add("ドメイン", escapeHtml(node.domain));
      if (node.account) add("アカウント", code(node.account));
      add("操作イベント", `${node.count || 0} 件`);
    } else if (node.type === "object") {
      if (node.object_type) add("種別", escapeHtml(node.object_type));
      if (node.path) add("パス / DN", code(node.path));
      add("操作イベント", `${node.count || 0} 件`);
    } else {
      if (node.image) add("実行ファイル", code(node.image));
      if (node.cmdline) add("コマンドライン", code(node.cmdline));
      if (node.pid) add("PID", escapeHtml(String(node.pid)));
      if (node.user) add("ユーザー", escapeHtml(node.user));
      if (node.integrity) add("整合性レベル", escapeHtml(node.integrity));
      if (node.synthetic) add("備考", "推定ノード（起動元の実行情報なし）");
    }
    if (node.ts) add("初回", escapeHtml(fmtWhen(node.ts)));
    if (node.last_ts && node.last_ts !== node.ts) {
      add("最終", escapeHtml(fmtWhen(node.last_ts)));
    }
    if (node.detection) {
      add("検知", `<span class="gd-hit">${escapeHtml(node.detection.rule_title || "")}</span>（${escapeHtml(node.detection.level || "")}）`);
    }
    const detectBtn = node.detection
      ? `<button class="ghost-btn small" data-open-job="${escapeHtml(node.detection.job_id || "")}">検知を開く</button>`
      : "";
    const focusBtn = `<button class="ghost-btn small" data-focus-id="${escapeHtml(node.id)}">このノードにフォーカス</button>`;
    host.classList.add("has-detail");
    host.innerHTML = `<div class="gd-head">
        <span class="gd-type">${typeLabel}</span>
        <span class="gd-name">${escapeHtml(node.label || node.path || "(不明)")}</span>
        ${detectBtn}
        ${focusBtn}
        <button class="gd-close" type="button" data-gd-close title="閉じる">×</button>
      </div>
      <div class="gd-grid">${rows.join("")}</div>`;
  }

  function graphShowEdge(edgeEl) {
    const host = $("#graph-detail");
    if (!host) return;
    const from = (_graphData?.nodes || []).find(n => n.id === edgeEl.dataset.edgeFrom);
    const to = (_graphData?.nodes || []).find(n => n.id === edgeEl.dataset.edgeTo);
    const label = edgeEl.dataset.edgeLabel || "関係";
    const type = edgeEl.dataset.edgeType || "";
    const count = edgeEl.dataset.edgeCount || "1";
    const typeJa = {
      spawn: "起動", create: "作成", execute: "実行（推定）",
      connect: "接続", resolve: "名前解決", audit: "監査操作",
    }[type] || type;
    host.classList.add("has-detail");
    host.innerHTML = `<div class="gd-head">
        <span class="gd-type">関係</span>
        <span class="gd-name">${escapeHtml(label)}</span>
        <button class="gd-close" type="button" data-gd-close title="閉じる">×</button>
      </div>
      <div class="gd-grid">
        <div class="gd-k">関係種別</div><div class="gd-v">${escapeHtml(typeJa)}</div>
        <div class="gd-k">From</div><div class="gd-v">${escapeHtml(from?.label || from?.path || edgeEl.dataset.edgeFrom || "")}</div>
        <div class="gd-k">To</div><div class="gd-v">${escapeHtml(to?.label || to?.path || edgeEl.dataset.edgeTo || "")}</div>
        <div class="gd-k">イベント数</div><div class="gd-v">${escapeHtml(String(count))} 件</div>
      </div>`;
  }

  function graphSearchText(node) {
    return [node.label, node.image, node.path, node.cmdline, node.host,
      node.ip, node.account, node.domain, node.object_type,
      node.creator_image].filter(Boolean).join(" ").toLowerCase();
  }

  function runGraphSearch() {
    const input = $("#graph-search");
    const term = (input?.value || "").trim().toLowerCase();
    const count = $("#graph-search-count");
    if (!term) { clearGraphSearch(); return; }
    if (!_graphData || !_graphSvg) {
      if (count) count.textContent = "先に図を生成してください";
      return;
    }
    const visible = _graphLayout?.pos;
    _graphMatches = (_graphData.nodes || []).filter(n =>
      (!visible || visible.has(n.id)) && graphSearchText(n).includes(term));
    _graphMatchIndex = 0;
    if (!_graphMatches.length) {
      clearGraphHighlight();
      if (count) count.textContent = "0 件";
      return;
    }
    focusGraphMatch();
  }

  function focusGraphMatch() {
    if (!_graphMatches.length) return;
    const count = $("#graph-search-count");
    if (count) {
      count.textContent = _graphMatches.length > 1
        ? `${_graphMatchIndex + 1} / ${_graphMatches.length} 件`
        : "1 件ヒット";
    }
    applyGraphHighlight(_graphMatches.map(n => n.id), false);
    graphShowNode(_graphMatches[_graphMatchIndex].id);
    focusGraphNode(_graphMatches[_graphMatchIndex].id);
  }

  function moveGraphMatch(dir) {
    if (!_graphMatches.length) return;
    _graphMatchIndex = (_graphMatchIndex + dir + _graphMatches.length)
      % _graphMatches.length;
    focusGraphMatch();
  }

  function clearGraphSearch() {
    _graphMatches = [];
    _graphMatchIndex = 0;
    clearGraphHighlight();
    const count = $("#graph-search-count");
    if (count) count.textContent = "";
  }

  function clearGraphHighlight() {
    const host = $("#graph-host");
    if (host) host.classList.remove("rg-searching");
    document.querySelectorAll("#graph-host .rg-node, #graph-host .rg-edge")
      .forEach(el => el.classList.remove("rg-dim", "rg-match"));
  }

  function highlightGraphNode(id) {
    applyGraphHighlight([id], true);
  }

  function applyGraphHighlight(matchIds, includeNeighbors) {
    const ids = new Set(matchIds || []);
    if (!ids.size) { clearGraphHighlight(); return; }
    const related = new Set(ids);
    if (includeNeighbors) {
      (_graphData?.edges || []).forEach(e => {
        if (ids.has(e.from) || ids.has(e.to)) {
          related.add(e.from);
          related.add(e.to);
        }
      });
    }
    const host = $("#graph-host");
    if (host) host.classList.add("rg-searching");
    document.querySelectorAll("#graph-host .rg-node").forEach(el => {
      const id = el.dataset.nodeId;
      el.classList.toggle("rg-match", ids.has(id));
      el.classList.toggle("rg-dim", !related.has(id));
    });
    document.querySelectorAll("#graph-host .rg-edge").forEach(el => {
      const match = ids.has(el.dataset.edgeFrom) || ids.has(el.dataset.edgeTo);
      el.classList.toggle("rg-match", match);
      el.classList.toggle("rg-dim", !match);
    });
  }

  function focusGraphNode(id) {
    const host = $("#graph-host");
    const svg = _graphSvg;
    const p = _graphLayout?.pos.get(id);
    if (!host || !svg || !p) return;
    // When the user searches from a zoomed-out view, bring the view back to
    // 100% so the matching node and its arrows are readable.
    if (_graphZoom < 1) {
      _graphZoom = 1;
      applyGraphZoom();
    }
    const rect = svg.getBoundingClientRect();
    const scale = _graphSize.w ? rect.width / _graphSize.w : 1;
    const x = (p.x + p.w / 2) * scale;
    const y = (p.y + p.h / 2) * scale;
    const nodeEl = document.querySelector(
      `#graph-host .rg-node[data-node-id="${id}"]`);
    if (nodeEl && nodeEl.scrollIntoView) {
      nodeEl.scrollIntoView({ block: "center", inline: "center",
                              behavior: "smooth" });
      return;
    }
    host.scrollTo({
      left: Math.max(0, x - host.clientWidth / 2),
      top: Math.max(0, y - host.clientHeight / 2),
      behavior: "smooth",
    });
  }

  function setGraphZoom(z) {
    _graphZoom = Math.max(0.2, Math.min(2.5, z));
    applyGraphZoom();
  }
  function applyGraphZoom() {
    const label = $("#graph-zoom-label");
    if (label) label.textContent = Math.round(_graphZoom * 100) + "%";
    if (_graphSvg) {
      _graphSvg.style.width = (_graphZoom * 100) + "%";
      _graphSvg.style.height = "auto";
    }
  }
  function closeGraphMenus() {
    document.querySelectorAll(".graph-menu").forEach(m => m.classList.add("is-hidden"));
  }
  function toggleGraphMenu(sel) {
    const menu = document.querySelector(sel);
    if (!menu) return;
    const show = menu.classList.contains("is-hidden");
    closeGraphMenus();
    if (show) menu.classList.remove("is-hidden");
  }

  function fitGraphView() {
    const host = $("#graph-host");
    if (!host || !_graphSize.w || !_graphSize.h) return;
    const z = Math.min(
      (host.clientWidth - 28) / _graphSize.w,
      (host.clientHeight - 28) / _graphSize.h,
      1);
    setGraphZoom(Math.max(0.25, z));
    setTimeout(() => {
      host.scrollLeft = Math.max(0, (host.scrollWidth - host.clientWidth) / 2);
      host.scrollTop = Math.max(0, (host.scrollHeight - host.clientHeight) / 2);
    }, 20);
  }

  function centerRelationshipGraph() {
    const host = $("#graph-host");
    if (!host) return;
    _graphZoom = 1;
    applyGraphZoom();
    host.scrollLeft = Math.max(0, (host.scrollWidth - host.clientWidth) / 2);
    host.scrollTop = 0;
  }
  function toggleGraphFullscreen() {
    const card = document.querySelector(".graph-card");
    const btn = $("#graph-fullscreen");
    if (!card) return;
    const on = card.classList.toggle("graph-fullscreen");
    document.body.classList.toggle("graph-fullscreen-open", on);
    if (btn) btn.textContent = on ? "全画面を戻す" : "全画面";
    if (on && _graphZoom < 1) {
      _graphZoom = 1;
      applyGraphZoom();
    }
    setTimeout(() => {
      const host = $("#graph-host");
      if (host) {
        host.scrollLeft = Math.max(0, (host.scrollWidth - host.clientWidth) / 2);
        host.scrollTop = 0;
      }
    }, 30);
  }
  function graphSvgXml() {
    const clone = _graphSvg.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", String(_graphSize.w));
    clone.setAttribute("height", String(_graphSize.h));
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.textContent = `
      .rg-box{fill:#fff;stroke:#b9c3d2;stroke-width:1.2}
      .rg-node-proc .rg-box{fill:#eef5ff;stroke:#8db4e2}
      .rg-node-file .rg-box{fill:#fff8d8;stroke:#d6b656}
      .rg-node-net .rg-box{fill:#f2eafb;stroke:#9b72c7}
      .rg-node-identity .rg-box{fill:#e8f5ee;stroke:#2e7d6b}
      .rg-node-object .rg-box{fill:#f3f0e6;stroke:#a18b5b}
      .rg-node-hit .rg-box{stroke:#c0392b;stroke-width:2}
      .rg-node-synth .rg-box{stroke-dasharray:5 4}
      .rg-label{font:600 12px sans-serif;fill:#1f2937}
      .rg-sub{font:10px sans-serif;fill:#5b6778}
      .rg-synth-tag{font:9px sans-serif;fill:#8a6d00}
      .rg-hit-tag{font:9px sans-serif;fill:#b03a2e}
      .rg-edge-label{font:10px sans-serif;fill:#5b6778;paint-order:stroke;stroke:#fff;stroke-width:3px}
    `;
    clone.insertBefore(style, clone.firstChild);
    return new XMLSerializer().serializeToString(clone);
  }

  function saveRelationshipGraph(format = "svg") {
    if (!_graphSvg) return;
    const xml = graphSvgXml();
    if (format === "svg") {
      const blob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "relationship-graph.svg";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      return;
    }
    const svgBlob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(2, 6000 / Math.max(1, _graphSize.w),
                             6000 / Math.max(1, _graphSize.h));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(_graphSize.w * scale));
      canvas.height = Math.max(1, Math.round(_graphSize.h * scale));
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(blob => {
        if (!blob) return;
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "relationship-graph.png";
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      }, "image/png");
      URL.revokeObjectURL(url);
    };
    img.src = url;
  }

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
      const gbtn = $("#host-pivot-graph");
      if (gbtn) gbtn.onclick = () => {
        switchTab("graph");
        setTimeout(async () => {
          const sel = $("#graph-computer");
          if (!sel) return;
          if (![...sel.options].some(o => o.value === host)) {
            const o = document.createElement("option");
            o.value = host;
            o.textContent = host;
            sel.appendChild(o);
          }
          sel.value = host;
          await populateGraphJobs(host);
          loadRelationshipGraph();
        }, 80);
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
                          "TEXTAREA","SCRIPT","STYLE","PRE","LABEL","SUMMARY"]);
    // 用語を長い順に (ATT&CK が AT より先に当たるように)
    const terms = Object.keys(GLOSSARY).sort((a,b)=>b.length-a.length);

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        let p = node.parentNode;
        while (p && p !== root) {
          if (p.nodeType === 1) {
            if (SKIP.has(p.tagName)) return NodeFilter.FILTER_REJECT;
            if (p.hasAttribute && p.hasAttribute("data-no-glossary")) return NodeFilter.FILTER_REJECT;
            if (p.classList && (p.classList.contains("term") ||
                p.classList.contains("home-kicker") ||
                p.classList.contains("page-head") ||
                p.classList.contains("brand") ||
                p.classList.contains("tab") ||
                p.classList.contains("snav"))) return NodeFilter.FILTER_REJECT;
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
  health(); refreshWorkspace(); refreshJobs(); updateScanButton();
  refreshStatusBar();
  installGlossary();
  setInterval(refreshWorkspace, 5000);
  setInterval(refreshStatusBar, 15000);   // status bar refresh
})();
