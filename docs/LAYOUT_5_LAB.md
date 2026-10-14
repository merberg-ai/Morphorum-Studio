# Layout step 5: Lab

The Image Lab page (page key `Image Lab`, shown as **Lab**) is rebuilt to the mockup layout.

## What changed
- **Stage** in the centre: the selected result at full panel size, with its file name and seed, plus **Save…** and
  **Full size…** (the existing viewer). The job title, progress bar and status sit above it.
- **Batch strip** under the stage: one thumbnail per result of the current job (or an earlier job from the
  drop-down). Clicking a thumbnail puts it on the stage. A new job shows its first image.
- **Right column**: model, prompt and negative prompt, LoRA, then Parameters.
  - **LoRA weights**: one slider per `<lora:name:weight>` tag in the prompt. Moving a slider rewrites the tag;
    editing the prompt updates the sliders; ✕ removes the tag. Add LoRA still inserts a tag.
  - **Aspect tiles**: one tile per size preset the backend reports for the selected model (nothing invented). The
    width/height boxes and the size drop-down stay in step.
  - **Steps and guidance sliders** are linked to their number boxes (the boxes remain the source of truth and keep the
    backend's limits).
  - **Lock seed**: follows the seed of the image on the stage (mode "fixed"); unlocking returns to random (-1).
- Not built because the backend has no endpoint for it: Upscale, Vary and Animate on a single image.

## Windows acceptance checklist
1. Pick a model, type a prompt, Generate: progress shows above the stage; the first image appears on it when done.
2. With a count of 2 or more, click each thumbnail: the stage, file name and seed change; the selected one is outlined.
3. Save… writes a PNG; Full size… opens the viewer.
4. Add a LoRA: a weight slider appears; drag it and the prompt tag changes; edit the tag by hand and the slider moves;
   ✕ removes it.
5. Click an aspect tile: width and height change and the tile stays highlighted; typing other sizes unhighlights it.
6. Drag the Steps and Guidance sliders: the number boxes follow, and typing a number moves the slider.
7. Tick Lock seed with an image selected: the seed box shows that image's seed; Generate reuses it. Untick: seed is -1.
8. Switch to a Flux model: ranges and presets change to that model's, with no stale tiles.
9. Earlier jobs drop-down still loads past results onto the strip.
