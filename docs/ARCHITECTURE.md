# Morphorum Studio architecture contract

## Purpose

Morphorum Studio is a **native PySide6 desktop client** for the separate Morphorum GPU backend.

It is not:

- an embedded copy of the Morphorum browser UI;
- a local inference bundle;
- a CUDA/PyTorch/model installer inside the Studio Python environment;
- a shared-filesystem wrapper around backend directories.

All generation, model indexing, animation rendering, media export and GPU work belongs to Morphorum. Studio owns native desktop UX, client state, safe request/recovery logic and optional management of a deliberately configured local backend installation.

## Current implementation boundary

As of 2026-10-14, the integrated `dev-ui` branch contains the working client stack through S5 plus the managed-backend track.

Representative package layout:

```text
src/morphorum_studio/
  app.py, __main__.py
  backend/
    client.py              HTTP transport and error handling
    session.py             active authenticated client/session state
    profiles.py            nonsecret connection profiles
    credentials.py         OS keyring token storage
    projects.py            project CRUD / ETag handling
    assets.py              project media transfer and verification
    images.py              still-image API
    renders.py             animation/render lifecycle
    videos.py              video export and verified download
    timeline.py            timeline/keyframe API model
    motion.py              Motion Lab data/API helpers
    audio.py               audio analysis/layer model
    graph.py               project pipeline graph model
    managed.py             local managed backend state/process/install support
    maintenance.py         managed backend maintenance
    backend_settings.py    backend settings/model path API
    console.py             backend console access
  ui/
    main_window.py
    home_page.py
    projects_page.py
    image_lab_page.py
    editor_page.py
    motion_panel.py
    audio_widgets.py
    graph_page.py
    queue_page.py
    console_page.py
    settings_page.py
    connections_panel.py
    managed_backend.py
    ...
tests/
docs/
scripts/
```

Exact filenames evolve. [HANDOFF.md](HANDOFF.md) and the source tree beat this summary if they differ.

## System boundary

```text
┌────────────────────────── Morphorum Studio ──────────────────────────┐
│ Native PySide6 UI                                                   │
│                                                                     │
│  pages/widgets                                                      │
│       │                                                             │
│  Qt services/workers ────── session snapshots / typed state         │
│       │                                                             │
│  API clients ─ profiles ─ OS keyring ─ durable request journals     │
│       │                                                             │
│  optional managed-local-backend lifecycle adapter                   │
└───────┼─────────────────────────────────────────────────────────────┘
        │ authenticated HTTP(S), optional ephemeral event streams
        ▼
┌──────────────────────── Morphorum backend ──────────────────────────┐
│ projects / models / telemetry / jobs / frames / exports / settings │
│ CUDA / model pipelines / render workers / FFmpeg / backend storage │
└─────────────────────────────────────────────────────────────────────┘
```

## Source of truth

The former backend `dev-backend` development line was merged into Morphorum `main` on 2026-10-14. Current client work must use:

1. the actual Morphorum `main` implementation;
2. the authenticated runtime capability response;
3. live response schemas exercised by tests/physical checks.

Old Studio milestone documents that mention `dev-backend` are historical evidence, not a promise that the branch or linked backend documents still exist.

Backend API contract version 1 remains the compatibility gate unless the live backend advertises otherwise.

## Connection/session model

There should be **one authoritative active session** shared by UI services.

Pages must not each:

- read tokens independently;
- create their own reconnect loops;
- invent their own backend identity rules;
- keep using a client after profile/session epoch changes.

When the active profile, instance or boot changes, pending page work must either be invalidated or explicitly reconciled.

Network I/O belongs off the Qt GUI thread.

## Security invariants

### Credentials

- Store bearer secrets in the OS credential store.
- Do not put them in profile JSON, QSettings, URLs, screenshots, logs or test output.
- Reject or scrub credential-bearing redirects.
- Never expose a token in the Console UI.

### HTTP trust

An explicit trusted-LAN approval means only that the user accepted sending credentials over plaintext HTTP to that exact target. It is **not** TLS authentication.

`instance_id` continuity is useful for detecting unexpected backend replacement, but it is not cryptographic identity.

### Remote lifecycle

A normal remote connection never grants Studio the right to stop the backend process.

Managed-local-backend process controls apply only to the installation/process Studio can positively identify as its configured local backend.

## Project integrity

- Read projects with their strong ETag.
- Save with `If-Match`.
- Treat HTTP 412 as a visible conflict requiring reload/review/cancel behavior.
- Never silently overwrite a newer backend revision.
- Do not infer backend filesystem paths as client-local paths.

## GPU request integrity

Before submitting a generation/render request that requires idempotency:

1. freeze the exact request body;
2. generate/store the durable idempotency key;
3. persist both before POST;
4. submit that exact pair;
5. reconcile uncertain/pending responses instead of generating a new key.

A 409 or lost response is not permission to duplicate expensive GPU work. Humanity already has enough accidental duplication.

## Job/reconnect semantics

- backend `boot_id` changes invalidate ephemeral event cursors;
- persisted job/render GET endpoints and completed frame manifests are authoritative;
- an event stream is an optimization, not durable history;
- backend process death can interrupt active GPU work;
- completed persisted output may recover after restart;
- Studio must never display a vanished running job as healthy merely because local state says it used to exist.

## Media transfer

For project media, generated images and exports:

- download to a temporary/part file;
- enforce expected origin;
- validate expected size/hash when provided;
- validate basic media signature/format;
- atomically replace the destination only after validation.

A failed transfer must not destroy an existing valid local file.

Soundtrack ownership and Motion Lab analysis audio are separate concepts. Do not silently substitute one for the other.

## Audio Director boundary

Current Studio can locally decode common compressed audio through Qt Multimedia into the WAV form expected by the backend's analysis endpoint. Backend-side decode/custom-band/extra-response behavior is not assumed unless advertised and implemented.

Potential expansions that need backend or deliberate local-analysis work are tracked in [BACKEND_PROPOSALS.md](BACKEND_PROPOSALS.md).

## Managed local backend boundary

The managed-backend track lets Studio deliberately install/manage a local Morphorum checkout.

It must remain isolated from normal remote-client semantics:

- explicit install consent;
- validated target folder;
- no destructive writes outside the managed folder except actions performed by Morphorum's own installer with user-visible consent;
- process ownership/identity checks before Stop/Restart;
- clear handling of port conflicts;
- no secret leakage;
- managed data excluded from Git.

See `C1_MANAGED_BACKEND.md`, `C2_INSTALLER.md`, `C3_LIFECYCLE.md`, `C4_MAINTENANCE.md`, `C5_ONBOARDING.md` and `BS*.md`.

## UI architecture

Pages should use service objects/signals rather than performing blocking backend work directly.

Stable internal page keys are important because navigation, saved preferences and cross-page links depend on them. User-facing display names may differ from those keys.

At smaller desktop sizes, functional scrolling/reflow is preferable to truncating controls. S6 will formalize high-DPI, accessibility, keyboard and performance review.

## Testing layers

Use all three where appropriate:

1. **unit/parse/model tests** for deterministic logic;
2. **Qt offscreen/CI tests** for native widget and service behavior on Windows/Ubuntu;
3. **physical Windows/backend tests** for codecs, playback, real network/backend lifecycle, GPU work and desktop-specific behavior.

Passing layer 2 does not magically prove layer 3. Computers remain stubbornly physical despite decades of marketing.

## Repository architecture rules

- `dev-ui` is the current integrated development branch.
- `main` stays untouched until explicitly approved.
- historical feature branches may be deleted after proving they are fully contained in `dev-ui`;
- `checkpoint/*` refs remain immutable evidence;
- `ui-screenshots` has intentionally independent generated history.

For current resume state, always read [HANDOFF.md](HANDOFF.md).
