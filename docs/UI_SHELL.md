# UI shell and design foundation

Branch: `feature/studio-ui-shell` (stacked on `feature/studio-s1-hardening`). Implements the approved
dark-only design mockup (ComfyUI/Runway mix). No backend behaviour changed.

## Pieces
- `ui/tokens.py`: every colour, radius and font name; `build_stylesheet(tokens)` fills the QSS template.
  A second theme later is another `Tokens` instance. QSS limits: no `letter-spacing`, no variables, rgba alpha is 0-255.
- `ui/fonts.py` + `assets/fonts/`: Sora, Geist, Geist Mono (SIL OFL, licence files shipped). If a font fails to load the
  stylesheet falls back to Segoe UI.
- `ui/icons.py`: inline-SVG stroke icons rendered at the device pixel ratio, with normal/checked/hover colours.
- `ui/shell.py`: `TitleBar` (brand, File/View/Help menus, connection pill, window controls; drag and double-click use
  `startSystemMove`), `NavRail` (icon rail, API-compatible with the old list: `count/currentRow/setCurrentRow/currentRowChanged`).
- `ui/frameless.py`: edge/corner resize via `startSystemResize` (native cursors and snapping).
- `ui/splash.py`: repainted splash using the transparent brand mark.
- Assets: `logo-mark.png` (transparent, luminance-keyed from the original PNG, intended for dark surfaces),
  `app-icon.png/.ico` (dark rounded tile). A true vector logo needs a designer or a manual trace.

## Deliberately not built yet
Lab/Graph/Timeline screens matching the mockups (see `LAYOUT_1_SHELL.md` and `docs/design/`), extra themes. The Ctrl K palette and host/footer status arrived in layout step 1.

## Windows acceptance checklist (physical test)
1. Window shows no native title bar; custom bar shows mark, menus, connection pill, controls.
2. Drag the title bar; double-click maximizes/restores; Win+Arrow and drag-to-edge snapping work.
3. Resize from all four edges and corners; cursors change.
4. Maximized window respects the taskbar and does not overlap it.
5. Minimize to the taskbar and restore. Close button closes cleanly.
6. Rail switches workspaces; Ctrl+1..9 shortcuts; View menu mirrors them; pill click opens Connections.
7. Fonts render as Sora/Geist (not Segoe UI) and the splash shows the mark and gradient progress bar.
8. Connections panel behaves exactly as before (connect, disconnect, token import).
