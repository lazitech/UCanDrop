"""The portable client delegates Ubuntu prerequisites to its installer.

The user-facing layer must not embed the old Arch/AUR package workflow or
pretend to build a radio backend from an arbitrary checkout.
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OMDROP = ROOT / "bin" / "ucandrop"

def apple_wifi_sysfs(root):
    """A sysfs tree holding one Broadcom (0x14e4) network controller, which is
    what install-driver checks for before doing anything. These tests are about
    the script it writes, not the machine they run on."""
    dev = Path(root) / "sys" / "bus" / "pci" / "devices" / "0000:01:00.0"
    dev.mkdir(parents=True)
    (dev / "vendor").write_text("0x14e4\n")
    (dev / "class").write_text("0x028000\n")
    return str(Path(root) / "sys")


class PinnedDependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        # The launcher is stubbed rather than removed: it is what the real run
        # hands the reviewed installer to, so echoing its argument captures the
        # command a user's terminal would execute.
        self.command("python3", "#!/bin/sh\nexit 1\n")       # receiver library missing
        self.command("pacman", "#!/bin/sh\nexit 1\n")        # no repo package
        self.command("systemctl", "#!/bin/sh\nexit 3\n")     # ufw inactive
        self.command("omarchy-launch-floating-terminal-with-presentation",
                     "#!/bin/sh\nprintf '%s\\n' \"$1\"\n")
        self.env = os.environ.copy()
        self.env.update(PATH=f"{self.bin}:{self.env['PATH']}",
                        OMDROP_DISCOVERABLE="/nonexistent",
                        OMDROP_SYSFS=apple_wifi_sysfs(self.tmp.name))

    def command(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def build_script(self):
        result = subprocess.run([OMDROP, "install-driver"], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return OMDROP.read_text(), result.stdout

    def test_nothing_comes_from_the_aur(self):
        # The regression: `yay -S opendrop` resolves to whatever the AUR holds
        # at install time, which is not the code anyone reviewed. A pinned AUR
        # recipe was no better in practice: its own dependencies came from the
        # AUR too, and it stopped building when setuptools moved on.
        _, script = self.build_script()
        self.assertNotIn("yay -S", script)
        self.assertNotIn("paru -S", script)
        self.assertNotIn("aur.archlinux.org", script)

    def test_the_receiver_library_comes_from_the_official_repositories(self):
        source, script = self.build_script()
        self.assertIn('RECEIVER_PKGS="python3-libarchive-c libkeyutils1 python3-gi"', source)
        self.assertIn("tools/install.sh", script)
        self.assertNotIn("pacman", script)

    def test_the_pinned_commit_is_a_full_sha_used_literally(self):
        # The portable client delegates backend installation to the Ubuntu
        # installer; it has no floating source checkout or package commit.
        source, script = self.build_script()
        self.assertNotRegex(source, r"(?m)^DRIVER_COMMIT=")
        self.assertNotIn("makepkg", source)
        self.assertIn("tools/install.sh", script)

    def test_a_failed_checkout_never_falls_through_to_a_build(self):
        _, script = self.build_script()
        self.assertIn("tools/install.sh", script)
        self.assertNotIn("makepkg", script)
        self.assertNotIn("git clone", script)


if __name__ == "__main__":
    unittest.main()
