# Development guide

## Current development entrypoint, 2026-10-13

The source tree most relevant to a **new session is Studio dev-ui**, not Studio main (which deliberately remains at S0). Read [HANDOFF.md](HANDOFF.md) first. Current inspected implementation SHA f91b3e6 includes accepted S1 native connections and Pre-S2 UI polish, secure OS tokens, trusted-LAN consent persistence, optional auto-connect, package-bundled logo and a fix for a Qt JPEG decoder warning. Windows and Ubuntu CI passed on that SHA. Later documentation-only commits may move dev-ui. Backend dev-backend is intentionally separate, and draft backend PR #32 must stay unmerged without user approval.

Quick Windows session:
~~~powershell
cd D:\Morphorum-Studio
git status --short --branch
git switch dev-ui
.\update.ps1
.\run.ps1
~~~

New clone must explicitly choose dev-ui:
~~~powershell
git clone --branch dev-ui https://github.com/merberg-ai/Morphorum-Studio.git
cd Morphorum-Studio
.\setup.ps1
.\run.ps1
~~~

The next proposed feature is **S2.1**: read-only telemetry and model discovery, beginning with a shared authenticated session service for Qt pages. Get user go-ahead and verify backend contract fields before modifying code. Do not merge or claim physical verification from automated CI alone.

**CI gate:** the workflow additionally builds a wheel and checks a clean virtualenv install can read the bundled JPEG through Qt. Run scripts/verify_clean_install.py for packaging regressions. The older checkpoint pre-S2-polish-ci-verified-20261012 predates the fixed JPEG, so starting new work there would reintroduce the warning. Current branch is dev-ui.

---


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

- Historical S0: Studio main is accepted scaffold and deliberately not updated. **Current work: dev-ui** (or a user-approved S2 branch from its accepted head).
- Future large phases may use dedicated feature branches based on dev-ui. Avoid unrelated changes and confirm the user's branch/merge decision first.
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
