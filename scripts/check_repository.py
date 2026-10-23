"""Validate new repository changes without displaying sensitive matches."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
TYPES = "feat|fix|docs|refactor|perf|test|ci|chore|release"
TITLE = re.compile(rf"^(?:{TYPES})(?:\([a-z0-9-]+\))?!?: \S.*$")
BRANCH = re.compile(rf"^(?:{TYPES})/[a-z0-9][a-z0-9/-]*$")
TOKENS = re.compile(
    rb"(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{40,255}|"
    rb"sk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,255}|AKIA[0-9A-Z]{16}|"
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)
PATHS = re.compile(rb"(?:[A-Z]:[\\/]Users[\\/]|/(?:Users|home)/)", re.I)
EMAILS = re.compile(rb"[A-Z0-9._%+-]{1,128}@[A-Z0-9.-]{1,128}\.[A-Z]{2,16}", re.I)
DIRECTIVES = re.compile(
    rb"(?:user\s+(?:asked|requested)|as\s+requested|per\s+(?:the\s+)?user|"
    rb"el\s+usuario\s+(?:pidio|pidi\xc3\xb3))", re.I
)
MAX_BYTES = 5 * 1024 * 1024


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def title_errors(value, limit):
    errors = []
    if not TITLE.fullmatch(value) or len(value) >= limit:
        errors.append("Use a Conventional Commit title within the length limit")
    return errors


def content_errors(data):
    errors = []
    if TOKENS.search(data):
        errors.append("Credential-like content")
    if PATHS.search(data):
        errors.append("Personal filesystem path")
    if DIRECTIVES.search(data):
        errors.append("Conversational instruction attribution")
    if len(data) > MAX_BYTES:
        errors.append("File exceeds the 5 MiB source limit")
    return errors


def file_errors(name, data, public=False):
    errors = content_errors(data)
    parts = PurePosixPath(name).parts
    basename = parts[-1]
    runtime = {"node_modules", ".next", ".vercel", "__pycache__", ".venv"}
    suffixes = {".key", ".pem", ".p12", ".pfx", ".sqlite3", ".db", ".dump", ".bak", ".log"}
    suffixes.update({
        ".sqlite", ".orig", ".old", ".tmp", ".zip", ".7z", ".rar", ".tar", ".gz",
        ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mp3", ".wav",
        ".m4a", ".flac", ".aac", ".ogg",
    })
    if ((basename == ".env" or basename.startswith(".env.")) and basename != ".env.example"
            or runtime.intersection(parts) or PurePosixPath(name).suffix.lower() in suffixes):
        errors.append("Credential, runtime, or backup file")
    if public:
        if parts[0] in {"design", "storage", "private"} and name != "storage/.gitkeep":
            errors.append("Private or runtime material in public source")
        for match in EMAILS.finditer(data):
            if not match.group().lower().endswith((b".invalid", b"@example.com")):
                errors.append("Email address in public source")
                break
    return errors


def pr_errors(pr):
    errors = title_errors(pr.get("title", ""), 64)
    if pr.get("base", {}).get("ref") != "main":
        errors.append("Pull requests must target main")
    if not BRANCH.fullmatch(pr.get("head", {}).get("ref", "")):
        errors.append("Use a typed, focused branch name")
    lines = [line.strip() for line in (pr.get("body") or "").splitlines() if line.strip()]
    if not lines or any(not re.match(r"^\[(?:public|private)\] \S", line) for line in lines):
        errors.append("Classify every PR body line as [public] or [private]")
    errors.extend(content_errors((pr.get("title", "") + "\n" + (pr.get("body") or "")).encode()))
    return errors


def changed_names(base, head):
    return git("diff", "--name-only", "-z", base, head).decode().split("\0")[:-1]


def check_range(base, public=False, working=False):
    errors = []
    commits = git("rev-list", f"{base}..HEAD").decode().splitlines()
    seen = set()
    for commit in commits:
        message = git("show", "-s", "--format=%B", commit).decode().strip()
        errors += [f"{commit[:8]}: {error}" for error in title_errors(message.splitlines()[0], 72)]
        errors += [f"{commit[:8]} metadata: {error}" for error in content_errors(message.encode())]
        names = git("diff-tree", "--root", "--no-commit-id", "--name-only", "--diff-filter=ACMR", "-r", "-z", commit).decode().split("\0")[:-1]
        for name in names:
            identity = git("rev-parse", f"{commit}:{name}").strip()
            if (name, identity) in seen:
                continue
            seen.add((name, identity))
            data = git("show", f"{commit}:{name}")
            errors += [f"{commit[:8]} {name}: {error}" for error in file_errors(name, data, public)]
    names = changed_names(base, "HEAD")
    if working:
        names += git("diff", "--name-only", "-z", "HEAD").decode().split("\0")[:-1]
        names += git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")[:-1]
        for name in set(names):
            path = ROOT / name
            if path.is_symlink():
                errors.append(f"{name}: Symlink requires manual review")
            elif path.is_file():
                errors += [f"{name}: {error}" for error in file_errors(name, path.read_bytes(), public)]
    if names and "CHANGELOG.md" not in names:
        errors.append("Include a CHANGELOG.md entry in the same change")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--audience", choices=["private", "public"], default="private")
    parser.add_argument("--working-tree", action="store_true")
    args = parser.parse_args()
    base = git("rev-parse", "--verify", "--end-of-options", f"{args.base}^{{commit}}").decode().strip()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()) if os.getenv("GITHUB_EVENT_PATH") else {}
    pr = event.get("pull_request")
    errors = check_range(base, args.audience == "public", args.working_tree)
    if pr:
        errors += pr_errors(pr)
    if errors:
        for error in sorted(set(errors)):
            print(error)
        return 1
    print("Repository policy passed; no matched values were printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
