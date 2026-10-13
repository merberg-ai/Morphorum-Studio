# S2.3 Project media (branch `feature/studio-s2-3-assets`)

Stacked on `feature/studio-s2-2-projects`. Nothing merged. Needs CI plus a physical Windows test.

## What it does
A **Project media** card on the Projects page, for the open project:
- **Source image**: thumbnail (verified download, skipped above 12 MiB), file name, size and short
  SHA-256. *Choose image…* uploads PNG/JPEG/WebP/BMP up to 32 MiB (the backend decodes it and stores
  PNG). *Remove* asks first. *Save copy…* writes a verified copy anywhere you choose.
- **Soundtrack**: shows the attached WAV/MP3/OGG/FLAC (name, format, size, short SHA-256, offset).
  *Attach audio…* / *Replace audio…* uploads up to 40 MiB with the offset you set. *Apply offset*
  changes only the offset (-30..+30 s). *Save copy…* writes a verified copy.

## Safety and behaviour
- Files are checked locally first (extension, non-empty, size) and uploaded with `X-Content-SHA256`,
  so the backend verifies the transfer. Uploads are never retried.
- Downloads stream to `<name>.part` beside the destination, are checked against the backend's SHA-256
  (and its `X-Content-SHA256` header when present), then renamed. A failed or mismatching copy leaves
  nothing behind and never touches an existing file of the same name.
- Source image upload/remove changes the project revision, so those two actions are paused while the
  form has unsaved edits, and the project is re-read afterwards to pick up the new ETag. Soundtrack
  actions do not change the project and stay available.
- One mutation at a time (shared with save/create/trash). Results from an older connection or an
  older project selection are discarded. Asset URLs are built from the project id, never trusted
  from the response, and the backend's server paths are never displayed.
- Backend error text (`detail`) is shown for refused uploads, for example an undecodable image.

## Not in S2.3
Motion Lab analysed WAVs (listed by the backend but not shown here), soundtrack removal (the backend
has no endpoint), drag and drop, a persistent local asset cache, audio playback and waveform display.

## Windows acceptance checklist
1. Open a project: media card shows the current image/soundtrack, or "No ... attached".
2. Choose a PNG, then a JPEG: thumbnail and details update; the project still saves afterwards.
3. Choose a `.txt` file renamed `.png`, and an oversized file: a clear message, nothing changes.
4. Edit the name without saving: *Choose image…* and *Remove* are disabled with an explanation;
   Revert or Save re-enables them.
5. Remove the image: asks first; card returns to "No source image attached.".
6. Attach a WAV and an MP3 with an offset; change the offset and Apply; reopen the project and check
   the values persisted. A name containing spaces/accents/`&` shows correctly.
7. Save copy of each: open the saved file; try a path in a read-only folder for a clear error.
8. Disconnect the backend during an upload: an error, no hang, controls recover on reconnect.
