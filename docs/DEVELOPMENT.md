# Morphorum Studio development guide

## Current development entrypoint

As of 2026-10-14, active integrated development is on **`dev-ui`**. Studio `main` intentionally remains the original S0 scaffold and must not be advanced without explicit user approval.

Read these before changing code:

1. [HANDOFF.md](HANDOFF.md)
2. [ROADMAP.md](ROADMAP.md)
3. [ARCHITECTURE.md](ARCHITECTURE.md)
4. the milestone document for the area being changed

The former Morphorum backend `dev-backend` work was merged into backend `main` on 2026-10-14. Use current Morphorum `main` and the live API capability response, not dead historical branch links, when validating client behavior.

## Windows setup

Fresh development clone:

```powershell
git clone --branch dev-ui https://github.com/merberg-ai/Morphorum-Studio.git
cd Morphorum-Studio
.\setup.ps1
.\run.ps1
```

Existing checkout:

```powershell
cd D:\Morphorum-Studio
git status --short --branch
git switch dev-ui
.\update.ps1
.\run.ps1
```

If the working tree is dirty, inspect it. Do not use a force reset as a substitute for reading what changed.

## Linux setup

```bash
git clone --branch dev-ui https://github.com/merberg-ai/Morphorum-Studio.git
cd Morphorum-Studio
./setup.sh
./run.sh
```

Python support is declared in `pyproject.toml`. The current package is PySide6-based and intentionally excludes local inference dependencies.

## Tests

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

CI runs both Windows and Ubuntu with `QT_QPA_PLATFORM=offscreen`, compiles the source, verifies the CLI, runs the test suite, performs a clean wheel-install check and renders diagnostic UI screenshots on Ubuntu.

A failing Windows Qt test can sometimes be followed by a teardown crash. The first real `FAILED`, `ERROR` or assertion in the log is usually more useful than the final process-exit noise.

## Branch workflow

For app work:

1. update `dev-ui`;
2. create one feature/fix branch for the coherent change;
3. add or update tests;
4. run CI;
5. perform the relevant Windows physical acceptance when the change touches real UI, media, backend lifecycle or hardware behavior;
6. update milestone docs and [HANDOFF.md](HANDOFF.md);
7. merge into `dev-ui` only when the requested acceptance gate is satisfied.

For documentation-only housekeeping, CI is still useful but a physical GPU/Windows acceptance run is not automatically required.

### Branch naming

Examples:

- `feature/studio-s6-resilience`
- `fix/studio-audio-audition`
- `chore/repo-cleanup-YYYYMMDD`

Avoid leaving completed feature branches around forever. Git already remembers history. Humans do not need forty signposts pointing to the same highway.

## Checkpoints

`checkpoint/*` branches represent physical or milestone verification evidence. Treat them as immutable unless the user explicitly decides otherwise.

Do not reuse a checkpoint name for newer code. Create a new checkpoint if a later milestone needs one.

## Studio main

`main` is intentionally behind `dev-ui`. This is unusual for a public repository, but it is currently deliberate.

Do not:

- fast-forward or merge `main` automatically;
- force-push `main`;
- rewrite `main` to make the repository look tidier;
- claim that current development features are present on `main`.

Changing that policy requires explicit user approval.

## Backend development boundary

Morphorum Studio and Morphorum are different repositories.

Studio may:

- call the documented/live API;
- start and maintain a **managed local backend** only through Studio's explicit managed-backend feature;
- inspect advertised runtime capabilities;
- submit project/generation/render requests.

Studio must not:

- vendor Morphorum inference code;
- import Torch/CUDA/model packages;
- require the backend's model directories to be locally mounted;
- silently stop a remote backend;
- invent API behavior from an old document;
- log or commit bearer credentials.

For managed-local-backend details, see the C1-C5 and BS1/BS2 milestone docs.

## Secrets and local state

Bearer tokens belong in the OS credential store. Nonsecret profile/preferences data may live in application configuration files or QSettings.

Never commit:

- token files;
- credentials;
- cache/session state;
- managed backend working data;
- private prompts or project media captured during testing.

The repository `.gitignore` already excludes the normal managed-backend and local-state paths; extend it if a new workflow introduces another generated location.

## Pull request / merge readiness

Before integration:

- exact base and head branches are known;
- no unique work is stranded on a different branch;
- unit/mock tests cover the changed behavior;
- Windows and Ubuntu CI are green for code changes;
- real backend/GPU behavior is physically tested when relevant;
- no secret or private local data is present;
- docs describe what is actually implemented, not what somebody hoped to implement two milestones ago;
- [HANDOFF.md](HANDOFF.md) states the correct next action.

## Current known verification gap

The main outstanding S5 verification items are:

- real MP3/FLAC/OGG decode paths in Audio Director;
- Audition playback;
- Graph keyboard selection;
- Graph behavior at 880x560.

See [S5_2A_AUDIO_DIRECTOR.md](S5_2A_AUDIO_DIRECTOR.md) and [S5_3_GRAPH.md](S5_3_GRAPH.md).

User-reported app defects take priority over adding speculative roadmap features.

## Repository cleanup rule

A merged feature branch is safe to remove when comparison against `dev-ui` shows it is fully contained and has no unique commits. Keep:

- `main`;
- `dev-ui`;
- immutable `checkpoint/*` branches;
- `ui-screenshots` while CI publishes/uses it.

Before deleting a branch, verify ancestry instead of trusting its name. Names are aspirational. Commits are evidence.
