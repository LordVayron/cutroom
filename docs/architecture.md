# Architecture and current implementation

See FEATURES.md for the release status and SETUP.md for installation.

## First vertical slice

`source + requested count -> real captions -> ranked clips -> render -> approve -> schedule/export`

The API owns durable state. The worker owns side effects. The browser never advances processing state directly.

## Project states

| State | Owner | Meaning |
| --- | --- | --- |
| `queued` | API | Source accepted and ingest job committed |
| `ingesting` | worker | Source is being copied or downloaded |
| `transcribing` | worker | Timed transcript is being produced |
| `scoring` | worker | Candidate windows are ranked |
| `ready` | worker | Ranked candidates are available |
| `rendering` | worker | A selected candidate is being rendered |
| `review` | worker | MP4 is available for review |
| `approved` | API | Human approved the rendered asset |
| `failed` | worker | Retry budget was exhausted |

Transitions are checked in `app/domain.py`; invalid transitions fail closed.
Failed jobs can be manually requeued through `POST /api/projects/{id}/retry`; this resets the bounded attempt counter while preserving the same idempotency key and job record.
Validation failures such as a source shorter than 30 seconds are marked non-retryable, so automatic retries do not repeat work that cannot succeed.
Re-analysis runs from the stored transcript. Every clip generation remains in PostgreSQL, while only the current generation is returned to the cutting room. All prior time ranges are hard exclusions, with a three-second guard band, so later generations cannot repeat or overlap earlier work.

## Queue and idempotency

PostgreSQL is the durable job source; Redis only wakes an idle worker. The stable key is `<kind>:<project_id>:<clip_id-or-source>` and has a database uniqueness constraint, so simultaneous duplicate requests converge on one job. A worker claims with `FOR UPDATE SKIP LOCKED`, renews a fenced lease while work is active, and can reclaim an expired lease after a crash. Failures increment `attempt`, store the error, and requeue with exponential delay until `WORKER_MAX_RETRIES` is reached.

Render jobs are also keyed by renderer version. Render-all uses one generation-and-version-scoped job and keeps the project in `rendering` until every current clip has a current-version file. Completed current-version clips are skipped on retry; older renders are regenerated without losing an existing approval.

## Provider seams

`TranscriptProvider` and `ClipRanker` are small protocol contracts. YouTube sources preserve JSON3 word offsets while removing speaker-control marks and overlapping rolling-caption repeats. Local uploads are split into ten-minute mono audio chunks and request word- and segment-level speech timestamps. Word timings are stored with each readable transcript passage, so ranking still operates on complete ideas while rendering uses the precise speech timeline. A deterministic pass proposes non-overlapping windows and rejects sponsor language, then Sol makes the editorial selection and writes clean titles. If Sol is unavailable, the deterministic shortlist remains usable; uploads fail clearly when no transcription credential is configured rather than inventing transcript text.

Long series candidates are evaluated separately and are deliberately rare: Sol may select at most one compelling sustained scene per analysis and split it into three or four transcript-aligned parts. Every part counts against the requested clip total.

Long single-clip candidates are another deliberate exception. Sol may keep at most two unusually strong moments over 60 seconds intact in a large selection (one when fewer than ten clips were requested). Every individual clip has a hard 120-second ceiling; ordinary candidates remain capped at 55 seconds.

The renderer samples short frame bursts with OpenCV's frontal-face and profile-face detectors, using upper-body detection only as a fallback. When multiple people are visible, lower-face motion relative to the rest of each face identifies the likely active speaker; weak or ambiguous evidence stays with the confirmed speaker. Duplicate detections are removed, a new target must win twice, and the crop holds flat before making one eased 450 ms move. A detected camera cut resets the identity lock and snaps to the framing of the new shot instead of panning through it. Missing detections preserve the last stable framing; a centered frame is used only when no person is detected anywhere in the clip.

Every render builds an ASS subtitle track from the clip's word timeline. The project's source settings persist a Clean, Pulse, or Kinetic motion treatment, one of three bundled FFmpeg-safe typefaces, and a validated hex accent color. Phrase length changes with the motion level, and each event begins and ends on the source word timestamps with one active word highlighted. Sources without word metadata use a bounded per-cue estimate rather than stretching words across a multi-sentence passage.

## Publishing queue

Approved clips may be placed in `publication_schedules`. Automatic distribution spreads a selected set over one to seven local calendar days; manual drag-and-drop updates an individual scheduled date. Sol writes a short cover title and platform-neutral SEO caption, with deterministic copy as a fallback. Rows remain `queued` until a later platform integration publishes them.

## Current rendering and editing contracts

Renderer v19 analyzes per-clip scenes before composition. Simultaneously visible,
verified camera tiles may use Duo. Mouth-motion evidence chooses two participants;
it does not manufacture camera views from separate cuts. Automatic uncertain
shots use a filled speaker crop, not added empty letterboxing. Full frame is an
explicit source-preserving override over a blurred source backdrop. Three-pane
composition is not implemented. Visual heuristics do not guarantee speaker identity.

Silence ranges drive both video and audio trims, then concatenation. Captions use
the same retained timeline. Source-language caption selection, word timestamps,
caption cleanup, platform-safe margins, style/font/color/size/phrase controls,
and PNG watermark placement all feed the renderer.

Director Mode stores per-clip trims, text corrections, framing, and visual settings.
Apply to all shares visual defaults without overwriting other clips' cuts or
individual text corrections. Existing renders require rerendering after changes.

Brand folders supply initial platform/caption/watermark defaults. The new-film
form may explicitly override caption defaults. Projects preserve their watermark
file reference when a folder is soft-deleted and its films become unfiled.
Archive hides/restores items; Delete is soft removal retaining files/history.

Transcript, ranking, speaker tracking, and layout caches include relevant source,
range, model/settings, or version identity. Renderer versions invalidate stale MP4s.
Taste feedback and duplicate concepts are heuristic ranking inputs, not measured
performance data. Quality reports assist review rather than guarantee correctness.

The Cover Designer UI and ordinary cover-generation calls were removed. Legacy
cover schema/routes remain. Manual analytics were removed; real analytics remain
deferred. The calendar stores selected platforms but does not deliver to them.

## Distribution boundary

Public source is exported from an allowlist into a new Git repository, excluding
personal media/captures, environment secrets, design records, and local history.
The private backup preserves source history, not storage or Docker volumes.
The portable installer copies a blank-key environment template only if absent
and verifies five running services plus API/web HTTP readiness. It does not claim
provider/media-dependent functionality was tested.

## Deferred work

- Composio and social account authorization
- external platform publishing state machines
- analytics ingestion
- performance-based learning
- multi-tenant authentication and billing

Those systems must consume the approved export contract rather than reach into worker storage.
