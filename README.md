# Morphorum Studio

**Native desktop control room for Morphorum AI image, animation, and video generation.**

Morphorum Studio is a Windows-first, Linux-compatible desktop application for configuring projects, composing animation and Motion Lab controls, launching image/video jobs, and viewing live render progress on **local or remote** [Morphorum](https://github.com/merberg-ai/Morphorum) GPU backends.

> **Development stage: S0 (application shell).** The initial Qt interface runs offline and displays future workspaces. Connections, project editing, image generation, and rendering are **not implemented in Studio yet**. Those are deliberate upcoming roadmap milestones, not broken buttons.

The GPU backend remains in the separate Morphorum repository. Studio must not download model weights, require CUDA, import PyTorch, or need shared backend folders.

## Run the S0 desktop shell

Install **Python 3.12** (the initial CI baseline). On Windows PowerShell:

~~~powershell
git clone https://github.com/merberg-ai/Morphorum-Studio.git
cd Morphorum-Studio
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m morphorum_studio
~~~

On Linux:

~~~bash
git clone https://github.com/merberg-ai/Morphorum-Studio.git
cd Morphorum-Studio
python3.12 -m venv .venv
./.venv/bin/python -m pip install -e '.[dev]'
./.venv/bin/python -m morphorum_studio
~~~

To run unit/UI-shell tests without displaying windows (Linux/CI):

~~~bash
QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m pytest -q
~~~

Windows PowerShell equivalent:

~~~powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:QT_QPA_PLATFORM
~~~

The packaging script entrypoint is also `morphorum-studio` after installation; `python -m morphorum_studio --version` does not need a display server.

## What exists today

- Python 3.12 packaging via `pyproject.toml`, Unlicense and focused `.gitignore`.
- PySide6 dark desktop shell with working navigation: Home, Connections, Projects, Image Lab, Editor, Motion Lab, Render Queue, Console, Settings.
- Honest **BACKEND OFFLINE** status, with no fake connection or render controls.
- Basic offline UI tests and GitHub Actions on Windows and Linux.

## Project documents

- **[docs/HANDOFF.md](docs/HANDOFF.md)**: **read first in a new ChatGPT session**. Exact baseline, state, decisions, next action, and stop conditions.
- [docs/ROADMAP.md](docs/ROADMAP.md): detailed S0–S7 implementation plan with physical acceptance gates and phase deliverables.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): application/backend ownership, security, state/reconnection and API boundaries.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): contribution workflow, local testing and milestone checklist.

## Backend relationship

The accepted backend is **`merberg-ai/Morphorum` on `dev-backend`**, combined merge SHA `2046d36ff6e084d801a14e2024d14665c207d884`. Backend PRs #27–#31 were integrated into `dev-backend` and post-integration CI passed (536 passed / 1 skipped). **Backend `main` has intentionally NOT been merged**: [draft review PR #32](https://github.com/merberg-ai/Morphorum/pull/32) is held until this desktop frontend is working and the user explicitly approves.

Canonical backend implementation guide: [STUDIO_CLIENT_HANDOFF.md](https://github.com/merberg-ai/Morphorum/blob/dev-backend/docs/STUDIO_CLIENT_HANDOFF.md). Runtime API version is **1**, discovered via authenticated `GET /api/client/capabilities`.

Do **not** copy backend Python inference packages or its browser UI into this repo. Studio is a separate client.

## License

[The Unlicense](LICENSE).
