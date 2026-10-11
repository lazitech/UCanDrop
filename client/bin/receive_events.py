#!/usr/bin/env python3
"""Bounded, best-effort lifecycle events for the desktop receive companion.

The receiver writes these events to its ordinary logger. A user-session
companion can follow the journal and select lines whose message starts with
``OMDROP_EVENT``; keeping the transport in the logger means the hardened
receiver does not need to open another socket or writable IPC endpoint.

This module deliberately has no dependency on the GUI. Event construction is
bounded before it reaches the logger, and :func:`emit` is best effort: a
broken logging handler must never turn into a failed AirDrop transfer.
"""

import json
import logging
import os
import time
from urllib.parse import urlsplit
import uuid


# Leave room for ``OMDROP_EVENT `` and a normal logger prefix too.  The JSON
# payload itself is therefore comfortably below the 32 KiB record boundary.
EVENT_MAX_BYTES = 32 * 1024 - 256
"""Maximum UTF-8 bytes in a serialized event payload."""

DISPLAY_STRING_MAX_BYTES = 2048
PATH_MAX_BYTES = 4095
MAX_NAMES = 512
MAX_PATHS = 512

EVENTS = frozenset(("incoming", "progress", "complete", "failed"))


def new_id():
    """Return the receiver-generated identifier used to join one transfer."""

    return uuid.uuid4().hex


def _text(value, limit=DISPLAY_STRING_MAX_BYTES):
    """Return bounded display text without raising for sender-controlled data."""

    if value is None:
        value = ""
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\x00", "")
    encoded = value.encode("utf-8", "replace")
    if len(encoded) <= limit:
        return value
    suffix = "…".encode("utf-8")
    return encoded[:max(0, limit - len(suffix))].decode("utf-8", "ignore") + "…"


def _names(values):
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]
    result = []
    for value in values:
        if len(result) >= MAX_NAMES:
            break
        result.append(_text(value))
    return result


def _paths(values):
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]
    result = []
    for value in values:
        if len(result) >= MAX_PATHS:
            break
        # A path is an action target, not display text. Never shorten it into
        # a different path. Omit unrepresentable values rather than inventing
        # a filename the receiver did not actually store.
        if (isinstance(value, str) and '\x00' not in value
                and len(value.encode('utf-8')) <= PATH_MAX_BYTES
                and os.path.isabs(value)):
            result.append(value)
    return result


def _base(event, transfer_id, sender, names, received, total):
    if event not in EVENTS:
        raise ValueError(f"unsupported receive event {event!r}")
    if not isinstance(transfer_id, str) or not transfer_id:
        raise ValueError("receive event id must be a non-empty string")
    try:
        received = max(0, int(received))
    except (TypeError, ValueError):
        received = 0
    if total is not None:
        try:
            total = max(0, int(total))
        except (TypeError, ValueError):
            total = None
    return {
        "v": 1,
        "event": event,
        "id": _text(transfer_id, 128),
        "sender": _text(sender),
        "names": _names(names),
        "received": received,
        "total": total,
        "ts": float(time.time()),
    }


def _serialized(event):
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def _fit(event):
    """Keep the event below the logger boundary while preserving its shape."""

    if len(_serialized(event).encode("utf-8")) < EVENT_MAX_BYTES:
        return event
    while len(event.get("names", [])) > 1 and len(_serialized(event).encode("utf-8")) >= EVENT_MAX_BYTES:
        event["names"] = event["names"][:len(event["names"]) // 2]
    while len(event.get("paths", [])) > 1 and len(_serialized(event).encode("utf-8")) >= EVENT_MAX_BYTES:
        event["paths"] = event["paths"][:len(event["paths"]) // 2]
    for key in ("sender", "error"):
        if key in event:
            event[key] = _text(event[key], 256)
    event['names'] = [_text(name, 64) for name in event.get('names', [])]
    if len(_serialized(event).encode('utf-8')) >= EVENT_MAX_BYTES:
        raise ValueError('receive event exceeds journal boundary')
    return event


def make(event, transfer_id, *, sender="", names=None, paths=None,
         received=0, total=None, error=None):
    """Build one bounded event dictionary without emitting it."""

    payload = _base(event, transfer_id, sender, names, received, total)
    if event == "complete":
        payload["paths"] = _paths(paths)
    elif event == "failed":
        payload["error"] = _text(error)
    return _fit(payload)


def emit(event, transfer_id, *, sender="", names=None, paths=None,
         received=0, total=None, error=None):
    """Log one structured lifecycle event, returning false on logger failure."""

    try:
        payload = make(event, transfer_id, sender=sender, names=names,
                       paths=paths, received=received, total=total,
                       error=error)
        line = _serialized(payload)
        logging.info("OMDROP_EVENT %s", line)
        return True
    except Exception:
        try:
            logging.getLogger(__name__).debug("receive event emission failed",
                                              exc_info=True)
        except Exception:
            pass
        return False


def names_from_ask(ask):
    """Extract human-facing item names from an AirDrop Ask plist."""

    names = []
    for item in ask.get("Files") or []:
        if isinstance(item, dict):
            name = item.get("FileName")
            if name is not None:
                names.append(name)
    for item in ask.get("Items") or []:
        if isinstance(item, str):
            # Items carries a URL for link transfers.  Keep the card useful
            # without putting query strings, tokens, or the full URL into the
            # journal event.
            try:
                parts = urlsplit(item)
                label = parts.path.rstrip("/").rsplit("/", 1)[-1] or parts.netloc
            except ValueError:
                label = "link"
            names.append(label or "link")
    return names

