# S3.3 Video and audio export (branch `feature/studio-s3-3-video`)

Stacked on `feature/studio-s3-2-animation`. Nothing merged. Needs CI plus a physical Windows test
against a backend host that has FFmpeg (and, for the audio checks, a project with an imported
soundtrack rendered with it).

## What it does
An **Export video** section appears in the Render card once a render is finished:
- **FFmpeg discovery**: asks the backend (`/api/animation/video/availability`) whether the *backend
  host* has FFmpeg. If not, the section says so, shows the backend's message, and disables export.
  Nothing is checked on the Windows machine.
- **Export**: choose MP4 or WebM, quality (high / balanced / compact) and optionally a frame rate.
  The request is journalled (kind `video`) before the POST with an `Idempotency-Key`, so *Retry the
  same export* after a lost response cannot start a second encode. Progress comes from REST polling.
- **Audio, stated honestly**:
  - Render with a frozen soundtrack: Studio says the backend will mux it in, that the frame-rate
    override is locked (the backend refuses it with audio), and that a missing or changed soundtrack
    file is refused rather than silently dropped.
  - Render without a frozen soundtrack: an explicit warning that the video will most likely have no
    audio.
  - After the export, the list shows **"With audio (source, offset)"** or **"No audio track"**
    taken only from the backend's `audio_included` field, never from what Studio expected.
- **Existing exports** for the render are listed (including ones from earlier backend runs; those
  marked *interrupted* are not downloadable, export again).
- **Save video…**: streams to `<name>.part`, requires the SHA-256 and size to match the export record
  (and the advertised header), then renames atomically. A mismatch saves nothing and never touches an
  existing file.
- **Play**: downloads the same verified copy into a small cache (last 5 kept, reused only if its hash
  still matches) and plays it with play/pause, seek, volume and mute. If the Qt build has no
  multimedia module, Play is disabled with a tooltip and Save still works.

## Windows acceptance checklist
1. Backend host without FFmpeg: section reads "unavailable", export disabled. With FFmpeg: enabled.
2. Render with a soundtrack, export MP4: note mentions the soundtrack, fps override locked, finished
   entry reads "With audio", Play has sound and sync, seek/pause/mute work.
3. Render without a soundtrack: warning visible; finished entry reads "No audio track".
4. Export WebM at another quality; both listed; Save each; compare file sizes with the list.
5. Kill Studio mid-encode, reopen the project: the export is still listed/finishing; restart the
   backend mid-encode: the entry shows *interrupted* and Save is disabled.
6. Disconnect the LAN during a save: nothing partial is left behind, an existing file is untouched.
7. Open a saved MP4/WebM in an external player and confirm the audio matches Play.
