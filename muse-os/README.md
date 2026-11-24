# Muse code bundle (2026-11-12)

Upload this zip to a new Claude session to keep working on the Muse systems.

- `muse-os/`: Muse OS, the self-hosted web app (FastAPI + SQLite). Tests: `cd muse-os && pip install -r requirements.txt pytest httpx && pytest -q` (57 pass).
- `muse-dm-bot/`: the Instagram DM bot that runs on Render and reads Muse OS through its API. Tests: `cd muse-dm-bot && pip install -r requirements.txt && pytest -q tests integration` (188 pass).
- `ENGINEER_HANDOFF.md`: how the two fit together, deployment, business rules and open items. Start with section 0 for the latest changes.

No keys, tokens, databases or guest data are included. Secrets live in Render and on the Muse OS server as environment variables.
