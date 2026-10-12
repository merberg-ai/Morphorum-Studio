# Development guide

## Workstations

- **Windows first:** Python 3.12 and PySide6, on the client PC or the same Windows Omen used to host Morphorum.
- **Linux compatibility:** same Python package and Qt modules, no platform-exclusive UI assumptions outside a dedicated adapter.
- **No local inference dependencies:** never import diffusers, transformers, torch, CUDA, or model weights in Studio.

## Install/test

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m morphorum_studio --version
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m morphorum_studio
```

For headless Windows tests set `$env:QT_QPA_PLATFORM='offscreen'` first. Linux: `python3.12 -m venv .venv; ./.venv/bin/python -m pip install -e '.[dev]'`, then run analogous commands; CI sets `QT_QPA_PLATFORM=offscreen`.

Both Windows and Linux jobs in `.github/workflows/ci.yml` must remain green.

## Branching / acceptance

- Bootstrap S0: existing Studio `main`; verify physically before checkpointing.
- Later phases: `feature/studio-s1-connection`, `feature/studio-s2-projects`, etc. Avoid unrelated changes.
- Keep the feature branch open while the user tests on Windows. Add fixture/mock tests before hardware checks.
- Create immutable `checkpoint/studio-sN-...-verified-YYYYMMDD` only after a physical PASS.
- Merge features into the **Studio** repository's `main` only with explicit approval. This does not authorize merging the Morphorum **backend** to its `main`.
- Never delete or rewrite accepted checkpoint branches as cleanup without explicit approval.

## Pull request readiness

1. Confirm exact target branch and diff.
2. Install/package compiles; tests green on Windows and Linux; offline/simulated tests don't hit real LAN.
3. No bearer token or identifying private project data in commits or CI logs.
4. Error/timeout/offline behaviors visible in UI and tested.
5. No fake feature flags or controls that secretly perform a different action.
6. Windows manual acceptance instructions given; user result recorded in docs.
7. New-chat handoff and roadmap updated with the precise head SHA and next physical gate.

## Rendering backend

For Studio's **S1+ physical tests**, run the trusted LAN Morphorum backend from the **backend repo** using `.\run.bat --backend-only --lan` (port 7866 by default). Never couple the Studio launcher to that working directory, and never commit or print `data/backend-access-token`.

Use the real backend `dev-backend` versioned API contract and authenticated `/api/client/capabilities`. The backend's `main` remains intentionally behind this feature until the native frontend has passed acceptance.
