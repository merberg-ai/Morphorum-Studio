# S3.2 Animation renders and job recovery (branch `feature/studio-s3-2-animation`)

Stacked on `feature/studio-s3-1-image-lab`. Nothing merged. Needs CI plus a physical Windows test
against a GPU backend. Use a tiny project first (4-8 frames, 256x256, few steps).

## What it does
A **Render** card at the bottom of each project's detail on the Projects page:
- **Render animation** sends the *complete saved project* (read fresh from the backend, never just
  its id) with an `Idempotency-Key`. A confirmation explains it uses the GPU. It is paused while the
  form has unsaved edits, because a render uses the saved version.
- **Durable start**: the exact body and key are written to the submission journal before the POST (the
  same journal as Image Lab, tagged `animation`). A lost response shows "may not have reached the
  backend"; *Retry the same request* resends the same key and body and cannot create a second render.
- **Progress**: queued, model loading (with percent), frame n of N, step, ETA, average seconds per
  frame; frozen soundtrack and hybrid-video notes when present.
- **Frame browser**: a slider over the completed frames with the selected frame shown at the left;
  "Follow latest" keeps the newest frame visible while rendering, moving the slider stops following,
  returning to the newest resumes it. Frames are fetched on demand (cache of 24). *Save frame…* writes
  a verified PNG.
- **Preview**: for completed renders, *Play preview* plays the backend's GIF in a small player;
  *Save preview…* writes it.
- **Cancel** while active. **Resume…** for failed, cancelled or interrupted renders asks first and
  continues from the frames already on disk.
- **Recovery**: the render list comes from the backend, so closing Studio, losing the LAN, or even a
  backend restart does not lose anything. A running render is picked up again automatically when you
  open the project or reconnect; after a backend restart it appears as *interrupted* and can be
  resumed. Journal entries for renders that finished (or that the backend no longer knows) are removed
  automatically.

## Decisions
- **No SSE client.** The roadmap suggested server-sent events with polling as the fallback. The backend
  generates those events by polling its own job state about every 0.75 s, so a Studio event stream
  would add a long-lived connection per render for no latency gain over polling once a second, and
  the backend documents that events are not replayable and that clients must GET state anyway. State
  therefore always comes from REST GETs (once a second while rendering, every 3 s while queued or
  loading). The backend's `boot_id` change is still handled: Studio's connection epoch resets and the
  job list is re-read.
- Journal entries for animations can hold a whole project, so the journal now accepts up to 2 MiB per
  entry (was 64 KiB) and request bodies up to 2 MiB for this call.

## Not in S3.2
Performance report tables, video/audio export (S3.3), editing the timeline or motion (S4/S5), several
renders watched at once, and downloading all frames.

## Windows acceptance checklist
1. Open a saved project with a source image if its mode needs one. Edit its name without saving: the
   Render button is paused with an explanation; Save re-enables it.
2. Start a tiny render: confirmation, then progress with frame/step/ETA and the newest frame shown.
3. Drag the slider back: the frame changes and following stops; tick *Follow latest* to catch up.
4. Let it finish: *Done: N frames*; *Play preview* plays; *Save frame…* and *Save preview…* produce
   files that open.
5. Start another and press Cancel: ends as *Cancelled*; *Resume…* asks, then continues and finishes.
6. Start a render, close Studio completely, reopen and select the project: the render is picked up
   again with its current progress.
7. Start a render and restart the backend process: after reconnecting the render shows *interrupted*;
   Resume continues it.
8. Pull the network right after pressing Render, restore it: the banner appears and Retry produces one
   render in the backend console.
9. A project that the backend refuses (for example a missing source image): the refusal text is shown
   and nothing is left in the journal.
