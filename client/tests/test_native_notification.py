"""Exercise the native notification helper against a private session bus."""

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin" / "airdrop_notify.py"
PYTHON = "/usr/bin/python3"


SERVICE_HARNESS = r'''
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from gi.repository import Gio, GLib


SCENARIO, FILE_PATH, BODY, OPENER, RESULT = sys.argv[1:]
PYTHON = "/usr/bin/python3"
BUS_NAME = "org.freedesktop.Notifications"
OBJECT_PATH = "/org/freedesktop/Notifications"
INTERFACE = "org.freedesktop.Notifications"
IFACE_XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="Notify">
      <arg type="s" direction="in"/>
      <arg type="u" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="as" direction="in"/>
      <arg type="a{sv}" direction="in"/>
      <arg type="i" direction="in"/>
      <arg type="u" direction="out"/>
    </method>
  </interface>
</node>
"""

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
iface = Gio.DBusNodeInfo.new_for_xml(IFACE_XML).interfaces[0]
loop = GLib.MainLoop()


def emit_signal(member, value):
    bus.emit_signal(
        None,
        OBJECT_PATH,
        INTERFACE,
        member,
        GLib.Variant(value[0], value[1]),
    )


def close_after_wrong_action():
    emit_signal("NotificationClosed", ("(uu)", (42, 2)))
    return GLib.SOURCE_REMOVE


def respond_to_notification():
    if SCENARIO == "default":
        emit_signal("ActionInvoked", ("(us)", (42, "default")))
    elif SCENARIO == "dismiss":
        emit_signal("NotificationClosed", ("(uu)", (42, 2)))
    else:
        emit_signal("ActionInvoked", ("(us)", (999, "default")))
        GLib.timeout_add(100, close_after_wrong_action)
    return GLib.SOURCE_REMOVE


def method_call(_connection, _sender, _object_path, _interface, method,
                parameters, invocation):
    if method != "Notify":
        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
        return
    app, replaces, icon, summary, body, actions, hints, timeout = parameters.unpack()
    Path(RESULT).write_text(json.dumps({
        "app": app,
        "replaces": replaces,
        "icon": icon,
        "summary": summary,
        "body": body,
        "actions": actions,
        "hints": hints,
        "timeout": timeout,
    }, ensure_ascii=False), encoding="utf-8")
    invocation.return_value(GLib.Variant("(u)", (42,)))
    GLib.timeout_add(100, respond_to_notification)


registration = bus.register_object(OBJECT_PATH, iface, method_call, None, None)
if not registration:
    raise RuntimeError("could not register fake notification object")

request_name = bus.call_sync(
    "org.freedesktop.DBus",
    "/org/freedesktop/DBus",
    "org.freedesktop.DBus",
    "RequestName",
    GLib.Variant("(su)", (BUS_NAME, 0)),
    GLib.VariantType("(u)"),
    Gio.DBusCallFlags.NONE,
    -1,
    None,
).unpack()[0]
if request_name not in (1, 4):
    raise RuntimeError("could not own notification name")

child = subprocess.Popen(
    [PYTHON, os.environ["OMDROP_HELPER"], FILE_PATH, BODY, OPENER],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)


def wait_for_child():
    child.wait()
    loop.quit()


threading.Thread(target=wait_for_child, daemon=True).start()
loop.run()
stdout, stderr = child.communicate()
print(json.dumps({"returncode": child.returncode, "stdout": stdout, "stderr": stderr}))
sys.exit(child.returncode)
'''


@unittest.skipUnless(
    shutil.which("dbus-run-session") and HELPER.exists(),
    "needs dbus-run-session and the native notification helper",
)
class NativeNotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.received = self.root / "相片 café photo 2.jpg"
        self.received.write_bytes(b"received")
        self.open_log = self.root / "opened.log"
        self.opener = self.root / "opener"
        self.opener.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$@\" > \"$OMDROP_OPEN_LOG\"\n",
            encoding="utf-8",
        )
        self.opener.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_helper(self, scenario):
        result_file = self.root / f"{scenario}.json"
        env = os.environ.copy()
        env.update(
            OMDROP_HELPER=str(HELPER),
            OMDROP_OPEN_LOG=str(self.open_log),
        )
        return subprocess.run(
            [
                "dbus-run-session",
                "--",
                PYTHON,
                "-c",
                textwrap.dedent(SERVICE_HARNESS),
                scenario,
                str(self.received),
                "Saved <here> & now",
                str(self.opener),
                str(result_file),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        ), result_file

    def notification_payload(self, result_file):
        return json.loads(result_file.read_text(encoding="utf-8"))

    def test_default_action_opens_exact_unicode_path(self):
        result, result_file = self.run_helper("default")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.open_log.read_text(encoding="utf-8").splitlines(),
            ["act", "open", str(self.received)],
        )
        notification = self.notification_payload(result_file)
        self.assertEqual(notification["app"], "AirDrop")
        self.assertEqual(notification["summary"], "AirDrop")
        self.assertEqual(
            notification["body"],
            "相片 café photo 2.jpg\nSaved &lt;here&gt; &amp; now",
        )
        self.assertEqual(notification["actions"], ["default", "Open file"])
        self.assertEqual(notification["icon"], str(self.received))
        self.assertEqual(notification["timeout"], 8000)

    def test_notification_dismissal_does_not_open(self):
        result, result_file = self.run_helper("dismiss")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.open_log.exists())
        self.assertEqual(self.notification_payload(result_file)["actions"], ["default", "Open file"])

    def test_action_for_another_notification_does_not_open(self):
        result, _result_file = self.run_helper("wrong-id")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.open_log.exists())


if __name__ == "__main__":
    unittest.main()
