# Cutroom

Cutroom turns long videos and podcasts into ranked short-form clip candidates,
then lets you refine framing, captions, and branding before exporting MP4s.
It is a local-first Next.js / FastAPI application, not a hosted publishing service.

## Install with your coding agent

Give Codex, Claude Code, or another local coding agent the public repository URL:

> Clone this repository into a new folder, read AGENTS.md and docs/SETUP.md, check
> prerequisites, and help me run Cutroom locally. Never ask for API keys in chat,
> commit credentials, delete existing data, or expose the service publicly.
> Verify the browser, API health, and worker before reporting success.

Requires local terminal access, Git, Python 3.10+, and Docker with Compose.
System permissions, Docker startup, and optional provider credentials may need
your input. Giving an agent a URL is not a guarantee of unattended installation.

~~~bash
git clone https://github.com/LordVayron/cutroom.git
cd cutroom
python scripts/install.py --check
python scripts/install.py --start
~~~

Use python3 on macOS/Linux or py -3 on Windows if needed. The helper creates a local
.env only if none exists, builds/starts Compose, checks readiness, and opens
http://localhost:3000. It never installs Docker, collects keys, or resets data.

## Features

- YouTube links or video uploads; request 1–20 clips.
- Timed transcripts, source-language captions, rolling-caption cleanup.
- AI-assisted ranking with deterministic fallback for usable captioned sources.
- Non-overlapping re-analysis, duplicate-idea filtering, and taste feedback.
- Rare three/four-part series and longer clips, capped at 120 seconds.
- Scene-aware framing, mouth-motion speaker tracking, verified two-person stacks,
  and filled automatic vertical crops without added letterbox bars.
- Silence tightening using one audio/video edit timeline.
- Clean/Pulse/Kinetic captions, fonts, colors, phrase length, size, and safe zones.
- Director Mode: trim, script correction, framing, captions, logo position/size,
  and shared visual settings with Apply to all.
- Brand folders with inherited defaults and per-film caption overrides.
- Collapsible library, three-dot actions, archive/restore, and soft removal.
- Render all, quality inspection, human review/approval, and MP4 export.
- Calendar platforms, manual dates, even 1–7 day distribution, and SEO-caption drafts.
- Transcript, analysis, layout, and tracking caches.
- Plum/ivory/sage interface and PNG wordmark.

## Limits and deferred integrations

The calendar stores an **internal publishing queue**. Social OAuth, Composio,
external posting, multi-account delivery, analytics ingestion, performance-based
learning, production authentication, and billing are not implemented.
Manual analytics and the Cover Designer UI were removed; legacy cover schema
and routes remain. Ordinary renders no longer generate covers.

Tracking, inspection, and duplicate ideas are heuristics, not guarantees.
Three-person stacks are not implemented. Review every clip; do not assume perfect
speaker recognition, universal movie understanding, restored resolution, or virality.

## Credentials and local data

An OpenAI API key is optional for usable captioned-source fallback, but required
for upload transcription and provider-backed ranking. Enter it locally in .env,
never in agent chat, issues, or commits. Set OPENAI_SCORING_MODEL to a model
available to your own API account; the historical default label may not be.
Kie.ai, Vercel, and GitHub credentials are not required to run the editor.

Caption selection follows source-language metadata when available. Uploads use
transcription, not invented text. Timing/availability depend on sources/providers.

Databases use Docker volumes; media/caches live in storage/. Archive is reversible.
Delete is soft removal retaining media/history; removing a folder unfiles its films.
Never use docker compose down -v as an ordinary shutdown or repair.

This single-user app has no production authentication. New Compose starts bind
web/API to loopback. Do not expose it publicly without a security/auth/storage design.
The public repo omits personal data, media, episode screenshots, design drafts,
provider task records, and the original Git history.

## Verify

~~~bash
docker compose exec -T api pytest -q
docker compose exec -T api ruff check app tests
docker compose run --rm --no-deps web npm test
docker compose run --rm --no-deps web npm run lint
~~~

Do not production-build against a live development .next directory:

~~~bash
docker compose stop web
docker compose run --rm --no-deps web npm run build
docker compose start web
~~~

Read [Setup](docs/SETUP.md), [architecture](docs/architecture.md),
[feature status](docs/FEATURES.md), [changelog](CHANGELOG.md), and
[security](SECURITY.md). Licensed under [MIT](LICENSE).

Clean-container build/test status is available in the repository's Actions tab.
Read [verification boundaries](docs/VERIFICATION.md) before assuming a passing
build covers provider-dependent ingestion or a particular source video.
