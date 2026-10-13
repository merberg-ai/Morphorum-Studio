# Morphorum Studio

**Native Windows-first desktop studio for controlling Morphorum AI image, animation and video generation on an existing GPU backend.** Linux compatible. Separate from the GPU/inference repository: https://github.com/merberg-ai/Morphorum.

> **Current development status (2026-10-13):** S1 secure connection manager and Pre-S2 native desktop polish are implemented on **dev-ui**. Authenticated LAN connection, reconnect, boot detection, OS keyring, session preferences, auto-connect, modern Qt controls and a branded splash exist. **S2.1 (live telemetry and model discovery) has NOT started.** Home, Projects, Image Lab, Editor, Motion Lab, Render Queue and Console still contain roadmap placeholders. Studio **main remains intentionally at S0** until the user explicitly approves a merge.

## Continue development in a new chat

**Read [docs/HANDOFF.md](docs/HANDOFF.md) first.** It is the authoritative current-state/recovery guide, with branch SHAs, physical acceptance notes, Windows commands, backend APIs, architectural invariants, open problems, and precise next steps. Then review [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/PRE_S2_UI_POLISH.md](docs/PRE_S2_UI_POLISH.md).



For a fresh ChatGPT conversation, this is enough to resume without reconstructing the project history:

> Continue development of Morphorum Studio from https://github.com/merberg-ai/Morphorum-Studio on branch **dev-ui**. First read docs/HANDOFF.md, docs/ROADMAP.md and docs/PRE_S2_UI_POLISH.md, inspect current source/CI and the Morphorum backend dev-backend contract. Preserve current tested behavior and checkpoints. Do not merge either main branch. Let's discuss or start the next S2.1 increment.

Current working branch: [dev-ui](https://github.com/merberg-ai/Morphorum-Studio/tree/dev-ui).
Inspected source implementation SHA: **f91b3e6cf05329c1816e0c68ff7358bd11c63d07** (subsequent documentation commits may advance dev-ui).
At that implementation SHA, GitHub Actions **Windows and Ubuntu Python 3.12 passed**, including the clean wheel-installed splash image check. Never assume a branch head or CI state without verifying it again.

## What works today

- Native PySide6 app with nine sidebar workspaces and a graphite/cyan/violet theme.
- Connections: named local profiles, bearer tokens stored in OS-protected keyring, locally imported token files, trusted-LAN HTTP authorization saved per profile + exact URL, authenticated API v1 discovery, instance-ID change prompt, boot-ID change detection.
- Live connection health probing, bounded passive reconnect, distinguish unauthorized vs offline vs incompatible backend, manual Disconnect does not stop the GPU backend.
- Settings: splash, restore window size/position/maximized state, last workspace, last selected profile, last successful backend, configurable automatic startup connection.
- Branded startup splash with staged initialization bar. Optimized logo is included in the Python package, not dependent on a manual file copy. A Windows report revealed a malformed JPEG warning, repaired by re-encoding the asset. CI now checks that Qt decodes the image without warnings; final human Windows warning-free retest is not separately documented.
- Source checkouts and fast-forward-only update/launch scripts for Windows and Linux, mock/offscreen tests, packaged wheel clean-install CI.

**Not yet implemented:** CPU/GPU telemetry dashboard, model discovery/selectors, project browser and save controls, GPU image/animation/video generation from Studio, live job render queue, SSE events, native animation editor, Motion Lab/audio editor, distributable installer. These belong to S2–S7, not broken P1–P4 implementations.

## Windows quickstart (working development branch)

Install **Python 3.12** and Git first. PowerShell:

~~~powershell
git clone --branch dev-ui https://github.com/merberg-ai/Morphorum-Studio.git
cd Morphorum-Studio
.\setup.ps1
.\run.ps1
~~~

To update an existing checkout without changing its branch:

~~~powershell
git status --short --branch
git switch dev-ui
.\update.ps1
.\run.ps1
~~~

The updater refuses dirty branches or unsafe ref updates; don't use git reset --hard to dodge those safeguards. Backend runs **separately**.

### Linux

~~~bash
git clone --branch dev-ui https://github.com/merberg-ai/Morphorum-Studio.git
cd Morphorum-Studio
bash setup.sh
bash run.sh
~~~

### Tests

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_clean_install.py
~~~

For headless tests set QT_QPA_PLATFORM=offscreen. CI workflow: [.github/workflows/ci.yml](.github/workflows/ci.yml), Windows + Ubuntu Python 3.12. Python package is version 0.1.0a1.

## GPU backend and credential setup

Morphorum Studio is a remote or local **client**. No PyTorch/CUDA, model downloads or shared backend installation directory are required on the Studio machine. To make the backend available on a trusted LAN, start the backend from its **separate repository**, typically:

~~~powershell
cd D:\Morphorum-test
.\run.bat --backend-only --lan
~~~

Usually uses TCP 7866; configure your real host URL in Studio Connections. Do not hardcode the example address into the app.

A revocable dedicated client token must be issued on the backend **host** and imported into Studio Connections (not posted to ChatGPT, GitHub, a URL or an application log):

~~~powershell
.\.venv\Scripts\python.exe -m morphorum clients issue "Morphorum Studio" --days 90 --out ".\data\studio-client.token"
~~~

See [docs/S1_FOUNDATION.md](docs/S1_FOUNDATION.md) for import and revocation procedure. Plain HTTP is unencrypted: use only a trusted private LAN or tunnel, otherwise use TLS/VPN.

## Important repository boundaries

- Studio **main** remains S0 by design. Continue on **dev-ui** until instructed differently; merging either repo to main requires explicit user approval.
- Morphorum backend **dev-backend** is pinned to **2046d36ff6e084d801a14e2024d14665c207d884** at this handoff. Backend [draft PR #32](https://github.com/merberg-ai/Morphorum/pull/32) remains open/unmerged against backend main. Do not merge it without explicit approval.
- Previously created immutable checkpoint refs record milestone evidence. The older Pre-S2 CI checkpoint was taken **before** the malformed JPEG correction. For a current implementation start from **dev-ui**, not an earlier checkpoint.
- Never mix backend inference or Web UI code into this repository. The backend API contract version is **1** and is discovered via /api/client/capabilities.

## Documentation index

- [HANDOFF.md](docs/HANDOFF.md): **new-chat starting point**, live implementation status, exact next steps and safety guardrails.
- [ROADMAP.md](docs/ROADMAP.md): S0–S7 feature delivery and testing plan.
- [PRE_S2_UI_POLISH.md](docs/PRE_S2_UI_POLISH.md): P1–P4 milestones, user feedback, logo re-encode history and CI evidence.
- [ARCHITECTURE.md](docs/ARCHITECTURE.md): client/backend separation, security, project revision and GPU job recovery rules.
- [DEVELOPMENT.md](docs/DEVELOPMENT.md): developer install, test and branch discipline.
- [S1_FOUNDATION.md](docs/S1_FOUNDATION.md): connection transport, credentials and LAN onboarding.
- [Backend Studio contract](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/STUDIO_CLIENT_HANDOFF.md): API endpoints and backend-side constraints.

## License

[The Unlicense](LICENSE).
