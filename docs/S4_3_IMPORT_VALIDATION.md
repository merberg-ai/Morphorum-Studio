# S4.3 Schedule validation and Deforum import (branch `feature/studio-s4-3-import-validation`)

Branched from `dev-ui` (S1–S4.2 and the console merged). Nothing merged. Needs CI plus a Windows check.

## Schedule validation
- The Editor page asks the backend (`/validate-schedules`) whether the saved project's schedules are
  valid after a project loads and after every keyframe edit or undo. The result appears under the
  values table: "Schedules are valid", or the number of errors/warnings with each issue listed
  (✖ error, ⚠ warning). Click an issue to jump to its track.
- **Render guard**: *Render animation* now runs the same check first. If there are schedule errors the
  render is not started, nothing is journalled, and the first errors are shown. (An older backend
  without the endpoint simply skips the check.)
- Studio shows the backend's verdict verbatim; it adds no rules of its own.

## Deforum settings import
Projects page, **Import Deforum…** (creates a *new* project; existing projects are never modified):
1. Choose a Deforum settings file (UTF-8 text or JSON, up to 1 MiB).
2. Choose an indexed checkpoint (the backend requires SDXL, Flux or Z-Image) and optionally a name.
3. **Preview** shows what the backend would create: frame count, fps, size, mode; how many settings
   were mapped, mapped with warnings, unsupported or kept as metadata; every warning and schedule
   issue; and a table of each Deforum setting, what it becomes and its status. Imported checkpoint
   paths are never used.
4. **Create project** is enabled only when the backend says it can be created. Changing the file,
   checkpoint or name discards the preview, so what you create is what you previewed.
The new project is selected on the Projects page when creation succeeds.

## Not in S4.3
- Applying Deforum *motion* settings onto an existing project (the backend's hash-guarded
  prepare/apply flow) and Motion Lab presets are left for S5, where they belong with the Motion Lab.

## Windows acceptance checklist
1. Open a project in the Editor: "Schedules are valid." Make an invalid edit through the Web UI (or a
   known-bad project): errors listed; clicking one jumps to the track.
2. Try to render a project with a schedule error: refused with the error text, no render appears.
3. Import Deforum…: pick a real Deforum settings file; Preview without a checkpoint says to choose one.
4. Choose a checkpoint, Preview: counts, warnings and the mapping table look right against your file.
5. Change the checkpoint: the preview clears; Preview again, Create: the project appears and opens.
6. Open the imported project in the Editor and compare a few keyframes/curves with the Deforum file.
