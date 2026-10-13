# Pre-S2 Studio UI/behavior polish

**Working branch:** `dev-ui`, branched from S1 accepted development HEAD `ed5ede962db2e2a2f249581e5ecc6a853ad3fae5`. This baseline passed Ubuntu + Windows CI. Last user-reported physical tests: initial authenticated LAN connection, reconnect after backend stop/start, boot ID change and manual disconnect; disposable revoked-token test subsequently reported PASS. The changed-instance scenario is tested by mock; do not claim physical acceptance with a second real server.

**Scope lock:** Do not start S2.1 telemetry/model discovery until this pre-S2 work is physically accepted. Studio `main` and Morphorum backend `main` remain unchanged.

## P1: theme and controls (first working increment)
- [x] Unified native styling for QPushButton, QLineEdit, QComboBox, QCheckBox, scrollbars and group cards in graphite/cyan/violet theme.
- [x] Primary/destructive action distinction on Connections.
- [ ] Windows visual/interaction acceptance across Home/Connections/Settings, hover/focus/high DPI, text clipping.
- [ ] Refine spacing/controls from real screenshots before checkpoint.

## P2: persist desktop state (after P1 acceptance)
- [x] `QSettings` service for nonsecret application options; credentials remain in OS keyring.
- [x] Restore size/position/maximized state, clamp offscreen windows when monitor layout changes.
- [x] Restore last selected workspace and last used profile.
- [x] Save last **successful** backend profile separately from last **selected** profile.
- [x] Native Settings toggles: splash, restore geometry, restore workspace, auto-connect (default off).

## P3: branded splash screen (after P2 acceptance)
- [ ] Add user-provided Morphorum desktop logo in repository-approved reduced-resolution asset, without changing its artwork.
- [ ] Splash with progress *stages* for actual startup work; never fabricate percentage or stall on network.
- [ ] Main window shown as soon as GUI is ready; background auto-connect must not block splash dismissal.
- [ ] Windows high-DPI/slow backend smoke tests.

## P4: optional startup reconnect (after P3 acceptance)
- [ ] If opted in, connect last successful profile on launch using stored OS-keyring token.
- [ ] Preserve HTTP LAN trust consent appropriately, avoid an unattended security bypass.
- [ ] Fail safely on missing/revoked credentials or unfamiliar backend instance.
- [ ] No GPU backend process startup/shutdown and no duplicate job POST.
- [ ] Windows physical pass + exact-commit Ubuntu/Windows CI, then checkpoint.

## Operating rules
Keep changes on `dev-ui`; make small code/test increments and run GitHub Actions on each. Physical acceptance after each pass. No auto-merge to Studio `main`, and no backend `main` merge. After polish acceptance proceed to S2.1.

## P2 candidate notes

P1 visual changes accepted by user. P2 implemented on dev-ui, pending exact-commit CI and Windows physical acceptance. Uses OS-native QSettings for only non-secret window/session preferences; no bearer tokens stored. Auto-connect and splash switches appear now, but their actual startup behaviors are reserved for P4 and P3. Last selected and last successful connection IDs are separate values. Geometry is restored only if enabled; maximize state and last workspace are remembered. If restoring a disconnected-monitor position, window geometry is moved onto an available screen. No implicit network connection occurs in P2.
