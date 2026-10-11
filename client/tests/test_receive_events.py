"""Lifecycle events emitted by the real AirDrop receiver.

The integration cases deliberately use the same TLS fixture as the protocol
tests: event shape is useful only when it follows the actual Ask/Upload
connection and the output files that the receiver stores.
"""

import json
import io
import logging
import os
import re
import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(Path(__file__).parent))

import receive_events
from test_receiver_protocol import ReceiverFixture, dvzip
from test_receiver_limits import receiver_namespace


def events_from(log):
    events = []
    for line in log.read_text().splitlines():
        marker = "OMDROP_EVENT "
        if marker in line:
            payload = line.split(marker, 1)[1]
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


def wait_for_events(log, count, start=0):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        found = events_from(log)
        if len(found) >= start + count:
            return found[start:]
        time.sleep(0.02)
    return events_from(log)[start:]


class EventSchemaTests(unittest.TestCase):
    def test_event_variants_have_bounded_shape_and_paths_only_on_complete(self):
        transfer_id = receive_events.new_id()
        self.assertRegex(transfer_id, r"^[0-9a-f]{32}$")
        for kind in ("incoming", "progress", "failed"):
            event = receive_events.make(
                kind, transfer_id, sender="sender", names=["one"],
                paths=["/should/not/be-present"], received=3, total=None,
                error="bad")
            self.assertEqual(set(event), {
                "v", "event", "id", "sender", "names", "received",
                "total", "ts", "error"} if kind == "failed" else {
                    "v", "event", "id", "sender", "names", "received",
                    "total", "ts"})
            self.assertNotIn("paths", event)
        complete = receive_events.make(
            "complete", transfer_id, sender="sender", names=["one"],
            paths=["/absolute/one"], received=3, total=3)
        self.assertEqual(complete["paths"], ["/absolute/one"])
        self.assertLess(
            len(json.dumps(complete, ensure_ascii=False,
                           separators=(",", ":")).encode()),
            receive_events.EVENT_MAX_BYTES)

    def test_hostile_lists_are_bounded_before_logging(self):
        event = receive_events.make(
            "complete", receive_events.new_id(), sender="x" * 10000,
            names=["名字" * 5000] * 5000,
            paths=["/tmp/" + "x" * 1000] * 5000,
            received=1, total=1)
        encoded = json.dumps(event, ensure_ascii=False,
                             separators=(",", ":")).encode()
        self.assertLess(encoded.__len__(), receive_events.EVENT_MAX_BYTES)
        self.assertTrue(all(len(path.encode()) <= receive_events.PATH_MAX_BYTES
                            for path in event["paths"]))

    def test_long_paths_are_exact_and_oversized_paths_are_omitted(self):
        path = '/tmp/' + 'a' * 900
        event = receive_events.make('complete', receive_events.new_id(),
                                    paths=[path, '/tmp/' + 'b' * 5000])
        self.assertEqual(event['paths'], [path])

    def test_logging_failure_is_optional(self):
        original = logging.info

        def broken(*_args, **_kwargs):
            raise RuntimeError("logger unavailable")

        logging.info = broken
        self.addCleanup(setattr, logging, "info", original)
        self.assertFalse(receive_events.emit(
            "incoming", receive_events.new_id(), names=["photo.jpg"]))

    def test_progress_callback_reports_body_bytes_and_wire_total(self):
        ns = receiver_namespace()
        seen = []
        deadline = ns["ReadDeadline"](
            on_progress=lambda received, total: seen.append((received, total)),
            total=6)
        target = io.BytesIO()
        ns["read_request_body"](
            io.BytesIO(b"abcdef"), {"Content-Length": "6"}, target, 64,
            deadline=deadline)
        self.assertEqual(target.getvalue(), b"abcdef")
        self.assertEqual(seen, [(6, 6)])


@unittest.skipUnless(ReceiverFixture.setUpClass is not None,
                     "uses the real TLS receiver fixture")
class RealReceiverEventTests(ReceiverFixture):
    """Ask/Upload and malformed Upload events on an actual TLS connection."""

    def ask(self, conn, names):
        import plistlib

        ask = plistlib.dumps({
            "SenderComputerName": "iPhone event test",
            "SenderModelName": "iPhone17,1",
            "TransferType": {"files": 1},
            "Items": [],
            "Files": [{"FileName": name, "FileType": "public.data",
                       "FileSize": 1} for name in names],
        }, fmt=plistlib.FMT_BINARY)
        return self.post(conn, "/Ask", ask)

    def test_real_tls_success_multi_file_and_punctuation_paths(self):
        names = ["a punctuation, (copy) #1.txt", "β-report[2].bin"]
        before = len(events_from(self.log))
        conn = self.connection()
        status, _ = self.ask(conn, names)
        self.assertEqual(status, 200)
        status, _ = self.post(
            conn, "/Upload", dvzip([(names[0], b"one"), (names[1], b"two")]),
            {"Content-Type": "application/x-dvzip", "TransferID": "events-1"})
        self.assertEqual(status, 200)
        self.assertEqual((self.out / names[0]).read_bytes(), b"one")
        self.assertEqual((self.out / names[1]).read_bytes(), b"two")

        events = wait_for_events(self.log, 3, before)
        self.assertTrue(events)
        incoming = next(e for e in events if e["event"] == "incoming")
        complete = next(e for e in events if e["event"] == "complete")
        self.assertEqual(incoming["id"], complete["id"])
        self.assertEqual(incoming["sender"], "iPhone event test")
        self.assertEqual(incoming["names"], names)
        self.assertEqual(set(complete["paths"]), {
            str(self.out / names[0]), str(self.out / names[1])})
        self.assertEqual(complete["names"], names)
        self.assertGreaterEqual(complete["received"], 1)

    def test_real_tls_malformed_upload_emits_terminal_failure(self):
        before = len(events_from(self.log))
        conn = self.connection()
        status, _ = self.ask(conn, ["broken.bin"])
        self.assertEqual(status, 200)
        status, _ = self.post(
            conn, "/Upload", b"not-a-dvzip",
            {"Content-Type": "application/x-dvzip", "TransferID": "events-bad"})
        self.assertEqual(status, 422)

        events = wait_for_events(self.log, 3, before)
        failures = [e for e in events if e["event"] == "failed"]
        self.assertTrue(failures)
        failed = failures[-1]
        incoming = [e for e in events if e["event"] == "incoming"][-1]
        self.assertEqual(failed["id"], incoming["id"])
        self.assertTrue(failed["error"])
        self.assertNotIn("paths", failed)


if __name__ == "__main__":
    unittest.main()

