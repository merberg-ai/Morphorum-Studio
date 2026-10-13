# S3.1 Image Lab (branch `feature/studio-s3-1-image-lab`)

Stacked on `feature/studio-s2-4-polish` (S2.2 projects, S2.3 media, conflict-dialog polish). Nothing
merged. Needs CI plus a physical Windows test against a GPU backend. This is the first Studio feature
that starts GPU work, so run the checklist with a small model and a small image first.

## What it does
- **Request form**: model (supported checkpoints only), prompt, negative prompt (hidden for families
  without one), LoRA picker that inserts `<lora:name:weight>` into the prompt (the backend's own
  syntax; only LoRAs of the same family are offered), size presets plus width/height, steps, guidance,
  sampler, image count, seed, seed mode (same / step / random each) and seed step.
- **Model-valid limits**: ranges and defaults come from the backend's `/api/generation/capabilities`,
  including variants (for example Flux Schnell: 1-8 steps, guidance fixed at 0). Size steps are 8
  (16 for Flux and Z-Image). The last model used is remembered per connection.
- **Durable submissions**: the exact body and a generated `Idempotency-Key` are written to a private
  journal file (fsynced, atomic) *before* the POST. If the connection drops after the backend accepted
  it, **Retry the same request** resends the same key and body, which returns the existing job instead
  of starting another. A definitive refusal (HTTP 400/401/403/404/422) removes the entry. Entries for a
  job that finished (or that the backend no longer knows, for example after a restart) are cleaned up
  automatically; a still-running job is picked up again when Studio reconnects.
- **Job monitor**: queued, model loading, per-step progress, image n of N, ETA, cancel. State comes
  from `GET /api/generation/jobs/{id}` once a second (slower while queued or struggling); the
  backend's answer always wins. Stops after repeated failures and says so.
- **Results**: verified-PNG thumbnails, a viewer with fit/zoom and *Save copy…* (streams to `.part`,
  checks the PNG signature, renames), and an *Earlier jobs* list from the backend.

## Safety notes
- Studio never invents defaults: every limit shown came from the backend, and the backend still
  validates; its refusal text (for example a missing checkpoint) is shown as-is.
- Server file paths in model or job responses are dropped and never displayed.
- One submission in flight and one watched job at a time. Results from an older connection are
  discarded. The journal is per connection profile, capped at 50 entries.
- Journal location: the OS local app-data folder, `Morphorum/Morphorum Studio/submissions`.

## Not in S3.1
Img2img from a source image, server-sent-event progress (S3.2 adds SSE with this polling as the
fallback), a persistent gallery of old images on this computer, queue reordering, and unloading the
model from the GPU.

## Windows acceptance checklist
1. Open Image Lab disconnected: explains itself. Connected: models load; unsupported families hidden.
2. Switch between an SDXL and a Flux model: steps/guidance/sampler/size and the negative prompt box
   change; Flux Schnell shows guidance disabled.
3. Add a LoRA: the tag appears in the prompt. Generate 1 image: progress, ETA and a thumbnail appear.
4. Generate 3 images with "Step the seed": thumbnails show the stepped seeds; open one, zoom, Save copy.
5. Press Cancel while generating: job ends as Cancelled and Generate re-enables.
6. Bad input (empty prompt, width 1020): a clear message and nothing is sent.
7. Pull the network cable right after pressing Generate, then restore it: the "may not have reached"
   banner appears; Retry the same request produces exactly one job (check the backend console).
8. Close Studio mid-job and reopen: the running job is picked up, or finished jobs are under Earlier jobs.
9. Restart the backend with a pending entry: the stale entry disappears without an error.
