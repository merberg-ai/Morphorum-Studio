# S5.4: Project Settings, Responsive Layout and UX Completion

**Status:** In progress on `feature/studio-s5-4-project-settings` (branched from `dev-ui`). Keep Studio `main`, `dev-ui`, and immutable checkpoints unchanged pending Windows acceptance and explicit integration.

## User-approved scope

1. **Responsive layouts:** All cards, controls, navigation, toolbars and inspectors should adapt to wider and smaller desktop windows and high-DPI scaling, avoiding clipping/overlap and preserving scroll access.
2. **Settings reorganization:** Distinguish Studio appearance/preferences, connections, managed local backend, backend configuration and advanced settings.
3. **Model paths:** Replace multiline backend model-directory input with individual single-line path fields, supporting multiple paths via explicit add/remove. Preserve remote-vs-local folder-selection semantics and validation.
4. **Backend feedback:** Shared non-blocking toast notifications for confirmations, warnings, errors and information. Add spinners or progress/busy indicators immediately on network operations; prevent duplicate submissions; report failure and timeouts.
5. **Console:** Hide routine API access logging by default, persist an explicit Show API requests toggle, preserve failures/warnings, and reflow the toolbar.
6. **Project settings:** Expand the new-project flow and add editing for existing projects. Expose model-aware sampler, diffusion steps, guidance, denoise strength/noise, seed behavior, cadence, temporal, mode-specific 2D/3D, and hybrid settings as supported by the backend. Retain advanced timeline schedule editing.
7. **Integrity:** Follow the backend's project template/capabilities, validate before writing, preserve ETag-based revision safety and avoid silent timeline-track divergence.

## Sequence

- **S5.4a Responsive foundations/settings:** audit fixed sizes, reflow panels, reorganize settings and folder paths.
- **S5.4b Feedback:** shared toasts, spinner/busy treatment and operation result messages.
- **S5.4c Console:** request-log filtering, persistence, responsive toolbar, tests.
- **S5.4d Project settings:** creation wizard, existing project editor, model-aware fields, tracked schema updates and validation.
- **S5.4e Verify/integrate:** CI (Ubuntu/Windows), physical Windows resizing and real backend test, docs/checkpoint, then review merge to `dev-ui`.

## S5.4a implementation progress (2026-10-14)

- Converted external checkpoint/LoRA directory lists to distinct single-line entries, with Add folder, Remove, Check folders and local-only Browse. An empty row is not persisted.
- Removed the model settings content column's old narrow width cap; cards can expand with the Settings page.
- Backend settings footer and Console filters/actions switch from rows to vertical stacks in compact windows.
- Updated the existing backend settings tests for per-path entries and Browse behavior.
- **Remaining in S5.4a:** application-wide responsive audit (Library, Timeline, Image Lab, Graph, managed backend, other settings), improved Settings information architecture, physical window/scaling acceptance. Do not represent this as completed responsive support.

## S5.4b physical-test fix: save acknowledgement and floating toast

- Windows screenshot exposed a misleading **Could not save: The backend did not describe its model families** after settings had persisted. Morphorum GET returns model_families; successful PUT returns status/settings/validation without model_families. Studio now confirms PUT then fetches a complete GET response before rebuilding the settings form.
- Regression tests now simulate the real partial PUT response, rather than an unrealistically complete mocked response.
- Backend Settings feedback is positioned as an overlay at top-right of the page, not inserted inline into the settings cards.
- Windows verification of the corrected toast and save flow remains required; don't claim this is a complete global toast system.

## S5.4b feedback foundation (in progress)

- Added a reusable Qt feedback banner with non-modal messages, an indeterminate progress indicator, auto-dismissed informational/success messages and persistent errors/warnings.
- Connected backend configuration load/save/rescan to immediate busy feedback and confirmed results; failures display persistent errors.
- Added offscreen feedback-state coverage.
- This is the **first integration**, not an app-wide toast manager yet. Other service-backed pages and operation-level state coverage remain pending.

## S5.4a follow-on responsive pass

- Library project detail switches from a side-by-side project list and details to a vertical arrangement in narrower windows.
- Image Lab uses a stacked stage/parameter layout in narrower windows instead of a permanently fixed-width parameter dock.
- Graph moves its inspector below the graph on narrower windows.
- Settings tabs use clearer Connections / Backend configuration / Studio preferences labels and scrolling under constrained width.
- Existing backend model-folder controls remain individually editable single-line fields.
- Further responsive work remains for Timeline, Home, Queue, managed backend and toolbar groupings. Physical Windows resizing acceptance is pending.

## First implementation slice

The Console now includes Show API requests (off by default), remembers the choice when preferences are available, and separates filters from other actions into two rows. The filter only removes routine debug/info HTTP API access records; 4xx/5xx records and warning/error levels remain visible. Regression tests added. **Do not regard this slice as the whole milestone; CI and physical Windows verification remain pending.**

## Acceptance conditions

Test 880×560, a standard laptop screen, 1080p, large desktop and 125%/150% Windows scaling. No controls may be unreachable through normal scrolling, no overlapping cards or clipped critical actions. Simulated slow/disconnected/failed backend operations must show timely feedback without duplicate writes. Model paths must maintain multiple-directory support. Current projects must retain unrelated fields and tracks after settings edits. Validate the real backend's behavior as well as CI mocks.
