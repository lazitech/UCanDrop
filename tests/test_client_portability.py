"""Read-only checks for the source UCanDrop client layout.

The tests exercise only the candidate checkout.  They do not install a unit,
invoke a privileged command, start a receiver, or depend on the host's home,
radio, desktop session, or system-wide installation.
"""

import json
import os
from pathlib import Path
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client"
BIN = CLIENT / "bin"
RECEIVER = ROOT / "receiver"


class ClientPortabilityTests(unittest.TestCase):
    def test_packaged_layout_finds_its_bundled_backend_without_an_override(self):
        """Use the package's real flattened layout and the public command link."""
        with tempfile.TemporaryDirectory(prefix="ucandrop-installed-layout-") as temporary:
            root = Path(temporary)
            package = root / "package % Δ"
            plugin = package / "usr/lib/ucandrop/client"
            shutil.copytree(CLIENT, plugin)
            radio = plugin.parent / "radio"
            radio.mkdir()
            probe = {
                "backend": "owl", "hardware": True,
                "missing": [{"id": "radio", "say": "Fixture Wi-Fi is disconnected."}],
            }
            bundled = radio / "omdrop-discoverable"
            bundled.write_text(
                "#!/bin/sh\n[ \"$*\" = 'probe --json' ] || exit 2\n"
                f"printf '%s\\n' {shlex.quote(json.dumps(probe))}\n"
            )
            bundled.chmod(0o755)
            public = package / "usr/bin/ucandrop"
            public.parent.mkdir(parents=True)
            public.symlink_to("../lib/ucandrop/client/bin/ucandrop")
            home = root / "home"
            home.mkdir()
            sysfs = root / "sys"
            (sysfs / "bus/pci/devices").mkdir(parents=True)
            fakebin = root / "bin"
            fakebin.mkdir()
            systemctl = fakebin / "systemctl"
            systemctl.write_text("#!/bin/sh\nexit 3\n")
            systemctl.chmod(0o755)
            # A leftover PATH backend must not shadow this package's helper.
            foreign = fakebin / "awdl-discoverable"
            foreign.write_text(
                "#!/bin/sh\nprintf '%s\\n' "
                "'{\"hardware\": false, \"missing\": [{\"id\": \"hardware\", "
                "\"say\": \"Wrong PATH backend.\"}]}'\n"
            )
            foreign.chmod(0o755)
            env = os.environ.copy()
            for key in ("UCANDROP_DISCOVERABLE", "OMDROP_DISCOVERABLE"):
                env.pop(key, None)
            env.update(
                HOME=str(home), XDG_CONFIG_HOME=str(root / "config"),
                XDG_RUNTIME_DIR=str(root / "run"), OMDROP_SYSFS=str(sysfs),
                PATH=f"{fakebin}:{env['PATH']}",
            )
            result = subprocess.run(
                [str(public), "doctor", "--json"], env=env,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            missing = json.loads(result.stdout)["missing"]
            self.assertIn(probe["missing"][0], missing)
            self.assertNotIn("hardware", {item["id"] for item in missing})

    def test_manifest_and_command_are_the_generic_v11_candidate(self):
        manifest = json.loads((CLIENT / "manifest.json").read_text())
        self.assertEqual(manifest["id"], "ucandrop")
        self.assertEqual(manifest["name"], "UCanDrop")
        self.assertEqual(manifest["version"], "1.1.0")
        self.assertEqual(manifest["author"], "UCanDrop contributors")
        self.assertEqual(manifest["kinds"], ["cli"])
        self.assertNotIn("entryPoints", manifest)
        self.assertNotIn("barWidget", manifest)

        command = BIN / "ucandrop"
        self.assertTrue(command.is_file())
        self.assertTrue(os.access(command, os.X_OK))
        env = os.environ.copy()
        env["HOME"] = tempfile.gettempdir()
        run = subprocess.run(
            [str(command), "--version"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(run.stdout.strip(), "ucandrop 1.1.0")

    def test_runtime_sources_have_no_account_or_installed_omdrop_path(self):
        paths = [*BIN.glob("*.py"), BIN / "ucandrop", *CLIENT.glob("share/**/*"),
                 CLIENT / "manifest.json", *RECEIVER.glob("*.py")]
        forbidden = ("/usr/lib/omdrop", "/home/", "/Users/")
        for path in paths:
            if not path.is_file():
                continue
            with self.subTest(path=path):
                text = path.read_text(errors="replace")
                for token in forbidden:
                    self.assertNotIn(token, text)

    def test_on_rejects_temporary_runtime_before_side_effects(self):
        with tempfile.TemporaryDirectory(prefix="ucandrop-runtime-guard-") as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            runtime = root / "runtime"
            runtime.mkdir()
            fakebin = root / "bin"
            fakebin.mkdir()
            for name in ("systemctl", "pkexec"):
                helper = fakebin / name
                helper.write_text(
                    f"#!/bin/sh\nprintf '%s\\n' {name} >> {shlex.quote(str(root / 'called'))}\n"
                    "exit 1\n"
                )
                helper.chmod(0o755)
            env = os.environ.copy()
            env.update(
                HOME=str(home),
                XDG_CONFIG_HOME=str(root / "config"),
                XDG_RUNTIME_DIR=str(runtime),
                XDG_BIN_HOME=str(root / "bin-home"),
                PATH=f"{fakebin}:{env['PATH']}",
            )
            result = subprocess.run(
                [str(BIN / "ucandrop"), "on", "1m"],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "use logged-in desktop session; remove temporary XDG_RUNTIME_DIR override",
                result.stderr,
            )
            self.assertFalse((root / "called").exists())
            self.assertFalse((runtime / "omdrop" / "window").exists())

    def test_candidate_uses_bundled_receiver_and_public_ucandrop_units(self):
        serve = (BIN / "airdrop-serve.py").read_text()
        command = (BIN / "ucandrop").read_text()
        self.assertIn("..', '..', 'receiver", serve)
        self.assertIn("install_local_upload_completion", serve)
        self.assertIn("ucandrop-receiver.service", command)
        self.assertIn("XDG_BIN_HOME", command)
        self.assertIn("/usr/lib/ucandrop/radio/omdrop-discoverable", command)
        self.assertIn("/usr/lib/ucandrop/radio/send-to-peer", command)
        self.assertIn(
            "PRIVILEGED_DISCOVERABLE=/usr/lib/ucandrop/radio/omdrop-discoverable",
            command,
        )
        self.assertNotIn('pkexec "$DISCOVERABLE"', command)
        self.assertIn("--config @CONFIG_PATH@", (CLIENT / "share/ucandrop-receiver.service").read_text())
        self.assertTrue((CLIENT / "share/ucandrop-receiver.service").is_file())
        for unit in (CLIENT / "share").glob("ucandrop-*.service"):
            text = unit.read_text()
            self.assertIn("@PLUGIN_DIR@", text)

        # Native notifications are the release's only desktop integration.
        self.assertTrue((BIN / "airdrop_notify.py").is_file())

    @unittest.skipUnless(shutil.which("systemd-analyze"),
                         "needs systemd-analyze to parse a rendered user unit")
    def test_rendered_receiver_unit_uses_custom_xdg_config_and_parses(self):
        """Render a real unit through setup without starting a user service."""
        with tempfile.TemporaryDirectory(prefix="ucandrop-unit-") as temporary:
            root = Path(temporary)
            plugin = root / "plugin % Δ"
            shutil.copytree(CLIENT, plugin)
            home = root / "home % Δ"
            home.mkdir()
            config_home = root / "config % Δ"
            config_dir = config_home / "airdrop"
            config_dir.mkdir(parents=True)
            download = root / "download % Δ"
            download.mkdir()
            (config_dir / "config.toml").write_text(
                f'name = "fixture"\n'
                f'download_dir = {json.dumps(str(download))}\n',
                encoding="utf-8",
            )
            fakebin = root / "bin"
            fakebin.mkdir()
            for name in ("systemctl", "xdg-mime", "update-desktop-database",
                         "update-mime-database"):
                helper = fakebin / name
                helper.write_text("#!/bin/sh\nexit 0\n")
                helper.chmod(0o755)
            env = os.environ.copy()
            env.update(
                HOME=str(home),
                XDG_CONFIG_HOME=str(config_home),
                XDG_BIN_HOME=str(root / "bin-home"),
                XDG_RUNTIME_DIR=str(root / "runtime"),
                UCANDROP_IFACE="fixture0",
                PATH=f"{fakebin}:{env['PATH']}",
            )
            result = subprocess.run(
                [str(plugin / "bin/ucandrop"), "setup"],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            unit = config_home / "systemd/user/ucandrop-receiver.service"
            self.assertTrue(unit.is_file())
            rendered = unit.read_text()
            escaped_plugin = str(plugin).replace("%", "%%").replace(" ", r"\x20")
            escaped_config_home = str(config_home).replace("%", "%%").replace(" ", r"\x20")
            escaped_config = str(config_dir / "config.toml").replace("%", "%%").replace(" ", r"\x20")
            escaped_download = str(download).replace("%", "%%").replace(" ", r"\x20")
            self.assertIn(f"WorkingDirectory={escaped_plugin}", rendered)
            self.assertIn(f"Environment=XDG_CONFIG_HOME={escaped_config_home}", rendered)
            self.assertIn("Environment=XDG_RUNTIME_DIR=%t", rendered)
            self.assertIn(f"--config {escaped_config}", rendered)
            self.assertIn(f"ReadWritePaths={escaped_download} %h/.omdrop", rendered)
            self.assertNotIn("@CONFIG_PATH@", rendered)
            verified = subprocess.run(
                ["systemd-analyze", "verify", str(unit)],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_download_resolution_honors_xdg_user_dirs_with_unicode_and_spaces(self):
        with tempfile.TemporaryDirectory(prefix="ucandrop-client-") as temporary:
            root = Path(temporary)
            home = root / "home user Δ"
            download = home / "Téléchargements %"
            home.mkdir()
            download.mkdir()
            fakebin = root / "bin"
            fakebin.mkdir()
            helper = fakebin / "xdg-user-dir"
            helper.write_text(
                "#!/bin/sh\n"
                "[ \"$1\" = DOWNLOAD ] || exit 1\n"
                f"printf '%s\\n' {shlex.quote(str(download))}\n"
            )
            helper.chmod(0o755)
            env = os.environ.copy()
            env.update(
                HOME=str(home),
                XDG_CONFIG_HOME=str(root / "config"),
                XDG_RUNTIME_DIR=str(root / "run"),
                PATH=f"{fakebin}:{env['PATH']}",
            )
            run = subprocess.run(
                [str(BIN / "ucandrop"), "dir"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(run.stdout.strip(), str(download))

    def test_download_dir_rejects_control_characters_before_writing_toml(self):
        with tempfile.TemporaryDirectory(prefix="ucandrop-dir-control-") as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            selected = root / "download\nfolder"
            selected.mkdir()
            fakebin = root / "bin"
            fakebin.mkdir()
            systemctl = fakebin / "systemctl"
            systemctl.write_text("#!/bin/sh\nexit 3\n")
            systemctl.chmod(0o755)
            config_home = root / "config"
            env = os.environ.copy()
            env.update(
                HOME=str(home),
                XDG_CONFIG_HOME=str(config_home),
                XDG_RUNTIME_DIR=str(root / "runtime"),
                PATH=f"{fakebin}:{env['PATH']}",
            )
            run = subprocess.run(
                [str(BIN / "ucandrop"), "dir", str(selected)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("control characters", run.stderr)
            self.assertFalse((config_home / "airdrop" / "config.toml").exists())

    def test_contact_settings_are_private(self):
        with tempfile.TemporaryDirectory(prefix="ucandrop-contacts-") as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            fakebin = root / "bin"
            fakebin.mkdir()
            systemctl = fakebin / "systemctl"
            systemctl.write_text("#!/bin/sh\nexit 3\n")
            systemctl.chmod(0o755)
            config_home = root / "config"
            env = os.environ.copy()
            env.update(
                HOME=str(home),
                XDG_CONFIG_HOME=str(config_home),
                XDG_RUNTIME_DIR=str(root / "runtime"),
                PATH=f"{fakebin}:{env['PATH']}",
            )
            visibility = subprocess.run(
                [str(BIN / "ucandrop"), "visibility", "contacts"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(visibility.returncode, 0, visibility.stderr)
            senders = subprocess.run(
                [str(BIN / "ucandrop"), "senders", "add", "friend@example.com"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(senders.returncode, 0, senders.stderr)
            contacts = config_home / "omdrop"
            self.assertEqual(stat.S_IMODE(contacts.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((contacts / "visibility").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((contacts / "known-senders").stat().st_mode), 0o600)

    def test_selected_download_dir_is_escaped_in_the_user_unit_dropin(self):
        with tempfile.TemporaryDirectory(prefix="ucandrop-dir-") as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            selected = root / "drop % Δ"
            selected.mkdir()
            fakebin = root / "bin"
            fakebin.mkdir()
            systemctl = fakebin / "systemctl"
            systemctl.write_text("#!/bin/sh\nexit 0\n")
            systemctl.chmod(0o755)
            env = os.environ.copy()
            env.update(
                HOME=str(home),
                XDG_CONFIG_HOME=str(root / "config"),
                XDG_RUNTIME_DIR=str(root / "run"),
                PATH=f"{fakebin}:{env['PATH']}",
            )
            run = subprocess.run(
                [str(BIN / "ucandrop"), "dir", str(selected)],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn(str(selected), run.stdout)
            dropin = (root / "config/systemd/user/ucandrop-receiver.service.d"
                       / "10-download-dir.conf")
            escaped = str(selected).replace("%", "%%").replace(" ", r"\x20")
            self.assertIn(f"ReadWritePaths={escaped}", dropin.read_text())

    def test_url_asks_stay_volatile_and_use_candidate_socket_namespace(self):
        sys.path.insert(0, str(BIN))
        try:
            import web_links
            address = web_links.link_socket_address("/tmp/isolated runtime Δ")
            self.assertTrue(address.startswith("\0ucandrop.links."))
            self.assertTrue(web_links.valid_web_url("https://example.test/path?q=1%20two"))
            self.assertFalse(web_links.valid_web_url("file:///etc/passwd"))
            serve = (BIN / "airdrop-serve.py").read_text()
            self.assertNotIn("def store_link", serve)
            self.assertIn("receive_links(self, items)", serve)
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
