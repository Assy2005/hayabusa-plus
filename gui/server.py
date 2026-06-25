from __future__ import annotations
"""
Hayabusa GUI — localhost web frontend for the Hayabusa DFIR scanner.

Pure Python stdlib (no external deps). Wraps the Hayabusa CLI binary as a
subprocess and exposes a small JSON API plus a static SPA on http://127.0.0.1:8787.

Design notes
------------
* Subprocess isolation: each scan is a `hayabusa json-timeline` invocation. The
  GUI never parses EVTX itself; Hayabusa remains the trust boundary for parsing
  and Sigma matching. This keeps the GUI a thin telemetry/control plane.
* JSONL streaming: Hayabusa is invoked with `--JSONL-output`, which emits one
  detection per line. We tail the file while the job runs so the frontend can
  display detections progressively over SSE.
* No write access outside the workspace: uploads land in ./workspace/uploads,
  results in ./workspace/results. Paths are validated against the workspace
  root to defeat path-traversal from the UI.
* Localhost-only bind by default. Treat this process as the local-admin
  console — there is no authentication.
"""

import json
import mimetypes
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# Local module — pure-stdlib SQLite layer.
sys_path_anchor = Path(__file__).resolve().parent
sys.path.insert(0, str(sys_path_anchor))
import store as _store  # noqa: E402
import rule_index as _rule_index  # noqa: E402
import process_tree as _process_tree  # noqa: E402
import behavioral as _behavioral  # noqa: E402
import feed_fetcher as _feed_fetcher  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GUI_DIR = ROOT / "gui"
STATIC_DIR = GUI_DIR / "static"
WORKSPACE = ROOT / "workspace"
UPLOAD_DIR = WORKSPACE / "uploads"
RESULTS_DIR = WORKSPACE / "results"
JOBS_DIR = WORKSPACE / "jobs"
LOOKUPS_DIR = ROOT / "lookups"
FP_HISTORY_DIR = LOOKUPS_DIR / "fp_history"
BIN_DIR = ROOT / "bin"
DB_PATH = WORKSPACE / "hayabusa-gui.sqlite"

for d in (UPLOAD_DIR, RESULTS_DIR, JOBS_DIR, FP_HISTORY_DIR):
    d.mkdir(parents=True, exist_ok=True)

STORE = _store.Store(DB_PATH, FP_HISTORY_DIR)
RULES_DIR_FOR_INDEX = BIN_DIR / "rules"
CUSTOM_RULES_DIR = ROOT / "rules-custom"
RULE_INDEX = _rule_index.RuleIndex(RULES_DIR_FOR_INDEX, CUSTOM_RULES_DIR)

# --- Bind / network mode -----------------------------------------------------
# Default is localhost-only (the safe single-user posture this tool was built
# for). Set HAYABUSA_GUI_HOST=0.0.0.0 to expose it on the LAN — e.g. a lab PC
# where anyone may investigate logs. Network mode has NO authentication, so it
# is only appropriate on a trusted LAN. Live analysis is refused in this mode.
_LOOPBACK = {"127.0.0.1", "localhost", "::1", ""}
BIND_HOST = os.environ.get("HAYABUSA_GUI_HOST", "127.0.0.1").strip()
NETWORK_MODE = BIND_HOST not in _LOOPBACK

# System-EVTX inspection root on Windows. We only attempt to read this when
# the user explicitly asks via /api/system/* — never automatically.
SYSTEM_EVTX_ROOT = Path("C:/Windows/System32/winevt/Logs")
SYSTEM_SNAPSHOT_DIR = UPLOAD_DIR / "system-snapshot"


def _is_admin_windows() -> bool:
    """Return True when the current process holds elevated rights.

    Uses the official shell32!IsUserAnAdmin call rather than checking for
    membership in BUILTIN\\Administrators, because UAC-restricted tokens
    return False even for users in the Administrators group — which is the
    behaviour we want (we can't open System32\\winevt\\Logs from a
    restricted token).
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


# Channels we always surface first in the UI — they're the high-signal
# DFIR sources. Anything else is grouped under "その他" by category.
PRIORITY_CHANNELS = [
    "Security",
    "System",
    "Application",
    "Microsoft-Windows-Sysmon%4Operational",
    "Microsoft-Windows-PowerShell%4Operational",
    "Windows PowerShell",
    "Microsoft-Windows-WMI-Activity%4Operational",
    "Microsoft-Windows-TaskScheduler%4Operational",
    "Microsoft-Windows-Windows Defender%4Operational",
    "Microsoft-Windows-CodeIntegrity%4Operational",
    "Microsoft-Windows-AppLocker%4EXE and DLL",
    "Microsoft-Windows-Bits-Client%4Operational",
]
PRIORITY_SET = {name.lower() for name in PRIORITY_CHANNELS}


def _list_system_channels() -> list[dict]:
    """Inventory every .evtx file under the Windows event-log directory.

    We tolerate per-file failures: it's common for a non-admin process to
    enumerate the directory but fail to stat individual privileged files.
    We always emit a row so the analyst sees which channel was unreachable.
    """
    out: list[dict] = []
    if not SYSTEM_EVTX_ROOT.exists():
        return out
    try:
        entries = sorted(SYSTEM_EVTX_ROOT.glob("*.evtx"),
                         key=lambda p: p.name.lower())
    except OSError:
        return out
    for p in entries:
        readable = False
        size = None
        mtime = None
        try:
            st = p.stat()
            size = st.st_size
            mtime = st.st_mtime
            # Cheap readability probe — open + close.
            with open(p, "rb"):
                readable = True
        except OSError:
            pass
        nice = p.stem.replace("%4", "/")
        out.append({
            "name": p.name,
            "channel": nice,
            "size": size,
            "mtime": mtime,
            "readable": readable,
            "priority": p.stem.lower() in PRIORITY_SET,
        })
    return out


def find_hayabusa() -> Path:
    """Locate the hayabusa binary inside ./bin (cross-platform).

    Prefers our forked build (`hayabusa-fx*`) over the upstream release
    binary because the fork ships the `lookup:` Sigma extension. On Windows
    we look for `*.exe`; on Linux/macOS for the extension-less ELF/Mach-O
    binary (built from engine/ with `cargo build --release`).
    """
    cands = [p for p in BIN_DIR.glob("hayabusa*") if p.is_file()]
    if sys.platform == "win32":
        cands = [p for p in cands if p.suffix.lower() == ".exe"]
    else:
        cands = [p for p in cands if p.suffix.lower() != ".exe"]
    if not cands:
        if sys.platform == "win32":
            hint = "Drop hayabusa-fx-*.exe into bin/."
        else:
            hint = ("Build the Linux engine first: tools/build_engine_linux.sh "
                    "(or `cd engine && cargo build --release`, then copy the "
                    "binary to bin/hayabusa-fx).")
        raise SystemExit(f"Hayabusa binary not found in {BIN_DIR}. {hint}")
    cands.sort()
    fx = [c for c in cands if "-fx" in c.name]
    return fx[0] if fx else cands[0]


HAYABUSA_BIN = find_hayabusa()
RULES_DIR = BIN_DIR / "rules"
CONFIG_DIR = BIN_DIR / "config"


# ---------------------------------------------------------------------------
# Job registry
# ---------------------------------------------------------------------------

class Job:
    """One Hayabusa scan invocation, tracked with progress + detections."""

    __slots__ = (
        "id", "kind", "args", "started_at", "finished_at", "status", "exit_code",
        "stdout_log", "stderr_log", "result_jsonl", "result_summary",
        "subscribers", "lock", "detection_count", "last_event_at",
        "_indexed_lines_at_start",
        "proc", "total_files", "cancel_requested",
        "total_bytes", "progress_pct",
    )

    def __init__(self, kind: str, args: list[str]):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.args = args
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.status = "queued"          # queued | running | done | failed | cancelled
        self.exit_code: int | None = None
        job_dir = JOBS_DIR / self.id
        job_dir.mkdir(parents=True, exist_ok=True)
        self.stdout_log = job_dir / "stdout.log"
        self.stderr_log = job_dir / "stderr.log"
        self.result_jsonl = job_dir / "timeline.jsonl"
        self.result_summary = job_dir / "summary.html"
        self.subscribers: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.detection_count = 0
        self.last_event_at = self.started_at
        self._indexed_lines_at_start = 0
        self.proc = None                # subprocess handle while running
        self.total_files = None         # parsed from Hayabusa stdout
        self.cancel_requested = False
        self.total_bytes = None         # estimated input size (for % progress)
        self.progress_pct = 0.0         # estimated completion 0..100

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "detection_count": self.detection_count,
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
            "progress_pct": round(self.progress_pct, 1),
            "args": self.args,
        }

    def cancel(self) -> bool:
        """Request cancellation of a running scan. Returns True if a live
        process was signalled. Safe to call repeatedly."""
        self.cancel_requested = True
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return False
        try:
            proc.terminate()
            # Give it a moment, then hard-kill if still alive.
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            return True
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[cancel] failed for {self.id}: {exc}\n")
            return False

    def persist(self):
        """Mirror the in-memory job to SQLite so it survives a restart."""
        try:
            STORE.upsert_job(self.to_dict())
        except Exception as exc:  # noqa: BLE001 — non-fatal
            sys.stderr.write(f"[store] upsert_job failed: {exc}\n")

    def publish(self, event: dict):
        self.last_event_at = time.time()
        payload = "data: " + json.dumps(event) + "\n\n"
        with self.lock:
            dead = []
            for q in self.subscribers:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self.subscribers.remove(q)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self.lock:
            self.subscribers.append(q)
        # Replay an initial state so a late subscriber gets context.
        q.put_nowait("data: " + json.dumps({"type": "state", "job": self.to_dict()}) + "\n\n")
        return q


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def register_job(job: Job):
    with JOBS_LOCK:
        JOBS[job.id] = job
    job.persist()


def _delete_job_dir(job_id: str):
    """Remove workspace/jobs/<id>/ so the boot reindexer won't re-import it.

    Defensive: resolve the path and confirm it is *inside* JOBS_DIR before
    deleting, so a malformed id can never escape the workspace.
    """
    target = (JOBS_DIR / job_id).resolve()
    try:
        if JOBS_DIR.resolve() not in target.parents:
            return  # refuse anything that isn't a direct child of jobs/
    except OSError:
        return
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)


def purge_job(job_id: str) -> int:
    """Forget a job everywhere: in-memory registry, SQLite, and disk.

    Returns the number of detection rows removed. Caller is responsible for
    ensuring the job is not still running.
    """
    with JOBS_LOCK:
        JOBS.pop(job_id, None)
    n = STORE.delete_job(job_id)
    _delete_job_dir(job_id)
    return n


# ---------------------------------------------------------------------------
# Hayabusa invocation
# ---------------------------------------------------------------------------

def safe_workspace_path(p: str) -> Path:
    """Reject paths that escape the workspace root."""
    candidate = (WORKSPACE / p).resolve()
    if WORKSPACE.resolve() not in candidate.parents and candidate != WORKSPACE.resolve():
        raise ValueError(f"Path escapes workspace: {p}")
    return candidate


def build_hayabusa_argv(job: Job, params: dict) -> list[str]:
    """
    Translate the GUI's scan request into a hayabusa argv.

    Only a vetted subset of CLI flags is exposed. We deliberately do NOT pass
    arbitrary user-supplied flags through — that would let the UI flip
    --live-analysis on hosts where it shouldn't run.
    """
    # Public (network) "danger ranking" mode: lock the scan parameters so
    # every entrant is scored on identical settings. Only the target comes
    # from the request — preset / min-level / tags / time-window are ignored.
    # Canonical = the "標準" preset: medium+, dedupe on, all-rules off.
    if NETWORK_MODE:
        params = {
            "target": params.get("target", {}),
            "allow_live": params.get("allow_live", False),
            "nickname": params.get("nickname", ""),
            "min_level": "medium",
            "remove_duplicates": True,
        }

    argv: list[str] = [str(HAYABUSA_BIN), "json-timeline", "--no-wizard",
                       "-L", "-o", str(job.result_jsonl),
                       "-C", "-q", "-K", "-s", "-b",
                       # -p verbose ensures ExtraFieldInfo (the raw EventData
                       # dict from EvtRender) is included with every detection.
                       # Without it we can't reliably reconstruct process
                       # trees from Sysmon EID 1, because ProcessGuid /
                       # ParentProcessGuid live outside the standard `Details`
                       # string. Verbose adds ~30% to the output size which is
                       # acceptable for a DFIR tool.
                       "-p", "verbose"]

    target = params.get("target", {})
    if target.get("type") == "file":
        resolved = safe_workspace_path(target["path"])
        argv += ["-f", str(resolved)]
        # Hayabusa needs an explicit -J flag for JSON/JSONL input or it
        # refuses with "only accepts .evtx files".
        if resolved.suffix.lower() in (".json", ".jsonl"):
            argv += ["-J"]
    elif target.get("type") == "directory":
        argv += ["-d", str(safe_workspace_path(target["path"]))]
    elif target.get("type") == "live" and params.get("allow_live"):
        # Live analysis reads THIS host's own event logs. It only makes sense
        # on a Windows machine the analyst is sitting at — never on a Linux
        # server or a shared network instance.
        if sys.platform != "win32":
            raise ValueError("ライブ解析は Windows でのみ利用できます。"
                             "EVTX ファイルをアップロードしてください。")
        if NETWORK_MODE:
            raise ValueError("ネットワーク公開モードではライブ解析は無効です。"
                             "EVTX ファイルをアップロードしてください。")
        argv += ["-l"]
    else:
        raise ValueError("Unknown or unauthorized target type")

    min_level = params.get("min_level")
    if min_level in {"informational", "low", "medium", "high", "critical"}:
        argv += ["-m", min_level]

    if params.get("eid_filter"):
        argv += ["-E"]
    if params.get("enable_all_rules"):
        argv += ["-A"]
    if params.get("proven_rules"):
        argv += ["-P"]
    if params.get("remove_duplicates"):
        argv += ["-X"]

    include_tags = params.get("include_tags") or []
    if include_tags:
        argv += ["--include-tag", ",".join(include_tags)]
    exclude_tags = params.get("exclude_tags") or []
    if exclude_tags:
        argv += ["--exclude-tag", ",".join(exclude_tags)]

    # Optional time window
    if params.get("timeline_start"):
        argv += ["--timeline-start", params["timeline_start"]]
    if params.get("timeline_end"):
        argv += ["--timeline-end", params["timeline_end"]]

    # HTML summary
    argv += ["-H", str(job.result_summary)]

    # Custom rules dir (live-response builds need this)
    argv += ["-r", str(RULES_DIR), "-c", str(RULES_DIR / "config")]

    return argv


SEVERITY_RANK = {"informational": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def tail_results(job: Job, stop_event: threading.Event):
    """
    Stream JSONL detections out of Hayabusa's output file as they appear, and
    mirror them into SQLite for cross-job querying.

    Hayabusa writes detections to disk during the scan. We tail the file with
    a small sleep — a polling tail is plenty fast for the volumes a single
    workstation produces, and it avoids needing inotify/ReadDirectoryChangesW.

    The line-number bookkeeping is kept in lockstep with the store's
    ``indexed_lines`` counter so reindex-on-boot is a no-op for jobs already
    fully indexed.
    """
    pos = 0
    line_no = job._indexed_lines_at_start  # set by run_job before we start
    while not stop_event.is_set():
        try:
            if job.result_jsonl.exists():
                with open(job.result_jsonl, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                    if chunk:
                        batch: list[tuple[int, str, dict]] = []
                        for raw in chunk.splitlines():
                            raw = raw.rstrip("\r")
                            if not raw.strip():
                                continue
                            try:
                                event = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            line_no += 1
                            batch.append((line_no, raw, event))
                            job.detection_count += 1
                            job.publish({"type": "detection", "event": event,
                                         "n": job.detection_count})
                        if batch:
                            inserted = STORE.insert_detections(job.id, batch)
                            STORE.bump_indexed_lines(job.id, inserted)
        except Exception as exc:  # noqa: BLE001 — best-effort tailer
            job.publish({"type": "error", "stage": "tail", "msg": str(exc)})
        time.sleep(0.4)


# ---------------------------------------------------------------------------
# Estimated progress %
# ---------------------------------------------------------------------------
# Hayabusa's progress bar is indicatif-based and only renders to a TTY — when
# we pipe its output to a file (as we must, to capture it) it emits nothing
# incremental. So a *true* percentage is impossible to read back. Instead we
# estimate completion from input size and elapsed time, calibrated against the
# throughput of past scans. The estimate is intentionally honest: it climbs
# linearly toward an ETA, is capped at 99% until the process actually exits,
# then snaps to 100%. On the first run it uses a seed throughput measured on a
# reference scan (≈1 MB/s for the full ~4,700-rule set); thereafter it adapts.

CALIBRATION_PATH = WORKSPACE / ".scan_calibration.json"
# Seed: a 16-file / 85.5 MiB upload set scanned in ~88 s with the full rule
# set ⇒ ~1.0 MB/s after a fixed rule-loading overhead.
_SEED_OVERHEAD_SEC = 4.0
_SEED_RATE_BPS = 1_050_000.0
_CALIB_EMA_ALPHA = 0.3  # weight of the newest sample


def _load_calibration() -> tuple[float, float]:
    """Return (overhead_sec, rate_bytes_per_sec), falling back to the seed."""
    try:
        data = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
        ov = float(data.get("overhead_sec", _SEED_OVERHEAD_SEC))
        rate = float(data.get("rate_bps", _SEED_RATE_BPS))
        if rate > 1000 and ov >= 0:
            return ov, rate
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return _SEED_OVERHEAD_SEC, _SEED_RATE_BPS


def _update_calibration(total_bytes: int, duration_sec: float):
    """Blend a freshly measured scan into the throughput estimate (EMA).

    Only scans large/long enough to be informative update the model — tiny
    scans are dominated by fixed overhead and would skew the rate downward.
    """
    if not total_bytes or total_bytes < 2_000_000 or duration_sec < 2.0:
        return
    ov, rate = _load_calibration()
    scan_sec = max(0.5, duration_sec - ov)
    sample_rate = total_bytes / scan_sec
    new_rate = (1 - _CALIB_EMA_ALPHA) * rate + _CALIB_EMA_ALPHA * sample_rate
    try:
        CALIBRATION_PATH.write_text(
            json.dumps({"overhead_sec": ov, "rate_bps": round(new_rate, 1),
                        "last_bytes": total_bytes,
                        "last_duration_sec": round(duration_sec, 2)}),
            encoding="utf-8")
    except OSError:
        pass


def _estimate_total_bytes(params: dict) -> int:
    """Best-effort sum of input bytes for the scan target.

    Returns 0 when the size can't be determined (e.g. an unreadable live set);
    the caller then falls back to an indeterminate bar.
    """
    target = params.get("target", {})
    ttype = target.get("type")
    try:
        if ttype == "file":
            return safe_workspace_path(target["path"]).stat().st_size
        if ttype == "directory":
            root = safe_workspace_path(target["path"])
            total = 0
            for p in root.rglob("*"):
                if p.suffix.lower() in (".evtx", ".json", ".jsonl"):
                    try:
                        total += p.stat().st_size
                    except OSError:
                        pass
            return total
        if ttype == "live":
            return sum(c["size"] or 0 for c in _list_system_channels()
                       if c.get("readable"))
    except OSError:
        return 0
    return 0


def _progress_ticker(job: Job, stop_event: threading.Event):
    """Publish an estimated completion % a few times a second while running.

    pct = min(99, elapsed / estimated_total_sec * 100). estimated_total_sec is
    rule-loading overhead plus input_bytes / calibrated_throughput. If we have
    no size estimate we stay silent and the UI keeps its indeterminate bar.
    """
    if not job.total_bytes:
        return
    overhead, rate = _load_calibration()
    est_total = max(2.0, overhead + job.total_bytes / rate)
    while not stop_event.is_set():
        elapsed = time.time() - (job.started_at or time.time())
        pct = min(99.0, elapsed / est_total * 100.0)
        # Never let the estimate slide backwards.
        if pct > job.progress_pct:
            job.progress_pct = pct
            eta = max(0, int(est_total - elapsed))
            job.publish({"type": "progress", "pct": round(pct, 1),
                         "eta_sec": eta, "elapsed_sec": int(elapsed)})
        stop_event.wait(0.5)


def run_job(job: Job, params: dict):
    try:
        argv = build_hayabusa_argv(job, params)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.exit_code = -1
        job.publish({"type": "error", "stage": "args", "msg": str(exc)})
        job.finished_at = time.time()
        job.persist()
        return

    # Estimate input size up front so the progress ticker has something to
    # work with. Cheap (a few stat calls); 0 ⇒ fall back to indeterminate bar.
    job.total_bytes = _estimate_total_bytes(params)

    job.status = "running"
    job.persist()
    job.publish({"type": "state", "job": job.to_dict()})

    stop_event = threading.Event()
    # Resume from wherever the indexer last left off — usually 0 for a fresh
    # job, nonzero only on the recovery path where a job restarted mid-scan.
    job._indexed_lines_at_start = STORE.indexed_lines(job.id)
    tailer = threading.Thread(target=tail_results, args=(job, stop_event), daemon=True)
    tailer.start()
    # Watch stdout for the "Total event log files" line so the UI can show
    # the scale of the scan. Hayabusa doesn't emit a real progress %% when
    # its output is piped (the indicatif bar is TTY-only), so this is the
    # best determinate signal we can surface.
    meta_thread = threading.Thread(target=_watch_stdout_meta,
                                   args=(job, stop_event), daemon=True)
    meta_thread.start()
    # Estimated-% ticker. Only does anything if we have a byte estimate.
    prog_thread = threading.Thread(target=_progress_ticker,
                                   args=(job, stop_event), daemon=True)
    prog_thread.start()

    try:
        with open(job.stdout_log, "wb") as out, open(job.stderr_log, "wb") as err:
            # cwd=BIN_DIR so hayabusa finds its sibling rules/ + config/ dirs.
            proc = subprocess.Popen(argv, stdout=out, stderr=err, cwd=str(BIN_DIR))
            job.proc = proc
            job.exit_code = proc.wait()
    except FileNotFoundError as exc:
        job.publish({"type": "error", "stage": "spawn", "msg": str(exc)})
        job.status = "failed"
        job.exit_code = -1
    finally:
        # Let the tailer drain anything written between the last poll and exit.
        time.sleep(0.6)
        stop_event.set()
        tailer.join(timeout=2)
        meta_thread.join(timeout=1)
        prog_thread.join(timeout=1)
        job.proc = None

    if job.cancel_requested:
        job.status = "cancelled"
    elif job.status != "failed":
        job.status = "done" if job.exit_code == 0 else "failed"
    job.finished_at = time.time()

    # Snap the bar to 100% on a clean finish, and feed the real duration back
    # into the throughput model so the next estimate is sharper. Cancelled /
    # failed runs are not representative, so they don't calibrate.
    if job.status == "done":
        job.progress_pct = 100.0
        job.publish({"type": "progress", "pct": 100.0, "eta_sec": 0,
                     "elapsed_sec": int((job.finished_at or 0) - job.started_at)})
        _update_calibration(job.total_bytes or 0,
                            (job.finished_at or 0) - job.started_at)

    job.persist()
    job.publish({"type": "state", "job": job.to_dict()})
    job.publish({"type": "complete"})


_TOTAL_FILES_RE = re.compile(r"Total event log files:\s*([\d,]+)")


def _watch_stdout_meta(job: Job, stop_event: threading.Event):
    """Poll the job's stdout log until the 'Total event log files: N' line
    appears, then publish it once over SSE. Cheap and one-shot."""
    while not stop_event.is_set() and job.total_files is None:
        try:
            if job.stdout_log.exists():
                text = job.stdout_log.read_text(encoding="utf-8", errors="replace")
                m = _TOTAL_FILES_RE.search(text)
                if m:
                    job.total_files = int(m.group(1).replace(",", ""))
                    job.publish({"type": "meta", "total_files": job.total_files})
                    return
        except OSError:
            pass
        time.sleep(0.4)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "HayabusaGUI/0.1"

    # Quiet the default access logging on the console.
    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # ------------------------------------------------------------------
    # Security middleware
    # ------------------------------------------------------------------
    # All security checks run BEFORE per-route handlers via these two
    # hooks: `_security_preflight()` runs at the top of each verb handler,
    # and `end_headers()` is overridden to attach baseline hardening
    # headers to every response. Three checks at preflight:
    #   1. Host header must be 127.0.0.1[:port] / localhost[:port] / [::1]
    #      → defeats DNS rebinding (an attacker's site cannot point a
    #      domain at 127.0.0.1, get the browser to issue a request, and
    #      have it land on our service).
    #   2. For POST / DELETE, an Origin or Referer header from the same
    #      host is required → defeats classic CSRF where another page in
    #      the browser hits our endpoints via fetch/form post.
    #   3. Hayabusa-FX-Token-style anti-CSRF token is NOT required because
    #      the Origin/Host pair is already authoritative for browser
    #      requests on a same-origin localhost service.

    ALLOWED_HOSTS = {
        "127.0.0.1", "localhost", "[::1]", "::1",
    }

    def _security_preflight(self) -> bool:
        """Return True if the request passes all gates; otherwise the
        handler has already responded with an appropriate 4xx and the
        caller must return early.

        Localhost mode keeps the strict DNS-rebinding defence (Host must be
        loopback). Network mode (HAYABUSA_GUI_HOST=0.0.0.0) is for a trusted
        LAN with no auth, so any Host is accepted — but we still enforce a
        *same-origin* check on POST/DELETE, which blocks classic cross-site
        CSRF from another website for free."""
        host_hdr = (self.headers.get("Host") or "").strip()
        host_only = host_hdr.rsplit(":", 1)[0].lower() if host_hdr else ""

        # --- 1. Host header check (DNS rebinding) — localhost mode only ---
        if not NETWORK_MODE and host_only not in self.ALLOWED_HOSTS:
            self._send_text(
                f"Bad Host header (DNS rebinding defence): {host_hdr!r}", 421)
            return False

        # --- 2. CSRF check on state-changing verbs ---
        if self.command in ("POST", "DELETE"):
            origin = (self.headers.get("Origin") or "").strip()
            referer = (self.headers.get("Referer") or "").strip()
            from urllib.parse import urlparse
            def _origin_ok(value: str) -> bool:
                if not value:
                    return False
                host = (urlparse(value).hostname or "").lower()
                if host in self.ALLOWED_HOSTS:
                    return True
                # Network mode: accept same-origin (Origin host == Host host).
                return NETWORK_MODE and host == host_only
            if not (_origin_ok(origin) or _origin_ok(referer)):
                self._send_text(
                    "Forbidden: cross-origin POST/DELETE blocked.", 403)
                return False
        return True

    # baseline security headers attached to every response. We intercept
    # `end_headers` rather than each `send_header` site to ensure no
    # handler can accidentally skip them.
    _SECURITY_HEADERS = (
        ("X-Frame-Options", "DENY"),                       # clickjacking
        ("X-Content-Type-Options", "nosniff"),             # MIME sniffing
        ("Referrer-Policy", "no-referrer"),                # cross-origin leak
        ("X-XSS-Protection", "0"),                         # disable legacy XSS auditor
        ("Cross-Origin-Opener-Policy", "same-origin"),     # browser process isolation
        ("Cross-Origin-Resource-Policy", "same-origin"),
        # CSP: the GUI ships its own JS/CSS, never loads from CDNs, never
        # embeds frames. 'self' is sufficient. 'unsafe-inline' is allowed
        # for style/script because we have inline onclick handlers and a
        # small bit of inline style in dynamically-rendered HTML — the
        # browser refusing those would break the modal close path that
        # we deliberately routed through inline onclick for reliability.
        ("Content-Security-Policy",
         "default-src 'self'; "
         "script-src 'self' 'unsafe-inline'; "
         "style-src 'self' 'unsafe-inline'; "
         "img-src 'self' data:; "
         "connect-src 'self'; "
         "frame-ancestors 'none'; "
         "base-uri 'self'; "
         "form-action 'self'"),
    )

    def end_headers(self):  # type: ignore[override]
        for k, v in self._SECURITY_HEADERS:
            self.send_header(k, v)
        super().end_headers()

    # ---------- helpers ----------

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, body: str, status=200, ctype="text/plain; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, ctype: str | None = None):
        if not path.exists() or not path.is_file():
            self._send_text("not found", 404)
            return
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # Local dev tool: never let the browser hold an old snapshot of our
        # JS/CSS. The cost is one extra round-trip per page load on
        # localhost, which is essentially free.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _read_json(self) -> dict:
        raw = self._read_body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc

    # ---------- routing ----------

    def do_GET(self):  # noqa: N802
        if not self._security_preflight():
            return
        u = urlparse(self.path)
        path = u.path

        if path == "/" or path == "/index.html":
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            target = (STATIC_DIR / rel).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                self._send_text("forbidden", 403)
                return
            self._send_file(target)
            return

        if path == "/api/health":
            self._send_json({
                "ok": True,
                "hayabusa": str(HAYABUSA_BIN),
                "version": self._hayabusa_version(),
                "rules_dir": str(RULES_DIR),
                "workspace": str(WORKSPACE),
            })
            return

        if path == "/api/workspace":
            self._send_json(self._list_workspace())
            return

        if path == "/api/jobs":
            # Source of truth is SQLite — survives restarts. Live in-memory
            # jobs may not yet be in SQLite if upsert hasn't happened, so we
            # also splice them in.
            seen: set[str] = set()
            out: list[dict] = []
            for row in STORE.list_jobs():
                d = dict(row)
                d["args"] = json.loads(d.pop("args_json") or "[]")
                seen.add(d["id"])
                out.append(d)
            with JOBS_LOCK:
                for jid, j in JOBS.items():
                    if jid not in seen:
                        out.append(j.to_dict())
            out.sort(key=lambda j: j.get("started_at") or 0, reverse=True)
            self._send_json(out)
            return

        m = re.match(r"^/api/jobs/([A-Za-z0-9_-]{6,64})$", path)
        if m:
            jid = m.group(1)
            job = JOBS.get(jid)
            row = STORE.get_job(jid)
            if not job and not row:
                self._send_json({"error": "not_found"}, 404)
                return
            qs = parse_qs(u.query)
            offset = int(qs.get("offset", ["0"])[0])
            limit = min(int(qs.get("limit", ["200"])[0]), 2000)
            level = (qs.get("level", [""])[0] or "").lower() or None
            text = qs.get("q", [""])[0] or None
            verdict = qs.get("verdict", [""])[0] or None
            include_suppressed = qs.get("include_suppressed", ["0"])[0] in ("1", "true", "yes")
            detections = [self._row_to_detection(r) for r in
                          STORE.query_detections(
                              job_id=jid, level=level, text=text,
                              verdict=verdict,
                              include_suppressed=include_suppressed,
                              offset=offset, limit=limit)]
            total = STORE.count_detections(
                job_id=jid, level=level, verdict=verdict,
                include_suppressed=include_suppressed)
            job_view = job.to_dict() if job else dict(row)
            if not job:
                job_view["args"] = json.loads(job_view.pop("args_json") or "[]")
            stderr_path = JOBS_DIR / jid / "stderr.log"
            stdout_path = JOBS_DIR / jid / "stdout.log"
            summary_path = JOBS_DIR / jid / "summary.html"
            self._send_json({
                "job": job_view,
                "detections": detections,
                "total": total,
                "stderr_tail": self._tail_text(stderr_path, 4000),
                "stdout_tail": self._tail_text(stdout_path, 4000),
                "summary_available": summary_path.exists(),
            })
            return

        m = re.match(r"^/api/jobs/([A-Za-z0-9_-]{6,64})/stream$", path)
        if m:
            job = JOBS.get(m.group(1))
            if not job:
                self._send_json({"error": "not_found"}, 404)
                return
            self._stream_sse(job)
            return

        m = re.match(r"^/api/jobs/([A-Za-z0-9_-]{6,64})/summary$", path)
        if m:
            jid = m.group(1)
            summary_path = JOBS_DIR / jid / "summary.html"
            if not summary_path.exists():
                self._send_text("not found", 404)
                return
            self._send_file(summary_path, "text/html; charset=utf-8")
            return

        if path == "/api/rules":
            self._send_json(self._summarize_rules())
            return

        if path == "/api/detections":
            qs = parse_qs(u.query)
            offset = int(qs.get("offset", ["0"])[0])
            limit = min(int(qs.get("limit", ["200"])[0]), 2000)
            filters = {
                "job_id": qs.get("job", [""])[0] or None,
                "level": (qs.get("level", [""])[0] or "").lower() or None,
                "rule_id": qs.get("rule_id", [""])[0] or None,
                "verdict": qs.get("verdict", [""])[0] or None,
                "text": qs.get("q", [""])[0] or None,
                "include_suppressed": qs.get("include_suppressed", ["0"])[0] in ("1", "true", "yes"),
            }
            detections = [self._row_to_detection(r) for r in
                          STORE.query_detections(offset=offset, limit=limit, **filters)]
            total = STORE.count_detections(**filters)
            self._send_json({"detections": detections, "total": total,
                             "offset": offset, "limit": limit})
            return

        m = re.match(r"^/api/detections/([A-Za-z0-9_-]{6,64})/(\d+)/process_tree$", path)
        if m:
            jid, line_no = m.group(1), int(m.group(2))
            qs = parse_qs(u.query)
            window = int(qs.get("window", ["10"])[0])
            try:
                tree = _process_tree.build_tree(STORE, jid, line_no,
                                                window_minutes=window)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
                return
            self._send_json(tree)
            return

        m = re.match(r"^/api/detections/([A-Za-z0-9_-]{6,64})/(\d+)/detail$", path)
        if m:
            jid, line_no = m.group(1), int(m.group(2))
            row = STORE.get_detection(jid, line_no)
            if not row:
                self._send_json({"error": "not_found"}, 404)
                return
            event = self._row_to_detection(row)
            rule_meta = None
            if row["rule_id"] and not row["rule_id"].startswith("h:"):
                rule_meta = RULE_INDEX.lookup(row["rule_id"])
            attack = _rule_index.attack_tags(rule_meta) if rule_meta else []
            related = STORE.related_on_host(
                row["computer"], row["ts"],
                window_minutes=5,
                exclude=(jid, line_no), limit=30)
            history = STORE.rule_history(row["rule_id"],
                                         exclude=(jid, line_no), limit=20)
            self._send_json({
                "detection": event,
                "rule": rule_meta,
                "attack_tags": attack,
                "related": related,
                "rule_history": history,
            })
            return

        if path == "/api/config":
            # Lightweight flags the SPA reads on load to adapt its UI.
            self._send_json({
                "network_mode": NETWORK_MODE,   # published "danger ranking" site
                "platform": sys.platform,
                "live_supported": (sys.platform == "win32" and not NETWORK_MODE),
            })
            return

        if path == "/api/collector":
            # Hand the Windows log-collection .bat to ranking entrants so they
            # can dump a standardised set of EVTX channels and upload them.
            bat = ROOT / "tools" / "collect_windows_logs.bat"
            if not bat.exists():
                self._send_json({"error": "collector not available"}, 404)
                return
            data = bat.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition",
                             'attachment; filename="collect_windows_logs.bat"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/api/ranking":
            qs = parse_qs(u.query)
            inc = qs.get("include_suppressed", ["0"])[0] in ("1", "true", "yes")
            try:
                rows = STORE.ranking(include_suppressed=inc)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
                return
            self._send_json({"ranking": rows, "total": len(rows),
                             "risk_weights": STORE.RISK_WEIGHTS})
            return

        if path == "/api/hosts":
            qs = parse_qs(u.query)
            inc = qs.get("include_suppressed", ["0"])[0] in ("1", "true", "yes")
            try:
                rows = STORE.host_summary(include_suppressed=inc)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
                return
            self._send_json({"hosts": rows, "total": len(rows),
                             "risk_weights": STORE.RISK_WEIGHTS})
            return

        m = re.match(r"^/api/hosts/([^/]+)$", path)
        if m:
            # The hostname might contain anything Windows allows; URL-decode it.
            computer = unquote(m.group(1))
            qs = parse_qs(u.query)
            inc = qs.get("include_suppressed", ["0"])[0] in ("1", "true", "yes")
            try:
                detail = STORE.host_detail(computer, include_suppressed=inc)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
                return
            self._send_json(detail)
            return

        if path == "/api/behavioral/anomalies":
            qs = parse_qs(u.query)
            top = min(int(qs.get("top", ["50"])[0]), 500)
            try:
                rows = _behavioral.analyse(STORE, top=top)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
                return
            self._send_json({"anomalies": rows, "total": len(rows)})
            return

        if path == "/api/hunt/facets":
            # Distinct values for the hunt form's dropdowns. Cheap because
            # SQLite indexes channel / level / computer / rule_id and the
            # cardinality is small.
            c = STORE._conn()
            rows_lvl = list(c.execute(
                "SELECT DISTINCT level FROM detections WHERE level IS NOT NULL "
                "ORDER BY CASE level WHEN 'critical' THEN 4 WHEN 'high' THEN 3 "
                "WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC"))
            rows_ch = list(c.execute(
                "SELECT channel, COUNT(*) AS n FROM detections "
                "WHERE channel IS NOT NULL GROUP BY channel "
                "ORDER BY n DESC LIMIT 50"))
            rows_host = list(c.execute(
                "SELECT computer, COUNT(*) AS n FROM detections "
                "WHERE computer IS NOT NULL GROUP BY computer "
                "ORDER BY n DESC LIMIT 50"))
            rows_eid = list(c.execute(
                "SELECT event_id, COUNT(*) AS n FROM detections "
                "WHERE event_id IS NOT NULL GROUP BY event_id "
                "ORDER BY n DESC LIMIT 50"))
            self._send_json({
                "levels": [r["level"] for r in rows_lvl],
                "channels": [{"name": r["channel"], "count": r["n"]} for r in rows_ch],
                "computers": [{"name": r["computer"], "count": r["n"]} for r in rows_host],
                "event_ids": [{"id": r["event_id"], "count": r["n"]} for r in rows_eid],
            })
            return

        if path == "/api/hunt/search":
            qs = parse_qs(u.query)
            offset = int(qs.get("offset", ["0"])[0])
            limit = min(int(qs.get("limit", ["500"])[0]), 5000)
            kw = self._hunt_filters(qs)
            order = qs.get("order", ["ts_desc"])[0]
            detections = [self._row_to_detection(r) for r in
                          STORE.query_detections(offset=offset, limit=limit,
                                                 order_by=order, **kw)]
            total = STORE.count_detections(**kw)
            self._send_json({"detections": detections, "total": total,
                             "offset": offset, "limit": limit,
                             "filters": kw})
            return

        if path == "/api/hunt/pivot":
            qs = parse_qs(u.query)
            dim = qs.get("dim", ["rule_id"])[0]
            limit = min(int(qs.get("limit", ["50"])[0]), 500)
            kw = self._hunt_filters(qs)
            try:
                rows = STORE.pivot_detections(dim, limit=limit, **kw)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"dim": dim, "rows": rows, "filters": kw})
            return

        if path == "/api/hunt/export":
            # Streaming-ish CSV of the search result. We cap at 50k rows
            # to keep the response sane; analysts asking for more should
            # filter further.
            qs = parse_qs(u.query)
            kw = self._hunt_filters(qs)
            limit = min(int(qs.get("limit", ["50000"])[0]), 50000)
            rows = STORE.query_detections(offset=0, limit=limit, **kw)
            import csv, io
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["timestamp", "level", "rule_id", "rule_title",
                        "computer", "channel", "event_id",
                        "verdict", "suppressed", "job_id", "line_no"])
            for r in rows:
                w.writerow([
                    r["ts"] or "", r["level"] or "",
                    r["rule_id"] or "", r["rule_title"] or "",
                    r["computer"] or "", r["channel"] or "",
                    r["event_id"] or "",
                    r["verdict"] or "",
                    "yes" if r["suppression_id"] else "no",
                    r["job_id"], r["line_no"],
                ])
            data = buf.getvalue().encode("utf-8-sig")  # BOM so Excel reads JP
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition",
                             "attachment; filename=hunt-results.csv")
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/api/system/info":
            channels = _list_system_channels()
            total = sum((c.get("size") or 0) for c in channels if c.get("readable"))
            unreadable = sum(1 for c in channels if not c.get("readable"))
            self._send_json({
                "platform": sys.platform,
                "evtx_root": str(SYSTEM_EVTX_ROOT),
                "admin": _is_admin_windows(),
                "channels": channels,
                "total_size": total,
                "unreadable_count": unreadable,
                "snapshot_dir": str(SYSTEM_SNAPSHOT_DIR.relative_to(WORKSPACE)).replace("\\", "/"),
            })
            return

        if path == "/api/lookups":
            # We can't reach into the forked engine's in-memory table
            # registry from out of process, so we reconstruct the
            # (table-name → file → referencing-rules) graph by parsing
            # every rule's `lookup:` block. The output is the analyst's
            # view of what tables exist and which rules need them.
            #
            # Returned items represent declared TABLE NAMES, not files —
            # a file may participate in multiple tables, or a table name
            # may be declared by multiple rules pointing to different
            # files (last-write-wins in the engine; we surface the
            # divergence so it's visible).
            bindings: dict[str, dict] = {}  # name → {file, referenced_by, conflicts}
            unbound_files: list[Path] = []
            for rule_path in (RULES_DIR / "hayabusa").rglob("*.yml"):
                try:
                    body = rule_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if "lookup:" not in body:
                    continue
                in_lookup = False
                cur_name = None
                for line in body.splitlines():
                    s = line.strip()
                    if not in_lookup:
                        if s == "lookup:" or s.startswith("lookup:"):
                            in_lookup = True
                        continue
                    # Exit lookup block on dedent to column 0 with a key
                    if line and not line.startswith(" ") and not line.startswith("\t") \
                            and not s.startswith("- "):
                        in_lookup = False
                        cur_name = None
                        continue
                    if s.startswith("- name:"):
                        cur_name = s.split(":", 1)[1].strip().strip('"').strip("'")
                    elif s.startswith("name:") and cur_name is None:
                        cur_name = s.split(":", 1)[1].strip().strip('"').strip("'")
                    elif s.startswith("file:") and cur_name is not None:
                        file_str = s.split(":", 1)[1].strip().strip('"').strip("'")
                        cand = (rule_path.parent / file_str).resolve()
                        b = bindings.setdefault(cur_name, {
                            "file_paths": set(), "referenced_by": []
                        })
                        b["file_paths"].add(cand)
                        if rule_path.name not in b["referenced_by"]:
                            b["referenced_by"].append(rule_path.name)
                        cur_name = None  # ready for the next entry
            # Build response.
            items = []
            for name, b in sorted(bindings.items()):
                # Pick a canonical file path (first that exists).
                paths = list(b["file_paths"])
                primary = next((p for p in paths if p.exists()), paths[0] if paths else None)
                entries = -1
                size = 0
                if primary and primary.exists():
                    try:
                        entries = sum(
                            1 for line in primary.read_text(
                                encoding="utf-8", errors="replace"
                            ).splitlines()
                            if line.strip() and not line.lstrip().startswith("#")
                        )
                        size = primary.stat().st_size
                    except OSError:
                        pass
                items.append({
                    "name": name,
                    "filename": primary.name if primary else "",
                    "rel": str(primary.relative_to(ROOT)).replace("\\", "/")
                            if primary and ROOT in primary.parents else str(primary or ""),
                    "exists": bool(primary and primary.exists()),
                    "entries": entries,
                    "size": size,
                    "referenced_by": b["referenced_by"],
                    "binding_count": len(paths),
                })
            # Also report files in lookups/ that no rule references.
            referenced_paths = {p for b in bindings.values() for p in b["file_paths"]}
            for p in sorted(LOOKUPS_DIR.glob("*")) if LOOKUPS_DIR.exists() else []:
                if p.is_file() and p.resolve() not in referenced_paths:
                    unbound_files.append({
                        "filename": p.name,
                        "rel": str(p.relative_to(ROOT)).replace("\\", "/"),
                        "size": p.stat().st_size,
                    })
            # Annotate each lookup with feed-fetch metadata (last fetch
            # time, entry count, error) when present.
            try:
                meta_map = _feed_fetcher.load_meta(LOOKUPS_DIR)
            except Exception:  # noqa: BLE001
                meta_map = {}
            for it in items:
                # The lookup name in rules vs the feed name in feeds.yml
                # are usually the same (we recommend it in feeds.yml).
                m = meta_map.get(it["name"])
                if m:
                    it["feed_meta"] = m
            self._send_json({"lookups": items, "unbound_files": unbound_files,
                             "dir": str(LOOKUPS_DIR),
                             "feeds": list(meta_map.values())})
            return

        if path == "/api/rule_feedback":
            rows = STORE.rule_feedback()
            self._send_json([dict(r) for r in rows])
            return

        if path == "/api/stats":
            qs = parse_qs(u.query)
            job_id = qs.get("job", [""])[0] or None
            include_suppressed = qs.get("include_suppressed", ["0"])[0] in ("1", "true", "yes")
            bucket = qs.get("bucket", ["hour"])[0]
            if bucket not in ("minute", "hour", "day"):
                bucket = "hour"
            by_level = STORE.stats_by_level(job_id, include_suppressed)
            total = sum(by_level.values())
            crit_high = by_level.get("critical", 0) + by_level.get("high", 0)
            self._send_json({
                "scope": {"job_id": job_id, "include_suppressed": include_suppressed,
                          "bucket": bucket},
                "totals": {
                    "detections": total,
                    "critical_high": crit_high,
                    "unique_computers": STORE.stats_unique("computer", job_id, include_suppressed),
                    "unique_rules": STORE.stats_unique("rule_id", job_id, include_suppressed),
                },
                "by_level": by_level,
                "top_rules": STORE.stats_top_rules(job_id, 12, include_suppressed),
                "top_computers": STORE.stats_top_computers(job_id, 10, include_suppressed),
                "timeline": STORE.stats_timeline(job_id, bucket, include_suppressed),
            })
            return

        if path == "/api/suppressions":
            rows = STORE.list_suppressions()
            out = []
            for r in rows:
                d = dict(r)
                # Echo back the original glob shape so the UI can show a
                # human-friendly pattern rather than the LIKE-escaped form.
                d["computer"] = _store.Store._like_to_glob(d.get("computer_like"))
                out.append(d)
            self._send_json(out)
            return

        self._send_text("not found", 404)

    def do_DELETE(self):  # noqa: N802
        if not self._security_preflight():
            return
        u = urlparse(self.path)
        m = re.match(r"^/api/suppressions/(\d+)$", u.path)
        if m:
            sid = int(m.group(1))
            if STORE.remove_suppression(sid):
                self._send_json({"deleted": sid})
            else:
                self._send_json({"error": "not_found"}, 404)
            return

        # Delete a single job (its detections + on-disk files). A running
        # job must be cancelled first — we refuse so we never yank files out
        # from under a live Hayabusa process.
        m = re.match(r"^/api/jobs/([A-Za-z0-9_-]{6,64})$", u.path)
        if m:
            jid = m.group(1)
            live = JOBS.get(jid)
            if live and live.status in ("running", "queued"):
                self._send_json({"error": "job is still running; cancel it first",
                                 "status": live.status}, 409)
                return
            if not live and STORE.get_job(jid) is None:
                self._send_json({"error": "not_found"}, 404)
                return
            removed = purge_job(jid)
            self._send_json({"deleted": jid, "detections_removed": removed})
            return

        self._send_text("not found", 404)

    def do_POST(self):  # noqa: N802
        if not self._security_preflight():
            return
        u = urlparse(self.path)
        path = u.path

        if path == "/api/scan":
            try:
                params = self._read_json()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            job = Job("scan", [])
            register_job(job)
            # Public-mode leaderboard label (team / nickname), optional.
            try:
                STORE.set_label(job.id, params.get("nickname") or "")
            except Exception:  # noqa: BLE001
                pass
            threading.Thread(target=run_job, args=(job, params), daemon=True).start()
            self._send_json({"job_id": job.id}, 202)
            return

        m = re.match(r"^/api/jobs/([A-Za-z0-9_-]{6,64})/cancel$", path)
        if m:
            job = JOBS.get(m.group(1))
            if not job:
                self._send_json({"error": "not_found"}, 404)
                return
            if job.status not in ("running", "queued"):
                self._send_json({"error": "not running", "status": job.status}, 409)
                return
            signalled = job.cancel()
            self._send_json({"cancelled": True, "signalled": signalled,
                             "status": job.status})
            return

        if path == "/api/jobs/clear":
            # Wipe ALL scan history (jobs + detections + on-disk job dirs).
            # Refuse while anything is still running so we don't delete files
            # a live process is writing. Suppressions are preserved.
            with JOBS_LOCK:
                running = [j.id for j in JOBS.values()
                           if j.status in ("running", "queued")]
            if running:
                self._send_json({"error": "scans are still running; cancel them first",
                                 "running": running}, 409)
                return
            report = STORE.clear_all()
            # Drop every job directory under workspace/jobs/.
            for child in JOBS_DIR.iterdir() if JOBS_DIR.exists() else []:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
            with JOBS_LOCK:
                JOBS.clear()
            self._send_json({"cleared": True, **report})
            return

        if path == "/api/upload":
            self._handle_upload()
            return

        if path == "/api/suppressions":
            try:
                params = self._read_json()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            try:
                sid = STORE.add_suppression(
                    rule_id=params.get("rule_id"),
                    computer_glob=params.get("computer"),
                    reason=params.get("reason"),
                    created_by=params.get("created_by") or "analyst",
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"id": sid}, 201)
            return

        if path == "/api/lookups/refresh":
            # Trigger feed fetch. Synchronous because the GUI shows a
            # spinner; for cron-like background refresh use the CLI.
            try:
                params = self._read_json() if self.headers.get("Content-Length") else {}
            except ValueError:
                params = {}
            names = params.get("feeds") or None
            try:
                results = _feed_fetcher.fetch_all(
                    LOOKUPS_DIR, filter_names=names)
                self._send_json({"results": results,
                                 "ok": sum(1 for r in results if not r.get("error")),
                                 "fail": sum(1 for r in results if r.get("error"))})
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
            return

        if path == "/api/system/import":
            # Copy the selected system EVTX channels into
            # workspace/uploads/system-snapshot/. Two reasons we do this
            # rather than scanning System32 in place:
            #   * the analyst can re-run scans against the same point-in-time
            #     snapshot without re-elevating each time;
            #   * Hayabusa locks files briefly during scan, and we never
            #     want to hand it a path inside C:\Windows\System32.
            try:
                params = self._read_json()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            names = params.get("channels") or []
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                self._send_json({"error": "channels must be a list of strings"}, 400)
                return
            if not names:
                self._send_json({"error": "no channels selected"}, 400)
                return
            SYSTEM_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            saved, errors = [], []
            for fname in names:
                # Defensive: file name only, no traversal, only known suffix.
                if "/" in fname or "\\" in fname or ".." in fname:
                    errors.append({"name": fname, "error": "invalid name"})
                    continue
                if not fname.lower().endswith(".evtx"):
                    errors.append({"name": fname, "error": "not an .evtx file"})
                    continue
                src = SYSTEM_EVTX_ROOT / fname
                if not src.exists():
                    errors.append({"name": fname, "error": "not found"})
                    continue
                dst = SYSTEM_SNAPSHOT_DIR / fname
                try:
                    shutil.copy2(src, dst)
                    saved.append({
                        "name": fname,
                        "size": dst.stat().st_size,
                        "rel": str(dst.relative_to(WORKSPACE)).replace("\\", "/"),
                    })
                except OSError as exc:
                    errors.append({"name": fname, "error": str(exc)})
            self._send_json({"saved": saved, "errors": errors,
                             "snapshot_dir": str(SYSTEM_SNAPSHOT_DIR.relative_to(WORKSPACE)).replace("\\", "/")})
            return

        m = re.match(r"^/api/detections/([A-Za-z0-9_-]{6,64})/(\d+)/feedback$", path)
        if m:
            jid, line_no = m.group(1), int(m.group(2))
            try:
                params = self._read_json()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            verdict = params.get("verdict")
            if verdict not in (_store.VERDICT_TP, _store.VERDICT_FP, None, ""):
                self._send_json({"error": "invalid verdict"}, 400)
                return
            try:
                result = STORE.record_feedback(jid, line_no, verdict or None)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            if result is None:
                self._send_json({"error": "detection not found"}, 404)
                return
            self._send_json(result)
            return

        self._send_text("not found", 404)

    # ---------- domain helpers ----------

    def _hayabusa_version(self) -> str:
        try:
            out = subprocess.check_output([str(HAYABUSA_BIN), "help"],
                                          cwd=str(BIN_DIR), timeout=10,
                                          stderr=subprocess.STDOUT).decode("utf-8", "replace")
            for line in out.splitlines():
                if line.startswith("Hayabusa"):
                    return line.strip()
        except Exception:
            pass
        return "unknown"

    def _list_workspace(self):
        def walk(base: Path):
            out = []
            if not base.exists():
                return out
            for p in sorted(base.iterdir()):
                if p.is_dir():
                    out.append({"name": p.name, "type": "dir",
                                "rel": str(p.relative_to(WORKSPACE)).replace("\\", "/")})
                else:
                    out.append({"name": p.name, "type": "file",
                                "rel": str(p.relative_to(WORKSPACE)).replace("\\", "/"),
                                "size": p.stat().st_size})
            return out
        return {"uploads": walk(UPLOAD_DIR), "results": walk(RESULTS_DIR)}

    def _summarize_rules(self):
        """Walk the bundled rules dir and bucket by level + category."""
        if not RULES_DIR.exists():
            return {"total": 0, "by_level": {}, "by_category": {}}
        levels: dict[str, int] = {}
        cats: dict[str, int] = {}
        total = 0
        # Hayabusa bundles ~3000 rules; this scan is best-effort and only inspects YAML headers.
        for path in RULES_DIR.rglob("*.yml"):
            total += 1
            level = None
            category = path.parent.name
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for _ in range(60):
                        line = f.readline()
                        if not line:
                            break
                        if line.startswith("level:"):
                            level = line.split(":", 1)[1].strip()
                            break
            except OSError:
                pass
            levels[level or "unknown"] = levels.get(level or "unknown", 0) + 1
            cats[category] = cats.get(category, 0) + 1
        return {"total": total, "by_level": levels, "by_category": cats}

    def _hunt_filters(self, qs: dict) -> dict:
        """Translate the hunt URL query string into store kwargs.

        Multi-valued params (level=critical&level=high) come through as
        lists; we forward them as `levels=[...]`. Empty strings are
        normalised to None so the store doesn't AND-in vacuous clauses.
        """
        def first(k):
            v = qs.get(k, [""])[0]
            return v if v else None
        def list_(k):
            vs = [v for v in qs.get(k, []) if v]
            return vs or None
        return {
            "computer": first("computer"),
            "computer_glob": first("host"),    # short alias for UI
            "channel": first("channel"),
            "event_id": first("eid"),
            "levels": list_("level"),
            "rule_id": first("rule_id"),
            "rule_ids": list_("rule_ids"),
            "ts_from": first("from"),
            "ts_to": first("to"),
            "verdict": first("verdict"),
            "text": first("q"),
            "include_suppressed":
                qs.get("include_suppressed", ["0"])[0] in ("1", "true", "yes"),
            "job_id": first("job"),
        }

    def _row_to_detection(self, row) -> dict:
        """
        Reify a sqlite row into the JSON shape the UI consumes.

        The full Hayabusa event is unpacked from raw_json so the existing
        detail pane keeps working unchanged. The verdict + line_no fields
        are injected so the UI can post feedback.
        """
        try:
            event = json.loads(row["raw_json"])
        except (json.JSONDecodeError, TypeError):
            event = {}
        event["_job_id"] = row["job_id"]
        event["_line_no"] = row["line_no"]
        event["_verdict"] = row["verdict"]
        event["_rule_id"] = row["rule_id"]
        # Suppression columns are present when the query went through the
        # _SUPP_JOIN path (the only callers in production).
        try:
            sid = row["suppression_id"]
        except (IndexError, KeyError):
            sid = None
        if sid is not None:
            event["_suppressed"] = True
            event["_suppression_reason"] = row["suppression_reason"]
        else:
            event["_suppressed"] = False
        return event

    def _tail_text(self, path: Path, max_bytes: int) -> str:
        if not path.exists():
            return ""
        try:
            size = path.stat().st_size
            with open(path, "rb") as f:
                if size > max_bytes:
                    f.seek(size - max_bytes)
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def _stream_sse(self, job: Job):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = job.subscribe()
        try:
            # If the job is already done, deliver one snapshot and close.
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    payload = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    if job.status in ("done", "failed", "cancelled"):
                        return
                    continue
                self.wfile.write(payload.encode("utf-8"))
                self.wfile.flush()
                if json.loads(payload[6:].strip()).get("type") == "complete":
                    return
        except (BrokenPipeError, ConnectionResetError):
            return

    def _handle_upload(self):
        """
        Minimal multipart parser for a single file field named 'file'.

        We avoid the cgi module (deprecated in 3.13) and only handle the one
        upload shape the UI produces.
        """
        ctype = self.headers.get("Content-Type", "")
        m = re.match(r"^multipart/form-data;\s*boundary=(.+)$", ctype)
        if not m:
            self._send_json({"error": "expected multipart/form-data"}, 400)
            return
        boundary = ("--" + m.group(1)).encode("ascii")
        body = self._read_body()
        if not body:
            self._send_json({"error": "empty body"}, 400)
            return
        parts = body.split(boundary)
        saved = []
        for part in parts:
            if not part or part in (b"--\r\n", b"--"):
                continue
            part = part.lstrip(b"\r\n")
            if part.endswith(b"\r\n"):
                part = part[:-2]
            try:
                head, payload = part.split(b"\r\n\r\n", 1)
            except ValueError:
                continue
            head_text = head.decode("utf-8", "replace")
            fn_match = re.search(r'filename="([^"]+)"', head_text)
            if not fn_match:
                continue
            filename = os.path.basename(unquote(fn_match.group(1)))
            if not filename or not re.match(r"^[A-Za-z0-9._\-]+$", filename):
                continue
            target = UPLOAD_DIR / filename
            with open(target, "wb") as f:
                f.write(payload)
            saved.append({"name": filename, "size": len(payload),
                          "rel": str(target.relative_to(WORKSPACE)).replace("\\", "/")})
        if not saved:
            self._send_json({"error": "no file part found"}, 400)
            return
        self._send_json({"saved": saved})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def pick_port(preferred: int) -> tuple[int, bool]:
    """
    Try the preferred port first, fall back to an OS-chosen one.

    Returns (chosen_port, fell_back).  When `fell_back` is True the caller
    should print a loud warning — the most common cause is a zombie server
    from a previous (often elevated) launch holding the port. A silent
    fallback in that case is exactly how we recently shipped a confusing
    "browser opens the wrong server" bug.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((BIND_HOST, preferred))
        s.close()
        return preferred, False
    except OSError:
        s.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((BIND_HOST, 0))
        port = s.getsockname()[1]
        s.close()
        return port, True


def _holder_of_port(port: int) -> str:
    """Diagnostic: find what is currently bound to the requested port so
    we can tell the user how to kill it. Best-effort, Windows-specific."""
    if sys.platform != "win32":
        return ""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"], stderr=subprocess.STDOUT,
            timeout=3,
        ).decode("utf-8", "replace")
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""
    needle = f":{port} "
    for line in out.splitlines():
        if needle in line and "LISTENING" in line:
            parts = line.split()
            if parts and parts[-1].isdigit():
                return parts[-1]
    return ""


def boot_reindex():
    """
    Replay any job timeline JSONLs on disk into SQLite, and fold in any
    suppression snapshots so a wiped DB can be restored from version
    control. Both operations are idempotent.
    """
    report = _store.reindex_jobs_dir(STORE, JOBS_DIR)
    if report:
        total = sum(report.values())
        print(f"  Reindex: {total} new detections across {len(report)} job(s)",
              flush=True)
    imported = STORE.import_suppression_snapshots()
    if imported:
        print(f"  Imported {imported} suppression(s) from snapshot files",
              flush=True)


PORT_FILE = WORKSPACE / ".port"


def _primary_lan_ip() -> str:
    """Best-effort: the IP other machines on the LAN would use to reach us.
    Uses a UDP socket's routing decision (no packets are actually sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return BIND_HOST


def main():
    boot_reindex()
    preferred = int(os.environ.get("HAYABUSA_GUI_PORT", "8787"))
    port, fell_back = pick_port(preferred)
    host = BIND_HOST

    print(f"\n  Hayabusa GUI")
    print(f"  Binary : {HAYABUSA_BIN}")
    print(f"  Rules  : {RULES_DIR}")
    print(f"  DB     : {DB_PATH}")

    if fell_back:
        # The most common cause of "browser shows the OLD server" is a
        # zombie that grabbed the preferred port. Be very loud about it
        # so the launcher script can show a usable error.
        # We deliberately avoid emoji here because Python on Windows-jp
        # defaults stdout to cp932 which cannot encode astral characters.
        holder = _holder_of_port(preferred)
        print(f"\n  [WARN] Preferred port {preferred} is already in use.")
        if holder:
            print(f"  [WARN] Holder: PID {holder} (run 'taskkill /PID {holder} /F'")
            print(f"         or use Task Manager; may need Administrator).")
        print(f"  [WARN] Falling back to a random port. The launcher will open")
        print(f"  [WARN] the correct URL automatically. If you started the browser")
        print(f"  [WARN] manually, use the URL below - not http://127.0.0.1:{preferred}/.\n")

    if NETWORK_MODE:
        disp = _primary_lan_ip()
        url = f"http://{disp}:{port}"
        print(f"  Bind   : {host}:{port}  (all interfaces)")
        print(f"  Access : {url}   ← この URL を LAN の他 PC に共有")
        print(f"  [WARN] 公開モード: 認証なし。誰でもアップロード/スキャン/削除が可能です。")
        print(f"  [WARN] 信頼できる LAN 内でのみ使用してください (インターネットに晒さない)。")
    else:
        url = f"http://{host}:{port}"
    print(f"  Listen : {url}\n", flush=True)

    # Write the port file so start.ps1 / external tooling can open the
    # right URL even when we fell back to a random port. Atomically swap
    # to avoid a half-written file under a fast launch.
    try:
        tmp = PORT_FILE.with_suffix(".port.tmp")
        tmp.write_text(str(port), encoding="utf-8")
        tmp.replace(PORT_FILE)
    except OSError as exc:
        print(f"  (warn: could not write port file {PORT_FILE}: {exc})", flush=True)

    httpd = ThreadingHTTPServer((host, port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("shutting down")
        httpd.shutdown()
    finally:
        # Best-effort cleanup so the next launch isn't fooled by a stale
        # file. We don't worry if the file is already gone.
        try:
            PORT_FILE.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    main()
