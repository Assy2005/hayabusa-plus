# Hayabusa GUI + Detection Platform Blueprint

This workspace contains two things:

1. **A working localhost GUI for Hayabusa** — a thin Python control plane that
   wraps the upstream `hayabusa.exe` (v3.9.0) and exposes a SPA at
   `http://127.0.0.1:8787` for triaging EVTX files interactively.
2. **`ARCHITECTURE.md`** — the design document for a next-generation,
   lightweight, Sigma-compatible, resident detection platform built on top of
   Hayabusa's core. This is the blueprint, not yet the implementation.

## Layout

| Path | Purpose |
| --- | --- |
| `bin/hayabusa-3.9.0-win-x64.exe` | Upstream Hayabusa binary (do not patch in place) |
| `bin/rules/`, `bin/config/` | Hayabusa rules + config (must sit next to the binary) |
| `hayabusa-src/` | Upstream source (shallow clone, reference only) |
| `gui/server.py` | Python stdlib HTTP server (no external deps) |
| `gui/static/` | SPA assets (HTML/CSS/JS — no framework, no build step) |
| `workspace/uploads/` | EVTX files dropped by the user |
| `workspace/jobs/<id>/` | Per-scan output (stdout, stderr, JSONL detections, HTML summary) |
| `start.ps1` | Launcher: starts the server, opens the browser |
| `ARCHITECTURE.md` | Detection platform blueprint (the design half of this work) |

## Run

```powershell
.\start.ps1
```

Requires Python 3.9+ on PATH. The launcher binds to `127.0.0.1:8787` (override
with `$env:HAYABUSA_GUI_PORT`).

## What the GUI does today

- Upload an EVTX (or point at a directory under `workspace/`)
- Filter by min level, ATT&CK tag, time window, EID-fast-path, proven-only rules
- Streams detections back over Server-Sent Events as the scan runs (live feed)
- Per-scan history with paginated detection table + JSON inspector
- Opens Hayabusa's native HTML summary in a new tab
- Indexes the bundled rule set (level / category breakdown)

The GUI is intentionally a thin wrapper: EVTX parsing and Sigma matching are
delegated to the unmodified Hayabusa binary, which keeps it as the trust
boundary. See `ARCHITECTURE.md` §7 for the modification plan to lift this from
"one-shot scanner UI" into a resident detection platform.

## Security notes

- Localhost-only bind. No authentication. Single-user assumption.
- Live-analysis (`-l`) requires the "Authorize live analysis" checkbox to be
  ticked, **and** running the process as Administrator (Hayabusa needs to read
  the System32 winevt logs). The server treats this as a privileged operation
  and never enables it implicitly.
- Uploaded filenames are validated against `^[A-Za-z0-9._-]+$`. Paths
  supplied from the UI are resolved and confined to `./workspace/`.
- The GUI never accepts user-supplied flags; it builds the Hayabusa argv from
  a whitelist. Argument-injection from the browser is not possible.

## Scope

This is an **offline / on-demand** DFIR analysis workbench. Resident
operation (ETW realtime sessions, Windows service, userland probe) is
**explicitly out of scope** — see `ARCHITECTURE.md` §0 for the scope
declaration and the consequences of that choice.

The platform is the *triage UI you can use today* plus the *blueprint* for
extending Hayabusa into a richer offline detection engineering workbench
(`correlate:`, `behavioral:`, `lookup:` Sigma extensions, 2-pass
correlation, AI-assisted rule generation). Implementation requires Rust
development against the forked Hayabusa core (`hayabusa-src/`).
