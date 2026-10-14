# C3: lifecycle polish for the managed backend

Branch `feature/studio-c3-lifecycle`, based on `dev-connections`. Five changes to how Studio runs its own backend.

## 1. The backend ends with Studio (Windows job object)
Studio creates a Windows job object with *kill on close* and puts the backend process in it as soon as it has a process id.
If Studio exits or crashes, Windows closes the job and ends the backend and everything it started. If the process cannot
be placed in the job (an environment that forbids nesting), the Backend output says so and Studio carries on; stopping
from Studio still works. Other systems do nothing here. A backend left by an *older* Studio or started by hand is still
recognised through the run record and is only ever connected to, never killed.

## 2. Crash recovery
If a backend that was running stops unexpectedly, Studio starts it again after 2, 5 and 15 seconds (three tries), reconnects
when it is ready, and says so in the status ("Starting it again in 2 s (attempt 1 of 3). Jobs that were running were
interrupted."). Rules:
- Only a backend that had been running. A start that fails stays failed, with the log, so a broken install never loops.
- Running steadily for 60 seconds gives the budget back. Pressing Start (or Restart) gives it back too.
- Stop, or choosing a different folder or port, cancels a pending restart.
- Setting: **Start the backend again if it stops unexpectedly** (on by default).

## 3. Port conflicts
When the port belongs to another program, the status names it on Windows ("python.exe (PID 4242)", from `netstat` and
`tasklist`, looked up off the UI thread). **Use a free port** moves Studio's backend and its connection to the next free
port. Studio never stops a program it did not start.

## 4. Let other computers connect (LAN)
Off by default. Turning it on shows a confirmation that explains plain HTTP and trusted networks only. The backend is then
started with `--host 0.0.0.0` (the backend's own `serve --host` option, so no backend change was needed). The page shows the
address other computers would use. Studio's own connection stays on `127.0.0.1`. Other computers need credentials of their
own; Studio does not hand out its own. The option is fixed while the backend runs and applies at the next start.

## 5. Status in more places
- **Home:** a "Local backend" strip with state, details, Start/Stop and a Settings link.
- **Footer:** "Local backend: Running" (click to open the settings).
- **Header:** while no connection is up, the host chip reads "Local backend · Stopped / Starting / Stopped unexpectedly".
Everything stays hidden until a Morphorum folder is set up for Studio to manage.

## Files
`backend/winjob.py`, `backend/managed.py` (LAN command and address, port-owner parsing, new settings),
`ui/managed_backend.py` (job, restarts, owner lookup), `ui/managed_panel.py` (settings, free port),
`ui/managed_status.py` (strip and chip), `ui/main_window.py`, `ui/home_page.py`, `tests/test_managed_lifecycle.py`.

## Windows checklist
1. Start the managed backend, then end Studio with Task Manager (End task on `python`... of Studio, not the backend). The backend
   process disappears within a second. Start Studio again: it starts a fresh backend.
2. With the backend running, end its `python.exe` from Task Manager: Studio says it stopped unexpectedly, restarts it after about
   2 s, reconnects, and the footer returns to Running. Kill it three times in a row: after the third it stops trying and says so.
3. Press Stop: no restart. Untick the restart option, kill the backend: it stays down.
4. Start any program on port 7866 first (for example `python -m http.server 7866`), then press Start: Studio names the
   program, **Use a free port** switches to 7867 and starts. The profile's address follows.
5. Tick **Let other computers on my network connect**: the warning appears; Cancel leaves it off. Allow, start the backend:
   Windows may ask about the firewall. From another computer, `http://<this PC's address>:7866/api/client/capabilities`
   answers 401 without a credential.
6. Home shows the Local backend strip with Start/Stop; the footer shows the state; with the backend stopped, the title bar says
   "Local backend · Stopped".
