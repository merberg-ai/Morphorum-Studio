# S2.2 Projects (branch `feature/studio-s2-2-projects`)

Stacked on `feature/studio-s2-1-dashboard`. Nothing merged. Needs CI plus a physical Windows test.

## What it does
- **Projects page**: list the backend's animation projects, search by name or id, pick one from a
  "Recently opened" list (kept per connection profile), open it, edit **name and notes**, save.
- **Create** (name only; the backend supplies its own valid defaults) and **Move to Trash**
  (confirmed; the backend refuses with 409 while the project is rendering, and that reason is shown).
- **Revision safe**: opening reads the strong ETag; saving sends `If-Match`. A 412 never overwrites:
  the form keeps the user's edits and offers *Reload from backend* or *Keep editing*.
- **Unsaved edits are protected**: prompt on switching project, Reload, New project and window close;
  a reconnect or "backend not responding" state keeps the form and disables the controls.
- Read-only details: frame size, length, mode, model, prompt keyframes, motion layers, source image,
  hybrid video, created/updated, and the five latest renders.

## Safety
- Writes are never retried. An ambiguous create failure (network drop) refreshes the list and warns.
- Saves send only `name` and `notes`; the backend merges partial PUT bodies. Project ids are validated
  against the backend pattern before they reach a URL; request bodies are capped at 256 KiB.
- Results from an older connection or an older selection are discarded.

## Not in S2.2
Editing animation, prompts, camera or model fields (S4/S5), project assets (S2.3), a side-by-side
conflict compare, and any rendering.

## Windows acceptance checklist
1. Projects page, disconnected: explains it, **Open Connections** works.
2. Connected: the list fills; search narrows it; the last project reopens after reconnect/restart.
3. Edit name/notes: "Unsaved changes" appears; Save works; Revert restores.
4. Edit, then pick another project / Reload / close the window: each asks before discarding.
5. Two clients: change the project elsewhere, then Save here: conflict dialog, edits kept, Reload works.
6. New project: appears selected. Move to Trash: it disappears; trashing while rendering shows the reason.
7. Stop the backend mid-edit: form kept, controls disabled; restart: Save works again.
