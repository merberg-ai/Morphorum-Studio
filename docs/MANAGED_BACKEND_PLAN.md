# Plan: Studio-managed local backend (branch dev-connections)

Status: **plan only, nothing built.** Written 2026-10-14 from the backend's installer scripts (dev-backend 2046d36, now
merged to backend main) and Studio's connection code.

## Goal
Keep today's behaviour exactly (connect to a backend that is already running, on this PC, another PC or the LAN) and add a
second, simpler path: Studio installs, starts, stops, updates and repairs its **own** Morphorum backend in a subfolder of the
Studio folder, then connects to it like any other backend. In Settings > Connections the person chooses:

- **Simple: let Studio manage a local backend.** Install, start and connect with a few clicks.
- **Advanced: connect to a running backend.** Today's connection manager, unchanged.

## It changes two standing rules (needs your approval)
The handoff says Studio must never install CUDA, PyTorch or models, and must never take over a backend or stop one. For the
managed mode I propose:
1. **Studio never installs those itself.** It runs the backend's own installer (`bootstrap.ps1` / `bootstrap.sh`), which
   downloads Python, PyTorch (hardware-specific) and dependencies, into the managed folder only. This is explicit opt-in: a
   consent screen states the size (8 GiB minimum free, several GB downloaded), the folder, and that no models are included.
2. **Studio only stops a backend it started and owns.** An advanced-mode backend is never started, stopped or updated by
   Studio. Whether the managed backend keeps running when Studio closes is a setting (see decisions).

## How the backend actually installs and runs (verified in its scripts)
- Install: `bootstrap.ps1 -InstallDir <dir> -Port <n> -Branch <name>` clones the repo, provisions Git (winget) if missing,
  a managed Python 3.12 and a private `.venv`, installs PyTorch with automatic CUDA selection, runs a self-test. Passing
  `-InstallDir` and `-Port` removes its prompts. Linux: `scripts/bootstrap.sh <dir>`. It checks 8 GiB free.
- Run headless: `.venv\Scripts\python.exe -m morphorum serve --backend-only --port <n>` (add `--lan` only on request).
  Default backend-only port is 7866. `run.bat --backend-only` wraps the same thing through PowerShell.
- Auth: the first backend-only start creates `data/backend-access-token`. `python -m morphorum clients issue "Morphorum
  Studio" --days 90 --out <file>` makes a revocable client token. Studio can read either locally, store it in the OS
  keyring as it does today, and never log it.
- Maintain: `update.bat` / `update.sh` (guarded updater), `repair.bat` / `repair.sh`, `python -m morphorum doctor --json`.
- Models are not installed. They are chosen later in Studio's Models browser or the backend.
- Projects and outputs live in the backend's own `data/` folder inside the managed folder.

## Design
**Managed profile.** A connection profile gets a `kind`: `remote` (today) or `managed`. A managed profile stores the folder
and port (non-secret), points at `http://127.0.0.1:<port>`, and trusts plain HTTP only because it is loopback. Everything
after connect (identity check, reconnect, features) is the existing code path, so no other page changes.

**Location.** Default `<Studio folder>/morphorum-backend`, with a folder chooser. The folder is git-ignored so Studio updates
never touch it. Caveat for S7: if Studio is later installed to a read-only place such as Program Files, the default must
move to the per-user data directory. The path is validated (writable, no unsafe characters, not inside a git checkout of
Studio source other than the ignored folder, enough free space).

**Install driver** (`ui/managed_install.py`): preflight (OS, disk, network to GitHub), consent, then run the bootstrap with a
QProcess off the GUI thread, streaming output to a progress view with a collapsible log. The installer's output has stable
stage markers (`>> SECTION`, `[>]`, `[+]`, `[!]`) that map to coarse stages. Cancel kills the process tree and leaves a
resumable state (re-running the bootstrap on an existing checkout is its guarded update path). Failures keep the log and
offer Repair.

**Process manager** (`ui/managed_backend.py`): start with QProcess using the venv's Python directly (no batch layers), hidden
console, in a new process group; wait for a healthy `/api/health`; stop by graceful signal, then tree-kill after a timeout.
State machine: not installed, installing, stopped, starting, running, stopping, needs update, error. A PID/port record
detects a backend left running by a previous Studio session so it is adopted, not duplicated. Port in use by something
else is reported with a "choose another port" action. A crash while running is shown with the last log lines and a Restart
button; it never auto-resubmits GPU jobs (existing rule).

**Token.** After the first start Studio runs `clients issue` (or reads the local token file), saves the secret in the keyring
under the managed profile, and connects. Secrets never go in settings, logs or the UI.

**UI.** Settings > Connections gets a top choice (Simple / Advanced). Simple shows one card: current state, size and
folder, version, and the buttons Install, Start, Stop, Restart, Open folder, Check for updates, Repair, Remove. The
header connection chip and Home show managed-backend state. Backend log lines from the managed process appear in the
existing Console page. Home with no connection offers both paths.

**Remove.** Deletes only the managed folder, behind a typed-name confirmation that says projects and outputs inside it
will be lost, and offers to open the folder first. Studio never deletes anything outside it.

**Platforms.** Windows first (your target); Linux uses the same driver with `bootstrap.sh`, tested in CI against fakes.

## Phases (each its own branch from dev-connections, CI green, your Windows test, then "merge")
1. **C1 Mode and manage an existing checkout.** Simple/Advanced choice, managed profile kind, "Use an existing Morphorum
   folder" (works with your D:\Morphorum-test), start/stop/restart, health wait, adopt a running one, token handling,
   logs to Console. Cheapest to test, proves the process management before any large install.
2. **C2 Installer (built, see C2_INSTALLER.md).** Preflight, consent, bootstrap driver with progress and cancel, resume and repair, auto-connect when done.
3. **C3 Lifecycle polish.** Auto-start with Studio, exit policy, crash recovery, port conflicts, LAN toggle with warning,
   status on header and Home.
4. **C4 Maintenance.** Update check and guarded update (only while stopped), doctor report, remove with confirmation.
5. **C5 First-run onboarding.** Home offers Simple or Advanced; hand-off to model setup once the API for it is confirmed.

## Testing
CI cannot do a multi-GB install. Tests use a tiny fake backend (a Python script that serves the health endpoint and issues a
token), a fake bootstrap script that prints the stage markers, and fakes for QProcess where needed. Physical Windows
tests cover a real install into an empty folder, start/stop, restart after reboot, and removal. Linux is tested in CI
with the fakes only.

## Risks
- Coupling to the bootstrap's text output. Mitigation: coarse stages only, full log always shown, and a backend proposal
  for a machine-readable `--json-progress` / unattended mode (to add to docs/BACKEND_PROPOSALS.md).
- winget/Git installs can raise a Windows permission prompt; the installer must say so before it starts.
- Windows Firewall prompts when LAN mode is enabled; loopback-only avoids them.
- Antivirus or long paths in the chosen folder can break a PyTorch install; the preflight warns about long paths.
- A real install takes a long time and a lot of bandwidth; Studio must stay usable and resumable during it.
- Studio and backend versions: the managed backend defaults to backend `main`; Studio checks the API contract version and
  the advertised features after connect and refuses an incompatible one with a clear message.

## Decisions (confirmed by Jim, 2026-10-14)
1. Default folder is `<Studio folder>/morphorum-backend`, with a folder chooser.
2. Studio stops the managed backend when Studio shuts down, by default. This is a setting ("Keep the backend running when Studio
   closes").
3. Simple mode installs backend **main**. After the install, the connection configuration lets the person **switch the
   backend branch** (see below).
4. The two standing rules are relaxed as described above (Studio runs the backend's own installer on explicit opt-in; Studio only
   stops a backend it started).
5. Still to confirm: build C1 first (manage an existing checkout) before the installer.

## Switching the backend branch (added to C4)
Available only for a managed install, in the connection configuration. Studio lists the remote branches (`git ls-remote`),
shows a warning that anything other than `main` may not match this Studio's API contract, and requires the backend to be
stopped. It runs a guarded `git fetch` and `git switch`, refuses if the checkout has local changes (never discards or force
resets), re-runs the backend's update/repair so dependencies match, then restarts and re-checks the API contract and
features. Projects live in the backend's `data/` folder, which the switch does not touch, but the screen says to back up
first. A failed switch leaves the previous branch checked out and offers to switch back.
