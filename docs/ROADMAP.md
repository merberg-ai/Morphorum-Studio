# Morphorum Studio development roadmap

**Current state, 2026-10-14:** current integrated source is `dev-ui`. S0 through S5.3 are implemented to varying verification levels, and the managed-local-backend work (C1-C5 plus BS1/BS2) is integrated. Studio `main` intentionally remains the old S0 scaffold until the user explicitly approves changing it.

This file is the current phase map. Detailed implementation notes and Windows test checklists live in the milestone documents beside it.

## Status summary

| Phase | Status | Notes |
|---|---|---|
| S0 Bootstrap | Complete / Windows verified | Native PySide6 shell, packaging, CI, initial checkpoints. |
| S1 Connections | Complete / Windows verified | Authenticated profiles, keyring, reconnect, identity/boot handling, preferences and splash. |
| S2 Projects/data | Complete / Windows verified | Telemetry/models, project CRUD, revision-safe saves, media assets. |
| S3 Generation/rendering | Complete / Windows verified | Still generation, animation jobs/recovery, export/download/playback. |
| S4 Editor/workflow | Complete / Windows verified in merged workflow | Timeline, keyframes, validation/import, project setup, UI/layout passes. |
| S5 Motion/Audio/Graph | Implemented | S5.1 physically tested. S5.2a Audio Director and S5.3 Graph passed CI but still need their dedicated Windows checks. S5.2b is not started. |
| Managed backend C1-C5 | Complete / Windows tested | Simple local backend lifecycle, install/startup/maintenance/onboarding. |
| Backend settings BS1/BS2 | Complete / Windows tested | Backend path/settings editing, checks and model rescanning. |
| S6 Resilience/polish | Not started as a dedicated phase | Some groundwork exists, but the formal pass remains. |
| S7 Packaging/release | Not started | Installer/portable/release-candidate work remains. |

## Immediate resume point

Before adding major new features:

1. Run the physical Windows acceptance checks for [S5_2A_AUDIO_DIRECTOR.md](S5_2A_AUDIO_DIRECTOR.md) and [S5_3_GRAPH.md](S5_3_GRAPH.md), especially real MP3/FLAC/OGG loading, Audition playback, Graph keyboard selection and the 880x560 layout.
2. Fix any discovered issues on a fresh feature branch from current `dev-ui`.
3. Reconfirm backend capability behavior against current Morphorum `main`; the old backend `dev-backend` branch is no longer the active source of truth.
4. Then continue with S6 resilience/accessibility work or the still-deferred S5.2b work, depending on priority.

The user's current request after repository housekeeping is to fix app issues, so actual reported defects take priority over speculative roadmap expansion.

## S0: bootstrap and native shell

Delivered:

- standalone public Studio repository and Unlicense;
- Python 3.12+ / PySide6 native application;
- desktop navigation shell and dark visual system;
- Windows/Linux CI and basic offscreen tests;
- development/architecture/handoff documentation;
- physical Windows launch verification.

Historical checkpoint refs remain intentionally immutable.

## S1: connection and client-service foundation

Delivered:

- typed HTTP transport and error handling;
- API contract/capability discovery;
- named profiles and OS keyring secrets;
- trusted-LAN HTTP consent;
- backend identity/boot tracking;
- reconnect and manual disconnect behavior;
- Qt worker-based network operations;
- preferences, splash and startup connection behavior.

The native client must never add browser `Origin` behavior, follow credentialed redirects blindly or stop a remote backend when Studio exits.

## S2: models, projects and assets

Delivered:

- live hardware/backend telemetry;
- model-family/model discovery;
- project list/create/open/trash/edit flows;
- strong ETag/`If-Match` saves and visible 412 conflict handling;
- source image and soundtrack assets;
- verified download/copy behavior;
- project setup/wizard integration.

## S3: generation and render lifecycle

Delivered:

- still-image generation;
- durable idempotency records before GPU submission;
- render queue/progress and still result viewer;
- animation render submission/recovery;
- completed-frame browsing;
- export requests;
- verified MP4/WebM/GIF/image downloads and playback.

Core invariant: uncertain GPU submission state is reconciled, not resubmitted with a new idempotency key.

## S4: native editing workflow

Delivered:

- timeline visualization;
- prompt/generation/camera schedules;
- keyframe editing and undo behavior;
- validation;
- Deforum Motion Studio settings import;
- project setup and model/LoRA selection;
- desktop layout and usability passes;
- queue/library/timeline/lab shell refinements.

Milestone records: `S4_*.md`, `UI_PASS.md`, `LAYOUT_*.md`.

## S5: Motion Lab, Audio Director and Graph

### S5.1 Motion Lab

Implemented and physically tested:

- motion layers;
- presets/curves;
- preview/apply flows;
- conflict handling.

### S5.2a Audio Director

Implemented and CI-tested:

- WAV plus local Qt decoding path for MP3/FLAC/OGG/M4A;
- fixed backend band analysis;
- level/transient driven layers;
- threshold/attack/return/gap/offset/range controls;
- envelope view and audition;
- soundtrack distinction/warnings.

Still requires dedicated physical Windows acceptance. See [S5_2A_AUDIO_DIRECTOR.md](S5_2A_AUDIO_DIRECTOR.md).

### S5.2b deferred audio expansion

Not started. Candidate work includes:

- custom bands;
- bass-intensity/ripple response modes;
- spectrum view;
- Backend vs Studio-local analysis selection;
- other ideas that require either backend support or a deliberately local implementation.

Backend gaps are tracked in [BACKEND_PROPOSALS.md](BACKEND_PROPOSALS.md). Do not expose controls that have no real implementation.

### S5.3 Graph

Implemented and CI-tested:

- read-only pipeline diagram;
- project-stage inspection;
- keyboard/click selection;
- navigation to editing workspaces.

Still requires dedicated physical Windows acceptance. See [S5_3_GRAPH.md](S5_3_GRAPH.md).

## Managed local backend track

This was a separate practical feature track, now integrated into `dev-ui`.

Delivered:

- C1 existing local backend management;
- C1b startup/reconnect integration;
- C2 backend install workflow;
- C3 process lifecycle/crash/port/LAN handling;
- C4 maintenance/update/repair/branch-management workflows;
- C5 onboarding;
- BS1/BS2 backend settings, folder validation and model rescanning.

Detailed records live in `docs/C*.md`, `docs/BS*.md` and [MANAGED_BACKEND_PLAN.md](MANAGED_BACKEND_PLAN.md).

## S6: resilience, accessibility and performance

Planned priorities:

- network-loss and reconnect regression coverage;
- corrupt/partial download recovery;
- stale ETag and conflict regression coverage;
- long render-manifest handling;
- lazy thumbnail/frame loading and bounded cache usage;
- high-DPI and multi-monitor review;
- keyboard navigation/tab order;
- accessible names/descriptions and contrast review;
- safe shutdown/session recovery;
- cleanup of known Qt teardown edge cases.

This phase should be driven by actual physical defects first, not cosmetic churn for its own sake.

## S7: packaging and release candidate

Planned:

- Windows installer and/or portable package;
- no bundled Torch/CUDA/model weights;
- credential migration/compatibility;
- update strategy;
- CI build artifacts;
- release documentation and screenshots;
- full clean-machine Windows acceptance;
- versioning/release checklist.

## Repository and branch discipline

1. Start feature/fix work from current `dev-ui`.
2. Use one coherent branch per change set.
3. Keep automated CI distinct from physical Windows acceptance.
4. Preserve immutable `checkpoint/*` refs.
5. Delete merged feature branches once ancestry is verified and they contain no unique work.
6. Do not merge Studio `main` without explicit user approval.
7. Keep backend and Studio repositories separate.
8. Update [HANDOFF.md](HANDOFF.md) whenever the actual resume point changes.

## Architecture rules that do not change

- Studio is a pure desktop client; GPU/model work belongs to Morphorum.
- Runtime backend capabilities beat historical prose.
- Secrets stay in the OS credential store.
- GUI threads do not perform blocking network/media work.
- Strong ETags protect project edits.
- Durable idempotency protects GPU submissions.
- Media downloads use temporary files plus integrity validation before replacement.
- A Studio disconnect or exit must not silently cancel or duplicate backend work.
