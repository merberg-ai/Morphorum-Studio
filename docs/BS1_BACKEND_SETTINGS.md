# BS1: Backend settings in Studio

Branch `feature/studio-bs1-backend-settings`, based on `dev-connections`. Settings gets a **Backend settings** tab for
the connected backend (managed or remote). It offers the settings the Morphorum web UI edits, read from the backend's
own `GET /api/settings` response, so it never shows a control the backend cannot serve.

## What is editable
| Area | Backend keys | Notes |
|---|---|---|
| Model folders | `models.<family>.checkpoints`, `models.<family>.loras` | One card per family and kind the backend reports in `model_families` (SDXL, Flux checkpoints and LoRAs; Z-Image LoRAs). One text box per folder list, one folder per line. **Check folders** asks the backend about each one; **Add folder…** opens a folder chooser (only when the backend is on this PC). |
| Managed model storage | `managed_models.locations.<family>` | Z-Image today. Relative paths resolve inside the backend's install folder. |
| Memory and performance | `performance.unload_after_generation`, `performance.sdxl_vae_tiling` | Two checkboxes with the web UI's wording. |

Not shown, on purpose: the web page's own look (theme, fonts, scale, preview count), which only affects that page, and
`server.*` (host, port, LAN, token), which the web UI does not edit either. LAN exposure arrives with C3 as a start option
with a warning; the access token is never displayed.

## Behaviour
- The tab loads when opened while connected; **Reload** re-reads. Disconnecting or switching backends clears it.
- **Save** sends only what changed (`PUT /api/settings`, which merges) and shows the backend's folder checks. Empty rows
  are ignored. **Revert** discards edits. Reload and Rescan are disabled while there are unsaved edits.
- **Rescan models** (`POST /api/models/scan`) applies folder changes and reports how many models were found, plus warnings.
- Paths belong to the backend's computer; the page says so. A remote backend gets text boxes only.
- Failures show the backend's reason in the status line.

## Files
`backend/backend_settings.py` (parse, minimal update, API), `ui/backend_settings_service.py`,
`ui/backend_settings_page.py`, `ui/settings_page.py` (new tab), `tests/test_backend_settings.py`,
`docs/BACKEND_PROPOSALS.md` (P8: advertise the settings API and give clients a safe subset).

## Windows checklist
1. Connected to the managed backend: Settings > Backend settings shows SDXL, Flux and Z-Image cards matching the web UI.
2. Add a models folder with **Add folder…**, **Check folders** (OK: … Folder found), **Save**, then **Rescan models**: Image Lab lists the models.
3. Type a folder that does not exist: Check says so; Save still works (the web UI allows it) and the card shows Problem:.
4. Toggle both memory options, Save, open the web UI settings page: the same values appear. Revert discards unsaved edits.
5. Connect to a remote backend: no Browse buttons; everything else works.
6. Disconnect: the tab says to connect. Reconnect: Reload fills it.

## Known gaps
- Folder lists are plain text boxes (one folder per line). A per-row editor with Remove buttons crashed the Windows test
  process at exit whenever more than one card with dynamic rows existed, and bisecting CI did not isolate why, so the page
  uses the simpler widgets.
- Text boxes carry a tooltip but no accessible name. The S6 accessibility step should label them with a visible label and
  buddy.
