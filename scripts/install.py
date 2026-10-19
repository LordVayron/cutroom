"""Non-destructive local setup helper; no third-party Python packages required."""
import argparse
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = {"postgres", "redis", "api", "worker", "web"}


def run(arguments, root=ROOT, timeout=45):
    return subprocess.run(
        arguments, cwd=root, check=True, text=True, capture_output=True, timeout=timeout
    ).stdout.strip()


def ensure_environment(root=ROOT):
    destination = root / ".env"
    if destination.exists():
        return False
    # Exclusive creation: never overwrite a key or a concurrently created file.
    try:
        with destination.open("x", encoding="utf-8") as output:
            output.write((root / ".env.example").read_text(encoding="utf-8"))
    except FileExistsError:
        return False
    return True


def prerequisites(root=ROOT):
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer is required.")
    for command in ("git", "docker"):
        if not shutil.which(command):
            raise RuntimeError(f"{command} is missing. Install it, then retry.")
    run(["git", "--version"], root)
    run(["docker", "compose", "version"], root)
    run(["docker", "info", "--format", "{{.ServerVersion}}"], root)
    print("Git, Python, Docker Engine, and Compose are available.")


def reachable(url):
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def wait_until_ready(root=ROOT, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if reachable("http://localhost:8000/health") and reachable("http://localhost:3000"):
            running = set(run([
                "docker", "compose", "ps", "--services", "--status", "running"
            ], root).splitlines())
            if SERVICES.issubset(running):
                return
        time.sleep(2)
    raise RuntimeError("Startup timed out. Inspect docker compose ps and private container logs.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check", action="store_true", help="Read-only prerequisite check")
    actions.add_argument("--start", action="store_true", help="Build/start local Docker services")
    parser.add_argument("--no-browser", action="store_true")
    options = parser.parse_args()
    try:
        prerequisites()
        if options.check:
            print("No files changed. Provider credentials and media have not been tested.")
            return 0
        print("Created local .env from template." if ensure_environment() else "Preserved existing .env.")
        print("Building and starting Docker services; this may take several minutes.")
        subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT, check=True)
        wait_until_ready()
        print("API, website, and all five services are running at http://localhost:3000")
        print("Startup verified. Ingestion/rendering still require authorized media and any needed key.")
        if not options.no_browser:
            webbrowser.open("http://localhost:3000")
        return 0
    except (RuntimeError, subprocess.SubprocessError, OSError):
        # Avoid dumping environment/provider values or private container output.
        print(
            "Setup did not complete. Check Docker availability, port conflicts, and "
            "docs/SETUP.md. No existing environment files or data were removed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
