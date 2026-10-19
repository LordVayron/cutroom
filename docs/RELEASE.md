# Source distribution and privacy

The public Cutroom source is a clean snapshot, not a clone of the private
development Git history. Its initial commit uses generic project attribution.
MIT permits installation/modification/redistribution subject to LICENSE.

## Included

Application source, dependencies/lockfile, migrations, tests, empty environment
template, generic wordmark, Docker configuration, installer, agent guidance,
architecture, setup, security, feature status, and changelog.

## Excluded

Personal account/contact information in files, machine-specific paths, local
environment values, tokens, media, transcripts, rendered clips, caches,
database dumps/volumes, design concepts, episode screenshots, provider job
records, personal shortcuts, and original commit history.

The GitHub account owning the repository is necessarily visible in its URL.
That URL is not a promise that local machine/account information is included.

The private source backup preserves tracked source/design history, but still
excludes active credentials, untracked personal assets, storage, and Docker data.
It is not a full machine or media backup.

## Verification boundary

Source/history scanning uses credential patterns and configured local secrets.
The public snapshot also checks personal path/contact/name patterns, uses an
allowlist, and omits private screenshots rather than trying to redact their pixels.
Automated scans reduce risk but do not prove absence of every possible secret.

Fresh source tests and setup checks must be recorded separately from provider
transcription/ranking or media-processing tests. Never claim unattended setup on
every OS or a new end-to-end clip without actually verifying it.

Do not publish future private history into this repository through a merge or
force push. Prepare and review a clean release again.
