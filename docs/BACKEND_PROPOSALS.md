# Backend feature proposals

Studio only exposes what the Morphorum backend serves (see docs/ROADMAP.md, S5). These are the gaps found while
building the Audio Director against the backend's Motion Lab. Each is written so it can be taken to the backend PR with
its own tests. Nothing here is in Studio yet.

Reference for the interaction design: Deforum Motion Studio by chicodog530 (used with permission).

## P1. Decode MP3, FLAC, OGG and M4A for analysis
`POST /motion-lab/audio-analyze` accepts only PCM WAV (20 MiB, 3 minutes). Proposal: accept the formats the soundtrack
attachment already accepts (WAV, MP3, OGG, FLAC) and decode with the FFmpeg the backend already uses for video, to mono
22.05 kHz, bounded by the project's duration. Advertise it as feature `motion_lab_audio_decode`; when present Studio
uploads the original file instead of decoding locally (Studio setting "Decode audio: Studio / Backend", default Backend
once available).

## P2. Custom frequency band per audio layer
Fixed bands (Kick, Bass, Snare, Highs) cannot target an arbitrary range. Proposal: the analysis returns a spectrogram-
grade representation or accepts `band_hz: [low, high]` per layer and computes the envelope server-side. Validation:
10 Hz ≤ low < high < Nyquist.

## P3. Response shapes: follow and ripple
Today a layer makes rigid push-and-return pulses. Deforum Motion Studio also has **Bass intensity** (a continuous
follower of the band's energy, always returning to the path) and **Ripple** (each hit starts a decaying oscillation).
Proposal: `response: "pulse" | "follow" | "ripple"`, with the pulse compiler staying travel-neutral.

## P4. Spectrum in the analysis result
A peak-hold spectrum on a log frequency grid (about 160 bins, dB relative to the loudest) would let Studio show where the
energy is, shade each layer's band, and create a layer centred on a clicked peak.

## P5. Uniform headroom scaling
The backend clips an axis at its limit and reports the frames clipped; clipping can unbalance a push and its return.
Proposal: optionally scale all pulses on an axis uniformly to fit the limit and report the retained percentage.

## P6. More presets
Deforum Motion Studio adds "Reveal drift" and "Fly-through". Proposal: add them to the preset list.

## S5.2b: how Studio will choose
Studio setting **Audio analysis: Backend (default) / Studio (local)**. Backend uses P1-P4 as they appear. Studio (local)
computes band envelopes and the spectrum on this PC and sends the envelope in the existing layer format; it needs a numerical
library bundled with Studio and cannot offer P3 (the pulse compiler is on the backend).

## P7. A scriptable installer (for Studio's managed backend)
Studio installs the backend by running `scripts/bootstrap.ps1 -InstallDir -Branch -Port` and reading its text output
(`>>` sections, `[>] [+] [!] [X]` lines). That works today but is coarse. Proposals, none required:
1. `-NonInteractive`: fail instead of prompting, so a wrapper can never hang on `Read-Host` or a winget confirmation.
2. `-JsonProgress`: one JSON object per line (`{"stage":"ai-dependencies","index":4,"of":8,"message":"..."}`) so Studio
   can show a real progress bar instead of a section name.
3. A stable exit code for each failure class (no space, no network, git missing, port busy) so Studio can explain it.
(`scripts/update_windows.ps1 -Branch` already exists, so Studio's branch switch in C4 needs no backend change.)

## P8. A capability flag for the settings API
Studio's Settings > Backend settings uses `GET/PUT /api/settings`, `POST /api/settings/validate-path` and
`POST /api/models/scan`. They are not advertised in `/api/client/capabilities`, so Studio shows the tab for any connected
backend and reports a refusal in words. Proposal: add `"settings_api": true` (and `"model_scan": true`) to `features`.
A client-safe subset would also help: a remote client currently can edit every setting, including `server.allow_lan`
and `server.access_token`, which Studio deliberately never shows.
