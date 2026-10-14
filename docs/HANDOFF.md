# Morphorum Studio: current development handoff

**Updated: 2026-10-13. Start here in a new chat.**
- Studio repository: https://github.com/merberg-ai/Morphorum-Studio
- GPU backend repository: https://github.com/merberg-ai/Morphorum
- Working Studio branch: **dev-ui**, latest inspected implementation SHA **f91b3e6cf05329c1816e0c68ff7358bd11c63d07**. Documentation-only commits made after that SHA may advance dev-ui; **inspect GitHub before changing code**.
- Studio main remains at S0 SHA **fb5024e7592a6d271a8eeb214fc2470387d2e363** and MUST NOT be merged without the user's approval.
- Backend dev-backend remains at **2046d36ff6e084d801a14e2024d14665c207d884**. Its draft PR **#32** is open and unmerged against backend main. Do NOT merge it before the Studio frontend is working and the user explicitly approves.
- Current phase: **S1 connection implementation + Pre-S2 native UI polish completed for now. S2.1 not started.** The user requested a detailed handoff and is pausing work.

## If you are a new ChatGPT chat

Read this file, docs/ROADMAP.md, docs/PRE_S2_UI_POLISH.md, docs/ARCHITECTURE.md, and the relevant backend contract documents. **Fetch current dev-ui source, branch heads and GitHub Actions instead of relying only on prose.** Stay on dev-ui unless the user directs otherwise; if beginning a major new phase, discuss whether to create a separate S2 feature branch from accepted dev-ui before editing. Never assume Studio main contains these features. Do not write files in the Morphorum backend repository unless separately approved.

The logical next phase is **S2.1: backend telemetry and model discovery with a useful Home/dashboard view**, followed by S2.2 revision-safe project browsing and S2.3 asset handling. Prior to implementing any screen, verify live backend endpoint response schema and feature flags and expose no fake data or dead controls. The user may instead want additional interface polish: follow their current instruction.

## Project goal and nonnegotiable architecture

Morphorum Studio is an independent **native PySide6 Windows-first desktop frontend** (Linux compatible) controlling an existing Morphorum GPU backend over authenticated REST and, in later milestones, SSE. This is NOT the browser UI in an embedded WebView and NOT a local inference installation. Studio must never install CUDA, PyTorch, model weights or require a shared GPU-host filesystem. All generation, model indexing, media export and GPU work happen in the separate backend. A Studio exit, disconnect or network failure must never stop or restart an attached backend, nor automatically resubmit a GPU job.

Backend reference docs, from dev-backend:
- https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/STUDIO_CLIENT_HANDOFF.md
- https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_CLIENT_CONTRACT.md
- https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_CONNECTION_MANAGER.md
- https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_PROJECT_ASSETS.md
- https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_LIVE_RECOVERY.md
- https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/DB2_FINAL_ACCEPTANCE.md

Backend API contract is **v1**. GET /api/health and GET /api/client/capabilities are currently implemented for authenticated discovery. Always inspect advertised backend features rather than inferring support from a UI label. Backend docs have some stale historical headings because Studio was created afterward; actual dev-backend source/response wins.

## Exact git state / recovery points

**Studio**
- dev-ui: working branch, inspected implementation commit **f91b3e6** (corrected logo JPEG and Qt decoder warning regression); exact Windows + Ubuntu CI GREEN.
- main: **fb5024e**, S0 scaffold only. Intentional: no merge.
- feature/studio-s1-connection-foundation: **ed5ede9**, S1 security closeout and regression tests; a historical development base. dev-ui already includes this work.
- checkpoint/studio-s0-windows-verified-20261012: **fb5024e**; physical S0 PASS.
- checkpoint/studio-s1-reconnect-windows-verified-20261012: **726f4ce**; physically confirmed connection/reconnect PASS, not blanket certification of later work.
- checkpoint/studio-p3-splash-windows-verified-20261012: **f16f65e**; earlier manual-logo splash accepted, not final bundled image.
- checkpoint/studio-pre-s2-polish-ci-verified-20261012: **aa7e798**; pre-S2 packaging and fresh-wheel CI passed. **This checkpoint predates correction of a malformed JPEG; do not mistake it for the latest best build.**
- A checkpoint for **f91b3e6** has **not** been created; user has not expressly reported a separate warning-free Windows retest after the JPEG re-encode. The user said the project is good for now and requested documentation. Do not invent additional physical acceptance or silently replace old checkpoint refs.

**Backend**
- dev-backend: **2046d36ff6e084d801a14e2024d14665c207d884**, completed DB2 PR integration #27–#31.
- Draft https://github.com/merberg-ai/Morphorum/pull/32 targets backend main; as checked 2026-10-13 it was open/draft/unmerged.
- Backend integrated CI had 536 passed, 1 skipped and user physically verified backend render/recovery/media flows in earlier sessions. Backend main is intentionally held until Studio is working and user approves.

## What is actually implemented in Studio today

### S0 native application scaffold
- src/morphorum_studio/app.py, __main__.py: Python CLI/Qt bootstrap, version 0.1.0a1, splash startup.
- ui/main_window.py: dark desktop shell with **nine workspaces** (Home, Connections, Projects, Image Lab, Editor, Motion Lab, Render Queue, Console, Settings), status header, navigation and footer.
- Only **Connections** and **Settings** are fully interactive milestone panels. Home and most other workspaces are **honest placeholders**: no models, project browser, render submission, telemetry, timeline editor or preview player yet.
- ui/theme.py: graphite + restrained neon cyan/violet widgets, styled primary/danger buttons, text inputs, combo boxes, checkboxes, cards and scrollbars. P1 visual refresh user accepted on Windows.
- Windows and Linux project-local install/run/update scripts are provided.

### S1 authenticated LAN connection manager
- backend/client.py: typed BackendClient (bounded timeouts, URL normalization, explicit error categories, disabled redirect following, v1 discovery validation). It is synchronous and must be called **off the Qt GUI thread**. get_json currently accepts fixed /api/... paths only, rejecting query strings: extend safely for model-family query parameters when S2 begins.
- backend/profiles.py: saved named connection profiles with URL + stable instance_id and boot_id in nonsecret JSON; profile IDs are generated locally. Profile data is separate from bearer tokens.
- backend/credentials.py: secure OS keyring (Windows Credential Manager) via keyring library. **Never print, log or commit bearer token values.**
- backend/worker.py: QRunnable discovery worker with signals, invoked by ui/connections_panel.py through QThreadPool.
- ui/connections_panel.py: create/save/remove/select profiles, import backend-issued token file into keyring, Connect/Test, Disconnect, backend version/mode/feature details. The import source file is NOT automatically deleted.
- Passive background probing every **15 seconds** while connected. Network failures show BACKEND RECONNECTING with **10–60 second** bounded passive retry; 401/403 stop retry and show BACKEND UNAUTHORIZED; API incompatibility and identity mismatch have separate errors.
- Changed backend instance_id triggers explicit user confirmation (not a TLS trust anchor). boot_id change is reported; **actual render-job restoration after backend restart is not implemented in Studio** (S3 task). In-flight discovery responses after user Disconnect are invalidated by an epoch.
- Connections ownership currently resides largely in ConnectionsPanel. For S2 shared telemetry/model data, design a reusable authenticated **application-level connection/session service** or a clean signal/data facade before having other screens reach into widget internals. Ensure no duplicate health pollers and no UI-thread network traffic.

### Pre-S2 polish: P1–P4
- ui/preferences.py wraps OS-native QSettings for **nonsecret** flags, last selected workspace, window geometry/maximized state, last selected connection ID and last successful connection ID (distinct).
- ui/startup_settings.py provides Show splash, Restore geometry, Restore workspace, Auto-connect preferences.
- Window size/position/maximized state and workspace are restored; offscreen restores are clamped when monitor geometry changes.
- After startup, if opted in, the **last successful backend** is connected in the background. This does not hold the splash visible.
- Plain-HTTP credential consent is persisted only for the selected profile ID **and exact backend URL**. Saving the trust checkbox retains it; changing URL/profile requires new approval. Missing consent blocks unattended HTTP auto-connect, rather than opening a startup security popup. Plain HTTP is suitable **only on a trusted LAN**; use TLS/VPN for untrusted links.
- ui/splash.py shows a compact 560x430 branded splash with real startup stage messages and a 3-step progress bar. Logo automatically scales to a maximum view of 410x308.
- Optimized image committed at assets/morphorum-studio-logo.jpg and also shipped in installable package at src/morphorum_studio/assets/splash-logo.jpg. Code loads via importlib.resources, not an assumed working directory. pyproject.toml declares the image in setuptools package-data.
- scripts/verify_clean_install.py builds a wheel, installs it into a temporary venv and verifies the bundled logo loads via Qt; this runs in the Windows+Ubuntu CI workflow.
- Original logo JPEG caused a Windows terminal warning: **qt.gui.imageio.jpeg: Corrupt JPEG data: 6 extraneous bytes before marker 0xc0**. It was re-encoded as valid JPEG in both locations by a one-time CI workflow, the one-time repair machinery was removed, and tests/test_splash.py now asserts **no Qt decoder warning**. Exact code commit **f91b3e6** passed dual-platform CI, including fresh-install wheel check. **A subsequent human Windows visual/terminal verification has not been explicitly documented.**

### Tests / build
- tests/test_shell.py, test_backend_client.py, test_profiles.py, test_connections_panel.py, test_preferences.py, test_splash.py.
- .github/workflows/ci.yml runs Python 3.12 Qt offscreen install, compile, CLI, pytest and fresh-wheel clean-install logo smoke test for **Windows and Ubuntu**.
- At exact f91b3e6, **both jobs completed successfully**. Rerun tests on any new implementation commit. No local Windows clean install was physically observed by the assistant; clean-install test is automated on hosted runners.

## Physical Windows acceptance evidence

Confirmed user reports over this project's chats:
1. S0 initial native shell, navigation, offline state and normal close: PASS.
2. Authenticated token-file LAN connection to existing Omen backend: PASS.
3. Backend stop/start, reconnect monitoring, boot ID change and manual disconnect: PASS.
4. Disposable client-token revocation: Studio showed unauthorized and stopped retry: user reported PASS. Mocked wrong/revoked credential and unexpected changed-instance acceptance tests are included; **no second real backend instance test documented**.
5. P1 visual control polish: PASS.
6. P2 geometry, maximized state, last workspace and settings toggles persisted: PASS.
7. After user found inert auto-connect and reset HTTP trust checkbox, fixes deployed; user reported startup reconnect and no repeated consent prompt: PASS.
8. P3 original branded splash + loading progress: PASS.
9. Bundled logo displayed on Windows but produced malformed-JPEG warning. Corrected re-encode completed; **CI passes, but no explicit final user confirmation that Windows terminal warning has disappeared**.

These are incremental acceptance reports. They do not imply S2, rendering or editor behavior is implemented.

## Workstations, launching, and test instructions

- Windows development/test checkout in the most recent user commands: **D:\Morphorum-Studio**. Some earlier sessions used **D:\SRC\Morphorum-Studio**; prefer the user's currently reported path or ask if unsure. Backend checkout is separate: **D:\Morphorum-test** on HP Omen 35L with NVIDIA RTX 4080 SUPER 16GB.
- Backend-only launch from backend checkout, if needed: **.\run.bat --backend-only --lan**, normally port **7866**. Illustrative previous LAN URL: http://192.168.1.24:7866. Do not hardcode a host address.
- Backend client token management (run in backend checkout on host):
  - .\.venv\Scripts\python.exe -m morphorum clients issue "Morphorum Studio" --days 90 --out ".\data\studio-client.token"
  - .\.venv\Scripts\python.exe -m morphorum clients list
  - .\.venv\Scripts\python.exe -m morphorum clients revoke CLIENT_ID
  The secret is in the emitted token file, NOT in chat or repository.
- Windows Studio checkout setup/update/run, with an already existing dev-ui checkout:

~~~powershell
cd D:\Morphorum-Studio
git status --short --branch
git switch dev-ui
.\update.ps1
.\run.ps1
~~~

For a *new clone*, explicitly choose **dev-ui** since main remains S0:

~~~powershell
git clone --branch dev-ui https://github.com/merberg-ai/Morphorum-Studio.git
cd Morphorum-Studio
.\setup.ps1
.\run.ps1
~~~

If git reports local changes before update, **do not discard or force-reset**; inspect the changes first. update.ps1 is a guarded fast-forward updater and should not switch branches. Studio run scripts do not start or stop the GPU backend.

Tests (after developer setup):
~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_clean_install.py
~~~
For Linux use ./setup.sh, ./run.sh, ./update.sh and the venv bin/python equivalent. Offscreen CI sets QT_QPA_PLATFORM=offscreen.

## What is NOT delivered / open items

- S2.1 dashboard/telemetry/model discovery: NOT STARTED. All model/media/project options must originate from backend.
- No shared app-wide connection service for multiple workspaces yet; connection probing is owned by ConnectionsPanel.
- No project list/open/save, ETag/If-Match 412 conflict UI, local cache or SHA-256 media download flow.
- No still image/animation/video job submissions, no idempotency journal, SSE events, live render preview, persisted job reconciliation, user media export or FFmpeg player.
- No native animation editor, Motion Lab, waveform analysis, gamepad/keyboard recording, prompts/keyframe timeline or New Project Wizard.
- No distributable installer, signed app or real package release yet. Editable source installation and wheel build testing are available.
- S1 automated host identity mismatch refusal is tested in mocks, but a **physical changed-instance acceptance with a second backend** remains optional/pending.
- Optional UI follow-ups: high-DPI/multi-monitor manual tests, slow-backend responsiveness, missing or rejected auto-connect credentials in startup-specific integration tests, keyboard navigation/accessibility polish.
- Corrected bundled JPEG needs a final user-visible Windows check only if the user wishes to close that last manual gate. Do not revert the repaired asset.
- Prior documentation records chronological candidate status, some of which is obsolete. **This handoff's current-status sections supersede dated candidate claims.**

## Next implementation target: S2.1

**Do not assume S2.1 has been authorized in this new chat.** When the user asks to continue, agree on a small first increment. Recommended sequence:
1. Verify current dev-ui and dev-backend branch tips and latest CI. Review docs/ROADMAP.md and backend contract against real API routes. Confirm relevant feature flags.
2. Design shared, Qt-safe authenticated connection context for screens other than Connections, preserving secure token/URL/instance trust checks, without changing S1 behavior.
3. Add typed read-only clients for real telemetry endpoints (backend docs list **GET /api/system/telemetry** and **GET /api/system/gpu-memory**) and model endpoints (**GET /api/models/families**, **GET /api/models?family=...**). Inspect real payloads before prescribing fields; URL-query support needs a safely encoded transport extension.
4. Add off-thread bounded polling and status models. Do not block Qt event loop; throttle, handle backend unplug/reconnect/authorization failure. Render unavailable metrics as unavailable, never fabricated zero. Confirm CPU/GPU/RAM/VRAM units/labels and GPU identification against live backend.
5. Replace Home placeholder with native overview cards and model lists, selected model defaults and ability to refresh. Controls not backed by a real supported API must be informative only or disabled, never pretend to load models or generate.
6. Mock/fake HTTP, Qt offline/connection regression tests, wheel tests, GitHub Actions on exact SHA; STOP for user Windows physical testing. Checkpoint only after PASS. Keep dev-ui and Studio/backend main separate unless user explicitly approves merges.

Later S2.2: version-safe project list/browser, GET revision ETag, conditional PUT If-Match, explicit 412 conflict UX and new-project wizard with valid camera defaults. S2.3: project assets upload/download, hash verification and soundtrack semantics. S3: idempotent image/animation jobs and recovery, media export verification, SSE as hint with authoritative REST state. S4/S5: editing/timeline/Motion Lab and Audio Director. S6: performance/accessibility. S7: packaging/releases.

## Safety and project rules worth repeating

- **Never auto-merge or delete checkpoint branches.** Studio main and backend main are independent, both require explicit approval. Backend draft PR #32 stays unmerged until specifically authorized.
- Do not put secrets in Git, URL queries, logs, settings JSON, test fixture results or user-facing text. Token file transfers stay local/trusted; keyring owns actual secret.
- Native backend-only HTTP client must omit browser Origin; reject credentialed redirects.
- instance_id continuity is not cryptographic proof; boot_id changes do not mean GPU jobs survive backend process death.
- Save frozen full render request JSON and same Idempotency-Key to protected local journal **before** POST. Unknown/409 pending state requires reconciliation; never resubmit with a new key blindly.
- SSE is ephemeral, REST GET + durable render manifests are authoritative. On reconnect or backend boot change, invalidate ephemeral cursors.
- Use strong project ETag/If-Match and show 412 conflicts; never silently overwrite.
- Download media to .part, validate size/SHA256/magic and atomically replace. Soundtrack and analyzed Motion Lab WAV are distinct.
- Keep source, CI, docs and user physical test results synchronized; never conflate unit/CI PASS with physical Windows PASS.

**At the end of this handoff:** no action is required while the user is paused. Source of truth for the next task is the user's new request plus live GitHub state, starting from dev-ui.

## UI shell foundation (branch feature/studio-ui-shell)
See docs/UI_SHELL.md. Stacked on feature/studio-s1-hardening; neither is merged. Awaiting CI and a physical Windows test.

## S2.1 dashboard (branch feature/studio-s2-1-dashboard)
See docs/S2_1_DASHBOARD.md. Stacked on feature/studio-ui-shell. Read-only; awaiting CI and a physical Windows test against a live backend. Nothing merged.

## S2.2 projects (branch feature/studio-s2-2-projects)
See docs/S2_2_PROJECTS.md. Stacked on feature/studio-s2-1-dashboard. Name/notes edit with ETag/If-Match, create, trash. CI green and physical Windows test passed. Nothing merged.

## S2.3 media (branch feature/studio-s2-3-assets)
See docs/S2_3_ASSETS.md. Stacked on feature/studio-s2-2-projects. Source image + soundtrack upload, verified save-copy. CI green and physical Windows test passed. Nothing merged.

## S3.1 Image Lab (branch feature/studio-s3-1-image-lab)
See docs/S3_1_IMAGE_LAB.md. Stacked on feature/studio-s2-4-polish. Durable journalled submissions with Idempotency-Key, REST job polling, viewer. First GPU-starting feature: test with a small model. CI green and physical Windows test passed. Nothing merged.

## S3.2 animation renders (branch feature/studio-s3-2-animation)
See docs/S3_2_ANIMATION.md. Stacked on feature/studio-s3-1-image-lab. Render card on the Projects page; journalled start, REST polling, resume, frame browser, GIF preview. CI green and physical Windows test passed. Nothing merged.

## S3.3 video exports (branch feature/studio-s3-3-video)
See docs/S3_3_VIDEO.md. Stacked on feature/studio-s3-2-animation. Export section in the Render card: backend FFmpeg discovery, journalled idempotent export, REST polling, audio stated only from the export record, SHA-256-verified save, cached verified playback. CI green and physical Windows test passed. Nothing merged.

## S4.1 timeline viewer (branch feature/studio-s4-1-timeline)
See docs/S4_1_TIMELINE.md. From dev-ui (S1-S3.3 + console merged). Read-only Editor page: lanes, scrubbing, backend-resolved values and curves. Awaiting CI and a physical Windows test. Nothing merged beyond dev-ui.

## S4.2 keyframe editing (branch feature/studio-s4-2-keyframes)
See docs/S4_2_KEYFRAMES.md. From dev-ui (S4.1 merged). Set/update/delete/move keyframes and interpolation via the backend track endpoints with an ETag guard before each edit, backend reload after, and Studio-side undo/redo. Awaiting CI and a physical Windows test.

## S4.3 validation + Deforum import (branch feature/studio-s4-3-import-validation)
See docs/S4_3_IMPORT_VALIDATION.md. From dev-ui (S4.2 merged). Backend schedule validation shown in the Editor and used as a render pre-flight; Deforum settings preview/create as a new project. Awaiting CI and a physical Windows test.

## S4.4 project setup (branch feature/studio-s4-4-project-setup)
See docs/S4_4_PROJECT_SETUP.md. From dev-ui (S4.3 merged). New-project wizard (backend template, local + backend review before create, never writes camera values), prompt/source start-mode selector on the media card (conditional PUT of animation.start_mode), read-only Models and LoRAs browser with LoRA inspection. Awaiting CI and a physical Windows test.

## UI pass (branch feature/studio-ui-pass)
See docs/UI_PASS.md. From dev-ui (S4.4 merged). CI screenshot job (ui-screenshots branch), control glyphs, dialog/tab styling, Projects toolbar and scrolling Editor layout, shortcuts (F5, Ctrl+N/S/Z/Y, F1), tooltips, remembered console view. Awaiting CI and a physical Windows test. S5 follows.
