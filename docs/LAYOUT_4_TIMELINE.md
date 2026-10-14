# Layout step 4: Timeline workspace

The Editor is now the **Timeline** workspace (page key `Editor`), and the Render card moved into it.

## What changed
- **Preview player** at the top centre: shows the rendered frame at the playhead, with transport
  (first, step back, Play/Pause, step forward, last) and a "Frame N / total · seconds" readout. It shows only frames
  the backend has actually rendered; otherwise it says "Frame N has not been rendered yet" or "No rendered frames
  yet". Frames are downloaded once and cached (32). Play advances at the project's fps, capped at 12 per second, and
  stops at the last frame.
- **Tracks dock** below the player (the existing painted lanes, scrubbing, track selection).
- **"At this frame" and schedule checks** under the tracks.
- **Right column**: the **Keyframe inspector** (curve, keyframes, value, set/update/move/delete, interpolation,
  undo/redo, all unchanged in behaviour) and the **Render** card (render, cancel, resume, history, progress, preview GIF,
  video export). In this workspace the card has no picture of its own; **Save frame…** saves the frame at the playhead.
- Library's project detail no longer holds the Render card; it has **Open in Timeline** instead. Home tiles still open
  the Library detail view.
- Not built because the backend does not support it: render *ranges* (the backend renders the whole saved project).

## Windows acceptance checklist
1. Open Timeline, pick a project that has been rendered: the player shows frame 1 of the latest render.
2. Step with the buttons and with ← →; drag in the tracks: the preview follows, with the readout. A frame beyond the
   rendered range says so.
3. Press Play: the playhead moves at the frame rate and stops at the end. Pause works mid-way.
4. Edit a keyframe, undo and redo: still saved immediately; values and checks update.
5. Start a render from the Render card: the player picks up new frames as they complete (move the playhead to see them).
6. Save frame… writes the PNG for the frame under the playhead (disabled on frames not yet rendered).
7. Library → project → Open in Timeline opens that project here.
8. At 880 × 560 the page scrolls instead of overlapping.
