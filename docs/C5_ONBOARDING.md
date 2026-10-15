# C5: First-run onboarding

Home (not connected) is now a "Get started" card:
- **Run Morphorum on this PC** opens Settings > Backend connection in Simple mode (install, start, stop by Studio).
- **Connect to a backend I already have** opens it in Advanced mode.
- "Open connection settings" stays as the plain link. The choice is remembered like the Simple/Advanced toggle.

Home (connected) shows a notice in the Models card when the backend has no indexed models: **Choose model folders**
opens Settings > Backend settings, where saving folders rescans automatically (BS2). The notice disappears once models exist.

The hand-off uses only the settings API Studio already uses (BS1), so nothing new is asked of the backend.

## Windows checklist
1. Fresh profile (no saved connections): Home shows the two choices. Simple opens the local-backend panel; Advanced opens the remote profile list.
2. After a connection exists, Home shows the normal dashboard.
3. Connect to a backend with no models indexed: the Models card shows the notice; the button opens Backend settings.
4. Add a folder, save: models appear and the notice goes away on Home.
