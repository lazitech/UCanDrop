"""Changing the saved audience must not restart a live receiver.

The receiver reads the audience file for each request.  `cmd_visibility` only
needs to persist the choice; an active service's ``start`` is a no-op, while a
restart would drop the receiver's loaded identity and discovery window.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OMDROP = ROOT / "bin" / "ucandrop"


class VisibilityCommandTests(unittest.TestCase):
    def run_visibility(self, active, *modes, initial=None):
        source = OMDROP.read_text()
        start = source.index("cmd_visibility() {")
        end = source.index("\n}\n\n# An Apple ID is an email address", start) + 2
        fragment = source[start:end]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contacts = root / "omdrop"
            contacts.mkdir()
            if initial == "contacts":
                (contacts / "visibility").write_text("contacts\n")
            capture = root / "systemctl-events"
            env = os.environ.copy()
            env.update(CONTACTS_DIR=str(contacts), CAPTURE=str(capture),
                       ACTIVE="1" if active else "0")
            harness = f"""
set -u
UNIT=ucandrop-receiver.service
receiving() {{ [[ "$ACTIVE" == 1 ]]; }}
systemctl() {{ printf '%s\\n' "$*" >> "$CAPTURE"; }}
sender_count() {{ printf '2\\n'; }}
die() {{ printf 'die %s\\n' "$*" >> "$CAPTURE"; return 9; }}
{fragment}
"""
            for mode in modes:
                harness += f'cmd_visibility {mode}\n'
            result = subprocess.run(["bash", "-c", harness], env=env,
                                    capture_output=True, text=True)
            events = capture.read_text().splitlines() if capture.exists() else []
            saved = ((contacts / "visibility").read_text().strip()
                     if (contacts / "visibility").exists() else "everyone")
            return result, events, saved

    def test_active_everyone_is_a_noop_without_a_restart(self):
        result, events, saved = self.run_visibility(True, "everyone", "everyone")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, [
            "--user start ucandrop-receiver.service",
            "--user start ucandrop-receiver.service",
        ])
        self.assertEqual(saved, "everyone")

    def test_active_contacts_change_uses_start_without_a_restart(self):
        result, events, saved = self.run_visibility(True, "contacts", "everyone")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, [
            "--user start ucandrop-receiver.service",
            "--user start ucandrop-receiver.service",
        ])
        self.assertEqual(saved, "everyone")

    def test_inactive_visibility_change_does_not_start_the_receiver(self):
        result, events, saved = self.run_visibility(False, "contacts", "everyone")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, [])
        self.assertEqual(saved, "everyone")


if __name__ == "__main__":
    unittest.main()
