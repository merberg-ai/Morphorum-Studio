# S2.1 Home dashboard and model discovery

Branch: `feature/studio-s2-1-dashboard`, stacked on `feature/studio-ui-shell` (which is stacked on
`feature/studio-s1-hardening`). Nothing is merged. Read-only: no request changes backend state, and no
control claims to load or run a model.

## Architecture
- `backend/session.py` `BackendSession`: the single shared view of the connection. `ConnectionsPanel` still owns
  connecting, the 15 s health probe, identity pinning and HTTP consent, and reports each outcome here. Other pages
  never monitor health themselves. `epoch` changes on a new profile/installation/boot or on disconnect; an outage
  ("reconnecting") keeps the epoch so a recovered backend simply resumes.
- `backend/schema.py`: typed parsers. Missing or wrong-typed values become `None` ("—" in the UI), never zero.
  Server file-system paths in model rows are dropped.
- `backend/api.py` `ReadApi`: `GET /api/system/telemetry`, `/api/system/gpu-memory` (on demand only; on Windows
  hosts the backend samples performance counters for it), `/api/models/families`, `/api/models/summary`,
  `/api/models?family=&kind=&limit=`, `/api/generation/capabilities` (backend-validated defaults).
- `backend/client.py`: `get_json` now accepts validated query parameters (short lowercase names, plain values or
  small integers). The path guard is unchanged and the token never appears in a URL.
- `ui/dashboard_service.py`: polls telemetry every 3 s (backing off to 15 s on errors) only while Home is visible
  and the session is connected; refreshes models on connect, every 60 s, on family change and on Refresh.
  Requests run on the thread pool, never overlap, are gated by the backend's `gpu_telemetry` and
  `model_discovery` feature flags, and results from an older epoch are discarded.
- `ui/home_page.py`: offline empty state, Backend / GPU / System cards, model inventory with family selector and
  backend defaults. A failed or stale reading shows a warning and dims the values.

## Known limits
- Only the first GPU is shown (others are counted). VRAM is whole-GPU use from `nvidia-smi`, not Morphorum's own
  allocator (that is `gpu_memory`, not polled).
- The model list is capped at 1000 rows per request; the summary shows the true total.

## Windows acceptance (physical)
1. Backend offline: Home shows the empty state and "Open Connections".
2. Connect: Backend card, GPU name, utilization, VRAM, temperature, CPU and memory match Task Manager / nvidia-smi
   on the host within a few seconds; the sparkline fills.
3. Stop the backend: warning appears, last values dim, Studio does not freeze; restart it and readings resume.
4. Models: counts match the old web UI; switching family shows that family's models and backend defaults.
5. Leave Home: polling stops (no repeated requests in the backend console); return: it resumes.
6. A backend without a GPU shows "No NVIDIA GPU reported", not zeros.
