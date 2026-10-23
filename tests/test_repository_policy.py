import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "repository_policy", Path(__file__).resolve().parents[1] / "scripts" / "check_repository.py"
)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


class PolicyTests(unittest.TestCase):
    def test_conventional_titles_and_limits(self):
        self.assertFalse(policy.title_errors("ci: validate repository changes", 64))
        self.assertTrue(policy.title_errors("Improve repository checks", 64))
        self.assertTrue(policy.title_errors("docs: " + "a" * 58, 64))
        self.assertFalse(policy.title_errors("fix(api): preserve approvals", 72))

    def test_detects_secrets_without_echoing_the_match(self):
        secret = b"sk-" + b"x" * 35
        errors = policy.content_errors(secret)
        self.assertIn("Credential-like content", errors)
        self.assertNotIn(secret.decode(), str(errors))
        self.assertFalse(policy.content_errors(b"OPENAI_API_KEY="))

    def test_detects_personal_paths_and_context_attribution(self):
        personal = b"C:" + b"\\" + b"Users" + b"\\" + b"sample"
        self.assertIn("Personal filesystem path", policy.content_errors(personal))
        self.assertTrue(policy.content_errors(b"user " + b"requested a change"))

    def test_blocks_runtime_files_and_large_assets(self):
        for name in [".env", "apps/web/.env.local", "key.pfx", "data.db", "copy.bak"]:
            self.assertTrue(policy.file_errors(name, b""), name)
        self.assertFalse(policy.file_errors(".env.example", b"OPENAI_API_KEY="))
        self.assertTrue(policy.file_errors("large.bin", b"x" * (policy.MAX_BYTES + 1)))

    def test_public_scope_and_email_checks(self):
        self.assertTrue(policy.file_errors("design/draft.md", b"draft", public=True))
        self.assertFalse(policy.file_errors("design/draft.md", b"draft", public=False))
        self.assertFalse(policy.file_errors("storage/.gitkeep", b"", public=True))
        self.assertTrue(policy.file_errors("README.md", b"person" + b"@mail.test", public=True))
        self.assertFalse(policy.file_errors("test.py", b"person" + b"@sample.invalid", public=True))

    def test_pr_requires_scope_labels_and_main(self):
        pr = {"title": "ci: validate source changes", "body": "[public] Change: add checks.\n[private] Scope: none.",
              "head": {"ref": "ci/repository-policy"}, "base": {"ref": "main"}}
        self.assertFalse(policy.pr_errors(pr))
        self.assertTrue(policy.pr_errors({**pr, "body": "Unclassified change"}))
        self.assertTrue(policy.pr_errors({**pr, "base": {"ref": "master"}}))
        self.assertTrue(policy.pr_errors({**pr, "head": {"ref": "misc"}}))


class GitRangeTests(unittest.TestCase):
    def test_intermediate_secret_cannot_be_hidden_by_a_later_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)

            def commit(message):
                git("add", ".")
                git("-c", "user.name=Test", "-c", "user.email=test@sample.invalid", "commit", "-m", message)

            git("init", "-q")
            (root / "README.md").write_text("Example\n")
            commit("docs: describe example")
            base = git("rev-parse", "HEAD").decode().strip()
            (root / "sample.txt").write_text("sk-" + "x" * 35)
            (root / "CHANGELOG.md").write_text("## Unreleased\n")
            commit("test: add fixture")
            (root / "sample.txt").write_text("sanitized\n")
            commit("test: sanitize fixture")
            with patch.object(policy, "ROOT", root):
                errors = policy.check_range(base)
            self.assertTrue(any("Credential-like content" in error for error in errors))
            self.assertNotIn("x" * 35, str(errors))

    def test_deletion_requires_a_changelog_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "sample.txt").write_text("example")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@sample.invalid",
                            "commit", "-qm", "test: add fixture"], cwd=root, check=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
            (root / "sample.txt").unlink()
            with patch.object(policy, "ROOT", root):
                errors = policy.check_range(base, working=True)
            self.assertIn("Include a CHANGELOG.md entry in the same change", errors)


if __name__ == "__main__":
    unittest.main()
