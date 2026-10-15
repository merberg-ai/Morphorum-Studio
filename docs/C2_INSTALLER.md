# C2: install the managed backend from Studio

Branch `feature/studio-c2-installer`, based on `dev-connections`. Simple mode can now **install** Morphorum into the
managed folder, then start it and connect, with no console window.

## What it does
1. The **Install Morphorum** card shows whenever the chosen folder is not an installed Morphorum (or while an install
   runs). With no folder chosen, the target is `<Studio folder>/morphorum-backend`.
2. The card lists what will happen and needs the tick-box **I agree to install Morphorum into this folder**. Nothing
   runs without it.
3. **Preflight** (`managed.preflight`) runs first and blocks with a plain reason: not Windows, relative path, drive root,
   a file, a non-empty folder that is not a Morphorum checkout, no write access, less than 8 GiB free (not for a resume),
   bad port or branch. Warnings (long path, other drive, port in use) are shown but do not block.
4. Studio downloads `scripts/bootstrap.ps1` for branch `main` from `raw.githubusercontent.com/merberg-ai/Morphorum`
   (https only, 512 KB cap, must contain `InstallDir`), then runs
   `powershell -NoProfile -ExecutionPolicy Bypass -File bootstrap.ps1 -InstallDir <folder> -Branch main -Port <port>`.
   Every answer is given up front and stdin is closed, so the installer cannot wait on a question.
5. Output streams to **Backend output** (opened automatically). The current section (`>> NAME`) is shown above an
   indeterminate bar. `\r` progress lines from pip are split into lines.
6. Success needs exit code 0, no `INSTALLATION FAILED`, and `check_folder` to pass. Then Studio runs the normal
   start path: create the revocable credential, start the backend, connect.
7. **Cancel install** ends the installer and everything it started (`taskkill /T /F`). **Resume install** appears when
   an unfinished checkout exists; the backend's bootstrap continues it (`git pull --ff-only`, then `install.bat`).
8. Closing Studio during an install asks first, then cancels it.

## Safety
- Studio writes only inside the chosen folder. Git and FFmpeg may be installed system-wide by the backend's own installer
  through winget, and the consent text says so.
- The branch is validated (`[A-Za-z0-9._/-]`, no `..`) before it reaches a command line; arguments are passed as a list.
- The downloaded script is saved under Studio's config folder (`install/bootstrap.ps1`), never executed from a temp name.
- Install is disabled while the backend runs, and choose-folder/port are locked during the install.

## Not in C2
Backend branch switch, update, repair and remove (C4); Windows job object and crash recovery (C3); first-run flow (C5).
See `BACKEND_PROPOSALS.md` P7 for installer changes that would make progress and errors better.

## Windows checklist
1. Settings > Simple with no folder: the Install card shows; **Install Morphorum** is disabled until the box is ticked.
2. Tick it and install into the default folder. Output opens; the section name updates; no console window appears.
3. A winget prompt or UAC dialog for Git/FFmpeg (only if missing) may appear; accept it.
4. At the end the card disappears, the backend starts, the chip shows Running and Studio connects. Open **Home**.
5. Quit and reopen: the splash starts the backend and connects (C1b behaviour).
6. Start another install, **Cancel install** after a minute: the output stops, no python/pip/git process remains in
   Task Manager. Install again: it says Resume and continues.
7. Choose a non-empty unrelated folder and try to install: blocked with a plain reason, nothing written.
8. Unplug the network and install: fails with a message; Install again after reconnecting works.
9. Close Studio during an install: it asks; confirming cancels the install and closes.
