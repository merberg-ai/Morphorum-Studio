# S4.1 Animation timeline viewer (branch `feature/studio-s4-1-timeline`)

Branched from `dev-ui` (which now contains S1–S3.3 and the console). Nothing merged. Needs CI plus
a Windows check. **Read-only**: it never changes a project.

## S4 is split into checkpoints
- **S4.1 (this)**: timeline view, scrubbing, backend-evaluated values and curves.
- S4.2: keyframe editing through the backend's track endpoints (add/change/delete/move, interpolation),
  with the project revision refreshed afterwards and an undo history in Studio.
- S4.3: schedule validation feedback, Deforum settings import preview/create, presets.
- S4.4: source image / img2img controls, LoRA manager, project wizard with pre-render validation.

## What it does
The **Editor** page loads a project's timeline from the backend (`/projects/{id}/timeline`):
- **Lanes** for every track the backend describes (prompts, 2D camera, 3D camera, generation,
  cadence), grouped, with a diamond at each keyframe. Cyan diamonds are plain numbers or prompts;
  violet diamonds are *expressions* (for example `1+0.5*sin(t)`), which only the backend evaluates.
- **Scrub**: click or drag in the ruler or lanes, type a frame number, or use ← → (Shift ×10).
  The playhead and a seconds readout follow.
- **At this frame**: the backend resolves the project at that frame (`/resolve-timeline`, one
  frame, debounced while dragging) and Studio shows each track's value, the positive/negative
  prompt (as `from → to` during a transition) and the seed.
- **Track panel**: click a lane to see its keyframes (frame expression and value as stored) and, for
  numeric tracks, the curve sampled by the backend (`/schedule-series`) with keyframe dots and the
  playhead. Prompt tracks list their keyframes; they have no curve.
- Studio never evaluates an expression itself. A curve the backend refuses (invalid schedule) is
  reported, not drawn.

## Windows acceptance checklist
1. Editor page, choose a project: lanes appear with sensible keyframes; the status line shows frames,
   fps and duration.
2. Scrub with the mouse, the frame box and the arrow keys; the values table follows within a moment.
3. Click a numeric track: keyframes listed, curve drawn, playhead moves with scrubbing.
4. Compare a few values at keyframe frames with the backend Web UI for the same project.
5. A project with an expression keyframe shows a violet diamond and the expression text.
6. A prompt-change project shows `from → to` text between its prompt keyframes.
7. Switch projects, press Reload, disconnect and reconnect: no stale lanes or values remain.
