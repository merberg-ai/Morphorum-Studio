# C4: Maintenance of the managed backend

A **Maintenance** card on Settings > Backend connection, shown once a Morphorum folder is set.

| Control | What it does |
| --- | --- |
| Install line | Version, branch and commit from `data/install.json`. |
| Check for updates | `git fetch` in the folder, then compares with `origin/<branch>`. Also lists the remote branches. Works while the backend runs. |
| Update | Runs the backend's `scripts/update_windows.ps1` (dirty-tree guard, backup, `--ff-only`, rollback). Enabled only when a check found updates, the folder has no local changes and the backend is stopped. Re-checks afterwards. |
| Switch branch | Same script with `-Branch NAME`. Same conditions. |
| Repair | `scripts/repair_windows.ps1` (repair, then doctor). Backend stopped. |
| Health check | `python -m morphorum doctor --json`, shown as OK/PROBLEM lines in the Backend output box. Backend stopped. |
| Cancel | Ends a running update or repair (and its child processes). |
| Remove Morphorum… | Deletes the whole folder after you type its name. Lists folders that probably hold your work (projects, outputs, data, backups, ckpts). Forgets Studio's profile and credential and clears the folder setting. |

## Rules
- Studio never edits backend source itself; it runs the backend's scripts and shows their output.
- Everything that changes the folder is disabled while the backend is running, starting, adopted, or while an install or another job runs. One job at a time.
- Removal refuses: drive roots, the home folder, links, folders containing Studio, and folders that do not look like Morphorum (no backend folder, `.git` or `data/install.json`). Read-only Git files are unlocked before deleting.
- Nothing runs without a click; there are no background update checks.

## Windows checklist
1. With the backend stopped, press Check for updates: note says up to date or N updates; branch list fills.
2. Start the backend: Update, Switch, Repair, Health check, Remove are all disabled; Check still works.
3. Stop it. Health check: the report appears under Backend output; a healthy install says all good.
4. If updates exist: Update runs, the output scrolls, the note says finished and re-checks.
5. Edit a tracked file in the folder, Check: the note warns and Update/Switch stay disabled.
6. Switch branch to another listed branch, then back.
7. Repair on a healthy install finishes without errors.
8. Cancel during an update (backend scripts roll back).
9. Remove on a throwaway install: the dialog needs the exact folder name; afterwards the folder is gone, the panel says No folder, and Connections no longer lists the local backend.
