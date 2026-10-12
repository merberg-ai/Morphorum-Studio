# Morphorum Studio development roadmap

**Baseline:** S0 initial PySide6 shell, 2026-10-12. **Primary target:** Windows native application. **Secondary:** Linux desktop. **Source of rendering truth:** Morphorum `dev-backend` API contract 1.

This is the canonical implementation/acceptance plan for future sessions. Treat each phase as incremental, with CI and **physical Windows testing before declaring it verified**. Use dedicated feature branches; preserve physical-acceptance checkpoint refs.

## S0. Bootstrap, design system and smoke tests (initial scaffold implemented)

Deliverables:

- [x] Standalone `merberg-ai/Morphorum-Studio` repo with existing Unlicense.
- [x] Python 3.12 PySide6 packaging, `python -m morphorum_studio` launch.
- [x] Dark graphite UI shell: sidebar, nine navigable native workspaces, explicit offline status.
- [x] No inference/GPU/model requirements and no backend code vendoring.
- [x] Basic Qt offscreen and version CLI tests, dual-platform CI workflow.
- [x] Roadmap, architecture, developer workflow and new-chat handoff.
- [ ] **Verify initial CI green** on Studio `main` (do not assume).
- [ ] **Physical Windows launch:** window opens, layout/scaling good, sidebar navigation works, no network or backend startup, close exits cleanly.
- [ ] User accepts UI shell; record actual test results and create S0 verified checkpoint.

**Exit criterion:** CI green and user-confirmed normal Windows GUI behavior. No remote features claimed.

## S1. Backend connections, security and native service layer

**S1.1 HTTP transport foundation**
- Typed `BackendClient` and `BackendError` with bounded timeouts, explicit status handling, URL normalization, redirect rejection and stable error codes.
- Authenticated `GET /api/health` and `GET /api/client/capabilities`; strictly require contract version 1 and validate modes/features.
- Mock/fake-HTTP tests covering 401, 403, 409, 412, unknown API, redirects, timeouts, malformed JSON.
- No Qt network calls on GUI thread; worker tasks emit signals and support cancellation.

**S1.2 Connection Manager UX**
- Named connection profiles: label, URL, pinned `instance_id`, last `boot_id`, preferred transport. Persist profiles **without secrets**.
- OS Credential Manager/secure keyring for per-client bearer tokens. Support interactive token entry or trusted local provisioning; avoid embedding a real token in test fixtures.
- UI connection panel: add/edit/test/remove, connection status, capabilities/version, local/remote context, troubleshoot.
- Explicit warning before transmitting secrets over plaintext HTTP on untrusted networks. Do not implement speculative network pairing; backend provides local-host admin `clients issue/list/revoke`.
- Correct handling of revoked tokens and backend instance mismatch. Reconnect after process restart and refresh capability flags.
- Never kill a remote backend when closing Studio. A user-started local backend is also not owned by Studio.

**S1 physical acceptance on Windows Omen + Studio client**
- [ ] Connect to running `dev-backend` over a trusted LAN using a dedicated client token and display actual hardware/capabilities.
- [ ] Wrong token/revoked token rejected; no secret leak to logs/config/clipboard.
- [ ] Backend restart changes boot ID but not installation identity; UI recovers.
- [ ] Wrong instance ID requires explicit confirmation. No automatic trust of another server.
- [ ] No UI freezes when backend is offline/slow; status changes meaningfully.
- [ ] Tests/CI pass; create verified S1 checkpoint.

## S2. Models, projects and media assets

**S2.1 Model discovery and dashboard**
- Display real backend model IDs for SDXL, FLUX and Z-Image, with installed/downloadable status and dynamic generation defaults. No local model scanning.
- Dashboard CPU/GPU/RAM/VRAM, backend status and console snippet; throttle telemetry refresh without UI jank.
- Model family changes update valid sampler/CFG/resolution choices according to backend capability, not hardcoded defaults.

**S2.2 Project Browser / revision-safe editing**
- List/search/create/open/trash project, project metadata, recent renders.
- GET full normalized project with strong ETag; edits use conditional `PUT If-Match`.
- Explicit 412 conflict UI: reload/compare/cancel, never silent overwrite.
- New Project Wizard based on backend's project template; address known historical invalid 3D camera settings through validated defaults and tests rather than copying bad values.
- Unsaved-change prompts, session restore and recent-project history.

**S2.3 Project-owned assets**
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

**S3.1 Single-image and queue**
- Prompt/negative prompt, model, LoRAs, seeds, batch, resolution/steps/CFG/sampler with model-valid defaults.
- Persist *exact* body and generated idempotency key **before** each POST; don't duplicate GPU jobs on lost response.
- Live job progress: queue, model load, per-step, ETA when available, results/preview/gallery and cancel where supported.
- Native result image viewer, zoom and safe save; backend does the generation.

**S3.2 Animation and job recovery**
- Submit **full saved project** in `POST /api/animation/renders`, never just project ID.
- Typed SSE `/api/client/jobs/{kind}/{job_id}/events` with authoritative GET polling fallback.
- Correct boot ID resets, console gaps, queued/running/failed/cancelled/interrupted/resumable distinctions, and explicit resume confirmation.
- Durable render session reattachment after Studio exit, LAN outage and backend restart; recover *all* completed frame records.
- Show running frame strip, selected frame, latest completed PNG, progress bars and render performance details.

**S3.3 Video/audio exports**
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
