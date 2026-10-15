# Morphorum Studio

**Native desktop frontend for Morphorum AI image, animation, motion and video workflows.**

Morphorum Studio is a Windows-first, Linux-compatible PySide6 application that controls a separate [Morphorum](https://github.com/merberg-ai/Morphorum) GPU backend. Studio is a client, not an inference package: it does not install CUDA, PyTorch or model weights into the desktop app.

> **Development status, 2026-10-14:** active development lives on `dev-ui`. Studio `main` is intentionally still the original S0 scaffold and is not the branch to use for current development. S0 through the current S5 work, plus the managed-local-backend and backend-settings work, are integrated on `dev-ui`.

## Current capabilities

The current `dev-ui` branch includes:

- authenticated backend connections with named profiles, OS keyring credentials, trusted-LAN HTTP consent, reconnect and backend identity/boot tracking;
- live dashboard telemetry and model discovery;
- project browsing, creation and revision-safe editing with ETag conflict handling;
- project source-image and soundtrack asset handling with verified downloads;
- Image Lab still-image generation with durable idempotent submissions and result viewing;
- animation rendering, recovery and frame browsing;
- video export/download/playback, including soundtrack-aware MP4/WebM workflows;
- backend Console;
- native Timeline/editor, keyframes, validation, Deforum settings import and project setup;
- Motion Lab preset/curve layers and Audio Director;
- a read-only project pipeline Graph;
- a managed local Morphorum backend mode that can install, start, reconnect, maintain and onboard a local backend;
- backend settings/model-path management and rescanning from Studio;
- Windows/Linux CI, wheel clean-install checks and offscreen UI screenshot generation.

### Current verification note

Most earlier milestones were physically exercised on Windows. S5.2a Audio Director and S5.3 Graph were merged after CI but still need the dedicated physical Windows checks recorded in their milestone docs.

## Get the current development build

For a fresh clone, explicitly select `dev-ui`:

```powershell
git clone --branch dev-ui https://github.com/merberg-ai/Morphorum-Studio.git
cd Morphorum-Studio
.\setup.ps1
.\run.ps1
```

Linux:

```bash
git clone --branch dev-ui https://github.com/merberg-ai/Morphorum-Studio.git
cd Morphorum-Studio
./setup.sh
./run.sh
```

For an existing checkout:

```powershell
git status --short --branch
git switch dev-ui
.\update.ps1
.\run.ps1
```

The updater is intentionally fast-forward-only. If Git reports local changes, inspect them rather than force-resetting them into the void where regrettable decisions go to breed.

## Backend relationship

The backend is a separate repository: [merberg-ai/Morphorum](https://github.com/merberg-ai/Morphorum).

The former long-running backend `dev-backend` work was merged into backend `main` on 2026-10-14. Studio should now treat Morphorum `main` plus the live authenticated capability response as the source of truth. Historical Studio docs may mention the old `dev-backend` baseline as milestone evidence.

Studio discovers backend support at runtime through API contract version 1 and advertised feature flags. It must not assume that a visible Studio control is supported merely because an older backend once supported it.

Plain HTTP should be used only on a trusted private LAN or inside a trusted tunnel/VPN. Credentials belong in the OS keyring, not source files, settings JSON, URLs or logs.

## Repository state

- **`dev-ui`**: current integrated development branch.
- **`main`**: intentionally preserved S0 scaffold until explicitly approved for integration.
- **`checkpoint/*`**: immutable historical verification points; do not rewrite or delete them casually.
- **`ui-screenshots`**: generated screenshot branch used by CI; it intentionally has unrelated history.

Merged feature branches are disposable once their ancestry is verified to be fully contained in `dev-ui`.

## Documentation

Start here when resuming development:

- [docs/HANDOFF.md](docs/HANDOFF.md): current branch/state, verification status, immediate resume point and non-negotiable rules.
- [docs/ROADMAP.md](docs/ROADMAP.md): current S0-S7 phase status and remaining work.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): client/backend boundary, session model, safety and data integrity rules.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): install, testing, branch and acceptance workflow.
- `docs/S*.md`, `docs/LAYOUT_*.md`, `docs/C*.md`, `docs/BS*.md`: milestone implementation records and physical test checklists.

## Development tests

Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_clean_install.py
```

Linux:

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python scripts/verify_clean_install.py
```

CI runs on Windows and Ubuntu with Qt in offscreen mode.

## License

[The Unlicense](LICENSE).
