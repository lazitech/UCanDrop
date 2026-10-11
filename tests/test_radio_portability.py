"""Read-only portability tests for the UCanDrop OWL radio helper.

The helper is privileged in production.  These tests source its functions in
an isolated bash process and replace ``iw``/``ip``/``ping`` with fixtures, so
no host radio, NetworkManager, polkit, or service state is touched.
"""
from __future__ import annotations

import ast
import json
import os
import shlex
import signal
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "radio" / "lib" / "omdrop-discoverable"
RESET_SHIM = ROOT / "radio" / "lib" / "ucandrop-exec-reset.py"
PROFILES = ROOT / "radio" / "lib" / "owl-profiles"
BLE_ADVERTISER = ROOT / "radio" / "lib" / "ble-airdrop-adv.py"
PEER_SENDER = ROOT / "radio" / "lib" / "send-to-peer"
AIR_DROP_SENDER = ROOT / "radio" / "lib" / "airdrop-send.py"
POLICY = ROOT / "packaging" / "ucandrop-radio.policy"
NM_CONF = ROOT / "packaging" / "ucandrop-networkmanager.conf"


class RadioFixture(unittest.TestCase):
    def make_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        holder = tempfile.TemporaryDirectory(prefix="ucandrop-radio-")
        root = Path(holder.name)
        for path in (root / "bin", root / "run", root / "conf", root / "sys" / "class" / "net"):
            path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(holder.cleanup)
        return holder, root

    @staticmethod
    def write_command(root: Path, name: str, body: str) -> None:
        path = root / "bin" / name
        path.write_text("#!/bin/bash\n" + textwrap.dedent(body))
        path.chmod(0o755)

    def add_wifi(self, root: Path, name: str = "radio0", *, driver: str = "mt7925e") -> None:
        iface = root / "sys" / "class" / "net" / name
        (iface / "phy80211").mkdir(parents=True)
        (root / "sys" / "ieee80211" / "phy0").mkdir(parents=True, exist_ok=True)
        (root / "sys" / "drivers" / driver).mkdir(parents=True, exist_ok=True)
        (iface / "phy80211").rmdir()
        (iface / "phy80211").symlink_to(root / "sys" / "ieee80211" / "phy0")
        (iface / "device").symlink_to(root / "sys" / "drivers" / driver)
        (iface / "address").write_text("02:00:00:00:00:02\n")

    def iw_fixture(self, root: Path, *, frequency: int = 5745, no_ir: bool = False,
                   connected: bool = True, monitor: bool = True,
                   decimal_frequency: bool = False) -> None:
        connection = (
            "Connected to 02:00:00:00:00:01 (on radio0)\n        freq: %d\n" % frequency
            if connected else "Not connected.\n"
        )
        value = f"{frequency}.0" if decimal_frequency else str(frequency)
        freq_line = "%s MHz [149]%s" % (value, " (no IR)" if no_ir else "")
        monitor_line = "\t\t * monitor\n" if monitor else ""
        self.write_command(
            root,
            "iw",
            'case "$*" in\n'
            '  "dev radio0 info")\n'
            "    cat <<'OUT'\n"
            'Interface radio0\n\ttype managed\n\twiphy 0\n'
            'OUT\n    ;;\n'
            '  "dev radio0 link")\n'
            "    cat <<'OUT'\n"
            f'{connection}'
            'OUT\n    ;;\n'
            '  "phy phy0 info")\n'
            "    cat <<'OUT'\n"
            'Wiphy phy0\n\tSupported interface modes:\n\t\t * managed\n'
            f'{monitor_line}'
            f'\tFrequencies:\n\t\t * {freq_line}\n'
            'OUT\n    ;;\n'
            '  "reg get") printf \'%s\\n\' \'country US: DFS-UNSET\' ;;\n'
            '  *) exit 1 ;;\n'
            'esac\n',
        )

    def run_bash(self, root: Path, body: str) -> subprocess.CompletedProcess[str]:
        source = f"""
        source {shlex.quote(str(HELPER))}
        RUN={shlex.quote(str(root / 'run'))}
        CONF={shlex.quote(str(root / 'conf'))}
        SYSFS_ROOT={shlex.quote(str(root / 'sys'))}
        PROFILES={shlex.quote(str(PROFILES))}
        OWL_BIN={shlex.quote(str(root / 'bin' / 'owl'))}
        set -e
        {textwrap.dedent(body)}
        """
        env = os.environ.copy()
        env["PATH"] = f"{root / 'bin'}:{env['PATH']}"
        env["LC_ALL"] = "C"
        return subprocess.run(
            ["bash", "-c", textwrap.dedent(source)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_associated_ipv6_only_link_never_calls_gateway_ping(self) -> None:
        _, root = self.make_root()
        self.add_wifi(root)
        self.iw_fixture(root)
        (root / "bin" / "owl").write_text("#!/bin/bash\nexit 0\n")
        (root / "bin" / "owl").chmod(0o755)
        self.write_command(root, "ping", 'printf "ping\n" >> "$TEST_ROOT/calls"\nexit 1\n')
        self.write_command(root, "ip", 'printf "ip %s\n" "$*" >> "$TEST_ROOT/calls"\nexit 0\n')
        self.write_command(root, "nmcli", 'printf "nmcli %s\n" "$*" >> "$TEST_ROOT/calls"\nexit 0\n')
        (root / "calls").touch()
        result = self.run_bash(
            root,
            r'''
            export TEST_ROOT="$RUN/.."
            need_root() { :; }
            station_iface() { printf '%s\n' radio0; }
            driver_of() { printf '%s\n' mt7925e; }
            load_profile() { PROF_STATUS=tested; PROF_MODE=shared; PROF_MONMAC=station; PROF_RECONNECT=no; PROF_PM=no; return 0; }
            station_link() { printf '%s\n' '02:00:00:00:00:01 5745 02:00:00:00:00:02'; }
            phy_of() { printf '%s\n' phy0; }
            frequency_legal() { return 0; }
            monitor_capable() { return 0; }
            # Fail before OWL starts, after association and radio gates.  A
            # blocked/missing IPv4 gateway must not be consulted on this path.
            cmd_start 1
            ''',
        )
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertNotIn("ping", (root / "calls").read_text())
        self.assertNotIn("gateway", result.stderr.lower())

    def test_invalid_configured_interface_is_rejected_without_leaking_name(self) -> None:
        _, root = self.make_root()
        self.add_wifi(root)
        self.iw_fixture(root)
        (root / "conf" / "infra-iface").write_text("bad/name\n")
        result = self.run_bash(
            root,
            r'''
            if station_iface; then exit 1; fi
            printf '%s\n' "$STATION_REASON"
            ''',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("configured Wi-Fi interface", result.stdout)
        self.assertNotIn("bad/name", result.stdout)

    def test_connected_managed_interface_wins_deterministically(self) -> None:
        _, root = self.make_root()
        self.add_wifi(root, "radio0")
        self.add_wifi(root, "radio1")
        self.write_command(
            root,
            "iw",
            r'''
            case "$*" in
              "dev radio0 info"|"dev radio1 info") printf '%s\n' 'Interface' '        type managed' ;;
              "dev radio0 link") printf '%s\n' 'Not connected.' ;;
              "dev radio1 link") printf '%s\n' 'Connected to 02:00:00:00:00:01 (on radio1)' '        freq: 5745' ;;
              *) exit 1 ;;
            esac
            ''',
        )
        result = self.run_bash(root, "station_iface\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "radio1")

    def test_integer_and_decimal_iw_frequencies_are_recognized(self) -> None:
        _, root = self.make_root()
        self.add_wifi(root)
        for frequency in (2437, 5220, 5745):
            for decimal in (False, True):
                with self.subTest(frequency=frequency, decimal=decimal):
                    self.iw_fixture(root, frequency=frequency, decimal_frequency=decimal)
                    result = self.run_bash(root, f"frequency_legal {frequency} phy0\n")
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_decimal_no_ir_frequency_is_still_rejected(self) -> None:
        _, root = self.make_root()
        self.add_wifi(root)
        self.iw_fixture(root, no_ir=True, decimal_frequency=True)
        result = self.run_bash(
            root,
            r'''
            if frequency_legal 5745 phy0; then exit 1; fi
            printf '%s\n' "$REG_REASON"
            ''',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("disabled or marked no-IR", result.stdout)

    def test_regulatory_no_ir_frequency_is_rejected(self) -> None:
        _, root = self.make_root()
        self.add_wifi(root)
        self.iw_fixture(root, no_ir=True)
        result = self.run_bash(
            root,
            r'''
            if frequency_legal 5745 phy0; then exit 1; fi
            printf '%s\n' "$REG_REASON"
            ''',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"no-IR|disabled|regulatory")

    def test_probe_reports_monitor_constraint_without_network_identity(self) -> None:
        _, root = self.make_root()
        self.add_wifi(root)
        self.iw_fixture(root, monitor=False)
        (root / "conf" / "allow-untested").write_text("1\n")
        (root / "bin" / "owl").write_text("#!/bin/bash\nexit 0\n")
        (root / "bin" / "owl").chmod(0o755)
        result = self.run_bash(root, "cmd_probe --json\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn("hardware", {item["id"] for item in report["missing"]})
        serialized = json.dumps(report)
        self.assertNotIn("02:00:00:00:00:01", serialized)
        self.assertNotIn("02:00:00:00:00:02", serialized)
        self.assertNotIn("radio0", serialized)

    def test_shared_channel_mapping_rejects_arbitrary_legal_frequency(self) -> None:
        _, root = self.make_root()
        result = self.run_bash(
            root,
            """
            if channel_for_frequency 5180; then exit 1; fi
            [ "$(channel_for_frequency 5745)" = 149 ]
            """,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_profile_known_driver_default_and_unknown_driver_gated(self) -> None:
        text = PROFILES.read_text()
        self.assertNotIn("Framework", text)
        self.assertIn("mt7925e    tested", text)
        self.assertIn("*          untested", text)
        _, root = self.make_root()
        self.add_wifi(root)
        self.iw_fixture(root)
        result = self.run_bash(
            root,
            r'''
            load_profile mt7925e
            printf '%s %s\n' "$PROF_STATUS" "$PROF_PM"
            profile_allowed && printf '%s\n' known-allowed || printf '%s\n' known-gated
            load_profile unknown-driver
            printf '%s %s\n' "$PROF_STATUS" "$PROF_PM"
            profile_allowed && printf '%s\n' unknown-allowed || printf '%s\n' unknown-gated
            printf '1\n' > "$CONF/allow-untested"
            profile_allowed && printf '%s\n' unknown-opted-in || printf '%s\n' unknown-gated
            ''',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "tested yes", "known-allowed", "untested no", "unknown-gated", "unknown-opted-in",
        ])

    def test_foreign_mon0_is_never_deleted_and_owned_names_are_product_prefixed(self) -> None:
        _, root = self.make_root()
        self.add_wifi(root)
        self.write_command(
            root,
            "iw",
            r'''
            printf 'iw %s\n' "$*" >> "$TEST_ROOT/calls"
            case "$*" in
              "dev mon0 info") printf '%s\n' 'Interface mon0' '        type monitor' '        wiphy 0' ;;
              *) exit 1 ;;
            esac
            ''',
        )
        (root / "calls").touch()
        result = self.run_bash(
            root,
            r'''
            export TEST_ROOT="$RUN/.."
            MON=mon0
            monitor_cleanup radio0 || true
            new_monitor_name
            ''',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().startswith("ucandrop"))
        calls = (root / "calls").read_text()
        self.assertNotIn("dev mon0 del", calls)

    def test_exec_reset_restores_ignored_term_before_exec(self) -> None:
        code = "import signal; print(signal.getsignal(signal.SIGTERM) is signal.SIG_DFL)"

        def ignore_term() -> None:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)

        result = subprocess.run(
            ["/usr/bin/setsid", "/usr/bin/python3", str(RESET_SHIM),
             "/usr/bin/python3", "-c", code],
            capture_output=True,
            text=True,
            preexec_fn=ignore_term,
            check=False,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True")

    def test_spawn_reset_background_pid_is_the_exec_target(self) -> None:
        _, root = self.make_root()
        result = self.run_bash(
            root,
            r'''
            launch=
            cleanup_child() {
                if [ -n "${launch:-}" ] && kill -0 "$launch" 2>/dev/null; then
                    kill -KILL "$launch" 2>/dev/null || true
                fi
                if [ -n "${launch:-}" ]; then
                    wait "$launch" 2>/dev/null || true
                fi
            }
            trap cleanup_child EXIT
            spawn_reset /usr/bin/sleep 30 &
            launch=$!
            for _ in $(seq 1 50); do
                if [ "$(readlink -f "/proc/$launch/exe")" = "$(readlink -f /usr/bin/sleep)" ]; then
                    break
                fi
                sleep 0.01
            done
            [ "$(readlink -f "/proc/$launch/exe")" = "$(readlink -f /usr/bin/sleep)" ]
            /usr/bin/python3 - "/proc/$launch/cmdline" <<'PY'
            from pathlib import Path
            import sys
            assert Path(sys.argv[1]).read_bytes() == b"/usr/bin/sleep\0" + b"30\0"
            PY
            kill -TERM "$launch"
            wait "$launch" 2>/dev/null || true
            launch=
            ''',
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_owned_process_requires_identity_snapshot_before_termination(self) -> None:
        _, root = self.make_root()
        result = self.run_bash(
            root,
            r'''
            launch=
            cleanup_child() {
                if [ -n "${launch:-}" ] && kill -0 "$launch" 2>/dev/null; then
                    kill -KILL "$launch" 2>/dev/null || true
                fi
                if [ -n "${launch:-}" ]; then
                    wait "$launch" 2>/dev/null || true
                fi
            }
            trap cleanup_child EXIT
            atomic_state owner-uid "$(id -u)"
            spawn_reset /usr/bin/sleep 30 &
            launch=$!
            record_process worker "$launch" "$(readlink -f /usr/bin/sleep)" /usr/bin/sleep 30
            [ -s "$RUN/worker.start" ]
            [ -s "$RUN/worker.uid" ]
            [ "$(readlink -f "/proc/$launch/exe")" = "$(readlink -f /usr/bin/sleep)" ]
            [ -s "$RUN/worker.argv" ]
            /usr/bin/python3 - "$RUN/worker.argv" "/proc/$launch/cmdline" <<'PY'
            from pathlib import Path
            import sys
            expected = b"/usr/bin/sleep\0" + b"30\0"
            for name in sys.argv[1:]:
                assert Path(name).read_bytes() == expected, (name, Path(name).read_bytes())
            PY
            owned_pid worker '/usr/bin/sleep' >/dev/null
            cp "$RUN/worker.argv" "$RUN/worker.argv.good"
            cp "$RUN/worker.start" "$RUN/worker.start.good"
            cp "$RUN/worker.uid" "$RUN/worker.uid.good"
            printf 'unrelated\0argv\0' > "$RUN/worker.argv"
            if owned_pid worker '/usr/bin/sleep' >/dev/null; then exit 1; fi
            mv "$RUN/worker.argv.good" "$RUN/worker.argv"
            printf '0\n' > "$RUN/worker.start"
            if owned_pid worker '/usr/bin/sleep' >/dev/null; then exit 1; fi
            mv "$RUN/worker.start.good" "$RUN/worker.start"
            printf '65534\n' > "$RUN/worker.uid"
            if owned_pid worker '/usr/bin/sleep' >/dev/null; then exit 1; fi
            mv "$RUN/worker.uid.good" "$RUN/worker.uid"
            owned_pid worker '/usr/bin/sleep' >/dev/null
            terminate_named_process worker '/usr/bin/sleep'
            wait "$launch" 2>/dev/null || true
            if kill -0 "$launch" 2>/dev/null; then exit 1; fi
            launch=
            clear_process_state worker
            ''',
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_record_process_waits_for_delayed_exec_before_recording(self) -> None:
        _, root = self.make_root()
        delayed = root / "bin" / "delayed-exec"
        delayed.write_text("#!/bin/bash\nsleep 0.15\nexec \"$@\"\n")
        delayed.chmod(0o755)
        result = self.run_bash(
            root,
            r'''
            launch=
            cleanup_child() {
                if [ -n "${launch:-}" ] && kill -0 "$launch" 2>/dev/null; then
                    kill -KILL "$launch" 2>/dev/null || true
                fi
                if [ -n "${launch:-}" ]; then
                    wait "$launch" 2>/dev/null || true
                fi
            }
            trap cleanup_child EXIT
            atomic_state owner-uid "$(id -u)"
            spawn_reset "$RUN/../bin/delayed-exec" /usr/bin/sleep 30 &
            launch=$!
            record_process worker "$launch" "$(readlink -f /usr/bin/sleep)" /usr/bin/sleep 30
            [ "$(readlink -f "/proc/$launch/exe")" = "$(readlink -f /usr/bin/sleep)" ]
            /usr/bin/python3 - "$RUN/worker.argv" "/proc/$launch/cmdline" <<'PY'
            from pathlib import Path
            import sys
            expected = b"/usr/bin/sleep\0" + b"30\0"
            for name in sys.argv[1:]:
                assert Path(name).read_bytes() == expected, (name, Path(name).read_bytes())
            PY
            terminate_named_process worker '/usr/bin/sleep'
            wait "$launch" 2>/dev/null || true
            if kill -0 "$launch" 2>/dev/null; then exit 1; fi
            launch=
            clear_process_state worker
            ''',
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_readonly_status_survives_hidden_root_exe_but_teardown_does_not(self) -> None:
        _, root = self.make_root()
        result = self.run_bash(
            root,
            r'''
            launch=
            cleanup_child() {
                if [ -n "${launch:-}" ] && kill -0 "$launch" 2>/dev/null; then
                    kill -KILL "$launch" 2>/dev/null || true
                fi
                if [ -n "${launch:-}" ]; then
                    wait "$launch" 2>/dev/null || true
                fi
            }
            trap cleanup_child EXIT
            atomic_state owner-uid "$(id -u)"
            spawn_reset /usr/bin/sleep 30 &
            launch=$!
            record_process worker "$launch" "$(readlink -f /usr/bin/sleep)" /usr/bin/sleep 30
            # Model hidepid/permission denial for a root-owned process.
            process_exe() { return 1; }
            owned_pid worker '/usr/bin/sleep' readonly >/dev/null
            if owned_pid worker '/usr/bin/sleep' >/dev/null; then exit 1; fi
            terminate_named_process worker '/usr/bin/sleep'
            kill -0 "$launch" 2>/dev/null
            kill -TERM "$launch"
            wait "$launch" 2>/dev/null || true
            launch=
            clear_process_state worker
            ''',
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_packaging_uses_a_named_fixed_polkit_path_and_product_monitor_prefix(self) -> None:
        policy = POLICY.read_text()
        self.assertIn("/usr/lib/ucandrop/radio/omdrop-discoverable", policy)
        self.assertNotIn("/bin/sh", policy)
        self.assertNotIn("github.com", policy.lower())
        config = NM_CONF.read_text()
        self.assertIn("interface-name:awdl0", config)
        self.assertIn("interface-name:ucandrop-?????", config)
        self.assertNotIn("interface-name:ucandrop*", config)
        self.assertNotIn("interface-name:mon0", config)

    def test_ble_and_sender_defaults_are_generic_and_privilege_path_fixed(self) -> None:
        ble = BLE_ADVERTISER.read_text()
        self.assertIn("GetManagedObjects", ble)
        self.assertIn("Powered", ble)
        self.assertIn("/org/ucandrop/airdrop/adv0", ble)
        self.assertNotIn("default='hci0'", ble)
        self.assertNotIn('default="hci0"', ble)

        peer = PEER_SENDER.read_text()
        self.assertIn('HELPER = "/usr/lib/ucandrop/radio/omdrop-discoverable"', peer)
        self.assertNotIn('HELPER = os.path.join(TOOLS, "omdrop-discoverable")', peer)
        self.assertIn('"--adapter", adapter', peer)
        self.assertIn('"--model", args.model', peer)
        self.assertIn("DEFAULT_SENDER_NAME", peer)
        self.assertNotIn('default="Omarchy"', peer)
        self.assertNotIn("default='Omarchy'", peer)

        sender = AIR_DROP_SENDER.read_text()
        self.assertIn("Mac1,1", sender)
        self.assertIn("socket.gethostname", sender)
        self.assertNotIn("default='f0010'", sender)
        self.assertNotIn('default="f0010"', sender)
        self.assertNotIn("default='MacBookPro18,3'", sender)
        self.assertNotIn('default="MacBookPro18,3"', sender)
        self.assertNotIn("default='f0010-awdl'", sender)
        self.assertNotIn('default="f0010-awdl"', sender)

    def test_ble_adapter_selection_requires_le_advertising_capability(self) -> None:
        """A powered controller without LE advertising must not win selection."""
        tree = ast.parse(BLE_ADVERTISER.read_text())
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "choose_adapter")

        class FakeDBus:
            @staticmethod
            def Interface(obj, _interface):
                return obj

        class FakeRoot:
            def __init__(self, managed):
                self.managed = managed

            def GetManagedObjects(self):
                return self.managed

        class FakeBus:
            def __init__(self, managed):
                self.root = FakeRoot(managed)

            def get_object(self, _service, path):
                return self.root if path == "/" else path

        namespace = {
            "dbus": FakeDBus,
            "ADAPTER_IFACE": "org.bluez.Adapter1",
            "ADM_IFACE": "org.bluez.LEAdvertisingManager1",
            "OBJECT_MANAGER_IFACE": "org.freedesktop.DBus.ObjectManager",
            "BLUEZ_ROOT": "/org/bluez",
            "re": __import__("re"),
        }
        module = ast.Module(body=[function], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(BLE_ADVERTISER), "exec"), namespace)

        adapter_iface = namespace["ADAPTER_IFACE"]
        manager_iface = namespace["ADM_IFACE"]
        managed = {
            "/org/bluez/hci0": {
                adapter_iface: {"Powered": True},
            },
            "/org/bluez/hci1": {
                adapter_iface: {"Powered": False},
                manager_iface: {"SupportedInstances": 1},
            },
            "/org/bluez/hci2": {
                adapter_iface: {"Powered": True},
                manager_iface: {"SupportedInstances": 0},
            },
        }
        selected, path = namespace["choose_adapter"](FakeBus(managed))
        self.assertEqual((selected, path), ("hci1", "/org/bluez/hci1"))
        with self.assertRaisesRegex(SystemExit, "LE advertising support"):
            namespace["choose_adapter"](FakeBus({
                "/org/bluez/hci0": {adapter_iface: {"Powered": True}},
            }))


if __name__ == "__main__":
    unittest.main()
