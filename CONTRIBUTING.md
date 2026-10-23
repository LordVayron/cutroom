# Contributing to Cutroom

Thanks for helping make the editing room better. Begin with [AGENTS.md](AGENTS.md),
[Setup](docs/SETUP.md), [Features](docs/FEATURES.md), and
[Architecture](docs/architecture.md).

## A safe development workflow

1. Create a new checkout and a focused branch. Preserve existing installations.
2. Run `python scripts/install.py --check` before starting the app.
3. Enter any provider keys locally in `.env`; never put them in chat or Git.
4. Keep changes small and include regression tests and relevant documentation.
5. State exactly what you tested and which checks require credentials or media.

Use the verification commands in the [README](README.md#verify). Stop the web
service before production builds so the build does not collide with its live
development directory. Do not delete storage, volumes, or databases to fix tests.

## Change delivery

Develop each focused change on a typed branch from the current remote main.
Use Conventional Commit titles and a matching PR title. Describe the technical
change and rationale, not conversational context. Classify each nonempty PR body
line with [public] or [private] and include a CHANGELOG entry in the same change.

Private review precedes a separately filtered public-source review. Each merge
requires explicit maintainer approval and passing policy and application checks.
Use squash merging; branch removal and repository-setting changes require
separate authorization. Do not publish local work until release is authorized.

Run `python -m unittest discover -s tests -v` and
`python scripts/check_repository.py --base backup/main --working-tree` locally
in the private checkout. In public clones use `origin/main` and `--audience public`.
The scanner checks new commits, including intermediate file versions; it is not
a proof that every possible secret or private concept can be recognized.

Keep the Git author associated with a verified maintainer account. Historical
commits are not rewritten by these checks. Release versioning and source privacy
require human review even when automated checks pass.

## Application contracts

- Keep audio and video on one edit timeline and captions in the source language.
- Preserve safe caption placement, approvals, branding, retries, and job fencing.
- Add migrations for schema changes; never rewrite an applied migration.
- Bump the renderer version and add regression tests for rendering changes.
- Keep API schemas, frontend types, tests, and documentation consistent.

## Public issues and screenshots

Use fictional demo data. Do not upload real episodes, transcripts, private source
URLs, local paths, databases, logs with secrets, or provider job records. Redact
diagnostics before sharing. Report vulnerabilities through [SECURITY.md](SECURITY.md),
not public issues. Contributions are made under the repository's [MIT license](LICENSE).
