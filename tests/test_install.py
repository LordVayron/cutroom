import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "cutroom_install", Path(__file__).resolve().parents[1] / "scripts" / "install.py"
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_existing_environment_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("PRIVATE_LOCAL_VALUE=keep", encoding="utf-8")
            self.assertFalse(installer.ensure_environment(root))
            self.assertEqual((root / ".env").read_text(), "PRIVATE_LOCAL_VALUE=keep")

    def test_empty_install_copies_template_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
            self.assertTrue(installer.ensure_environment(root))
            self.assertEqual((root / ".env").read_text(), "OPENAI_API_KEY=\n")
            self.assertFalse(installer.ensure_environment(root))

    def test_readiness_requires_worker_not_just_http(self):
        with patch.object(installer, "reachable", return_value=True), patch.object(
            installer, "run", return_value="postgres\nredis\napi\nweb"
        ), patch.object(installer.time, "monotonic", side_effect=[0, 0, 601]), patch.object(
            installer.time, "sleep"
        ):
            with self.assertRaises(RuntimeError):
                installer.wait_until_ready(timeout=600)

    def test_readiness_accepts_full_stack(self):
        with patch.object(installer, "reachable", return_value=True), patch.object(
            installer, "run", return_value="postgres\nredis\napi\nworker\nweb"
        ):
            installer.wait_until_ready(timeout=1)


if __name__ == "__main__":
    unittest.main()
