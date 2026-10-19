# Security and privacy

Cutroom targets a trusted single-user local machine. There is no production
authentication or tenant isolation. Do not expose it publicly or interpret a
calendar entry as an externally published social post.

- Keep keys in private local .env/secret stores, not chats, issues, or Git.
- Exclude OAuth sessions, .vercel files, database dumps, media, transcripts,
  and episode screenshots from releases.
- Revoke/rotate credentials exposed in chat, logs, or history.
- Private GitHub repositories are not secret stores.
- Public source uses clean history and generic author attribution.
- Source backups omit .env, local media, and Docker volumes. Back those up
  separately through a private local backup process.

Archive retains data. Delete is soft removal, not secure erasure; folder deletion
unfiles films. Do not erase logos while films still reference them.
Process only authorized content. Provider-backed transcription/ranking transmits
audio/transcripts to the configured provider; review costs and limits.

Do not put secrets, private footage, local paths, screenshots, or database exports
in public bug reports. Use synthetic examples. Contact the maintainer privately
through GitHub for sensitive vulnerabilities before posting exploit details.
