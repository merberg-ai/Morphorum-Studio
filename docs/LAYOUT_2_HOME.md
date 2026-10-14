# Layout step 2: Home

Home now follows the mockup's structure on top of the live dashboard cards.

## What changed
- **Hero** with New project, Open project and Generate image. They open the wizard in Library, the Library, and Lab.
- **Recent projects**: the six most recently updated projects as tiles. Each tile shows a thumbnail from the
  project's latest rendered frame, size/fps/duration (only what the backend reported), and a status chip
  (Draft, Queued, Rendering, Rendered, Failed, Cancelled, Interrupted). Click or press Enter to open it in Library.
  A project that has never rendered shows "No render yet".
- **Render queue** card: the newest render of each recent project. The backend has no cross-project jobs list,
  so this is "recent projects", not every job on the backend; it says so on the card.
- The Backend / GPU / System / Models cards are unchanged below. Not built because the backend does not report
  them: power draw, uptime. The VRAM ring and model family chips are left for a later visual pass.

## How it loads
`RecentProjectsService` lists projects, reads each recent project's render list, and downloads the latest frame
once per (render, frame). Frames are scaled to a 360 px PNG off the GUI thread and kept in memory. It refreshes
every 15 s while Home is showing and stops when you leave; one project's failure never hides the others.

## Windows acceptance checklist
1. Connected: the hero shows; the three buttons go to the wizard, Library and Lab.
2. Recent projects shows tiles newest-first; projects with renders show a thumbnail of their last frame.
3. A project that is rendering shows a blue "Rendering" chip and appears at the top of the Render queue card.
4. Click a tile: Library opens with that project selected. (With unsaved edits you are asked first.)
5. Start a render, return to Home: within ~15 s the chip and queue card update.
6. Backend without project support, or offline: the recent/queue sections are hidden or the old connect card shows.
7. Resize to 880 wide: tiles stay readable (three across at 1200).
