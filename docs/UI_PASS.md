# UI pass (branch `feature/studio-ui-pass`)

Branched from `dev-ui` (S1–S4.4 merged). Nothing merged. Needs CI plus a Windows check.

## How it was reviewed
CI now renders every page offscreen against a scripted fake backend (`scripts/render_screenshots.py`)
at 1200×760, 880×560 and 1600×900, offline and connected, plus the wizard and model dialogs and a 175%
scaling run. The PNGs are uploaded as the `ui-screenshots` artifact and pushed to the
`ui-screenshots` branch of the repository, so layout can be reviewed without a display.

## Changes
- **Controls:** dropdown and spin-box arrows and check marks were invisible; they are drawn now
  (glyph PNGs generated at start-up into the cache directory and referenced from the stylesheet).
  Spin buttons, tabs, list widgets and dialogs are themed; unused scrollbar handles no longer draw.
- **Layout:** the Projects toolbar no longer clips "Import Deforum…" (two rows). The Editor body
  scrolls instead of overlapping at small window sizes, its edit buttons wrap onto two rows, and the
  keyframe panel gets most of the height. Dialogs have padding. Footer and Render Queue wording fixed.
- **Shortcuts:** Ctrl+1…9 switch workspace (existing); F5 refresh (Projects list / Editor timeline);
  Ctrl+N new project and Ctrl+S save (Projects); Ctrl+Z, Ctrl+Shift+Z / Ctrl+Y undo and redo
  (Editor); F1 lists them (Help → Keyboard shortcuts). Page shortcuts act only on their own page,
  and a focused text box keeps its own editing keys.
- **Tooltips** on the Projects, Editor, wizard, media-card and model-browser controls.
- **Remembered:** window size/position and last workspace (already), and now the console's level
  filter, Follow and Wrap.

- **Connection setup moved into Settings:** the separate Connect workspace is gone. Settings now has
  two tabs, *Backend connection* (the profile, credential and Connect / Test controls, unchanged) and
  *Desktop preferences*. Everything that used to open Connections (the status pill, the Open connection
  settings buttons) now opens Settings on the Backend connection tab, and a saved "Connections"
  last-workspace opens Settings.

## Not done
- Resizable docks/panels and multi-monitor layouts (S6), theme/font selection (S6).
- The offscreen header pill shows "BACKEND OFFLINE" in screenshots because the fake bypasses the
  Connections panel; this is a screenshot artefact, not an app bug.

## Windows acceptance checklist
1. Every dropdown and number box shows an arrow; ticked checkboxes show a tick.
2. Projects: all four toolbar buttons readable at the default size and when narrowed to the minimum.
3. Editor at the minimum window size: nothing overlaps; scroll to reach the edit buttons.
4. Ctrl+Z / Ctrl+Y in the Editor undo and redo a keyframe edit; while typing in the value box, Ctrl+Z
   undoes text instead.
5. Ctrl+N opens the wizard, Ctrl+S saves edited notes, F5 refreshes, F1 lists the shortcuts.
6. Hover the main buttons: tooltips appear.
7. Set the console to Warnings and untick Follow, restart Studio: both are remembered.
8. The rail has no Connect item; Settings has the two tabs. Click the status pill and the Open connection
   settings buttons: each lands on Settings → Backend connection. Connect, restart, and auto-connect still work.
9. Try Windows display scaling of 125% and 150%: no clipped text or overlapping controls.
