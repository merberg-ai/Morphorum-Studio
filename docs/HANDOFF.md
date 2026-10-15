# Morphorum Studio: current development handoff

**Updated: 2026-10-14. Read this first in a new chat.**

- Studio repository: https://github.com/merberg-ai/Morphorum-Studio
- Backend repository: https://github.com/merberg-ai/Morphorum
- Current integrated Studio branch: **`dev-ui`**
- Studio `main`: intentionally preserved S0 scaffold at `fb5024e7592a6d271a8eeb214fc2470387d2e363`; do not merge/update it without explicit user approval.
- Last major Studio code merge before repository housekeeping: **`6569373190a4a444bbf9935f23fa2bd3e2d034df`**, merging `dev-connections` into `dev-ui` with managed local backend C1-C5 plus backend settings BS1/BS2.
- Previous roadmap code merge: **`62eb67fc6cab001b79b763264d8a6274318ca289`** for S5.3 Graph.
- Backend development formerly held on `dev-backend` was merged to Morphorum `main` on 2026-10-14. Backend `main` had advanced to **`6fb8a26f9ae210a57fe2e84481bb18ac21b76cc9`** when this handoff was refreshed. The old `dev-backend` branch/reference docs are no longer the active source of truth.

## Current user goal

The user asked to:

1. audit/catch up on the Morphorum-Studio repository;
2. clean up the repository;
3. then fix current app issues.

Repository housekeeping comes first. After cleanup, actual user-reported app defects take priority over adding new roadmap features.

## Repository audit result

The repository had accumulated many historical feature branches and stale canonical documentation.

### Branch ancestry

Every normal feature/development branch checked was a strict ancestor of current `dev-ui` and had **zero unique commits** relative to it. This includes:

- `dev-connections`
- `feature/studio-bs1-backend-settings`
- `feature/studio-bs2-rescan`
- `feature/studio-c1-managed`
- `feature/studio-c1b-startup`
- `feature/studio-c2-installer`
- `feature/studio-c3-lifecycle`
- `feature/studio-c4-maintenance`
- `feature/studio-c5-onboarding`
- `feature/studio-console`
- `feature/studio-layout-1-shell` through `feature/studio-layout-6-queue`
- `feature/studio-s1-connection-foundation`
- `feature/studio-s1-hardening`
- `feature/studio-s2-1-dashboard` through `feature/studio-s2-4-polish`
- `feature/studio-s3-1-image-lab` through `feature/studio-s3-3-video`
- `feature/studio-s4-1-timeline` through `feature/studio-s4-4-project-setup`
- `feature/studio-s5-motion-audio`
- `feature/studio-s5-2a-audio-director`
- `feature/studio-s5-3-graph`
- `feature/studio-ui-pass`
- `feature/studio-ui-shell`

These are safe branch-deletion candidates once the cleanup branch itself is integrated.

Keep:

- `main`
- `dev-ui`
- all `checkpoint/*` branches
- `ui-screenshots` while CI uses it

`ui-screenshots` intentionally has unrelated generated history, so comparing it to `main`/ `dev-ui` has no common ancestor. That is expected, not missing app code.

### Documentation drift found

Before this cleanup:

- README still described S1 / “S2.1 not started”.
- ROADMAP header still said S2.1 was next while lower sections described S5 work.
- DEVELOPMENT and ARCHITECTURE still described the project as mostly pre-S2.
- HANDOFF correctly recorded the backend merge near the top but later still contained one obsolete rule saying backend PR #32 must stay unmerged.
- several canonical references pointed to backend `dev-backend` documents that no longer exist after backend cleanup.

The canonical docs are being refreshed during the repository-cleanup branch. Historical milestone docs may still mention their original branch/baseline and should be treated as milestone evidence, not live state.

## What is implemented on dev-ui

Nothing below is on Studio `main` yet.

| Area | Current implementation |
|---|---|
| Connections / S1 | named profiles, keyring credentials, HTTP consent, capability discovery, reconnect, instance/boot tracking |
| Dashboard / S2.1 | telemetry, GPU/memory/backend status, model discovery |
| Projects / S2.2 | list/create/open/edit/trash, ETag/`If-Match`, conflict handling |
| Assets / S2.3 | source image/soundtrack handling and verified local saves |
| Image Lab / S3.1 | still generation, durable idempotent submission, result viewer |
| Animation / S3.2 | render submission, polling/recovery, completed-frame browsing |
| Video / S3.3 | export, verified download and playback |
| Console | backend log/event UI |
| Editor / S4 | timeline, keyframes, validation, Deforum import, project setup |
| Motion Lab / S5.1 | presets/curves/layers, preview/apply/conflict handling |
| Audio Director / S5.2a | WAV and local compressed-audio decode path, band analysis/layers, envelope/audition UI |
| Graph / S5.3 | read-only project pipeline graph and navigation |
| Managed backend C1-C5 | local backend selection/install/startup/lifecycle/maintenance/onboarding |
| Backend settings BS1/BS2 | backend model paths/settings, validation and rescan |

## Physical acceptance state

Reported PASS / physically exercised on Windows:

- S0
- S1
- S2.1-S2.3
- S3.1-S3.3
- S4/layout work as merged
- S5.1
- managed backend C1-C5
- backend settings BS1/BS2

Still requiring dedicated physical Windows acceptance:

- **S5.2a Audio Director**
  - real MP3/FLAC/OGG load/decode
  - Audition playback
  - real audio behavior beyond CI fakes
- **S5.3 Graph**
  - keyboard selection
  - 880x560 behavior

See `docs/S5_2A_AUDIO_DIRECTOR.md` and `docs/S5_3_GRAPH.md`.

## Known implementation caveats

- Backend audio analysis accepts PCM WAV; Studio currently decodes compressed formats locally through Qt Multimedia before upload.
- Analyzed Motion Lab audio and the final-video soundtrack remain distinct concepts.
- Timeline at 880x560 may require horizontal scrolling.
- Timeline render-frame playback is intentionally limited; Audition follows audio position instead.
- Windows Qt tests can emit a teardown crash after a prior test failure. Diagnose the first real assertion/error rather than the final process exit.
- `tests/test_preferences.py` has historically had an unused-import lint issue; CI currently focuses on compile/pytest/clean-install rather than a strict Ruff gate.

## Backend source of truth

Do **not** rely on the now-removed `dev-backend` documentation URLs.

For current work:

1. inspect current Morphorum `main`;
2. inspect authenticated `GET /api/client/capabilities`;
3. validate live response schemas in tests or against the real backend;
4. preserve Studio's contract-v1 safety rules unless the backend explicitly evolves them.

If a proposed Studio control cannot be served by the actual backend, either implement a deliberate local behavior or record a backend proposal. Do not ship decorative fiction with a button attached.

## Non-negotiable architecture/safety rules

- Studio is a native PySide6 client, not the backend UI in a WebView.
- Studio does not install Torch/CUDA/model weights into its own Python environment.
- Secrets remain in the OS credential store, never profile JSON, QSettings, URLs or logs.
- Plain HTTP requires explicit trusted-LAN consent.
- `instance_id` continuity is not cryptographic authentication.
- `boot_id` changes invalidate ephemeral event state.
- Project saves use strong ETag/`If-Match`; 412 conflicts are visible and never silently overwritten.
- GPU submissions persist the exact request + idempotency key before POST.
- Unknown/409 submission state is reconciled, not resubmitted with a fresh key.
- Media downloads use temporary files plus size/hash/signature validation before atomic replacement.
- Normal remote connections never allow Studio to stop the backend.
- Managed-local-backend Stop/Restart applies only to a process/install Studio can positively identify as its managed backend.
- GUI-thread blocking network/media work is not acceptable.

## Development workflow

Start new code/fix work from current `dev-ui`.

Typical Windows session:

```powershell
cd D:\Morphorum-Studio
git status --short --branch
git switch dev-ui
.\update.ps1
.\run.ps1
```

Tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_clean_install.py
```

Use one coherent branch per fix/feature. CI should pass before integration. Physical Windows testing is required when the change depends on real codecs, playback, backend lifecycle, GPU behavior or desktop interaction.

## Repository branch policy

- `dev-ui` is the current integration branch.
- `main` remains untouched until the user explicitly approves changing that policy.
- `checkpoint/*` branches are immutable evidence.
- merged historical feature branches should be deleted after ancestry verification.
- `ui-screenshots` is generated CI state, not an app development branch.

Repository cleanup on 2026-10-14 was prepared on **`chore/repo-cleanup-20261014`** from `dev-ui`. After integration, resume ordinary work from `dev-ui` and remove the temporary cleanup branch.

## Next work after cleanup

Once repository cleanup is integrated and the redundant remote branches are removed, continue with the app issues the user reports. Do not automatically resume S6 or S5.2b merely because they are next on the old roadmap.

If no app defect is yet specified, the outstanding Windows acceptance checks for S5.2a/S5.3 are the most useful existing verification target.

## Files to read in a new chat

1. this file;
2. [ROADMAP.md](ROADMAP.md);
3. [ARCHITECTURE.md](ARCHITECTURE.md);
4. [DEVELOPMENT.md](DEVELOPMENT.md);
5. the milestone document for the area being changed;
6. current GitHub branch/CI state.

Live source and Git history outrank stale prose.
