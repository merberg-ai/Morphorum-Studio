# S4.4 Project setup: new-project wizard, start mode, model and LoRA browser (branch `feature/studio-s4-4-project-setup`)

Branched from `dev-ui` (S1–S4.3 and the console merged). Nothing merged. Needs CI plus a Windows check.

## New project wizard
**Projects → New project** now opens a wizard instead of a bare name prompt.
- Defaults (frame rate, length, size) come from the backend's `/api/animation/project-template`.
  You choose: name, checkpoint, size (presets or custom), frame rate, frames (the length in seconds is
  shown), 2D or 3D, how frame 0 starts (prompt or source image), and the first/negative prompts.
- **Check** first runs Studio's local sanity checks (name, size 64–8192, sizes not a multiple of 8,
  frames/fps range, checkpoint chosen, very large frames), then asks the backend to validate the
  schedules the new project would have (`/validate-schedules`). Errors (✖) block creation; warnings
  (⚠) are shown but do not.
- **Create project** stays disabled until Check passes, and any edit afterwards discards the result,
  so what is created is what was checked. The new project is selected when creation succeeds.
- **Camera safety:** the wizard never writes a camera value. Studio sends the template's own 3D
  camera sections unchanged and omits `tracks`, so the backend derives its timeline; nothing the
  wizard creates can seed a 3D schedule that projects behind the camera. The backend's validation
  is still the final word.
- Starting from a source image: pick "A source image" and attach the image afterwards on the
  Projects page (the project must exist first).

## Start from: prompt or source image (img2img)
The project media card has a **Start from** selector. "Source image" is offered once an image is
attached. Changing it reads the project's current revision and saves it conditionally (a project
changed elsewhere is refused, not overwritten), then the page reloads. The generation `strength`
schedule (Editor → generation tracks) controls how far frames move from the source.

## Models and LoRAs browser
**Projects → Models and LoRAs…** lists the backend's indexed checkpoints and LoRAs, with a family
filter and search. Selecting a LoRA inspects it: family, format, base model, tensor count, ranks,
trigger words and any warnings. It is read-only: no online lookups and no usage records are
written, and server file paths are never shown or kept. Add files in the backend's model folders
and use Refresh.

## Not in S4.4
- Applying a LoRA inside a project's timeline (the LoRA track group is still reserved) and the
  Civitai lookup / runtime audit tools.
- Layout save/restore, keyboard shortcuts, undo shortcuts and help tooltips: left for the UI pass.

## Windows acceptance checklist
1. Projects → New project: the wizard opens; the checkpoint list is filled; the length shows seconds.
2. Press Check with no checkpoint: told to choose one, nothing is created. Choose one, Check again:
   "Ready to create".
3. Change the frame count: the result clears and Create is disabled until Check is pressed again.
4. Create a 3D project: it appears and opens; in the Editor its camera tracks are the defaults
   (translation z 0:(0), fov 40) and the schedules are valid.
5. Try an odd width (e.g. 1001): a "multiple of 8" warning, creation still allowed.
6. On a project, attach a source image, set **Start from** to the source image: the setting survives
   Reload. Render and confirm frame 0 looks like the image.
7. Switch it back to the prompt. With no source image attached the source option is greyed out.
8. Models and LoRAs…: checkpoints and LoRAs listed; filter to one family; select a LoRA and check the
   trigger words and warnings against the Web UI's LoRA manager.
9. Disconnect while the browser is open: it clears and tells you to refresh.
