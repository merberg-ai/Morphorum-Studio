# Morphorum Studio S1.1 foundation

## CURRENT STATUS (2026-10-13)

**This document started as a historical S1.1 guide.** S1.2 and the follow-on connection reliability features have now been implemented on Studio **dev-ui**, physically tested on a Windows LAN client, and documented in [HANDOFF.md](HANDOFF.md). The statements below that refer to "UI still offline", "client not wired", or "S1.2 will add" describe the earlier S1.1 milestone **at that point in history**, not current functionality. In current dev-ui, Connections is live, bearer tokens use OS keyring, QThreadPool handles network discovery, status monitors backend health/reconnect, and startup auto-connect can be enabled in Settings.

**Latest checked implementation:** f91b3e6, Windows+Ubuntu CI green. Use dev-ui; Studio main remains an S0-only scaffold. Backend main is deliberately held. Do not merge either repository without explicit user approval.

---

S0 Windows physical acceptance: PASS (user report, 2026-10-12).
Immutable branch: `checkpoint/studio-s0-windows-verified-20261012`.

## Local install / run / update

Windows PowerShell, from the Studio checkout:

```powershell
.\setup.ps1
.\run.ps1
.\update.ps1
```

Linux, from the Studio checkout:

```bash
bash setup.sh
bash run.sh
bash update.sh
```

Setup creates/reuses a project-local Python 3.12/3.13 virtualenv and installs Studio only. Run launches the **native Studio frontend only**. Update fast-forwards the **current Git branch** and re-runs setup, refusing uncommitted changes or detached HEAD. No backend, PyTorch, CUDA or model installation. No implicit switch to main and no forced reset.

For developer tests, install `-e ".[dev]"` into the virtualenv and run `python -m pytest -q`.

## S1.1 typed connection transport

`morphorum_studio.backend.client.BackendClient` currently provides **non-Qt** discovery for the existing backend `GET /api/health` and `GET /api/client/capabilities` endpoints. It uses bounded timeouts, optional bearer Authorization, URL validation, strict contract/schema 1 checks, identity + boot ID parsing, dynamic feature flags, redirect refusal and stable errors. Pure mock tests never contact a live GPU host.

**Historical S1.1 context:** The transport itself is synchronous. Current dev-ui correctly calls it through Qt background QRunnable workers (with epoch invalidation on disconnect); network work is not on the GUI thread. S1.2 later implemented OS keyring storage, named profiles and identity approval. Never commit a real bearer token or place it in scripts, logs, query strings or test fixtures. Plain HTTP is appropriate only on a trusted LAN or secure tunnel.

This milestone is a foundation, not a claim of live Studio-to-backend connection acceptance. Stop for Windows physical smoke tests and CI review before merging.

## Importing a backend-issued token (S1.2)

1. On the GPU backend host, open PowerShell in its checkout and issue a revocable per-client token:
   `.\\.venv\\Scripts\\python.exe -m morphorum clients issue "Studio PC" --days 90 --out ".\\data\\studio-client.token"`
2. Securely transfer the resulting file to the **Studio PC** via removable drive or authenticated encrypted transfer. Do not send the credential to an HTTP endpoint, commit it to GitHub or paste it into chat.
3. In Studio > Connections, create and **Save profile**, check the trusted-HTTP acknowledgment if using plain HTTP on a trusted LAN, click **Import Token File…**, select the transferred file, then **Connect / Test**.
4. Studio stores the token through the OS credential manager. The transfer file is left untouched so deletion is an explicit user action; remove temporary copies after verifying connectivity.
5. Revoke an old client credential on the backend host via `python -m morphorum clients list` and `python -m morphorum clients revoke CLIENT_ID`.

This is local file import, **not remote pairing or automatic backend-host retrieval**. Importing does not change the backend or bypass authentication.

## S1.2 UX hotfix after Windows screenshot (2026-10-12)

The initial import button incorrectly required HTTP trust confirmation *before* it would open a local file picker. Updated behavior: Save profile -> Browse and import token file -> choose the host-issued file -> token saved to OS keyring. HTTP trust is checked only when **Connect / Test** is about to transmit credentials, at which point a specific warning and confirmation are shown. The provisioning instructions are now separated into readable steps. A regression test imports from file while the trusted HTTP checkbox is unchecked. This is a testing candidate pending CI and Windows confirmation.
