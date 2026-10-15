"""Moving Wi-Fi to an access point of the same network that AWDL can share.

A fake nmcli answers from a JSON description of the air, so no host radio or
NetworkManager state is read or changed.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STEER = ROOT / "bin" / "wifi_steer.py"
UCANDROP = ROOT / "bin" / "ucandrop"
SHARED = "2437,5220,5745"

FAKE_NMCLI = r'''#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["FAKE_NM"]
state = json.load(open(state_path))
args = sys.argv[1:]
with open(state_path + ".log", "a") as log:
    log.write(json.dumps(args) + "\n")

def esc(v):
    return str(v).replace("\\", "\\\\").replace(":", "\\:")

def row(*vals):
    print(":".join(esc(v) for v in vals))

if args[:6] == ["-t", "-e", "yes", "-f", "DEVICE,TYPE,STATE", "device"]:
    for d in state["devices"]:
        row(*d)
elif args[:4] == ["-t", "-e", "yes", "-f"] and args[5:8] == ["device", "wifi", "list"]:
    dev = args[9]
    for ap in state["aps"].get(dev, []):
        here = "*" if state["in_use"].get(dev) == ap["bssid"] else " "
        if args[4] == "IN-USE,BSSID,FREQ":
            if here == "*":
                row(here, ap["bssid"], "%d MHz" % ap["freq"])
        else:
            row(here, ap["bssid"], ap["ssid"], "%d MHz" % ap["freq"], ap["signal"])
elif args[:4] == ["-g", "GENERAL.CON-UUID", "device", "show"]:
    print(state["uuid"].get(args[4], ""))
elif args[:5] == ["-g", "connection.permissions", "connection", "show", "uuid"]:
    print(state.get("owner", ""))
elif args == ["-t", "-f", "PERMISSION,VALUE", "general", "permissions"]:
    for perm, value in state.get("permissions", {}).items():
        row(perm, value)
elif args[:5] == ["-g", "802-11-wireless.bssid", "connection", "show", "uuid"]:
    print(esc(state.get("pinned", {}).get(args[5], "")))
elif args[:5] == ["connection", "modify", "--temporary", "uuid", args[4]] and args[5] == "802-11-wireless.bssid":
    state.setdefault("pinned", {})[args[4]] = args[6]
    json.dump(state, open(state_path, "w"))
elif args[0] == "-w" and args[2:4] == ["connection", "up"]:
    if state.get("up_rc"):
        print("Error: Connection activation failed: (7) Secrets were required.", file=sys.stderr)
        sys.exit(state["up_rc"])
    uuid, dev = args[args.index("uuid") + 1], args[args.index("ifname") + 1]
    # What NetworkManager 1.54 did on real hardware: without a BSSID in the
    # profile, wpa_supplicant takes the strongest access point of the SSID,
    # whatever `ap` asked for.
    pin = state.get("pinned", {}).get(uuid, "")
    here = next(ap for ap in state["aps"][dev] if ap["bssid"] == state["in_use"][dev])
    same = [ap for ap in state["aps"][dev] if ap["ssid"] == here["ssid"]]
    if pin and not state.get("ignore_pin"):
        state["in_use"][dev] = pin
    else:
        state["in_use"][dev] = max(same, key=lambda ap: ap["signal"])["bssid"]
    json.dump(state, open(state_path, "w"))
else:
    sys.exit(10)
'''


def air(**over):
    """Two mesh nodes of 1236ab, as in the report that prompted this."""
    state = {
        "devices": [["wlan0", "wifi", "connected"], ["lo", "loopback", "connected (externally)"]],
        "aps": {"wlan0": [
            {"bssid": "84:70:D7:6F:4E:A6", "ssid": "1236ab", "freq": 5180, "signal": 85},
            {"bssid": "84:70:D7:6F:4E:A7", "ssid": "1236ab", "freq": 2437, "signal": 70},
            {"bssid": "84:70:D7:6F:4E:A8", "ssid": "1236ab", "freq": 5745, "signal": 60},
            {"bssid": "84:70:D7:6F:06:E8", "ssid": "1236ab", "freq": 5745, "signal": 20},
            {"bssid": "58:96:30:A8:A8:86", "ssid": "1236abab", "freq": 5220, "signal": 99},
        ]},
        "in_use": {"wlan0": "84:70:D7:6F:4E:A6"},
        "uuid": {"wlan0": "f5c57ecd-5527-4bb5-b1a7-d697ff1ccc8d"},
        "pinned": {},
        # A sudo/netdev member on Ubuntu: may edit system profiles unasked.
        "permissions": {
            "org.freedesktop.NetworkManager.network-control": "yes",
            "org.freedesktop.NetworkManager.settings.modify.own": "yes",
            "org.freedesktop.NetworkManager.settings.modify.system": "yes",
        },
    }
    state.update(over)
    return state


def install_fake_nmcli(bindir: Path, state: dict) -> dict:
    """Put the fake on BINDIR and return the env entries that point it at STATE."""
    path = bindir / "nmcli"
    path.write_text(FAKE_NMCLI.replace("/usr/bin/env python3", sys.executable, 1))
    path.chmod(0o755)
    nm = bindir / "nm-state.json"
    nm.write_text(json.dumps(state))
    return {"FAKE_NM": str(nm)}


class WifiSteerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name)

    def steer(self, action, state, current=5180, args=None):
        env = os.environ.copy()
        env.update(install_fake_nmcli(self.bin, state))
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        args = args or ["--from", str(current), "--supported", SHARED]
        result = subprocess.run([sys.executable, STEER, action, *args],
                                env=env, capture_output=True, text=True, timeout=30)
        log = self.bin / "nm-state.json.log"
        calls = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
        return result.returncode, json.loads(result.stdout), calls

    def state(self):
        return json.loads((self.bin / "nm-state.json").read_text())

    def test_prefers_a_supported_5ghz_access_point_of_the_same_network(self):
        rc, plan, _ = self.steer("plan", air())
        self.assertEqual(rc, 0, plan)
        self.assertEqual(plan["to"], {"bssid": "84:70:d7:6f:4e:a8", "freq": 5745,
                                      "channel": 149, "signal": 60})
        self.assertEqual(plan["from"]["channel"], 36)
        self.assertEqual(plan["uuid"], "f5c57ecd-5527-4bb5-b1a7-d697ff1ccc8d")

    def test_a_6ghz_association_is_named_as_such(self):
        state = air()
        state["aps"]["wlan0"][0]["freq"] = 6135
        rc, plan, _ = self.steer("plan", state, current=6135)
        self.assertEqual(rc, 0, plan)
        self.assertEqual(plan["from"]["channel"], "37 (6 GHz)")

    def test_falls_back_to_channel_6_when_5ghz_is_too_weak(self):
        state = air()
        state["aps"]["wlan0"][2]["signal"] = 25
        rc, plan, _ = self.steer("plan", state)
        self.assertEqual(rc, 0, plan)
        self.assertEqual(plan["to"]["channel"], 6)

    def test_never_moves_to_a_different_network_name(self):
        state = air()
        state["aps"]["wlan0"] = [ap for ap in state["aps"]["wlan0"] if ap["freq"] == 5180 or ap["ssid"] != "1236ab"]
        rc, plan, _ = self.steer("plan", state)
        self.assertEqual((rc, plan), (1, {"reason": "no-access-point"}))

    def test_a_profile_pinned_to_a_bssid_is_left_alone(self):
        rc, plan, _ = self.steer("plan", air(pinned={"f5c57ecd-5527-4bb5-b1a7-d697ff1ccc8d": "84:70:D7:6F:4E:A6"}))
        self.assertEqual(rc, 1)
        self.assertEqual(plan["reason"], "pinned")
        self.assertEqual(plan["to"]["channel"], 149)

    def test_a_user_who_would_be_asked_for_a_password_is_never_steered(self):
        state = air()
        state["permissions"]["org.freedesktop.NetworkManager.settings.modify.system"] = "auth"
        rc, plan, calls = self.steer("plan", state)
        self.assertEqual(rc, 1)
        self.assertEqual(plan["reason"], "no-permission")
        self.assertEqual(plan["to"]["channel"], 149)
        rc, out, calls = self.steer("hold", air(in_use={"wlan0": "84:70:D7:6F:4E:A8"},
                                                permissions=state["permissions"]),
                                    args=["--supported", SHARED])
        self.assertEqual((rc, out), (1, {"reason": "no-permission"}))
        self.assertFalse([c for c in calls if "modify" in c])

    def test_a_user_owned_profile_needs_only_modify_own(self):
        state = air(owner="user:someone")
        state["permissions"]["org.freedesktop.NetworkManager.settings.modify.system"] = "auth"
        rc, plan, _ = self.steer("plan", state)
        self.assertEqual(rc, 0, plan)

    def test_only_the_device_on_the_reported_frequency_is_considered(self):
        rc, plan, _ = self.steer("plan", air(), current=5500)
        self.assertEqual((rc, plan), (1, {"reason": "no-device"}))

    def test_ssids_with_colons_survive_terse_escaping(self):
        state = air()
        for ap in state["aps"]["wlan0"]:
            ap["ssid"] = ap["ssid"].replace("1236ab", "home:5G")
        rc, plan, _ = self.steer("plan", state)
        self.assertEqual(rc, 0, plan)
        self.assertEqual(plan["ssid"], "home:5G")

    UUID = "f5c57ecd-5527-4bb5-b1a7-d697ff1ccc8d"

    def test_switch_pins_the_bssid_in_memory_then_reactivates_the_same_profile(self):
        rc, result, calls = self.steer("switch", air())
        self.assertEqual(rc, 0, result)
        self.assertTrue(result["ok"])
        changes = [c for c in calls if "modify" in c or "up" in c]
        self.assertEqual(changes, [
            ["connection", "modify", "--temporary", "uuid", self.UUID,
             "802-11-wireless.bssid", "84:70:D7:6F:4E:A8"],
            ["-w", "30", "connection", "up", "uuid", self.UUID, "ifname", "wlan0"]])
        self.assertFalse([c for c in calls if "delete" in c or
                          ("modify" in c and "--temporary" not in c)])
        self.assertEqual(self.state()["in_use"]["wlan0"], "84:70:D7:6F:4E:A8")
        self.assertEqual(self.state()["pinned"][self.UUID], "84:70:D7:6F:4E:A8")

    def test_landing_elsewhere_is_a_failure_and_drops_the_pin(self):
        rc, result, _ = self.steer("switch", air(ignore_pin=True))
        self.assertEqual(rc, 2, result)
        self.assertIn("not to the chosen access point", result["error"])
        self.assertEqual(self.state()["pinned"][self.UUID], "")

    def test_a_failed_activation_is_reported_and_drops_the_pin(self):
        rc, result, _ = self.steer("switch", air(up_rc=4))
        self.assertEqual(rc, 2)
        self.assertFalse(result["ok"])
        self.assertIn("Secrets were required", result["error"])
        self.assertEqual(self.state()["pinned"][self.UUID], "")

    def test_hold_pins_the_current_supported_access_point_without_reconnecting(self):
        rc, out, calls = self.steer("hold", air(in_use={"wlan0": "84:70:D7:6F:4E:A8"}),
                                    args=["--supported", SHARED])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["to"], {"bssid": "84:70:d7:6f:4e:a8", "freq": 5745, "channel": 149})
        self.assertEqual(self.state()["pinned"][self.UUID], "84:70:D7:6F:4E:A8")
        self.assertFalse([c for c in calls if "up" in c])

    def test_hold_does_nothing_off_a_supported_channel(self):
        rc, out, calls = self.steer("hold", air(), args=["--supported", SHARED])
        self.assertEqual((rc, out), (1, {"reason": "no-device"}))
        self.assertFalse([c for c in calls if "modify" in c])

    def test_hold_leaves_a_profile_the_user_pinned(self):
        rc, out, calls = self.steer("hold", air(in_use={"wlan0": "84:70:D7:6F:4E:A8"},
                                                pinned={self.UUID: "84:70:D7:6F:4E:A8"}),
                                    args=["--supported", SHARED])
        self.assertEqual((rc, out), (1, {"reason": "pinned"}))
        self.assertFalse([c for c in calls if "modify" in c])

    def test_release_drops_only_the_pin_switch_set(self):
        rc, out, _ = self.steer("release", air(pinned={self.UUID: "84:70:D7:6F:4E:A8"}),
                                args=["--uuid", self.UUID, "--bssid", "84:70:d7:6f:4e:a8"])
        self.assertEqual((rc, out), (0, {"released": True}))
        self.assertEqual(self.state()["pinned"][self.UUID], "")

    def test_release_leaves_a_pin_the_user_changed(self):
        rc, out, calls = self.steer("release", air(pinned={self.UUID: "84:70:D7:6F:4E:A7"}),
                                    args=["--uuid", self.UUID, "--bssid", "84:70:d7:6f:4e:a8"])
        self.assertEqual((rc, out), (0, {"released": False}))
        self.assertFalse([c for c in calls if "modify" in c])



class PinRecordTests(unittest.TestCase):
    """`ucandrop`'s wifi_release, extracted and run against the fake nmcli."""
    UUID = "f5c57ecd-5527-4bb5-b1a7-d697ff1ccc8d"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.state_record = self.root / "state" / "ucandrop" / "wifi-pin"
        self.runtime_record = self.root / "run" / "ucandrop" / "wifi-pin"

    def release(self, state, record):
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(f"{self.UUID} 84:70:d7:6f:4e:a8\n")
        source = UCANDROP.read_text()
        start = source.index("\n# The in-memory BSSID pin")
        end = source.index("\n# Before `on` touches the radio")
        env = os.environ.copy()
        env.update(install_fake_nmcli(self.bin, state))
        env.update(PATH=f"{self.bin}:{env['PATH']}",
                   XDG_STATE_HOME=str(self.root / "state"),
                   XDG_RUNTIME_DIR=str(self.root / "run"),
                   HOME=str(self.root))
        harness = f"PROJ={ROOT}\n{source[start:end]}\nwifi_release\n"
        result = subprocess.run(["bash", "-c", harness], env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertFalse(record.exists())
        log = self.bin / "nm-state.json.log"
        calls = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
        return json.loads((self.bin / "nm-state.json").read_text()), calls

    def test_the_record_survives_logout_and_releases_the_pin(self):
        state, _ = self.release(air(pinned={self.UUID: "84:70:D7:6F:4E:A8"}), self.state_record)
        self.assertEqual(state["pinned"][self.UUID], "")

    def test_a_window_opened_by_1_2_0_is_still_released(self):
        state, _ = self.release(air(pinned={self.UUID: "84:70:D7:6F:4E:A8"}), self.runtime_record)
        self.assertEqual(state["pinned"][self.UUID], "")

    def test_after_a_reboot_the_stale_record_changes_nothing(self):
        _, calls = self.release(air(), self.state_record)
        self.assertFalse([c for c in calls if "modify" in c])


if __name__ == "__main__":
    unittest.main()
