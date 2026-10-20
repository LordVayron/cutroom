# Agent instructions for Cutroom

Read README.md, docs/SETUP.md, docs/FEATURES.md, and docs/architecture.md first.
For Codex, Claude Code, and other local coding agents.

## Install and verify

1. Use a new checkout. Never overwrite an existing installation.
2. Check Git, Python 3.10+, Docker Engine/Desktop, and Compose v2.
3. Run python scripts/install.py --check. Ask the user to start/install Docker
   if missing; do not silently install system software.
4. Run python scripts/install.py --start only when authorized to launch the app.
   It copies .env.example only if .env does not exist.
5. Provider keys are entered locally by the user, never through agent chat.
   Do not print .env or environment values. Use a model accessible to their account.
6. Verify localhost:8000/health, localhost:3000, and docker compose ps.
   Then test an authorized source when available. HTTP 200 alone does not prove
   ingestion, transcription, or rendering works.
7. Report only checks completed; identify credential/media-dependent checks.

## Preserve data and contracts

- Never delete storage, volumes, credentials, or an existing checkout.
- Never use docker compose down -v or git reset --hard to repair installation.
- Keep schemas, frontend types, migrations, tests, and documentation consistent.
- State belongs to API/worker, not browser. Preserve fencing, retries, idempotency,
  shared audio/video timestamps, language, safe captions, approvals, and branding.
- Add migrations for schema changes; never rewrite an applied migration.
- Rendering changes require a version bump and relevant regression tests.
- Stop web before production builds; never collide with the live dev .next directory.

## Release boundaries

No secrets, media, transcripts, databases, real episode screenshots, personal paths,
private designs, or provider job records in public releases. Do not publish local
Git history. Do not push, deploy publicly, or spend credits without authorization.

Publishing calendar UI and scheduling routes are removed; preserve legacy records.
Manual analytics and Cover Designer UI are removed. The landing page is a separate static website in
landing-site/, released independently from the local editor.
