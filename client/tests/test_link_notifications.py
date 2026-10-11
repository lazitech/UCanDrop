"""Use the real volatile socket listener, without notifying the user's desktop."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
from web_links import link_message, link_socket_address


class LinkNotificationTests(unittest.TestCase):
    def test_ready_marker_is_written_after_binding_and_removed_on_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = root / "ucandrop" / "watch-ready"
            ready.parent.mkdir()
            env = {**os.environ, "XDG_RUNTIME_DIR": str(root)}
            watcher = subprocess.Popen([
                "/usr/bin/python3", str(BIN / "receive_notify.py"),
                "--opener", "/bin/true", "--ready-file", str(ready)
            ], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
               stderr=subprocess.PIPE, env=env)
            try:
                deadline = time.monotonic() + 3
                while not ready.is_file():
                    if time.monotonic() > deadline:
                        self.fail("notification listener did not publish readiness")
                    time.sleep(0.02)
                self.assertEqual(ready.read_text(), "ready\n")
                watcher.stdin.close()
                watcher.stdin = None
                watcher.wait(timeout=3)
                self.assertEqual(watcher.returncode, 0)
                self.assertFalse(ready.exists())
            finally:
                if watcher.poll() is None:
                    watcher.terminate()
                watcher.communicate(timeout=3)

    def test_link_once_closes_without_waiting_for_a_file_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            capture = root / "calls"
            opener = root / "opener"
            opener.write_text(
                "#!/usr/bin/python3\nimport json,os,sys\n"
                "with open(os.environ['CAPTURE'], 'a') as f:\n"
                " f.write(json.dumps(sys.argv[1:]) + '\\n')\n")
            opener.chmod(0o755)
            runner = root / "bin/systemd-run"
            runner.write_text(f"#!/bin/sh\nexec '{opener}' shutdown \"$@\"\n")
            runner.chmod(0o755)
            env = {**os.environ, "CAPTURE": str(capture), "XDG_RUNTIME_DIR": str(root),
                   "PATH": f"{root / 'bin'}:{os.environ['PATH']}"}
            watcher = subprocess.Popen([
                "/usr/bin/python3", str(BIN / "receive_notify.py"),
                "--opener", str(opener), "--once"], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            try:
                url = "https://example.test/once"
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
                    deadline = time.monotonic() + 3
                    while True:
                        try:
                            sender.sendto(link_message("one", [url]), link_socket_address(str(root)))
                            break
                        except OSError:
                            if time.monotonic() > deadline:
                                self.fail("notification listener did not become ready")
                            time.sleep(0.02)
                watcher.wait(timeout=3)
                self.assertEqual(watcher.returncode, 0)
                calls = [json.loads(line) for line in capture.read_text().splitlines()]
                self.assertEqual(calls[0], ["handle-url", url])
                self.assertEqual(calls[1][0], "shutdown")
                self.assertEqual(calls[1][-2:], ["off", "--force"])
            finally:
                if watcher.poll() is None:
                    watcher.terminate()
                watcher.communicate(timeout=3)

    def test_links_group_deduplicate_and_invalid_packets_do_not_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "calls"
            opener = root / "opener"
            opener.write_text(
                "#!/usr/bin/python3\nimport json,os,sys\n"
                "with open(os.environ['CAPTURE'], 'a') as f:\n"
                " f.write(json.dumps(sys.argv[1:]) + '\\n')\n")
            opener.chmod(0o755)
            env = {**os.environ, "CAPTURE": str(capture), "XDG_RUNTIME_DIR": str(root)}
            watcher = subprocess.Popen([
                "/usr/bin/python3", str(BIN / "receive_notify.py"),
                "--opener", str(opener)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            try:
                urls = ["https://first.example.test/a?q=1#part",
                        "https://second.example.test/b"]
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
                    deadline = time.monotonic() + 3
                    while True:
                        try:
                            sender.sendto(link_message("one", urls), link_socket_address(str(root)))
                            break
                        except OSError:
                            if time.monotonic() > deadline:
                                self.fail("notification listener did not become ready")
                            time.sleep(0.02)
                    sender.sendto(link_message("one", urls), link_socket_address(str(root)))
                    sender.sendto(b'{"id":"bad","urls":["javascript:alert(1)"]}',
                                  link_socket_address(str(root)))
                    # This later packet is a barrier proving the prior duplicate
                    # and invalid packet have both passed through the listener.
                    sender.sendto(link_message("two", [urls[1]]), link_socket_address(str(root)))
                deadline = time.monotonic() + 3
                calls = []
                while time.monotonic() < deadline:
                    if capture.exists():
                        calls = [json.loads(line) for line in capture.read_text().splitlines()]
                        if len(calls) >= 2:
                            break
                    time.sleep(0.02)
                self.assertEqual(calls, [["handle-url", *urls], ["handle-url", urls[1]]])
                self.assertFalse(list(root.glob("*.url")))
                self.assertFalse(list(root.glob("*.webloc")))
            finally:
                watcher.stdin.close()
                watcher.stdin = None
                out, error = watcher.communicate(timeout=3)
                self.assertEqual(watcher.returncode, 0, out + error)


if __name__ == "__main__":
    unittest.main()
