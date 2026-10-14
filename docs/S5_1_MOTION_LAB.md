# S5.1: Motion Lab (camera motion layers)

Motion Lab is a second tab, **Motion**, in the Timeline workspace's right column (next to **Keyframes**).
It composes six-axis 3D camera motion from layers; the backend compiles them. Studio never computes motion itself.

## What you can do
- See the project's motion layers in order (applied top to bottom), switch them on or off, add, copy, remove and
  reorder them (up to 24).
- **Preset layers**: Gentle drift, Wave, Spiral, Figure eight, Rocking, Push in, Pull out, Still (the list comes from the
  backend). Per layer: strength, cycle, fade, frame range, and whether it adds to or replaces the camera.
- **Curve layers**: one camera axis, a set of keyframes (frame, per-frame move), interpolation (linear, hold,
  smoothstep, smootherstep, cubic) and range.
- **Preview** asks the backend to compile the draft and draws the six resolved curves with the playhead; axes can be
  hidden. Values the backend clipped to its safety limits are reported. Nothing is saved.
- **Apply to camera** saves the result into the project's six camera tracks. If the camera tracks were edited by hand
  since the last Apply, Studio asks before using them as the new base. The timeline reloads afterwards.
- **Revert** returns the draft to what is saved.

## Rules and limits
- Motion Lab needs a project in **3D** mode; in 2D it explains this and stays disabled.
- Recorded-take and audio-pulse layers (made in the web app) are **kept exactly as stored** and sent back unchanged;
  they can be switched off, moved or removed, but not edited yet. Audio layers get their editor in S5.2.
- Frame 0 never moves (the backend enforces this) and a curve needs at least one keyframe.
- Apply needs at least one layer.

## Windows acceptance checklist
1. Open a 3D project in the Timeline, click **Motion**: its layers are listed (empty for a new project).
2. Add a preset layer, set Strength 0.8, press **Preview**: curves appear; moving the playhead moves the marker.
3. Add a Curve layer on Pan (Y) with two keys, Preview: the Pan curve follows your keys.
4. Apply, switch to **Keyframes**, select a camera track: its keyframes/curve now hold the composed motion.
5. Edit a camera keyframe by hand, return to Motion and Apply again: you are asked before the hand edit becomes the base.
6. Reopen the project (reload): the layers are still there and Preview matches.
7. A project with an audio or recorded layer from the web app: it is listed, not editable, and still applied.
8. A 2D project: Motion explains it needs 3D.
