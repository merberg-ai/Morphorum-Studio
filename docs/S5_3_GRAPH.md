# S5.3: Graph (pipeline view)

The **Graph** workspace shows how one project is put together as a left-to-right diagram, generated entirely from what the
backend reports about that project. It is read-only: nothing on the canvas edits the project. The inspector lists a
stage's settings and has a button that opens the workspace where that stage is edited.

```
Source ─┐
        ├─► Prompts ─┐
Checkpoint ┤          ├─► Camera ─► Render & export
        └─► Generation schedules ─┘     ▲
                         Audio ─► Motion Lab ─┘
```

## Stages
| Stage | Shows | Edit button |
|---|---|---|
| Source | start mode, source image | Open in Library |
| Checkpoint | model, family, variant, LoRA schedules | Open in Library |
| Prompts | prompt keyframe count, first prompt | Edit in Timeline |
| Generation schedules | every other animated schedule track | Edit in Timeline |
| Camera | 2D or 3D, each camera track and its keyframes | Edit in Timeline |
| Motion Lab | non-audio motion layers | Open Motion tab |
| Audio | audio layers and the final-video soundtrack (file, format, offset) | Open Motion tab |
| Render & export | size, frames, duration, fps, hybrid video | Render in Timeline |

A stage that is not in use is dimmed ("off"). A stage that probably needs attention is amber: no checkpoint, no prompts,
an image start with no image, or audio layers with no soundtrack for the exported video.

## Using it
- Pick a project (newest first). Click a stage or move with the arrow keys; the inspector follows.
- **Refresh** (or F5) reloads the project. The timeline and soundtrack are optional: if the backend cannot provide
  them the rest of the pipeline is still shown.
- The graph is rebuilt from the project each time; there is nothing to save.

## Why read-only
The backend has no concept of a node graph, so a freely editable one would be Studio inventing a model it cannot
store. Parameters stay editable where the backend already serves them (Timeline, Motion tab, Library).

## Windows acceptance checklist
1. Open **Graph** with a backend connected: the newest project's diagram appears with eight stages and arrows.
2. Click each stage: the inspector shows its settings and the correct button.
3. Arrow keys move the selection; the focus outline is visible.
4. Pick another project: the diagram and inspector change; "Edit in Timeline" opens that project in the Timeline.
5. A project with audio layers but no soundtrack shows Audio in amber with "none attached".
6. A project with no motion layers shows Motion Lab dimmed.
7. Resize the window to 880×560: the diagram stays readable and inside the page.
8. Disconnect: the page says to connect; reconnect and it loads again.
