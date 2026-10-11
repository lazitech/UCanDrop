"""A one-file window has to actually close after its one file.

2026-09-17, twice: the watcher announced the file it had stored and stopped,
and the receiver stayed listening -- so the next sender got in too. `off`
calls `cancel_window`, which stops `ucandrop-watch.service`; the watcher was
running INSIDE that service, so systemd killed its cgroup partway through the
shutdown it had just started. The close has to outlive the watcher.
"""

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OMDROP = ROOT / "bin" / "ucandrop"


class OneFileShutdownTests(unittest.TestCase):
    def run_watch(self, once=True):
        source = OMDROP.read_text()
        start = source.index("cmd_watch() {")
        fragment = source[start:source.index("\n# The URL inside", start)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arrived = root / "arrived.jpg"
            arrived.write_text("x")
            capture = root / "events"
            fakebin = root / "fakebin"
            fakebin.mkdir()
            stored = f"upload ABC: stored {arrived}"
            event = json.dumps({
                "v": 1,
                "event": "complete",
                "id": "once-test-transfer",
                "sender": "iPhone test",
                "names": [arrived.name],
                "paths": [str(arrived)],
                "received": 1,
                "total": 1,
                "ts": 0,
            }, ensure_ascii=False, separators=(",", ":"))
            complete = f"OMDROP_EVENT {event}"
            lines = " ".join(
                shlex.quote(line) for line in (stored, complete)
            )
            # receive_notify.py calls systemd-run through Python's PATH, so a
            # shell function in the surrounding harness would not intercept
            # it. This executable records the arguments and exits; it never
            # contacts the user's systemd manager.
            systemd_run_spy = fakebin / "systemd-run"
            systemd_run_spy.write_text(
                "#!/bin/sh\n"
                "printf 'systemd-run' >> \"$CAPTURE\"\n"
                "for arg do printf ' %s' \"$arg\" >> \"$CAPTURE\"; done\n"
                "printf '\\n' >> \"$CAPTURE\"\n",
                encoding="utf-8",
            )
            systemd_run_spy.chmod(0o755)
            harness = f"""
set -uo pipefail
SELF={shlex.quote(str(root / 'omdrop'))}
PROJ={shlex.quote(str(ROOT))}
UNIT=ucandrop-receiver.service
CAPTURE={shlex.quote(str(capture))}
effective_dir(){{ printf '%s' {shlex.quote(str(root))}; }}
journalctl(){{ printf '%s\\n' {lines}; }}
{fragment}
cmd_watch {"--once" if once else ""}
"""
            # $SELF is invoked directly for `handle`, and must be a real file.
            self_stub = root / "omdrop"
            self_stub.write_text(
                "#!/bin/sh\n"
                "printf 'self %s\\n' \"$*\" >> \"$CAPTURE\"\n",
                encoding="utf-8",
            )
            self_stub.chmod(0o755)
            env = os.environ.copy()
            env["CAPTURE"] = str(capture)
            env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
            result = subprocess.run(["bash", "-c", harness], env=env,
                                    capture_output=True, text=True)
            events = capture.read_text() if capture.exists() else ""
            return result, events, arrived

    def test_the_close_outlives_the_watcher_that_asked_for_it(self):
        # The regression: `off` ran as a child of the unit `off` stops, so it
        # died with it and the receiver was never stopped.
        result, events, arrived = self.run_watch(once=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [line for line in events.splitlines() if line.startswith("self ")],
            [f"self handle {arrived}"],
        )
        self.assertRegex(
            events,
            r"systemd-run .*--user .*--quiet .*--collect .* off --force",
        )

    def test_an_ordinary_window_is_not_closed_by_an_arrival(self):
        result, events, arrived = self.run_watch(once=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [line for line in events.splitlines() if line.startswith("self ")],
            [f"self handle {arrived}"],
        )
        self.assertNotIn("systemd-run", events)
        self.assertNotIn(" off ", events)


if __name__ == "__main__":
    unittest.main()
