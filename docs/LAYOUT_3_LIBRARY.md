# Layout step 3: Library

The Projects page is now the **Library** (display name and page title; the page key `Projects` is unchanged).

## What changed
- **Three tabs**: Projects, Models, LoRAs.
- **Projects** opens on a **thumbnail grid** (up to 24 most recently updated): preview from the project's latest
  rendered frame, size/fps/length, status chip. The grid re-flows from 1 to 5 columns with the window width and has
  its own search, New project, Import Deforum and Refresh. Click a tile to open the existing detail view (name,
  notes, assets, render card, recent renders); **‹ All projects** goes back. Unsaved edits are still protected by the
  existing prompt. New and imported projects, and tiles on Home, open straight into the detail view.
- **Models** and **LoRAs** show what the backend has indexed as a grid with a family filter and search. Models are
  read-only. Clicking a LoRA opens the existing inspector (including the opt-in Civitai lookup) on that LoRA.
  They load on first use and reload when the connection changes. The old "Models and LoRAs…" button still works.
- Nothing the backend does not report is shown: sizes show `—` when absent, a project with no render says "No render yet".

## Windows acceptance checklist
1. Library opens on the grid; tiles show thumbnails for projects that have rendered frames.
2. Type in the grid search: tiles filter. Resize the window: columns change; nothing overlaps at 880 px wide.
3. Click a tile: the detail view appears with that project; **‹ All projects** returns to the grid.
4. Edit a name without saving, go back, click another tile: you are asked before discarding.
5. New project creates and opens in detail; the grid shows it after the next refresh (or Refresh).
6. Models tab lists checkpoints; LoRAs tab lists LoRAs; family filter and search work; clicking a LoRA opens the inspector.
7. Disconnect: grid and tabs show a plain message instead of stale data.
