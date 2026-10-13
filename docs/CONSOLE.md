# Live console (branch `feature/studio-console`)

Branched from `dev-ui` after the S3.3 merge. Nothing merged. Needs CI plus a Windows check.

## What it does
The **Console** page shows the backend's log live:
- On connect, Studio reads the backend's recent history (`/api/console`) once, then follows the
  server-sent-event stream (`/api/console/stream`) from the last id it has. The stream runs for as
  long as you are connected, so history is already there when you open the page.
- Why a stream, not polling: every API call (including a console poll) is itself logged by the
  backend, so polling would fill the backend's 1500-line buffer with its own traffic.
- **Gaps and restarts are shown, not hidden.** If the backend dropped lines before Studio read them,
  or restarted, a cyan marker says so. If the connection drops, Studio reconnects with backoff
  (1, 2, 4, 8, 10 s) and resumes from the last id; the marker "stream interrupted; reconnecting…"
  appears in the log.
- **Controls**: level filter, category filter (filled in as categories appear), text search, Follow
  (auto-scroll), Wrap, **Clear view** (Studio's copy only; the backend's buffer is untouched), **Copy**
  and **Save…** (both use the current filter).
- Studio keeps up to 5000 lines; the backend keeps its own 1500.
- Authentication problems stop the stream with a message instead of retrying forever.

## Windows acceptance checklist
1. Connect: the Console page shows recent backend lines and "Live".
2. Trigger an action (Refresh on Home, start an Image Lab job): lines arrive within a second or two,
   colour-coded by level.
3. Filters: Warnings and up, a category, and search narrow the view; Copy/Save contain only what is shown.
4. Disconnect the LAN briefly: marker "interrupted; reconnecting…", then lines resume without
   duplicates after the LAN returns.
5. Restart the backend: marker "The backend restarted; the console starts over.".
6. Closing Studio exits promptly.
