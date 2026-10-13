# Morphorum Studio: NEW-CHAT HANDOFF

**Last authored:** 2026-10-12.
**Read this file first when resuming development in a new chat.**
**Owner-created repository:** https://github.com/merberg-ai/Morphorum-Studio
**Backend repository:** https://github.com/merberg-ai/Morphorum

## The user's exact decision

The user created a **separate** repository for the real native Morphorum desktop Studio application. The user explicitly instructed: **do NOT merge the Morphorum backend into `main` until the frontend app is working**. Keep the backend's [draft PR #32](https://github.com/merberg-ai/Morphorum/pull/32) **unmerged** while Studio development proceeds. An explicit later user approval is required. Do not create another UI repo.

The purpose is a **true native desktop frontend**, not an embedded copy of the existing browser UI. It must control an existing GPU backend over a documented network API and use no local GPU/model installation.

## Repo state at S0 initialization

- `Morphorum-Studio` was initially created by the user as a public repository with **The Unlicense** and the agreed GitHub description.
- The S0 scaffold was initialized on **Studio `main`**, not on the backend repo. Implemented files:
  - `pyproject.toml`: installable Python 3.12+ PySide6 app, version `0.1.0a1`.
  - `src/morphorum_studio/app.py`, `__main__.py`: Qt launcher and version CLI.
  - `src/morphorum_studio/ui/main_window.py`: dark desktop shell, nine real navigable pages, offline status.
  - `src/morphorum_studio/ui/theme.py`: dark graphite theme.
  - `tests/test_shell.py`: version, navigation, initial offline-state assertions.
  - `.github/workflows/ci.yml`: Linux/Windows Python 3.12 install + offscreen UI test.
  - `README.md`, docs, gitignore.
- **S0 is scaffold-only**. Backend connection, auth, projects, generation and render-monitoring are **NOT yet implemented in Studio**. UI placeholder pages say so.
- **S0 CI and physical Windows launch are separate gates.** Don't claim S0 physically verified until the user launches it on their machine and confirms.

### Current branch policy

Start with Studio `main` for the initial scaffold. Develop each substantial milestone on a dedicated `feature/studio-s1-...` branch (or subsequent S2 etc.), run CI, stop for Windows physical acceptance, then merge to Studio `main` **only with explicit user approval**. Preserve an immutable verified checkpoint when each phase passes physical tests.

Avoid rewriting previous accepted checkpoints or automatically merging unrelated backend changes.

## Backend: actual accepted baseline

Backend `merberg-ai/Morphorum` `dev-backend` HEAD after ordered merge of #27–#31:

```text
2046d36ff6e084d801a14e2024d14665c207d884
```

- All five DB2 PRs were merged in order into **`dev-backend`**, preserving their milestone checkpoints.
- Combined branch post-merge CI: **536 passed, 1 skipped** backend tests; backend self-test, browser syntax, and installer checks green. Draft PR #32 against `main` remained unmerged.
- Actual Windows Omen backend tests verified remote SDXL still-image and 120-frame animation, live disconnect/re-attachment to same render ID, SHA-256 project assets, conditional saves, backend restart recovery for **completed** render, safe idempotent replay, and FFmpeg MP4/WebM exports with WAV audio. Existing browser mode also passed physical user verification.
- Backend runtime version `0.1.0a1`, API contract **1**; Studio must inspect `GET /api/client/capabilities` at runtime rather than assuming all features always work.

Backend integration reference:
[docs/STUDIO_CLIENT_HANDOFF.md](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/STUDIO_CLIENT_HANDOFF.md)
Additional backend technical references:
[DB2_CLIENT_CONTRACT.md](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_CLIENT_CONTRACT.md),
[DB2_CONNECTION_MANAGER.md](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_CONNECTION_MANAGER.md),
[DB2_PROJECT_ASSETS.md](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_PROJECT_ASSETS.md),
[DB2_LIVE_RECOVERY.md](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_LIVE_RECOVERY.md),
[DB2_FINAL_ACCEPTANCE.md](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_FINAL_ACCEPTANCE.md).

The backend docs may describe their own **historical** feature-branch state; current `dev-backend` source and live feature discovery take precedence over stale headings.

## Test environment from the completed backend work

- Primary Windows GPU host: HP Omen 35L, RTX 4080 SUPER 16 GB VRAM, existing checkout `D:\Morphorum-test`.
- Backend test launcher: `.\run.bat --backend-only --lan` (backend-only default port **7866**). A known **example** local LAN endpoint was `http://192.168.1.24:7866`; treat this as environment-specific and configurable, **never hardcode it**.
- Normal backend Web UI: `.\run.bat`, usually http://127.0.0.1:7865. Studio is independent of it.
- Ubuntu Mini/ConnectBot was the successful remote API acceptance client. Studio Windows testing can initially run on the Omen or another Windows client on the LAN.
- Authentication uses a bearer token or per-client credentials issued by the **backend host's** admin CLI. Do not print tokens, commit credentials, or fake a pairing-code endpoint.
- Plain HTTP is not encrypted. Document use of **trusted LAN only** until TLS/VPN transport can be configured; no public exposure.

## Proposed technology and package boundaries

- Python 3.12+ / **PySide6 Qt 6**, Windows-first, Linux next.
- Pure client. **No CUDA, PyTorch, model downloads or dependency on shared backend directories.**
- Split UI and network/service code: `ui/` holds Qt widgets; `backend/` (future Studio client transport namespace) holds API, reconnect, credential store, asset verification, long-lived session logic.
- Real native widgets and media display; don't embed the old Morphorum browser UI in a WebView.
- Never let network I/O or FFmpeg media probing block Qt's UI thread. Introduce cancellable worker/async layer when S1 begins.
- Use OS-protected credential storage (Windows Credential Manager via Python `keyring` or equivalent) rather than JSON secrets. S0 stores no credentials.
- Projects remain authoritative on the backend; Studio must use `If-Match` when saving. Local files only where explicitly imported/exported or cached, with checksums.

## The immediately NEXT TASK after this handoff

1. Check Studio `main` repo files and GitHub Actions for the scaffold. Verify the Windows/Linux CI result; fix only real failures.
2. Ask user to run the S0 shell on Windows using the README. The physically visible UI should have nine navigable workspaces and say **BACKEND OFFLINE**. It must not start/stop the backend.
3. User accepts or reports S0 UI issues. Fix, rerun CI, create an **S0-verified checkpoint**, if accepted.
4. Begin **S1.1 connection foundation** on a new Studio feature branch. First implement versioned `/api/health` + `/api/client/capabilities` transport and pure mocked tests; then named profiles, secure credential storage and worker-thread Qt binding in deliberate substeps. Stop for live Windows LAN acceptance before merging.
5. Use [ROADMAP.md](ROADMAP.md) for complete S0–S7 phase plan and checklists.

**Do not jump directly into full Motion Lab UI before securing the API and project contract.**

## Nonnegotiable correctness rules

- A stable backend `instance_id` is NOT a TLS trust anchor; changed instance requires explicit user confirmation.
- A changed `boot_id` resets ephemeral event cursors and triggers authoritative job GET.
- Browser `Origin` headers are forbidden by backend-only mode; native client must not add them.
- Durable `Idempotency-Key` and **identical** frozen POST body must be persisted **before** submitting GPU jobs.
- A `409` with pending/uncertain submission is a stop-and-reconcile condition, **not** an invitation to submit under a different key.
- SSE history is not durable. Poll job GET and list persisted frames on reconnect; never claim it is.
- SHA-256 verify downloaded project and exported video assets before atomic replacement. Never silently overwrite a good local file with corrupt bytes.
- Backend restart can interrupt active GPU work; don't automatically resume it. Completed media persisted through restart as physically verified.
- Backend's **`main` stays untouched** until frontend is working and user explicitly approves draft #32.
- Do not claim Studio features or CI/physical outcomes that have not been implemented/tested.

## S0 accepted and S1.1 work in progress (2026-10-12)

- User confirmed all S0 physical Windows shell tests PASS.
- S0 Windows-verified checkpoint branch: `checkpoint/studio-s0-windows-verified-20261012`, from Studio commit `fb5024e7592a6d271a8eeb214fc2470387d2e363`. Exact checkpoint CI passed on both Windows and Linux.
- Work branch: `feature/studio-s1-connection-foundation`. Do **not** merge pending S1 changes until physical review and user approval.
- S1.1 pure Python typed discovery client at `src/morphorum_studio/backend/client.py`, tested using mocked HTTP in `tests/test_backend_client.py`. This is **not yet connected to the Qt interface**. No live LAN acceptance claimed.
- User additionally requested setup/install/update/launch scripts; added `setup.ps1`, `run.ps1`, `update.ps1`, plus `setup.sh`, `run.sh`, `update.sh`. See `docs/S1_FOUNDATION.md` for security notes and usage.
- Next physical acceptance: switch to S1 feature branch, run Windows `.\setup.ps1`, `.\run.ps1`, `.\update.ps1`; verify app still navigates nine pages offline, does not launch backend, update safely preserves current branch. Then begin S1.2 worker-backed connection panel with keyring and instance identity confirmation.
- Ignore earlier handoff wording that says S0 physical verification is pending; this appended record supersedes it.

## S1.2 connection manager candidate (2026-10-12)

S1.2 implementation on `feature/studio-s1-connection-foundation` now includes `backend/profiles.py` (named, non-secret, atomic JSON profiles), `backend/credentials.py` (OS keyring tokens), `backend/worker.py` (Qt QRunnable network discovery), and `ui/connections_panel.py` (New/Save/Remove/Connect/Test/Disconnect UI, backend details, safe offline status, HTTP trust confirmation, and explicit identity mismatch approval). The Connections workspace is wired to this real panel; top-bar status changes with connection tests. The keyring package is installed in pyproject dependencies.

**Acceptance not yet claimed:** CI on the final commit and physical Windows LAN tests must pass. The current worker model supports one-shot manual connection tests; automatic retry/backoff, long-lived reconnect state, cancel-in-flight, and persisted-session job reconciliation remain follow-up S1 hardening. Do not treat the green CONNECTED label as continuous liveness monitoring. No ability to start/stop the backend is added. Backend `main` and Studio `main` remain untouched.

## S1.2 LAN milestone user verification (2026-10-12)

User confirmed Studio **connected successfully to the remote Morphorum backend over LAN** after token-file-import UX and syntax fixes. Initial authenticated backend discovery is physically PASS by user report. Both Windows and Ubuntu CI passed on correction commit `a3c01452bf630da76b6380d144c05bf943be8569`. This is not blanket S1 physical acceptance: revoked/wrong-token tests, backend restart and boot-ID refresh, identity mismatch, offline responsiveness, and reconnect behavior remain separate gates. S1.2 stays unmerged.
