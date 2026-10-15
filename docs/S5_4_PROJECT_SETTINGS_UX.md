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

## First implementation slice

The Console now includes Show API requests (off by default), remembers the choice when preferences are available, and separates filters from other actions into two rows. The filter only removes routine debug/info HTTP API access records; 4xx/5xx records and warning/error levels remain visible. Regression tests added. **Do not regard this slice as the whole milestone; CI and physical Windows verification remain pending.**

## Acceptance conditions

Test 880×560, a standard laptop screen, 1080p, large desktop and 125%/150% Windows scaling. No controls may be unreachable through normal scrolling, no overlapping cards or clipped critical actions. Simulated slow/disconnected/failed backend operations must show timely feedback without duplicate writes. Model paths must maintain multiple-directory support. Current projects must retain unrelated fields and tracks after settings edits. Validate the real backend's behavior as well as CI mocks.
