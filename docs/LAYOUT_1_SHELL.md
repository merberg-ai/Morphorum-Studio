# Layout step 1: Shell

First of the layout-matching steps (see `docs/design/`). Only the chrome changes; every page behaves as before.

## What changed
- **Rail names** follow the mockups: Home, Library, Lab, Timeline, Graph, Queue, Console, Settings. These are
  display names only (`DISPLAY` in `main_window.py`); the page keys (`Projects`, `Image Lab`, `Editor`,
  `Motion Lab`, `Render Queue`) and rail order are unchanged, so saved workspaces still restore.
  Graph is still a placeholder until S5.
- **Ctrl+K command palette** and a search button in the title bar: go to any workspace, New project,
  Refresh, Backend connection settings, Keyboard shortcuts, About. Type to filter, Up/Down, Enter, Esc.
- **Host chip** beside the status pill: `profile · host:port · N ms` while connected (N is the last
  telemetry round trip), hidden when offline.
- **Live footer**: `VRAM used/total`, `GPU %` (first GPU), and `Queue` (idle, or the status of the render
  this Studio is watching) on every page. Telemetry now polls while connected, not only on Home. Missing
  values show `—`, never a guess. Queue covers only the render Studio is following; a cross-project
  queue arrives with the Queue page.

## Windows acceptance checklist
1. Rail tooltips and View menu show the new names; Ctrl+1…8 still switch pages.
2. Click the title-bar search (or press Ctrl+K): palette opens centred; typing filters; Enter runs; Esc closes.
3. "Go to Timeline" opens the old Editor; "New project" opens the wizard in Library.
4. Connect a backend: host chip shows profile, address and a millisecond figure; disconnect hides it.
5. Footer shows VRAM and GPU on every page (not just Home) and updates every few seconds.
6. Start a render: footer Queue shows its status, then idle when done.
7. Narrow the window to the minimum (880 wide): bar does not overlap; the search button and chip fit.
