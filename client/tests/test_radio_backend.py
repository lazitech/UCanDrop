"""A radio backend other than omdrop-awdl can describe itself.

omdrop's radio half is a separate package. Its helper may answer
`omdrop-discoverable probe --json` (docs/radio-backend.md); when it does, the
hardware and install checks are the backend's, so a machine without Apple's
Broadcom Wi-Fi is not refused out of hand. A helper that does not answer gets
the Broadcom checks exactly as before.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_wifi_steer import air, install_fake_nmcli


ROOT = Path(__file__).resolve().parents[1]
OMDROP = ROOT / "bin" / "ucandrop"

BROADCOM_SAYS = "no Apple Broadcom Wi-Fi"


def helper(probe):
    """An omdrop-discoverable that answers probe with PROBE (a dict), or, given
    None, behaves like omdrop-awdl's: usage and exit 2 for a subcommand it does
    not know."""
    if probe is None:
        return '#!/bin/sh\necho "usage: omdrop-discoverable start|stop|status" >&2\nexit 2\n'
    return ("#!/bin/sh\n"
            "[ \"$1\" = probe ] || exit 2\n"
            f"cat <<'EOF'\n{json.dumps(probe)}\nEOF\n")


class RadioBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        self.bin = tmp / "bin"
        self.bin.mkdir()
        # The receiver's service is installed (`systemctl --user cat` finds it),
        # so doctor's only findings are the radio's and the receiver
        # library's; nothing is active, ufw included.
        self.command("systemctl", '#!/bin/sh\ncase "$*" in *is-active*) exit 3 ;; esac\nexit 0\n')
        self.command("omarchy-launch-floating-terminal-with-presentation",
                     "#!/bin/sh\nprintf '%s\\n' \"$1\"\n")
        # A machine with no PCI network hardware at all: not a Mac.
        (tmp / "sys" / "bus" / "pci" / "devices").mkdir(parents=True)
        self.env = os.environ.copy()
        self.env.update(PATH=f"{self.bin}:{self.env['PATH']}",
                        HOME=str(tmp),
                        XDG_CONFIG_HOME=str(tmp / ".config"),
                        OMDROP_SYSFS=str(tmp / "sys"),
                        OMDROP_DISCOVERABLE=str(self.bin / "omdrop-discoverable"))

    def command(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def omdrop(self, *args):
        return subprocess.run([OMDROP, *args], env=self.env, capture_output=True, text=True)

    def doctor(self):
        result = self.omdrop("doctor", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def without_receiver_library(self):
        # A libarchive without the API the receiver calls, ahead of the real
        # one, is what "not installed" looks like to receiver_libs_installed.
        fake = Path(self.tmp.name) / "py" / "libarchive"
        fake.mkdir(parents=True)
        (fake / "__init__.py").write_text("")
        self.env["PYTHONPATH"] = str(fake.parent)

    def test_a_probing_backend_owns_the_hardware_check(self):
        self.command("omdrop-discoverable", helper({
            "backend": "owl", "version": "0.1.0", "hardware": True, "contract": "0.7.0",
            "missing": [{"id": "radio", "say": "Wi-Fi is not connected."}]}))
        missing = self.doctor()["missing"]
        self.assertEqual(missing[0], {"id": "radio", "say": "Wi-Fi is not connected."})
        self.assertNotIn(BROADCOM_SAYS, json.dumps(missing))

    def test_a_ready_backend_leaves_only_the_plugins_own_findings(self):
        self.command("omdrop-discoverable", helper({
            "backend": "owl", "version": "0.1.0", "hardware": True, "contract": "0.7.0",
            "missing": []}))
        ids = {m["id"] for m in self.doctor()["missing"]}
        self.assertTrue(ids <= {"library"}, ids)

    def test_hardware_the_backend_cannot_drive_is_reported_alone(self):
        self.command("omdrop-discoverable", helper({
            "backend": "owl", "version": "0.1.0", "hardware": False,
            "missing": [{"id": "hardware", "say": "No supported Wi-Fi card."},
                        {"id": "radio", "say": "never shown"}]}))
        self.without_receiver_library()
        self.assertEqual(self.doctor()["missing"],
                         [{"id": "hardware", "say": "No supported Wi-Fi card."}])

    def test_a_helper_without_probe_gets_the_broadcom_checks(self):
        self.command("omdrop-discoverable", helper(None))
        missing = self.doctor()["missing"]
        self.assertEqual([m["id"] for m in missing], ["hardware"])
        self.assertIn(BROADCOM_SAYS, missing[0]["say"])

    def test_install_with_a_probing_backend_never_builds_the_broadcom_driver(self):
        self.command("omdrop-discoverable", helper({
            "backend": "owl", "version": "0.1.0", "hardware": True, "missing": []}))
        self.command("pacman", "#!/bin/sh\nexit 1\n")
        self.without_receiver_library()
        result = self.omdrop("install-driver")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("tools/install.sh", result.stdout)
        self.assertIn("Ubuntu prerequisites", result.stdout)
        self.assertNotIn("pacman", result.stdout)
        for broadcom in ("brcmfmac-awdl-dkms", "makepkg", "omdrop-awdl"):
            self.assertNotIn(broadcom, result.stdout)

    CHANNEL_PROBE = {
        "backend": "owl", "version": "1.1.0", "hardware": True, "contract": "0.8.1",
        "shared_frequencies": [2437, 5220, 5745],
        "missing": [{"id": "radio", "frequency": 5180,
                     "say": "Wi-Fi is on 5180 MHz, channel 36, outside AWDL's supported shared-channel set (6, 44, or 149)."}]}

    def test_an_unshared_channel_with_a_supported_access_point_is_not_a_blocker(self):
        self.command("omdrop-discoverable", helper(self.CHANNEL_PROBE))
        self.env.update(install_fake_nmcli(self.bin, air()))
        report = self.doctor()
        self.assertTrue({m["id"] for m in report["missing"]} <= {"library"}, report)
        self.assertEqual(len(report["notices"]), 1)
        self.assertIn("channel 36", report["notices"][0])
        self.assertIn("channel 149", report["notices"][0])

    def test_an_unshared_channel_without_one_still_blocks(self):
        state = air()
        state["aps"]["wlan0"] = [ap for ap in state["aps"]["wlan0"] if ap["freq"] == 5180]
        self.command("omdrop-discoverable", helper(self.CHANNEL_PROBE))
        self.env.update(install_fake_nmcli(self.bin, state))
        report = self.doctor()
        say = self.channel_say(report)
        self.assertIn("5180 MHz, channel 36", say)
        self.assertIn("No access point of this network in range", say)
        self.assertIn("Set the router's 5 GHz channel to 44 or 149", say)
        self.assertNotIn("notices", report)

    def channel_say(self, report):
        rows = [m["say"] for m in report["missing"] if "channel 36" in m["say"]]
        self.assertEqual(len(rows), 1, report)
        return rows[0]

    def test_a_locked_profile_names_the_access_point_it_could_use(self):
        state = air(pinned={"f5c57ecd-5527-4bb5-b1a7-d697ff1ccc8d": "84:70:D7:6F:4E:A6"})
        self.command("omdrop-discoverable", helper(self.CHANNEL_PROBE))
        self.env.update(install_fake_nmcli(self.bin, state))
        say = self.channel_say(self.doctor())
        self.assertIn("access point on channel 149 in range", say)
        self.assertIn("locked to one access point", say)

    def test_a_user_without_permission_is_told_about_netdev(self):
        state = air()
        state["permissions"]["org.freedesktop.NetworkManager.settings.modify.system"] = "auth"
        self.command("omdrop-discoverable", helper(self.CHANNEL_PROBE))
        self.env.update(install_fake_nmcli(self.bin, state))
        say = self.channel_say(self.doctor())
        self.assertIn("access point on channel 149 in range", say)
        self.assertIn("usermod -aG netdev", say)

    def test_switching_turned_off_keeps_the_channel_blocker(self):
        self.command("omdrop-discoverable", helper(self.CHANNEL_PROBE))
        self.env.update(install_fake_nmcli(self.bin, air()))
        self.assertEqual(self.omdrop("wifi-switch", "off").returncode, 0)
        self.assertEqual(self.omdrop("wifi-switch").stdout.strip(), "off")
        report = self.doctor()
        say = self.channel_say(report)
        self.assertIn("access point on channel 149 in range", say)
        self.assertIn("ucandrop wifi-switch on", say)
        self.assertNotIn("notices", report)

    def test_install_with_a_probing_backend_and_nothing_missing_does_nothing(self):
        self.command("omdrop-discoverable", helper({
            "backend": "owl", "version": "0.1.0", "hardware": True, "missing": []}))
        result = self.omdrop("install-driver")
        if "Opening a terminal" in result.stdout:
            self.skipTest("this machine lacks the receiver's packages; covered above")
        self.assertIn("Nothing to do", result.stdout)
        self.assertIn("owl 0.1.0", result.stdout)


if __name__ == "__main__":
    unittest.main()
