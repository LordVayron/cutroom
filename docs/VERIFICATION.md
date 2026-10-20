# Release verification

## Completed locally

- Four non-destructive installer regression tests pass.
- Python source and test syntax compilation passes in the clean export.
- Source/history credential scan reports no matches for its configured patterns.
- Public allowlist/personal-pattern scan reports no matches.
- Original application backend suite passed: 76 tests, plus backend lint.

## Independent clean check

Passed on 2026-10-19 for public source commit `9e5b626`:
[Clean source verification](https://github.com/LordVayron/cutroom/actions/runs/39313698543).
This includes fresh backend/frontend images, installer tests, backend tests/lint,
frontend tests/lint, and the frontend production build. A fresh public clone also
passed the four installer tests and Python syntax compilation locally.

The Clean source verification GitHub Actions workflow builds fresh backend and
frontend images, runs backend/frontend tests and lint, and builds the frontend.
It has read-only repository permissions, no provider credentials, no private
media, and no deployment step. Check the current Actions result rather than
assuming a workflow file proves successful execution.

The original local Docker build could not be confirmed after Docker Desktop
stopped. No database or media was deleted to repair it.

Neither source tests nor successful startup prove a new user's real source can
be downloaded/transcribed/rendered. That remains dependent on authorized media,
caption availability, provider access, and source-specific human review.

## Calendar removal — 2026-10-20

The public source snapshot passed 78 backend tests, including checks that
schedule-writing routes are absent and approval/export routes remain.
Branded screenshots use fictional data and show the calendar-free workspace.
No private media, provider calls, or real-source renders were needed for removal.
