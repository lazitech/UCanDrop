#!/usr/bin/python3
"""Announce one completed AirDrop transfer, preserving the receiver's order."""
from collections import OrderedDict
import argparse
import json
import os
import queue
import socket
import struct
import subprocess
import sys
import threading
import tempfile

from web_links import MAX_LINK_MESSAGE_BYTES, link_message, link_socket_address


def completed_paths(line):
    _, marker, payload = line.partition("OMDROP_EVENT ")
    if not marker or len(payload.encode("utf-8")) > 32 * 1024:
        return None
    try:
        event = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(event, dict) or event.get("v") != 1:
        return None
    transfer_id = event.get("id")
    if (event.get("event") != "complete" or not isinstance(transfer_id, str)
            or not transfer_id or len(transfer_id) > 128):
        return None
    paths = event.get("paths")
    if not isinstance(paths, list) or not 1 <= len(paths) <= 512:
        return None
    # Never split human-readable log lines on commas: commas and whitespace
    # can be legitimate parts of a saved filename. The structured event is
    # emitted once, only after the entire transfer has been stored.
    existing = []
    for path in paths:
        if (isinstance(path, str) and "\0" not in path and os.path.isabs(path)
                and os.path.isfile(path) and path not in existing):
            existing.append(path)
    return (transfer_id, existing) if existing else None


class Dispatcher:
    def __init__(self, opener, once=False):
        self.opener = opener
        self.once = once
        self.finished = False
        self.seen = OrderedDict()
        self.lock = threading.Lock()

    def announce(self, transfer_id, action, targets):
        with self.lock:
            if self.finished or transfer_id in self.seen:
                return
            self.seen[transfer_id] = None
            if len(self.seen) > 1024:
                self.seen.popitem(last=False)
            result = subprocess.run([self.opener, action, *targets], check=False)
            if result.returncode:
                print("ucandrop: could not announce received transfer", file=sys.stderr)
            if not self.once:
                return
            # off stops our watcher; its shutdown must run in its own unit.
            subprocess.run([
                "systemd-run", "--user", "--quiet", "--collect",
                self.opener, "off", "--force"], check=True)
            self.finished = True


class LinkListener:
    def __init__(self, dispatcher, ready_file=None):
        self.dispatcher = dispatcher
        self.ready_file = ready_file
        self.stop = threading.Event()
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        self.connection.bind(link_socket_address())
        self.connection.settimeout(0.3)
        self.thread = threading.Thread(target=self.listen, daemon=True)

    def _mark_ready(self):
        if not self.ready_file:
            return
        parent = os.path.dirname(os.path.abspath(self.ready_file)) or "."
        fd, temporary = tempfile.mkstemp(prefix=".ready-", dir=parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as marker:
                fd = None
                marker.write("ready\n")
                marker.flush()
                os.fsync(marker.fileno())
            os.replace(temporary, self.ready_file)
        finally:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def __enter__(self):
        try:
            self.thread.start()
            # bind() completed in __init__, and the listener thread is now
            # running.  The command starting this transient unit may expose
            # the receiver only after this marker appears.
            self._mark_ready()
        except Exception:
            self.stop.set()
            self.connection.close()
            raise
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.connection.close()
        self.thread.join(timeout=1)
        if self.ready_file:
            try:
                os.unlink(self.ready_file)
            except FileNotFoundError:
                pass

    def listen(self):
        while not self.stop.is_set():
            try:
                data, ancillary, flags, _address = self.connection.recvmsg(
                    MAX_LINK_MESSAGE_BYTES, socket.CMSG_SPACE(struct.calcsize("3i")))
                if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                    continue
                credentials = [struct.unpack("3i", value[:12])
                               for level, kind, value in ancillary
                               if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS]
                if not credentials or credentials[0][1] != os.getuid():
                    continue
                payload = json.loads(data)
                # Validate the same bounded contract at both ends of the socket.
                link_message(payload.get("id"), payload.get("urls"))
                self.dispatcher.announce(payload["id"], "handle-url", payload["urls"])
            except socket.timeout:
                continue
            except (ValueError, TypeError, AttributeError):
                continue
            except OSError:
                if not self.stop.is_set():
                    print("ucandrop: link notification handoff failed", file=sys.stderr)


def follow(lines, opener, once=False, dispatcher=None):
    dispatcher = dispatcher or Dispatcher(opener, once)
    for line in lines:
        completion = completed_paths(line)
        if completion is not None:
            transfer_id, paths = completion
            dispatcher.announce(transfer_id, "handle", paths)
            if dispatcher.finished:
                break
    return 0


def journal_lines(dispatcher):
    pending = queue.Queue(maxsize=1024)

    def read():
        for line in sys.stdin:
            pending.put(line)
        pending.put(None)

    threading.Thread(target=read, daemon=True).start()
    # A link-only `once` has no file event to wake stdin. Poll the finished
    # state so the watcher can exit after handing off the independent shutdown.
    while not dispatcher.finished:
        try:
            line = pending.get(timeout=0.1)
        except queue.Empty:
            continue
        if line is None:
            return
        yield line


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--opener", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--ready-file")
    args = parser.parse_args()
    dispatcher = Dispatcher(args.opener, args.once)
    with LinkListener(dispatcher, args.ready_file):
        return follow(journal_lines(dispatcher), args.opener, args.once, dispatcher)


if __name__ == "__main__":
    raise SystemExit(main())
