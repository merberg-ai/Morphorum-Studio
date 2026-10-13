# S4.2 Keyframe editing (branch `feature/studio-s4-2-keyframes`)

Branched from `dev-ui` (S1–S4.1 and the console merged). Nothing merged. Needs CI plus a Windows
check against a backend whose projects you don't mind editing (duplicate one first).

## What it does
On the **Editor** page, select a track lane, then use the controls under its keyframe list:
- **Set at playhead**: add a keyframe at the playhead frame, or change it if one is there, using the
  value box (a number, an expression such as `1+0.5*sin(t)`, or prompt text).
- **Update selected**: change the value of the keyframe selected in the list.
- **Delete**: remove the selected keyframe (a prompt track's frame-0 keyframe cannot be removed).
- **Move to playhead**: move the selected keyframe; if one already exists at the target, Studio asks
  before replacing it.
- **Interpolation**: switch the track between its supported modes (linear/hold, blend/hold for prompts).
- **Undo / Redo**: step back and forward through this session's edits for the open project.

## Safety rules
- Every edit is saved to the backend immediately (the backend's track endpoints have no preview), and
  Studio then **reloads the timeline from the backend** instead of trusting its own prediction.
- **Revision guard**: the backend's keyframe calls have no revision check, so before each edit Studio
  compares the project's ETag with the one it loaded. If the project changed elsewhere, nothing is sent,
  history is cleared, the timeline reloads and a message says so.
- Numeric values and expressions are validated by the backend; a refusal (for example a bad
  expression) is shown and leaves the project and undo history untouched.
- Any other failure (such as a network drop) clears the undo history and reloads, because the backend
  may or may not have applied the change.
- Keyframes whose *frame* is an expression are shown but not editable here (edit them in the Web UI).
- Undo/redo is per loaded project and is dropped when you switch project, reload or reconnect.
- Saving the project's name/notes on the Projects page after timeline edits can report a revision
  conflict (the revision changed); use the existing compare/reload dialog.

## Windows acceptance checklist (use a copy of a project)
1. Add a numeric keyframe at the playhead; it appears in the list, lane and curve; the backend Web UI shows it.
2. Change it; Undo restores the old value; Redo reapplies it.
3. Delete a keyframe; Undo brings it back with the same value.
4. Move a keyframe onto an empty frame, then onto an occupied one (confirm); Undo restores both.
5. Change interpolation and undo it; render a few frames to confirm the effect.
6. Enter a bad expression: a clear error, nothing changed, Undo still works for earlier edits.
7. Change the project in the Web UI (or another Studio), then edit here: refused with "changed elsewhere".
8. Edit a prompt track: frame 0 cannot be deleted or moved.
