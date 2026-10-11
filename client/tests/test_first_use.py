"""The first `ucandrop on` sets up a fresh install without being asked.

Issue 12: on a fresh install the panel's switch refused with "Run: ucandrop
setup", but `ucandrop` reaches PATH only through `setup` itself, so the command
it named was not found. The first use has to install the receiving service and
the command on its own.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OMDROP = ROOT / "bin" / "ucandrop"

# A user systemd that knows a unit only once its file exists, and refuses to
# start anything, so the run stops right after setup with nothing left behind.
FAKE_SYSTEMCTL = """#!/bin/bash
unit="$XDG_CONFIG_HOME/systemd/user/ucandrop-receiver.service"
case " $* " in
  *" cat "*)       [[ -f "$unit" ]] ;;
  *" is-active "*) echo inactive; exit 3 ;;
  *" start "*)     exit 1 ;;
  *)               exit 0 ;;
esac
"""


class FirstUseTests(unittest.TestCase):
    def test_first_on_installs_the_service_and_the_command(self):
        with tempfile.TemporaryDirectory() as home:
            home = Path(home)
            # This test exercises setup's first-use path with an isolated
            # runtime. Copy the candidate tree and replace only the production
            # runtime guard in this fixture; no production escape hatch is
            # added to the command.
            plugin = home / "plugin"
            shutil.copytree(ROOT, plugin)
            command = plugin / "bin/ucandrop"
            source = command.read_text()
            start = source.index("require_canonical_runtime() {")
            end = source.index("\n}", start) + 2
            command.write_text(source[:start] + "require_canonical_runtime() { :; }" + source[end:])
            fakebin = home / "fakebin"
            fakebin.mkdir()
            for name, body in (("systemctl", FAKE_SYSTEMCTL),
                               ("systemd-run", "#!/bin/sh\nexit 1\n"),
                               ("pkexec", "#!/bin/sh\nexit 1\n")):
                (fakebin / name).write_text(body)
                (fakebin / name).chmod(0o755)
            # Its own runtime directory: `on` takes the identity lock and
            # writes the window file there, and must never touch the real one.
            runtime = home / "run"
            runtime.mkdir(mode=0o700)
            env = {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_BIN_HOME": str(home / ".local" / "bin"),
                "XDG_RUNTIME_DIR": str(runtime),
                "PATH": f"{fakebin}:{os.environ['PATH']}",
            }
            result = subprocess.run([str(command), "on", "1m"], env=env,
                                    capture_output=True, text=True, timeout=60)
            output = result.stdout + result.stderr

            self.assertNotIn("Run: ucandrop setup", output)
            self.assertTrue(
                (home / ".config/systemd/user/ucandrop-receiver.service").is_file(), output)
            link = home / ".local/bin/ucandrop"
            self.assertEqual(link.resolve(), command.resolve(), output)


if __name__ == "__main__":
    unittest.main()
