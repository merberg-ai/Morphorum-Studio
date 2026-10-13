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
- [x] Add user-provided Morphorum desktop logo in repository-approved reduced-resolution asset, without changing its artwork.
- [x] Splash with progress *stages* for actual startup work; never fabricate percentage or stall on network.
- [x] Main window shown as soon as GUI is ready; background auto-connect must not block splash dismissal.
- [ ] Windows high-DPI/slow backend smoke tests (beyond prior physical Windows splash acceptance).

## P4: optional startup reconnect (after P3 acceptance)
- [x] If opted in, connect last successful profile on launch using stored OS-keyring token.
- [x] Preserve HTTP LAN trust consent appropriately, avoid an unattended security bypass.
- [ ] Fail safely on missing/revoked credentials or unfamiliar backend instance.
- [ ] No GPU backend process startup/shutdown and no duplicate job POST.
- [ ] Windows physical pass + exact-commit Ubuntu/Windows CI, then checkpoint.

## Operating rules
Keep changes on `dev-ui`; make small code/test increments and run GitHub Actions on each. Physical acceptance after each pass. No auto-merge to Studio `main`, and no backend `main` merge. After polish acceptance proceed to S2.1.

## P2 candidate notes

P1 visual changes accepted by user. P2 implemented on dev-ui, pending exact-commit CI and Windows physical acceptance. Uses OS-native QSettings for only non-secret window/session preferences; no bearer tokens stored. Auto-connect and splash switches appear now, but their actual startup behaviors are reserved for P4 and P3. Last selected and last successful connection IDs are separate values. Geometry is restored only if enabled; maximize state and last workspace are remembered. If restoring a disconnected-monitor position, window geometry is moved onto an available screen. No implicit network connection occurs in P2.

## P2 physical feedback and targeted P4 activation (2026-10-12)

User verified window size/maximized persistence and Settings checkbox persistence on Windows. User identified two missing behaviors: auto-connect setting was inert pending P4, and trusted HTTP permission was cleared every time a profile was saved. Implemented early P4 startup auto-connect on `dev-ui`, using the last **successful** profile and QTimer to start after GUI setup. Saved HTTP permission is stored as nonsecret QSettings metadata bound to both profile ID and exact backend URL; changed URL/profile must be explicitly re-approved. Saving a checked box now persists it across runs, and automatically connecting with an unapproved HTTP destination stops safely without prompting at startup. Credentials remain in OS keyring. Actual P4/permission Windows verification and exact-commit CI are still pending. No splash implemented yet: P3 follows physical acceptance of this fix.

## P2 Windows acceptance (2026-10-12)

**User reports PASS:** Saved trusted-HTTP permission persists across profile save/restart and startup auto-connect now reconnects as configured; window size/state and Settings checkbox persistence had already passed. Windows/Linux CI for fix commit `3d0ffbe2260433ef43c17c063bea158fc955e07e` both succeeded. P2 plus early P4 behavioral fixes physically accepted. Proceed with P3 branded startup splash. 

## P3 splash implementation candidate (2026-10-12)

Code committed on dev-ui: `ui/splash.py` implements a 560x430 QSplashScreen, with three stage-driven progress-bar updates and concise status labels during actual startup work. GUI appears immediately after initialization; background auto-connect remains asynchronous and never holds splash open. `app.py` respects the persisted `show_splash` toggle. A 410x308 maximum logo view is applied with smooth scaling. The code looks for user logo at `assets/morphorum-studio-logo.png` relative to repository root; if missing, a compact text-only fallback displays. **Logo bytes are not yet bundled in GitHub**, so image-branded splash physical acceptance remains pending. CI and actual Windows testing also remain pending. Keep P3 unaccepted until the asset and test are verified.

## P3 Windows physical acceptance (2026-10-12)

**PASS by user report:** branded splash works as expected after manually placing the approved user logo at `assets/morphorum-studio-logo.png`. Both Windows and Ubuntu CI passed on code/docs commit `f16f65edfb0a5a3f546a110ab4c1cd68a5e5aae8`. The tested startup behavior is accepted, but the logo file itself is still **not committed** to the repository. A fresh clone without the manual asset shows text fallback; bundling and packaged-resource lookup remain a follow-up before shipping. Do not mark the logo packaging task complete or start S2.1 until final pre-S2 polish is finished.

## Final pre-S2 code packaging checkpoint (2026-10-12)

Optimized source artwork committed as `assets/morphorum-studio-logo.jpg` and included in Python wheel at `src/morphorum_studio/assets/splash-logo.jpg`. Splash uses `importlib.resources`, not an absolute/source-checkout-only assets path. `scripts/verify_clean_install.py` builds a wheel, installs in an isolated venv with OS dependencies exposed, verifies bundled JPEG signature and loads it through Qt. Both Windows and Ubuntu GitHub Actions **passed on exact commit `aa7e7988e30f4d332699a5f74eebd3a9fcec3022`** (35 tests plus wheel smoke check). Immutable code checkpoint `checkpoint/studio-pre-s2-polish-ci-verified-20261012` points to that SHA. Prior Windows user physical acceptance covers UI/control polish, persisted options, secure reconnect, and splash with manual supplied logo. Bundled reduced-size JPEG is CI-verified, but the user has not yet personally inspected the reduced artwork on Windows; do not claim an additional post-bundle physical test. Do not merge Studio or backend main until user explicitly authorizes.
