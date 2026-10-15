# C1: Simple mode, manage an existing Morphorum folder

Settings > Backend connection now has two views:

- **Simple:** Studio runs a Morphorum backend on this PC and connects to it.
- **Advanced:** the connection manager as before (connect to a backend that is already running, on this PC, another PC or the
  LAN). Nothing about it has changed. A new install starts in Simple; anyone who already saved a connection starts in
  Advanced. The choice is remembered, and switching view never disconnects.

C1 manages a Morphorum folder that is **already installed**. There is no install button yet (that is C2), and Studio shows no
control it cannot honour.

## What Simple mode does
- **Choose folder:** the folder must contain `backend\morphorum` and the `.venv` Python environment. Anything else is explained.
- **Start and connect:** Studio creates a revocable client credential with the backend's own `clients issue` command the first
  time (valid 365 days, the backend's maximum), keeps it in the OS credential store, starts
  `python -m morphorum serve --host 127.0.0.1 --port <n> --backend-only`, waits for the port to open, then connects through the
  same connection code as Advanced mode. The one-time token file Studio asks for is deleted as soon as it is read.
- **Stop / Restart:** only for a backend Studio started in this session. Stopping asks first if jobs are running.
- **Reset credential:** replaces Studio's credential (use it if the backend says the credential was rejected).
- **Backend output:** a collapsible log of the process output.
- **Port** (default 7866) and **Stop the backend when Studio closes** (default on). Closing Studio with jobs running asks:
  stop it, keep it running, or cancel.
- The backend listens on loopback only. LAN exposure is not offered in this step.

## Safety rules kept
- Studio only stops a process it started. A backend left running by an earlier Studio session is recognised from a run record,
  shown as "Already running" and can be connected to, but Studio does not kill it because it cannot positively identify the process
  (a later step will tie the backend to Studio with a Windows job object so none are left behind).
- A port used by some other program is reported ("Port in use"); pick another port.
- The credential never goes in profile files, settings or the log.
- Studio never auto-connects to the managed backend silently.

## Where things are saved
Studio's config folder (next to `connections.json`): `managed.json` (folder, port, stop-on-exit, profile id) and
`managed-run.json` (the backend Studio started: folder, port, process id). The managed connection is a normal profile with
`kind: "managed"` that Advanced mode does not list.

## Known limits (by design for C1)
- No install, update, repair, branch switch or removal yet (C2 and C4).
- The log is in the Simple panel, not the Console page. Once connected, the Console page shows the backend's own events.
- Stopping on Windows ends the process directly (a console service has no window to close); graceful shutdown comes with the job
  object in C3.

## Windows acceptance checklist (use `D:\Morphorum-test`)
1. Settings > Backend connection shows **Simple** and **Advanced**. With a saved connection you land in Advanced; check both views.
2. Simple: **Choose folder** `D:\Morphorum-test`. The note says "Morphorum <version> found" and Start is enabled. A wrong folder
   (for example Documents) is rejected with an explanation.
3. **Start and connect** with no other backend running: it creates a credential, starts the backend (no console window), the chip
   goes Starting then Running, and the status line says Connected. Home and the other pages work.
4. **Backend output** shows the server lines and never prints a token.
5. **Stop**: the chip goes Stopped and Studio shows as disconnected. **Start and connect** again works; **Restart** works.
6. Start again, then close Studio (default setting): the backend stops (no leftover python.exe in Task Manager).
7. Turn off "Stop the backend when Studio closes", start, close Studio: the backend keeps running. Reopen Studio: Simple shows
   "Already running"; **Connect** works; Stop is disabled with the explanation.
8. With a backend already running on 7866 that Studio did not start: Simple shows "Port in use"; changing the port enables Start.
9. Advanced still connects to your usual saved backend exactly as before and does not list the managed profile.
10. Windows Firewall does not prompt (loopback only).

## Opening Studio with the managed backend (C1b)
If the backend you used last is the Studio-managed one, Studio brings it up while the splash screen is showing, so the window
opens already connected:

1. Studio checks the managed folder and what is on the port.
2. If nothing is running it starts the backend (creating a credential first if there is none); if a backend from an earlier
   session is still running it connects to it; if something else owns the port, or the backend crashes, it stops waiting.
3. The splash shows the real step ("Starting the local backend…", "Preparing the backend credential…", "Connecting to the local
   backend…") and the window appears once Studio is connected. The wait is capped at about 100 seconds.
4. If it could not be done, the window opens on Settings > Backend connection > Simple, which shows the reason and the Start button.
   Nothing is retried in a loop.

It only happens when the managed backend was the last one you connected to (connecting to a remote backend changes that), and
it can be turned off with **Start the backend and connect when Studio opens** in the Simple view (on by default). With the
splash turned off in Desktop preferences there is nothing to wait behind, so the window opens at once and the backend comes up
in the background.

### Added to the Windows checklist
11. Close Studio with the managed backend running (stop-on-close on). Reopen: the splash says "Starting the local backend…", then
    the window opens connected, with no clicks needed.
12. Close Studio with stop-on-close off, then reopen: the splash finds the running backend and connects; Stop stays disabled.
13. Put another program on the port (or start the backend by hand on 7866) and reopen: the window opens on Settings showing "Port in use".
14. Untick "Start the backend and connect when Studio opens", reopen: the window opens at once and stays disconnected.
15. Connect to a remote backend in Advanced, close, reopen: the managed backend is not started.
