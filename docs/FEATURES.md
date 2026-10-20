# Current feature status

Updated for the 2026-10-19 source release.

## Available

- Ingestion, timed transcripts, 1–20 clips, range memory, and duplicate-concept
  heuristics informed by approval/rejection feedback.
- Rare series and longer clips, capped at 120 seconds.
- Renderer v19: scene layouts, verified Duo, mouth-motion tracking, filled auto crop.
- Manual Full frame preserves the image over a blurred video background.
- Shared-clock silence edits and language-aware, cleaned, word-timed captions.
- Clean/Pulse/Kinetic, fonts, colors, phrase length, size, and safe positioning.
- Director Mode trimming, script correction, framing, captions, logos, and
  shared visual settings (not unrelated clip cuts/corrections).
- Brand defaults/inheritance and per-film overrides; collapsible folders,
  three-dot actions, archive/restore, and soft removal.
- Batch rendering, inspection, human review/approval, and MP4 export.
- Transcript, analysis, layout, and tracking caches.
- Plum/ivory/sage UI and PNG wordmark.

## Removed or deferred

The publishing calendar, scheduling controls, and schedule-writing API routes
have been removed. Existing records remain stored for compatibility.
Rendering, approval, and MP4 export remain available.

Cover Designer UI and ordinary cover generation were removed; legacy routes,
schema fields, and tests remain. Manual analytics were removed. Real analytics,
Composio/social OAuth, external posting, multi-account delivery, billing,
production auth/tenant isolation, and three-person stacks are not implemented.
The production product website is deployed separately at
https://cutroom-website-delta.vercel.app, with source in
https://github.com/LordVayron/cutroom-website. It uses actual UI captures with
synthetic demo data, not private episode screenshots. The editor still runs locally.

Tracking and inspection are heuristics, not guarantees. Duplicate detection is
not a universal multilingual semantic model. Caption timing varies by source.
Do not promise virality, restored resolution, perfect speakers, or live publishing.
