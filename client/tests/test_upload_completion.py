"""Real HTTPS regressions for the bundled UCanDrop receiver."""
import ast
import gzip
from pathlib import Path
import plistlib
import sys
import tempfile
import time
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_receiver_limits as limits
import test_receiver_protocol as protocol


CANDIDATE_RECEIVER = ROOT / "bin" / "airdrop-serve.py"


def compressed_dvzip(cpio):
    block = zlib.compress(cpio)
    return len(block).to_bytes(4, "big") + block


def write_fast_runner(path):
    """Create an isolated AST runner with a short body-read timeout."""
    source = CANDIDATE_RECEIVER.read_bytes()
    module = ast.parse(source, filename=str(CANDIDATE_RECEIVER))
    patch = ast.parse(
        """
_local_original_handler_setup = Handler.setup

def _local_fast_handler_setup(self):
    _local_original_handler_setup(self)
    self.request.settimeout(0.25)

Handler.setup = _local_fast_handler_setup
"""
    )
    for index, node in enumerate(module.body):
        if isinstance(node, ast.ClassDef) and node.name == "Handler":
            module.body[index + 1:index + 1] = patch.body
            break
    else:
        raise AssertionError("candidate receiver has no Handler class")
    ast.fix_missing_locations(module)
    runner = f"""#!/usr/bin/python3
import ast
import sys
from pathlib import Path

sys.path.insert(0, {str(ROOT / 'tests')!r})

source = Path({str(CANDIDATE_RECEIVER)!r})
module = ast.parse(source.read_bytes(), filename=str(source))
patch = ast.parse({ast.unparse(patch)!r})
for index, node in enumerate(module.body):
    if isinstance(node, ast.ClassDef) and node.name == "Handler":
        module.body[index + 1:index + 1] = patch.body
        break
else:
    raise SystemExit("candidate receiver has no Handler class")
ast.fix_missing_locations(module)
exec(compile(module, str(source), "exec"), {{
    "__name__": "__main__", "__file__": str(source),
}})
"""
    path.write_text(runner)
    path.chmod(0o700)


class FastCandidateRunnerMixin:
    """Run the bundled candidate with a short isolated body-read timeout."""

    @classmethod
    def setUpClass(cls):
        cls._runner_temp = tempfile.TemporaryDirectory()
        cls._runner_path = Path(cls._runner_temp.name) / "run-receiver.py"
        write_fast_runner(cls._runner_path)
        old = protocol.SERVE
        protocol.SERVE = cls._runner_path
        try:
            protocol.ReceiverFixture.setUpClass.__func__(cls)
        finally:
            protocol.SERVE = old

    @classmethod
    def tearDownClass(cls):
        try:
            protocol.ReceiverFixture.tearDownClass.__func__(cls)
        finally:
            cls._runner_temp.cleanup()


class LocalCompletionTests(FastCandidateRunnerMixin, protocol.ReceiverFixture):

    def setUp(self):
        for item in self.out.iterdir():
            item.unlink()

    def upload_entries(self, files, ending, total, *, wire=None):
        conn = self.connection()
        conn.timeout = 40
        ask = plistlib.dumps({
            "TransferType": {"files": 1}, "Items": [],
            "Files": [{"FileName": name, "FileType": "public.data",
                       "FileSize": len(data)} for name, data in files],
        }, fmt=plistlib.FMT_BINARY)
        self.assertEqual(self.post(conn, "/Ask", ask)[0], 200)
        if wire is None:
            wire = limits.stored_dvzip(limits.cpio_bytes(files))
        conn.putrequest("POST", "/Upload")
        conn.putheader("Content-Type", "application/x-dvzip")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.putheader("Connection", "keep-alive")
        conn.putheader("TotalBytes", str(total))
        conn.endheaders()
        started = time.monotonic()
        for offset in range(0, len(wire), 16371):
            chunk = wire[offset:offset + 16371]
            conn.send(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
        conn.send(ending)
        response = conn.getresponse()
        response.read()
        return conn, response, time.monotonic() - started

    def upload(self, payload, ending, total, *, wire=None):
        return self.upload_entries([("probe.bin", payload)], ending, total,
                                   wire=wire)

    def upload_with_delayed_end_marker(self, files, total, delay):
        """Send the complete archive, then a terminator after the grace period."""
        conn = self.connection()
        conn.timeout = 40
        ask = plistlib.dumps({
            "TransferType": {"files": 1}, "Items": [],
            "Files": [{"FileName": name, "FileType": "public.data",
                       "FileSize": len(data)} for name, data in files],
        }, fmt=plistlib.FMT_BINARY)
        self.assertEqual(self.post(conn, "/Ask", ask)[0], 200)
        wire = limits.stored_dvzip(limits.cpio_bytes(files))
        conn.putrequest("POST", "/Upload")
        conn.putheader("Content-Type", "application/x-dvzip")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.putheader("Connection", "keep-alive")
        conn.putheader("TotalBytes", str(total))
        conn.endheaders()
        started = time.monotonic()
        for offset in range(0, len(wire), 16371):
            chunk = wire[offset:offset + 16371]
            conn.send(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
        time.sleep(delay)
        try:
            conn.send(b"0\r\n\r\n")
        except OSError:
            # The receiver is allowed to close as soon as the verified archive
            # grace period expires. The response remains readable below.
            pass
        response = conn.getresponse()
        response.read()
        return conn, response, time.monotonic() - started

    def test_complete_large_archive_without_zero_chunk(self):
        payload = b"A" * 5_309_900
        _, response, elapsed = self.upload(payload, b"", len(payload))
        self.assertEqual(response.status, 200)
        self.assertTrue(response.will_close)
        self.assertLess(elapsed, 1)
        self.assertEqual((self.out / "probe.bin").read_bytes(), payload)

    def test_complete_archive_without_final_trailer_blank_line(self):
        payload = b"B" * 65536
        _, response, elapsed = self.upload(payload, b"0\r\n", len(payload))
        self.assertEqual(response.status, 200)
        self.assertTrue(response.will_close)
        self.assertLess(elapsed, 5)

    def test_delayed_end_marker_after_grace_stores_archive_and_closes(self):
        payload = b"delayed-end-marker" * 4096
        files = [("delayed.bin", payload)]
        _, response, elapsed = self.upload_with_delayed_end_marker(
            files, len(payload), 0.5)
        self.assertEqual(response.status, 200)
        self.assertTrue(response.will_close)
        self.assertLess(elapsed, 2)
        self.assertEqual((self.out / "delayed.bin").read_bytes(), payload)

        # A timed-out upload must not leave the HTTPS server's connection
        # handling wedged. A fresh TLS connection should still answer.
        self.assertEqual(self.post(self.connection(), "/Discover",
                                   plistlib.dumps({}))[0], 200)

    def test_normal_terminator_preserves_keep_alive(self):
        payload = b"C" * 5_309_900
        conn, response, _ = self.upload(payload, b"0\r\n\r\n", len(payload))
        self.assertEqual(response.status, 200)
        self.assertFalse(response.will_close)
        self.assertEqual(self.post(conn, "/Discover", plistlib.dumps({}))[0], 200)

    def test_wrong_declared_file_size_cannot_use_missing_tail_fallback(self):
        payload = b"D" * 8192
        before = set(self.out.iterdir())
        _, response, _ = self.upload(payload, b"", len(payload) - 1)
        self.assertEqual(response.status, 408)
        self.assertEqual(set(self.out.iterdir()), before)


class FastLocalCompletionTests(FastCandidateRunnerMixin, protocol.ReceiverFixture):
    """Completion regressions with an isolated 250 ms body-read timeout."""

    def setUp(self):
        for item in self.out.iterdir():
            item.unlink()

    def upload_entries(self, files, ending, total, *, wire=None):
        return LocalCompletionTests.upload_entries(self, files, ending, total,
                                                   wire=wire)

    def upload(self, payload, ending, total, *, wire=None):
        return LocalCompletionTests.upload(self, payload, ending, total,
                                           wire=wire)

    def test_compressed_ten_megabyte_archive_without_zero_chunk(self):
        payload = b"A" * 10_000_000
        wire = compressed_dvzip(limits.cpio_bytes([("large.bin", payload)]))
        self.assertLess(len(wire), len(payload))

        _, response, elapsed = self.upload_entries(
            [("large.bin", payload)], b"", len(payload), wire=wire)

        self.assertEqual(response.status, 200)
        self.assertTrue(response.will_close)
        self.assertLess(elapsed, 5)
        self.assertEqual((self.out / "large.bin").read_bytes(), payload)

    def test_compressed_four_member_archive_counts_only_media(self):
        files = [
            ("one.jpg", b"A" * 5_567_526),
            ("two.jpg", b"B" * 1_252_919),
            ("three.jpg", b"C" * 448_208),
            ("four.jpg", b"D" * 290_073),
            ("._four.jpg", b"M" * 10_000),
        ]
        media = [(name, data) for name, data in files
                 if not name.startswith("._")]
        total = sum(len(data) for _, data in media)
        wire = compressed_dvzip(limits.cpio_bytes(files))
        self.assertLess(len(wire), total)

        _, response, elapsed = self.upload_entries(
            files, b"", total, wire=wire)

        self.assertEqual(response.status, 200)
        self.assertTrue(response.will_close)
        self.assertLess(elapsed, 5)
        for name, data in media:
            self.assertEqual((self.out / name).read_bytes(), data)
        self.assertFalse((self.out / "._four.jpg").exists())

    def test_gzip_compressed_four_member_archive_without_zero_chunk(self):
        files = [
            ("one.jpg", b"A" * 5_567_526),
            ("two.jpg", b"B" * 1_252_919),
            ("three.jpg", b"C" * 448_208),
            ("four.jpg", b"D" * 290_073),
            ("._four.jpg", b"M" * 10_000),
        ]
        media = [(name, data) for name, data in files
                 if not name.startswith("._")]
        total = sum(len(data) for _, data in media)
        wire = gzip.compress(limits.cpio_bytes(files))
        self.assertLess(len(wire), total)

        _, response, elapsed = self.upload_entries(
            files, b"", total, wire=wire)

        self.assertEqual(response.status, 200)
        self.assertTrue(response.will_close)
        self.assertLess(elapsed, 5)
        for name, data in media:
            self.assertEqual((self.out / name).read_bytes(), data)
        self.assertFalse((self.out / "._four.jpg").exists())

    def test_truncated_compressed_archive_without_zero_chunk_is_rejected(self):
        payload = b"E" * 65_536
        complete = compressed_dvzip(limits.cpio_bytes([("short.bin", payload)]))
        wire = complete[:-4]
        self.assertLess(len(wire), len(payload))
        before = set(self.out.iterdir())

        _, response, elapsed = self.upload_entries(
            [("short.bin", payload)], b"", len(payload), wire=wire)

        self.assertEqual(response.status, 408)
        self.assertLess(elapsed, 3)
        self.assertEqual(set(self.out.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
