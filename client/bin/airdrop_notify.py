#!/usr/bin/python3
"""Show an AirDrop notification and open its file when the body is clicked.

The notification is sent over the session bus directly instead of through
``notify-send``.  The latter is confined on some Ubuntu installations and can
therefore fail before it reaches GNOME's notification daemon.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

from gi.repository import Gio, GLib
from web_links import valid_web_url as _is_valid_web_url


NOTIFICATIONS_BUS_NAME = "org.freedesktop.Notifications"
NOTIFICATIONS_OBJECT_PATH = "/org/freedesktop/Notifications"
NOTIFICATIONS_INTERFACE = "org.freedesktop.Notifications"
MAX_LIFETIME_SECONDS = 24 * 60 * 60
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".avif"}
)


class NotificationState:
    """State shared by the two DBus signal callbacks."""

    def __init__(
        self,
        loop: GLib.MainLoop,
        opener: str,
        file_path: str | None = None,
        url: str | None = None,
    ) -> None:
        self.loop = loop
        self.opener = opener
        self.file_path = file_path
        self.url = url
        self.is_url = url is not None
        self.notification_id: int | None = None
        self.exit_status = 0
        self.action_handled = False


def _quit_after_timeout(state: NotificationState) -> bool:
    """Bound the lifetime of the callback even if the daemon sends no signal."""

    state.loop.quit()
    return GLib.SOURCE_REMOVE


def _on_action_invoked(
    _connection: Gio.DBusConnection,
    _sender_name: str,
    _object_path: str,
    _interface_name: str,
    _signal_name: str,
    parameters: GLib.Variant,
    state: NotificationState,
) -> None:
    notification_id, action = parameters.unpack()
    if notification_id != state.notification_id or state.action_handled:
        return

    state.action_handled = True
    if action == "default":
        try:
            # Keep this synchronous: the opener is the handoff that owns the
            # GUI application after this short-lived notification process exits.
            if state.is_url:
                subprocess.run(
                    [state.opener, "act", "open-url", state.url],
                    check=False,
                )
            else:
                subprocess.run(
                    [state.opener, "act", "open", state.file_path],
                    check=False,
                )
        except OSError as exc:
            if state.is_url:
                print(f"ucandrop: could not open link: {exc}", file=sys.stderr)
            else:
                print(f"ucandrop: could not open {state.file_path}: {exc}", file=sys.stderr)
            state.exit_status = 1
    state.loop.quit()


def _on_notification_closed(
    _connection: Gio.DBusConnection,
    _sender_name: str,
    _object_path: str,
    _interface_name: str,
    _signal_name: str,
    parameters: GLib.Variant,
    state: NotificationState,
) -> None:
    notification_id, _reason = parameters.unpack()
    if notification_id == state.notification_id:
        # Closing, expiring, or dismissing a notification must never open the
        # received file.  Only the default action above is an explicit click.
        state.loop.quit()


def _escape_markup(value: str) -> str:
    """Keep file names and receiver status literal in GNOME's body markup."""

    return GLib.markup_escape_text(value)


def _notify(file_path: str, body: str, opener: str) -> int:
    loop = GLib.MainLoop()
    state = NotificationState(loop, opener, file_path)
    return _run_notification(loop, state, body)


def _notify_url(url: str, body: str, opener: str) -> int:
    loop = GLib.MainLoop()
    state = NotificationState(loop, opener, url=url)
    return _run_notification(loop, state, body)


def _run_notification(
    loop: GLib.MainLoop, state: NotificationState, body: str
) -> int:
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    action_subscription = connection.signal_subscribe(
        NOTIFICATIONS_BUS_NAME,
        NOTIFICATIONS_INTERFACE,
        "ActionInvoked",
        NOTIFICATIONS_OBJECT_PATH,
        None,
        Gio.DBusSignalFlags.NONE,
        _on_action_invoked,
        state,
    )
    closed_subscription = connection.signal_subscribe(
        NOTIFICATIONS_BUS_NAME,
        NOTIFICATIONS_INTERFACE,
        "NotificationClosed",
        NOTIFICATIONS_OBJECT_PATH,
        None,
        Gio.DBusSignalFlags.NONE,
        _on_notification_closed,
        state,
    )

    try:
        escaped_body = _escape_markup(body)
        if state.is_url:
            # The URL itself remains private to the opener action.  Showing
            # only its hostname avoids leaking query strings or fragments in
            # the notification while still making the destination legible.
            hostname = urlsplit(state.url).hostname or ""
            first_line = _escape_markup(hostname)
            icon = ""
            action_label = "Open link"
        else:
            first_line = _escape_markup(os.path.basename(state.file_path))
            icon = (
                state.file_path
                if Path(state.file_path).suffix.lower() in IMAGE_SUFFIXES
                else ""
            )
            action_label = "Open file"
        parameters = GLib.Variant(
            "(susssasa{sv}i)",
            (
                "AirDrop",
                0,
                icon,
                "AirDrop",
                f"{first_line}\n{escaped_body}",
                ["default", action_label],
                {},
                8000,
            ),
        )
        result = connection.call_sync(
            NOTIFICATIONS_BUS_NAME,
            NOTIFICATIONS_OBJECT_PATH,
            NOTIFICATIONS_INTERFACE,
            "Notify",
            parameters,
            GLib.VariantType("(u)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        state.notification_id = result.unpack()[0]
        GLib.timeout_add_seconds(MAX_LIFETIME_SECONDS, _quit_after_timeout, state)
        loop.run()
    finally:
        connection.signal_unsubscribe(action_subscription)
        connection.signal_unsubscribe(closed_subscription)

    return state.exit_status


def main(argv: list[str]) -> int:
    if len(argv) == 5 and argv[1] == "--url":
        _mode, url, body, opener = argv[1:]
        if not _is_valid_web_url(url):
            print("ucandrop: invalid web URL", file=sys.stderr)
            return 2
        notify = lambda: _notify_url(url, body, opener)
    elif len(argv) == 4:
        file_path, body, opener = argv[1:]
        if not os.path.isfile(file_path):
            print(f"ucandrop: received file does not exist: {file_path}", file=sys.stderr)
            return 2
        notify = lambda: _notify(file_path, body, opener)
    else:
        print(
            f"usage: {argv[0]} FILE BODY OPENER | {argv[0]} --url URL BODY OPENER",
            file=sys.stderr,
        )
        return 2

    try:
        return notify()
    except GLib.Error as exc:
        print(f"ucandrop: could not show notification: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ucandrop: could not show notification: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
