# S5.2a: Audio Director

Audio now steers the camera from the **Motion** tab of the Timeline. A sound file is analysed by the backend; each
**audio layer** listens to one frequency band and fires a short camera push that always returns to where it started.

## Acknowledgement
The channel model (frequency bands that each steer one camera axis, level and transient detection, threshold,
attack/return, minimum gap, timing offset, start/end range, one-click starter channels) is based on the ideas and
detection approach of **Deforum Motion Studio** by chicodog530 (https://github.com/chicodog530/Deforum-Motion-Studio),
used with the author's permission. Studio's code is an independent implementation against the Morphorum backend.

## What you can do
- **Load audio…**: WAV, MP3, FLAC, OGG or M4A. A WAV that fits (PCM, at most 20 MiB and 3 minutes) is sent as it is.
  Anything else is decoded on this PC with Qt Multimedia to mono 16-bit 22.05 kHz, cut to the project's length (plus
  a second) and sent as a WAV. Your file is never changed. If your Windows has no codec for a format, Studio says so;
  use WAV or convert it.
- The backend measures the loudness of the whole mix and of four bands (Kick 35–140 Hz, Bass 40–250 Hz, Snare 150–2400 Hz,
  Highs 2.5–10 kHz) for every frame of the project at its frame rate.
- **+ Audio** adds a starter layer: Kick → Move forward, Snare → Pan, Highs → Roll, Full mix → Move forward. Each layer
  has: the camera axis it drives, band, detection (**Level**: pulse when it gets loud; **Transient**: pulse on sudden
  hits, with sensitivity), threshold, strength, attack, return, minimum gap and timing offset (shown in seconds, stored
  as whole frames), blend (add/replace) and its frame range.
- The **envelope view** shows the band's loudness, the threshold line, the pulses the backend will make (after a
  **Preview**; dimmed as soon as you change something) and the playhead.
- **Preview** and **Apply to camera** work as in S5.1; the clipping report tells you if a pulse was limited.
- **Audition** plays the sound from the playhead and the playhead follows it in real time (the picture catches up
  when it settles). This is for judging timing by ear, not a frame-accurate sync.
- Saved audio layers (including ones made in the web app) can be edited: Studio fetches the layer's stored audio from the
  backend when you select it. If that file is missing, pulse settings still work but the band and frame range are locked.
- A line under the Audio controls says whether the project has a **final video soundtrack**. The analysed audio is a
  separate thing from the soundtrack that ends up in the exported video; attach it in Library → project → Media.

## Not in this slice (see docs/BACKEND_PROPOSALS.md)
Custom Hz bands, "bass intensity" and "ripple" response shapes, the spectrum view with click-to-create-channel,
backend-side decoding of MP3/FLAC/OGG, uniform headroom scaling. Studio will not offer controls the backend cannot serve.

## Checking against the backend
`scripts/verify_backend_audio_layers.py <path to Morphorum/backend>` builds the starter layers from synthetic audio and
runs them through the real backend compiler: all are accepted and every pulse returns to zero.

## Windows acceptance checklist
1. 3D project open in the Timeline → Motion. **Load audio…** with a WAV: "Analysed: …" appears with the length and fps.
2. Repeat with an MP3, a FLAC and an OGG. Each should analyse (or say clearly that Windows cannot decode it).
3. **+ Audio → Kick → Move forward**: a layer appears and the envelope view shows the kick band with a dashed threshold.
4. **Preview**: green pulse marks appear on the beats; the camera chart shows the Move-forward curve. Lower the
   threshold: after Preview there are more pulses.
5. Add Snare → Pan with Transient detection; change band, axis, attack/return/gap; Preview each time.
6. Narrow the frame range (to 10 s for example) and Preview: pulses stay inside it.
7. **Audition**: sound plays from the playhead and the playhead moves with it; Stop works.
8. **Apply**, reload the project: the layers are still listed; selecting one loads its envelope; Preview matches.
9. A project with no soundtrack: the note under Audio says exports will have no sound.
10. A file over 20 MiB WAV or longer than 3 minutes: it is cut to the project length (decoded formats) or refused with
    the backend's message (oversized WAV).
