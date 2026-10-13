# Morphorum Studio architecture contract

## Current implementation boundary (verified 2026-10-13)

This file describes both **implemented** components and **future** components. The original "Planned packages" tree below is historical guidance, not a directory listing. For exact present code and current branches consult [HANDOFF.md](HANDOFF.md) and fetch dev-ui.

Implemented on Studio **dev-ui**:
- Native Qt bootstrap/splash: app.py, ui/splash.py, package artwork in src/morphorum_studio/assets/splash-logo.jpg.
- Desktop shell: ui/main_window.py, ui/theme.py, nine workspaces; only Connections and Settings have real milestone interfaces.
- Session preferences: ui/preferences.py (QSettings, nonsecret), ui/startup_settings.py (visible settings controls), window geometry/workspace/last selected+successful connection persistence.
- Secure connection: backend/client.py (discovery HTTP), backend/worker.py (off-thread QRunnable), backend/profiles.py (nonsecret JSON profiles), backend/credentials.py (OS keyring), ui/connections_panel.py (credential import, consent, identity, status, passive monitoring/reconnect).
- CI/read-only wheel smoke: tests/* and scripts/verify_clean_install.py.

**S2 architectural decision needed before coding:** other workspaces require telemetry and models via a shared authenticated connection context. Currently ConnectionsPanel owns the active profile, probes, and reconnect state. Do not give individual pages their own keyring lookups and duplicate health pollers. Extract a reusable session/data boundary, publish signals or typed snapshots from worker threads, and ensure profile switch/disconnect invalidates all pending requests. Keep network off the Qt event loop.

**Two security distinctions:** QSettings trusted-HTTP approval means the user explicitly accepted sending credentials over **unencrypted** HTTP to that exact profile URL, not that the host is cryptographically verified. instance_id detects unexpected backend changes but is not TLS identity; an unfamiliar instance still requires independent user approval.

---


## System boundary

```text
  ┌──────────────────────────── Morphorum Studio ──────────────────────────┐
  │ PySide6 / Qt native Windows desktop UI; Linux-compatible              │
  │                                                                    │
  │  Native Workspaces / Navigation / Editors / Video Preview             │
  │             │                                    │                     │
  │        State models                         Qt workers                │
  │             │                                    │                     │
  │      Connection profiles ─ secure OS token store ─ API client          │
  │                               │                                        │
  └───────────────────────────────┼────────────────────────────────────────┘
                                  │ HTTP(S) REST + ephemeral SSE
                                  ▼
  ┌──────────────────── Morphorum GPU backend ────────────────────────────┐
  │ /api/client/capabilities, models, projects, jobs, events, media files │
  │ CUDA / SDXL / FLUX / Z-Image / render workers / FFmpeg / storage       │
  └────────────────────────────────────────────────────────────────────────┘
```

The backend is a **different repository**: https://github.com/merberg-ai/Morphorum. Studio does not import backend source, share its model directories or control its process lifetime simply because it connects to it.

**Accepted backend baseline:** `dev-backend` commit `2046d36ff6e084d801a14e2024d14665c207d884`, API contract v1. Backend `main` remains unchanged pending the user's future approval of draft PR #32.

## Planned packages

```text
src/morphorum_studio/
  __main__.py, app.py              # process bootstrap
  ui/
    theme.py, main_window.py       # S0 existing native shell
    connections.py                 # S1
    projects.py, assets.py         # S2
    image_lab.py, render_queue.py  # S3
    editor/, timeline/             # S4
    motion_lab/, audio_director/   # S5
  backend/                         # Added during S1+
    client.py                      # typed, authenticated API transport
    credentials.py                 # OS-native keyring
    profiles.py                    # non-secret stored profiles
    events.py                      # SSE and state reconciliation
    sessions.py                    # durable keyed render sessions
    downloads.py                   # verified media transfer
  models/                          # UI-only typed view state
tests/
docs/
```

The example tree above originated during S0. Implemented S1/pre-S2 modules now exist as listed at the top of this file. Future project/editor/job/media modules are **planned** and must not be represented as implemented.

## API and job lifecycle invariants

- Authenticate capabilities and health before claiming connection. Treat `api_contract_version=1` as a strict gate, recheck flags as capabilities evolve.
- Do not send browser `Origin` headers. The backend rejects them in backend-only mode.
- Store base URL and persistent `instance_id` separately. Identical instance ID is a continuity hint, **not** cryptographic identity. TLS certificate verification is independent.
- Changed `boot_id` resets in-memory SSE cursors. Never rely on durable SSE replay; job GET and persisted completed-frame records are the source of truth.
- Persist the *exact full project POST body* plus stable `Idempotency-Key` to protected local session storage **before** submitting a render. Never retry uncertain submits with a new key automatically. HTTP 409 pending/uncertain means stop and reconcile.
- Existing browser mode can still edit projects. Studio must use strong project revision ETags on conditional save (`If-Match`); return HTTP 412 conflict to user rather than overwriting.
- Download image/WAV/MP4/WebM/GIF into a temporary file, check expected size/hash and media signature, then atomically replace. A failed transfer must not destroy an existing file.
- Audio input analysis and imported soundtrack attachment are separate capabilities; do not fuse them into a fictitious single API.
- A backend process restart can interrupt active renders. Never imply GPU inference keeps running through process death. Completed renders are persistently recoverable.
- Never stop a remotely attached backend on Studio exit.

## Security and privacy

- Auth secrets are never committed, printed, echoed in a diagnostic panel or written to plain JSON profile/session files.
- Use a backend-host CLI to issue/revoke per-client credentials. Studio does not invent a new insecure pairing endpoint.
- Treat bare HTTP as **trusted-LAN-only**. Prefer authenticated encrypted VPN or TLS when leaving a trusted network.
- Restrict redirects and URL origins for authenticated media downloads to the connected backend. Scrub secrets from error logs.
- User-provided prompts, images and soundtrack files can be private. Keep cache/session data out of Git, apply OS permissions and offer cache clearing.
- Never infer a local filesystem path from server-relative diagnostic paths.
- Do not block the Qt GUI event loop on network, downloads, FFmpeg, or image decoding.

## Backend reference documentation

- [Backend's full Studio handoff](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/STUDIO_CLIENT_HANDOFF.md)
- [Client contract](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_CLIENT_CONTRACT.md)
- [Client security and profiles](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_CONNECTION_MANAGER.md)
- [Project media assets](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_PROJECT_ASSETS.md)
- [Live events and recovery](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_LIVE_RECOVERY.md)
- [Final backend physical acceptance](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_FINAL_ACCEPTANCE.md)

If documentation and the actual runtime diverge, inspect the `dev-backend` source and live authenticated capabilities before implementing UI behavior.
