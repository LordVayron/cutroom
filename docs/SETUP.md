# Setup and troubleshooting

Requires Git, Python 3.10+, and Docker with Compose v2. Docker Desktop is suitable
for Windows/macOS; Docker Engine works on Linux. Allow disk for sources, audio,
clips, and caches. Internet is needed for builds, YouTube, and provider calls.
Global Node, FFmpeg, PostgreSQL, and Redis are not needed with Docker.

## Start

Clone into a new folder, read AGENTS.md, then:

~~~bash
python scripts/install.py --check
python scripts/install.py --start
~~~

Use python3 or py -3 where appropriate. The installer never installs system
dependencies, overwrites .env, or deletes data. Add --no-browser for terminal use.
Manual equivalent: copy .env.example to .env only if none exists, then run
docker compose up -d --build.

Enter OPENAI_API_KEY locally for uploads/transcription and AI ranking. Use an
account-supported OPENAI_SCORING_MODEL; historical labels may not be available.
No provider key is needed for startup/health checks.
API docs: http://localhost:8000/docs; health: http://localhost:8000/health;
website: http://localhost:3000. API startup runs migrations.

## Agent verification

Check docker compose ps and both HTTP endpoints, then confirm the empty library.
With authorized media/credentials: ingest, rank, render, inspect, approve, export.
Review actual sync, captions/language/safety, framing, and duration. Separate
setup checks from media/provider-dependent checks in the final report.

Windows users may run scripts/Start-VideoClipFactory.ps1 to reopen the app and
start Docker Desktop. Personal Start Menu shortcuts are not distributed.

## Troubleshooting

- Docker unavailable: start Desktop/Engine; repeat --check.
- Ports occupied: identify the existing service first. Defaults are loopback
  3000/8000. API URL and CORS must match any changed ports.
- No transcript: use permitted captioned sources or configure transcription.
- Model inaccessible: choose an accessible model; refresh API/worker environments.
- Old rendered file: rerender after renderer-version changes.
- Slow processing: CPU tracking/layout, decoding, and encoding take time.
- Build/dev conflict: stop web before production builds, then restart web.
- Database failure: inspect migration logs privately, never remove volumes as a fix.

Before updates, privately back up .env, storage, and database volumes.
Review changes, then git pull --ff-only and docker compose up -d --build.
Use docker compose stop to stop. Never use docker compose down -v for shutdown.
