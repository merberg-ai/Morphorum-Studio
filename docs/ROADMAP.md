# Morphorum Studio development roadmap

**Current state (2026-10-13):** S0 Windows-verified; S1 connection manager and pre-S2 polish implemented on **Studio dev-ui** and physically tested in increments. **S2.1 is next and NOT started.** Latest checked source SHA `f91b3e6` passed Windows + Ubuntu CI after JPEG re-encode. Studio `main` remains intentionally S0, backend `main` remains intentionally unmerged. See [HANDOFF.md](HANDOFF.md) for detailed live state, acceptance limitations, branch policy and immediate tasks.

This is the canonical implementation/acceptance plan for future sessions. Treat each phase as incremental, with CI and **physical Windows testing before declaring it verified**. Use dedicated feature branches; preserve physical-acceptance checkpoint refs.

## S0. Bootstrap, design system and smoke tests (initial scaffold implemented)

Deliverables:

- [x] Standalone `merberg-ai/Morphorum-Studio` repo with existing Unlicense.
- [x] Python 3.12 PySide6 packaging, `python -m morphorum_studio` launch.
- [x] Dark graphite UI shell: sidebar, nine navigable native workspaces, explicit offline status.
- [x] No inference/GPU/model requirements and no backend code vendoring.
- [x] Basic Qt offscreen and version CLI tests, dual-platform CI workflow.
- [x] Roadmap, architecture, developer workflow and new-chat handoff.
- [x] **Verify initial CI green** on Studio `main`: GitHub Actions run 38316458956 passed on Windows Python 3.12 and Ubuntu Python 3.12 at `af77b402edb7e06ec8297db3961f6535e21e5afc`.
- [x] **Physical Windows launch (user PASS, 2026-10-12):** window opens, layout/scaling good, sidebar navigation works, no network or backend startup, close exits cleanly.
- [x] User accepts UI shell; S0 verified checkpoint branch `checkpoint/studio-s0-windows-verified-20261012` from `fb5024e7592a6d271a8eeb214fc2470387d2e363`.

**Exit criterion:** CI green and user-confirmed normal Windows GUI behavior. No remote features claimed.

## S1. Backend connections, security and native service layer

**S1.1 HTTP transport foundation (implemented, CI + live LAN exercised)**
- [x] Typed `BackendClient` and `BackendError` with bounded timeouts, explicit status handling, URL normalization, redirect rejection and stable error codes.
- [x] Authenticated `GET /api/health` and `GET /api/client/capabilities`; strictly require contract version 1 and validate modes/features.
- [x] Mock/fake-HTTP tests covering 401, 403, 409, 412, unknown API, redirects, timeouts, malformed JSON.
- [x] Discovery requests execute via Qt QRunnable workers off GUI thread; epoch invalidation discards late results after disconnect. Actual low-level network cancellation is not yet implemented.

**S1.2 Connection Manager UX (implemented on dev-ui)**
- [x] Initial Windows/Linux setup, fast-forward-only update, and native launch scripts delivered with S1.1; test on physical Windows before acceptance.
- [x] Named connection profiles: label, URL, pinned `instance_id`, last `boot_id`, preferred transport. Persist profiles **without secrets**.
- [x] OS Credential Manager/secure keyring for per-client bearer tokens. Support interactive token entry or trusted local provisioning; avoid embedding a real token in test fixtures.
- [x] UI connection panel: add/edit/test/remove, connection status, capabilities/version, local/remote context, troubleshoot.
- [x] Explicit warning before transmitting secrets over plaintext HTTP on untrusted networks. Do not implement speculative network pairing; backend provides local-host admin `clients issue/list/revoke`.
- [x] Correct handling of revoked tokens and backend instance mismatch. Reconnect after process restart and refresh capability flags.
- [x] Never kill a remote backend when closing Studio. A user-started local backend is also not owned by Studio.

**S1 and pre-S2 acceptance evidence**

- [x] User physically connected authenticated Studio over trusted LAN with host-issued revocable token.
- [x] User physically exercised backend stop/restart, boot change, automatic reconnect, manual disconnect and status changes.
- [x] User physically reported disposable token revocation produces BACKEND UNAUTHORIZED and stops retrying; separate mocked wrong-token/403 cases are in tests.
- [x] Identity mismatch **rejection** in automated Qt tests preserves previously pinned host; **not physically tested against a second real backend**.
- [x] OS keyring stores secrets; persisted profile JSON and QSettings hold only nonsecret data. This is an implementation property and tested behavior, not a formal penetration audit.
- [x] Windows/Ubuntu CI on S1 increment; S1 reconnect checkpoint recorded. P1 theme, P2 settings/geometry/last profile, P3 splash, early P4 auto-connect/HTTP consent accepted by user on Windows.
- [x] Optimized branded logo included in wheel; fresh-wheel install and warning-free Qt JPEG decoder checks passed on Windows/Ubuntu CI at f91b3e6.
- [ ] Last manual Windows recheck of **corrected** JPEG (no terminal warning) has not been explicitly documented; user stated current state is sufficient and paused.
- [ ] Higher-DPI/multimonitor/slow backend startup tests and physical second-instance mismatch approval remain optional/future hardening. No claim of full comprehensive security acceptance.
- [ ] No main merge or replacement of earlier immutable checkpoint without explicit user approval.

**Pre-S2 details:** [PRE_S2_UI_POLISH.md](PRE_S2_UI_POLISH.md). An older pre-S2 checkpoint (`aa7e798`) **predates** the JPEG re-encode; current source is dev-ui. P1–P4 application functionality is in place; do not restart it from S0.

## S2. Models, projects and media assets

**S2.1 Model discovery and dashboard (IMPLEMENTED on feature/studio-s2-1-dashboard; awaiting CI + physical Windows test, see [S2_1_DASHBOARD.md](S2_1_DASHBOARD.md))**

Incremental implementation order (stop for user review before GPU operations):
- [ ] Confirm dev-ui head/CI and live dev-backend API schema/feature flags; agree on branch from current dev-ui. S2 must not be written to Studio main automatically.
- [ ] Extract a reusable authenticated connection/session read facade for pages besides Connections; preserve existing manual disconnect, automatic reconnect, HTTP consent, keyring, instance/boot-ID behavior. Avoid a second independent connection poller.
- [ ] Add **typed, read-only** backend API for GET /api/system/telemetry and /api/system/gpu-memory with bounded timeouts. Respect exact response schema, missing fields, real GPU/VRAM units and hardware identification; never fabricate values.
- [ ] Add GET /api/models/families and GET /api/models?family=... endpoints; extend safe query handling of BackendClient, which currently rejects query strings. Use supported backend dynamic defaults and family flags. Do not scan client filesystem for models.
- [ ] Offload telemetry/model requests to background Qt workers. Bounded refresh interval and transient error handling must not stall GUI; stop or rebind polling on disconnect, profile change and different instance/boot.
- [ ] Replace Home placeholder with real connected/offline dashboard cards (CPU, GPU, RAM, VRAM, backend version/mode, useful model inventory). Provide accessible unavailable/unknown states. No cosmetic zeroes or fake bars.
- [ ] Add native model inventory and family selector when API data is available; changing families should reflect backend-validated sampler/CFG/resolution defaults. Do **not** expose a button that claims to load/run a model until a real supported endpoint exists.
- [ ] Mock authenticated success/failures, missing GPU, malformed data, auth rejection, invalid query, reconnect and stale worker completions. Both Windows/Ubuntu CI must pass exact SHA.
- [ ] Stop for **user physical Windows test** with backend online/offline and at least one installed model from each applicable family. Only then checkpoint/merge with explicit approval.

**S2.1 exit:** Live metrics and model metadata are real, useful and resilient, with no local GPU dependencies. Console stream and more advanced diagnostic UI may wait for S3 where appropriate.

**S2.2 Project Browser / revision-safe editing (IMPLEMENTED on feature/studio-s2-2-projects; awaiting CI + physical Windows test, see [S2_2_PROJECTS.md](S2_2_PROJECTS.md))**
- List/search/create/open/trash project, project metadata, recent renders.
- GET full normalized project with strong ETag; edits use conditional `PUT If-Match`.
- Explicit 412 conflict UI: reload/compare/cancel, never silent overwrite.
- New Project Wizard based on backend's project template; address known historical invalid 3D camera settings through validated defaults and tests rather than copying bad values.
- Unsaved-change prompts, session restore and recent-project history.

**S2.3 Project-owned assets (PARTLY IMPLEMENTED on feature/studio-s2-3-assets: source image + soundtrack; awaiting CI + physical Windows test, see [S2_3_ASSETS.md](S2_3_ASSETS.md))**
- Upload selected local PNG source image, import soundtrack WAV/MP3/OGG/FLAC and analyze Motion Lab WAV using real API limits.
- Download/list assets and validate sizes/SHA-256; atomic `.part` replacement and private local cache.
- Distinguish server-relative asset URL from local path; no shared path assumptions.

**S2 physical acceptance**
- [ ] Real models and GPU state displayed; backend-only reachable without old browser UI.
- [ ] Create/rename/save/reload a disposable project, including ETag 412 conflict after parallel edit.
- [ ] Upload and retrieve source PNG, soundtrack and analyzed WAV with matching SHA-256.
- [ ] New-project default camera schedules validated and safe on the test project.
- [ ] Tests/CI and Windows GUI acceptance; S2 verified checkpoint.

## S3. Image generation, animations, job monitoring, downloads

**S3.1 Single-image and queue (IMPLEMENTED on feature/studio-s3-1-image-lab, except img2img; awaiting CI + physical Windows test, see [S3_1_IMAGE_LAB.md](S3_1_IMAGE_LAB.md))**
- Prompt/negative prompt, model, LoRAs, seeds, batch, resolution/steps/CFG/sampler with model-valid defaults.
- Persist *exact* body and generated idempotency key **before** each POST; don't duplicate GPU jobs on lost response.
- Live job progress: queue, model load, per-step, ETA when available, results/preview/gallery and cancel where supported.
- Native result image viewer, zoom and safe save; backend does the generation.

**S3.2 Animation and job recovery (IMPLEMENTED on feature/studio-s3-2-animation; SSE deliberately not used, see [S3_2_ANIMATION.md](S3_2_ANIMATION.md); awaiting CI + physical Windows test)**
- Submit **full saved project** in `POST /api/animation/renders`, never just project ID.
- Typed SSE `/api/client/jobs/{kind}/{job_id}/events` with authoritative GET polling fallback.
- Correct boot ID resets, console gaps, queued/running/failed/cancelled/interrupted/resumable distinctions, and explicit resume confirmation.
- Durable render session reattachment after Studio exit, LAN outage and backend restart; recover *all* completed frame records.
- Show running frame strip, selected frame, latest completed PNG, progress bars and render performance details.

**S3.3 Video/audio exports (IMPLEMENTED on feature/studio-s3-3-video, see [S3_3_VIDEO.md](S3_3_VIDEO.md); awaiting CI + physical Windows test)**
- Discover host FFmpeg availability; MP4/WebM with audio; track encoding and return completed URLs.
- SHA-256-verified/atomic downloads of PNG/GIF/MP4/WebM. Play animation/video with correct media controls and audio.
- Explicit warning if frozen soundtrack missing; do not claim audio present without evidence.

**S3 physical acceptance**
- [ ] Remote GPU SDXL still job complete and saved locally.
- [ ] Remote short animation completes, showing progress/frames/ETA and its GIF.
- [ ] Kill/disconnect Studio client mid-render; reopen and recover same job without duplicate.
- [ ] Backend process restart: completed jobs recover, interrupted jobs not incorrectly shown running.
- [ ] Verified MP4/WebM download with actual audio track; no corrupt overwrite.
- [ ] CI and Windows physical acceptance; S3 verified checkpoint.

## S4. Native animation editor and authoring workflow

- Native timeline of prompt, negative-prompt, generation, 2D motion, six-axis 3D camera, cadence and seed schedules.
- Flexible keyframes, easing/interpolation and preview scrubbing. Backend normalization owns schedule interpretation.
- Presets and Deforum Motion Studio settings import with correct axis/strength translation, user-visible range units and reliable UI feedback.
- Source-image start / image-to-image controls, model & LoRA manager, project wizard for guided setup.
- Save/restore layouts, keyboard shortcuts, validation, undo/redo design, useful help popovers and tooltips.
- New Project Wizard must never seed 3D camera values that project behind the camera: add validation/error review before generation.
- Physical tests covering imported motion values, native timelines, nontrivial keyframes, 2D and 3D render parity, project load/edit/save round trips.

**Exit:** S4 editor generates the same project semantics as the accepted backend Web UI and handles schema conflicts safely.

## S5. Native Motion Lab and Audio Director

- Six-axis motion layer composer, preset curves, configurable interpolation/smoothing, layered effects, deterministic frame-aligned recording.
- Keyboard/touch/gamepad input where appropriate for desktop. Live motion recording does not fight text field shortcuts.
- Audio-driven camera effects: frequency-band filters, envelope/beat analysis, amplitude, trigger thresholds, offset/sync, audio-duration matching.
- Song waveform/scrub controls; segment-accurate prompts, per-frame seed and keyframe visualizations, careful preview cache.
- Audio soundtrack must remain attached to final MP4/WebM; imported soundtrack snapshot and Motion Lab WAV ownership handled distinctly.
- GUI never assumes all features in the Web UI map to implemented API endpoints. If a control lacks a backend API, specify and test a **separate backend feature proposal** before exposing it.
- Physical check of layered motion previews and output reproducibility, no missing soundtrack, deterministic timeline, stable saved project.

**Exit:** Core Motion Lab effects tested on physical Windows backend and consistent after reopen.

## S6. Desktop usability, polish and performance

- Windows desktop layout: resizable docks/panels, multi-monitor/high-DPI, keyboard navigation, tooltips, error dialogs, autosave prompts.
- Native thumbnail cache, lazy frame loading, bounded disk/memory, no UI stalls with thousands of frames.
- Settings and diagnostics for backend logs/network/API compatibility; accessible contrast and screen reader labels.
- User-selectable themes/fonts, refined dark glass visuals and Morphorum branding/logo assets approved by the user.
- Graceful shutdown without cancelling server jobs, fail-safe active tasks and session recovery.
- Robust regression tests for network loss, corrupt downloads, stale project ETags and long render manifests.

## S7. Packaging, updater, documentation and release candidate

- Installer/portable build for Windows without bundling torch, CUDA or model weights. Optional Linux AppImage/package later.
- OS-protected credential persistence and migration. Manual update/pinned API compatibility strategy.
- CI build artifacts, signed binary strategy if available, comprehensive Windows physical acceptance.
- Clean first-run flow for connecting to an existing backend; no surprise GPU installation or service takeover.
- Release checklist, screenshots, onboarding docs, license and reproducible build instructions.
- Only after frontend works and user explicitly approves: separate review of Morphorum backend draft PR #32 for merging `dev-backend` to backend `main`.

## Discipline for every milestone

1. Check [HANDOFF.md](HANDOFF.md) and actual GitHub refs/CI before claiming state.
2. Branch `feature/studio-sN-...` from last accepted Studio checkpoint or `main`, never from an unrelated backend branch.
3. One coherent implementation increment at a time; add unit/mock tests and maintain portable dependencies.
4. CI must pass on the exact candidate commit.
5. Stop and give short **Windows physical acceptance instructions**, then fix what the user finds.
6. After user reports PASS, document test evidence, create an immutable checkpoint ref, and seek user approval before merging Studio code into `main`.
7. Preserve backend contract boundaries and existing model projects. Avoid speculative controls and code that only looks functional.
8. Record any discovered backend API gaps as new separate tasks rather than silently weakening Studio correctness.

### Important: what is NOT yet delivered

At the S0 scaffold milestone, there is **no functional connection manager, project editor, render client, media player or release installer**. Those are explicit S1–S7 deliverables. Physical acceptance of the backend does not imply these Studio components already exist.
