# Morphorum Studio: current development handoff

**Updated: 2026-10-14. Start here in a new chat.**
- Studio repository: https://github.com/merberg-ai/Morphorum-Studio
- GPU backend repository: https://github.com/merberg-ai/Morphorum
- Working Studio branch: **dev-ui**. Its last code merge is **6569373** (dev-connections: managed local backend C1-C5 plus Backend settings BS1/BS2, all Windows-tested by the user and CI green on both OSes). Before that, **62eb67f** (S5.3 Graph). Documentation commits may advance it; **inspect GitHub before changing code**.
- Studio **main** is still the S0 scaffold, SHA **fb5024e7592a6d271a8eeb214fc2470387d2e363**. Do NOT merge it without the user's explicit approval.
- Backend: **PR #32 (dev-backend to backend main) was merged by the user on 2026-10-14 at 12:51 UTC** (merge commit 0cb5d48; PR head and dev-backend are still 2046d36). Backend main had moved to cd8ddda when checked. Earlier notes below that call the PR "unmerged" are obsolete. Studio was built and tested against dev-backend 2046d36; re-check the API against backend main before relying on newer behaviour.
- Current phase: **S5 (Motion Lab and Audio Director) is implemented and merged into dev-ui. The user paused work to review the roadmap.** S5.2a and S5.3 have passed CI but have NOT had a physical Windows test; S5.2b is not started.

## RESUME POINT (the separate managed-backend feature is DONE and merged into dev-ui at 6569373; resume the roadmap here)

The user paused the main roadmap to build an unrelated feature while waiting for time to do solid Windows testing. When that feature is finished, resume exactly here. `dev-ui` is clean and fully contains every feature branch; there is no half-finished branch. Start the separate feature on its own branch from `dev-ui` and keep it out of the roadmap work.

State at the pause: dev-ui last code merge `62eb67f` (S5.3), docs commit on top. S5.1 merged and tested; **S5.2a Audio Director and S5.3 Graph are merged but have not had a physical Windows test.**

Do these in order when resuming:
1. Ask the user for the Windows test result of S5.2a and S5.3 (checklists in docs/S5_2A_AUDIO_DIRECTOR.md and docs/S5_3_GRAPH.md). Priorities: MP3, FLAC and OGG loading, Audition playback, arrow-key selection in the Graph, the 880x560 window size. Fix whatever it finds on a new `feature/studio-s5-fixes-*` branch from dev-ui.
2. Re-check the API against backend `main` (PR #32 was merged by the user on 2026-10-14; Studio was built against dev-backend 2046d36) and note any differences, especially anything new for audio analysis.
3. Ask the user which comes next. The planned options, in the order I suggested them:
   - **S6 resilience and performance:** regression tests for network loss, corrupt downloads, stale ETags and long render manifests; thumbnail cache limits; lazy frame loading; session recovery.
   - **S6 accessibility and keyboard pass:** accessible names, contrast, tab order across all workspaces.
   - **S5.2b:** custom bands, bass-intensity and ripple modes, spectrum view and the Backend/local analysis setting. Mostly blocked on the backend proposals in docs/BACKEND_PROPOSALS.md; ask whether to take those to the backend or build local analysis.
   - **Controller recording, A/B loop, motion-preview wireframe, motion undo, custom presets** (ideas from Deforum Motion Studio).
4. Then S7 packaging. Create immutable checkpoint refs for tested milestones before any discussion of merging Studio `main`; never merge `main` without explicit approval.

## If you are a new chat

Read this file, docs/ROADMAP.md, docs/ARCHITECTURE.md, the per-step docs (S5_1, S5_2A, S5_3, BACKEND_PROPOSALS) and the backend contract documents. **Fetch current dev-ui source, branch heads and GitHub Actions instead of relying only on prose.** Never assume Studio main contains these features. Do not write files in the Morphorum backend repository unless separately approved.

## Working rules the user set (follow them)
- One feature branch per step, from dev-ui. CI must be green on the exact commit on both Ubuntu and Windows.
- The user does a physical Windows test and then says "merge". Only then merge into **dev-ui** with `--no-ff` and push. Never merge Studio main or touch the backend without explicit approval.
- Never invent a control the backend cannot serve. If a control lacks a backend API, write a separate backend proposal first (docs/BACKEND_PROPOSALS.md) and do not expose it.
- UI direction: ComfyUI/Runway mix, dark only, frameless title bar. Page keys stay stable (Home, Projects, Image Lab, Editor, Motion Lab, Render Queue, Console, Settings); `DISPLAY`/`NAV_META` in ui/main_window.py give the names people see (Library, Lab, Timeline, Graph, Queue).
- The friend's project (chicodog530/Deforum-Motion-Studio, used with permission, no licence file) is a source of ideas and detection logic only. Studio's code is an independent implementation, credited in docs/S5_2A_AUDIO_DIRECTOR.md.

## What is implemented in Studio today (all on dev-ui)
Nothing here has been merged into Studio main.

| Area | Where | Doc |
|---|---|---|
| Connections, profiles, keyring tokens, reconnect (S1) | backend/client.py, profiles.py, credentials.py, session.py | S1_FOUNDATION.md |
| Dashboard / telemetry (S2.1) | ui/dashboard_service.py, home_page.py | S2_1_DASHBOARD.md |
| Projects: list, create, edit name/notes with ETag, trash (S2.2) | backend/projects.py, ui/projects_* | S2_2_PROJECTS.md |
| Media: source image, soundtrack, verified save-copy (S2.3) | backend/assets.py | S2_3_ASSETS.md |
| Image Lab: journalled idempotent submissions, viewer (S3.1) | ui/image_lab_page.py | S3_1_IMAGE_LAB.md |
| Animation renders, resume, frame browser (S3.2) | backend/renders.py | S3_2_ANIMATION.md |
| Video export, verified save, playback (S3.3) | backend/videos.py | S3_3_VIDEO.md |
| Console (backend log) | ui/console_* | CONSOLE.md |
| Timeline viewer, keyframe editing with undo, validation, Deforum import, project wizard (S4.1-S4.4) | backend/timeline.py, ui/editor_page.py | S4_*.md |
| UI pass and layout steps 1-6: shell, Home, Library, Timeline, Lab, Queue | ui/*_page.py | UI_PASS.md, LAYOUT_*.md |
| **S5.1 Motion tab**: preset and curve layers, preview, apply, conflict handling | backend/motion.py, ui/motion_service.py, motion_panel.py | S5_1_MOTION_LAB.md |
| **S5.2a Audio Director**: load WAV/MP3/FLAC/OGG/M4A, band analysis, audio layers with level/transient detection, threshold, attack, return, gap, offset and range, envelope view, audition, soundtrack note | backend/audio.py, ui/audio_decode.py, audio_service.py, audio_widgets.py | S5_2A_AUDIO_DIRECTOR.md |
| **S5.3 Graph**: read-only pipeline diagram with inspector and jump-to-workspace buttons | backend/graph.py, ui/graph_service.py, graph_page.py | S5_3_GRAPH.md |

Key facts about S5.2a that a successor must know:
- **The backend cannot decode MP3/FLAC/OGG today.** Its analyze endpoint takes PCM WAV only (20 MiB, 180 s). Studio decodes other formats locally with Qt Multimedia (mono 16-bit 22.05 kHz, cut to project length) and uploads a WAV. Backend-side decoding is proposal P1 in BACKEND_PROPOSALS.md; Studio should send the original file once the backend advertises a feature flag such as `motion_lab_audio_decode`.
- The analysis bands are fixed on the backend (kick, bass, snare, highs, plus full mix). Custom Hz bands, bass-intensity and ripple response shapes, a spectrum, uniform headroom scaling and extra presets are backend proposals P2-P6, not in Studio.
- The analysed audio is separate from the final-video soundtrack. Studio shows a note when no soundtrack is attached; it does not attach one from the Motion tab.
- `scripts/verify_backend_audio_layers.py <backend path>` runs Studio-built audio layers through the real backend compiler (manual check).
- Real audio decoding and playback have never run: CI only exercises fakes.

## Tests, CI and local limits
- pytest under tests/ (Qt offscreen) on Windows and Ubuntu; fresh-wheel clean-install check. Recent steps add test_motion.py, test_audio.py, test_graph.py.
- A Windows teardown crash (exit 139) appears in CI logs whenever a test fails, and it also appeared once from orphaned nested layouts. The real failure is in the check-run annotation `E`/`FAILED` lines. Build list rows as per-row QWidget containers and parent widgets in tests.
- In the assistant's cloud workspace PySide6 cannot be installed and CI logs cannot be downloaded; use check-run annotations (`gh api repos/merberg-ai/Morphorum-Studio/check-runs/<id>/annotations`).
- `tests/test_preferences.py` has a known unused-import lint error (ConnectionsPanel). It is unrelated to recent work; leave it unless asked.

## Physical Windows acceptance status
- PASS as reported by the user: S0, S1 connection/reconnect, S2.1-S2.3, S3.1-S3.3, and the layout steps and S5.1 as they were merged on the user's instruction.
- **Not physically tested yet:** S5.2a (including MP3/FLAC/OGG decoding and Audition playback) and S5.3. Their checklists are in docs/S5_2A_AUDIO_DIRECTOR.md and docs/S5_3_GRAPH.md. The user said "merge" after CI, so treat these as merged but unverified, and fix what the Windows test finds.
- No immutable checkpoint refs exist after `checkpoint/studio-p3-splash-windows-verified-20261012` and `checkpoint/studio-pre-s2-polish-ci-verified-20261012`. Roadmap discipline calls for checkpoints and recorded evidence before any merge into Studio main; none of that has been done for S2-S5.

## Roadmap: what is left
1. **S5.2b** (not started; mostly waits on backend proposals): custom bands, bass-intensity and ripple modes, spectrum view, and a setting "Audio analysis: Backend (default) / Studio (local)". Local analysis would need a bundled numerical library and cannot provide the response shapes the backend compiler owns.
2. **Later ideas from Deforum Motion Studio:** live recording from an Xbox controller (XInput via ctypes; the backend already supports "recording" layers), A/B loop, backend `motion-preview` wireframe, undo history for motion, custom presets. Song waveform and scrub controls and per-frame seed visualisation from the S5 roadmap list are also not built.
3. **S6** desktop usability and performance: docks, high-DPI/multi-monitor, keyboard navigation, accessible names and contrast, thumbnail cache limits and lazy frame loading, themes/fonts, safe shutdown, regression tests for network loss, corrupt downloads, stale ETags and long render manifests.
4. **S7** packaging: Windows installer/portable build without torch/CUDA/weights, OS-protected credentials, update strategy, CI artifacts, release docs and checklist.
5. Only after the frontend works and the user approves: decide about Studio main. The backend PR has already been merged by the user.

Known caveats: the Timeline at 880x560 scrolls horizontally; the Timeline render-frame player plays at most 12 frame steps per second, so Audition drives the playhead from the audio position instead.

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

