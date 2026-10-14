"""The project pipeline as a graph (S5.3): a read-only description built from what the backend
reports about one project, never from anything Studio invents.

Nodes are the stages a frame passes through (source, checkpoint, prompts, schedules, camera,
motion, audio, export). Each carries the facts the inspector lists and the workspace that edits
them. Stages that are not in use are still shown, marked ``off``, so the shape of the pipeline
stays the same from project to project.
"""

from __future__ import annotations

from dataclasses import dataclass

from .assets import Soundtrack
from .projects import ProjectDetail
from .timeline import Timeline, Track

# Which workspace edits a stage (page keys used by the main window).
TIMELINE, LIBRARY = "Editor", "Projects"

CAMERA_PREFIX = "camera"
PROMPT_GROUP, LORA_GROUP = "prompts", "loras"


@dataclass(frozen=True)
class GraphNode:
    id: str
    title: str
    summary: str
    state: str  # "on" | "off" | "warn"
    column: int  # left-to-right position in the flow
    lane: int  # vertical position inside the column
    rows: tuple[tuple[str, str], ...] = ()
    target: str | None = None  # page key that edits this stage
    target_label: str = ""


@dataclass(frozen=True)
class Graph:
    project_id: str
    name: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[tuple[str, str], ...]

    def node(self, node_id: str) -> GraphNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)


def _plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else many or one + 's'}"


def duration_text(frames: int | None, fps: float | None) -> str:
    if not frames or not fps:
        return "unknown length"
    seconds = frames / fps
    return f"{frames} frames · {seconds:.1f} s at {fps:g} fps"


def animated(tracks: tuple[Track, ...]) -> tuple[Track, ...]:
    """Tracks that have at least one keyframe."""
    return tuple(t for t in tracks if t.keyframes)


def _tracks(timeline: Timeline | None, predicate) -> tuple[Track, ...]:
    return tuple(t for t in timeline.tracks if predicate(t.group)) if timeline else ()


def _track_rows(tracks: tuple[Track, ...], limit: int = 12) -> tuple[tuple[str, str], ...]:
    rows = [(t.label, _plural(len(t.keyframes), "keyframe")) for t in animated(tracks)[:limit]]
    extra = len(animated(tracks)) - limit
    if extra > 0:
        rows.append(("…", f"{extra} more"))
    return tuple(rows)


def build_graph(detail: ProjectDetail, timeline: Timeline | None = None,
                soundtrack: Soundtrack | None = None) -> Graph:
    is_3d = (detail.mode or "").upper() == "3D"
    nodes: list[GraphNode] = []

    # -- inputs --------------------------------------------------------------------------
    start = detail.start_mode or "unknown"
    source_rows = [("Start", start)]
    if detail.source_image_name:
        source_rows.append(("Source image", detail.source_image_name))
    has_source = bool(detail.source_image_name)
    nodes.append(GraphNode(
        "source", "Source", detail.source_image_name or f"Starts from {start}",
        "on" if has_source or start != "image" else "warn", 0, 0, tuple(source_rows),
        LIBRARY, "Open in Library"))

    model_rows = [(label, value) for label, value in (
        ("Checkpoint", detail.model_id), ("Family", detail.model_family),
        ("Variant", detail.model_variant)) if value]
    loras = animated(_tracks(timeline, lambda g: g == LORA_GROUP))
    if loras:
        model_rows.append(("LoRA schedules", _plural(len(loras), "track")))
    nodes.append(GraphNode(
        "checkpoint", "Checkpoint", detail.model_id or "No checkpoint chosen",
        "on" if detail.model_id else "warn", 0, 1, tuple(model_rows), LIBRARY, "Open in Library"))

    # -- schedules -----------------------------------------------------------------------
    prompt_rows = [("Prompt keyframes", str(detail.prompt_keyframes))]
    if detail.first_prompt:
        prompt_rows.append(("First prompt", detail.first_prompt))
    nodes.append(GraphNode(
        "prompts", "Prompts", _plural(detail.prompt_keyframes, "prompt keyframe"),
        "on" if detail.prompt_keyframes else "warn", 1, 0, tuple(prompt_rows),
        TIMELINE, "Edit in Timeline"))

    other = _tracks(timeline, lambda g: g not in (PROMPT_GROUP, LORA_GROUP)
                    and not g.startswith(CAMERA_PREFIX))
    moving = animated(other)
    nodes.append(GraphNode(
        "schedules", "Generation schedules",
        _plural(len(moving), "animated track") if moving else "Constant values",
        "on" if moving else "off", 1, 1, _track_rows(other), TIMELINE, "Edit in Timeline"))

    # -- camera and motion ----------------------------------------------------------------
    camera = _tracks(timeline, lambda g: g.startswith(CAMERA_PREFIX))
    moving_camera = animated(camera)
    camera_rows = [("Mode", "3D camera" if is_3d else "2D camera")]
    camera_rows.extend(_track_rows(camera))
    nodes.append(GraphNode(
        "camera", "Camera", ("3D" if is_3d else "2D") + (
            f" · {_plural(len(moving_camera), 'animated track')}" if moving_camera else " · still"),
        "on" if moving_camera else "off", 2, 0, tuple(camera_rows), TIMELINE, "Edit in Timeline"))

    other_layers = detail.motion_layers - detail.audio_layers
    motion_rows = [("Motion layers", str(other_layers))]
    nodes.append(GraphNode(
        "motion", "Motion Lab", _plural(other_layers, "layer") if other_layers else "No layers",
        "on" if other_layers else "off", 2, 1, tuple(motion_rows), TIMELINE, "Open Motion tab"))

    audio_rows = [("Audio layers", str(detail.audio_layers))]
    if soundtrack:
        audio_rows += [("Soundtrack", soundtrack.filename),
                       ("Format", soundtrack.format.upper()),
                       ("Offset", f"{soundtrack.offset_seconds:g} s")]
    else:
        audio_rows.append(("Soundtrack", "none attached"))
    audio_state = "on" if (detail.audio_layers or soundtrack) else "off"
    if detail.audio_layers and not soundtrack:
        audio_state = "warn"
    nodes.append(GraphNode(
        "audio", "Audio",
        (_plural(detail.audio_layers, "audio layer") if detail.audio_layers else "No audio layers")
        + ("" if soundtrack else " · no soundtrack"),
        audio_state, 2, 2, tuple(audio_rows), TIMELINE, "Open Motion tab"))

    # -- output --------------------------------------------------------------------------
    size = f"{detail.width}×{detail.height}" if detail.width and detail.height else "unknown size"
    export_rows = [("Size", size), ("Length", duration_text(detail.max_frames, detail.fps))]
    if detail.hybrid_enabled:
        export_rows.append(("Hybrid video", "enabled"))
    nodes.append(GraphNode(
        "export", "Render & export", f"{size} · {duration_text(detail.max_frames, detail.fps)}",
        "on", 3, 0, tuple(export_rows), TIMELINE, "Render in Timeline"))

    edges = (("source", "prompts"), ("checkpoint", "prompts"), ("checkpoint", "schedules"),
             ("prompts", "camera"), ("schedules", "camera"), ("motion", "camera"),
             ("audio", "motion"), ("camera", "export"))
    return Graph(detail.id, detail.name, tuple(nodes), edges)
