# Layout step 6: Queue

The `Render Queue` page (shown as **Queue**) is now a live list instead of a placeholder.

## What it shows
- **Image jobs** (the Lab's generations) and **animation renders** in one list. Running and waiting jobs come first
  (oldest first, so the next to run is on top), then the newest finished ones.
- Each row: kind, title (the prompt for an image, "Render <id>" for a render), model or project name, a plain-language
  status line, a progress bar while running, a status chip, and buttons.
- **Cancel** appears only for a job the backend says is running or waiting. **Resume** appears only for a render the
  backend marks resumable. **Open in Timeline** (renders) and **Open in Lab** (images) jump to that workspace.
- Filters: All, Running and waiting, Finished. A summary shows the counts. F5 or Refresh reloads.
- Refreshes every 3 seconds while anything is running and every 15 seconds otherwise, only while the page is open.

## Limits (the backend has no endpoint for them)
- There is no cross-project render list, so renders come from the 12 most recently updated projects' own lists.
  Older projects' renders appear once their project is among the recent ones.
- No reordering, priority or pause: the backend has none.
- A source the backend does not advertise (image generation, animation renders) is simply not read.

## Windows acceptance checklist
1. Open Queue while idle: finished jobs and renders are listed, newest first, with the counts on the right.
2. Start an image generation in the Lab and a render from the Timeline; switch to Queue: both appear at the top with
   moving progress bars.
3. Cancel one: the row says "(cancelling…)" and then shows Cancelled. Cancel on a finished job is not offered.
4. An interrupted or failed render shows Resume; pressing it starts it again.
5. Open in Timeline / Open in Lab switch workspaces (Timeline opens that render's project).
6. Filters narrow the list; F5 reloads; disconnecting shows the connection message instead of a list.
7. At 880 × 560 the rows stay readable and the list scrolls.
