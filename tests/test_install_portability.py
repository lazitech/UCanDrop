"""Static portability checks for the source-only UCanDrop installer.

These checks intentionally do not install a package, start a service, invoke
sudo, or inspect the current user's radio.  The release build is tested by
building a .deb separately and inspecting its archive contents.
"""

from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
PACKAGING = ROOT / "packaging"


class InstallPortabilityTests(unittest.TestCase):
    def test_shell_entrypoints_parse(self):
        for name in ("build.sh", "build-deb.sh", "install.sh"):
            with self.subTest(name=name):
                subprocess.run(
                    ["bash", "-n", str(TOOLS / name)],
                    check=True,
                    capture_output=True,
                    text=True,
                )

    def test_no_checkout_or_personal_paths_in_release_control(self):
        paths = [
            TOOLS / "build.sh",
            TOOLS / "build-deb.sh",
            TOOLS / "install.sh",
            PACKAGING / "control",
            PACKAGING / "README.Debian",
            PACKAGING / "copyright",
        ]
        forbidden = re.compile(
            r"(?:/(?:home|root|Users)/[^/\s|]+|omdrop-home)"
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertIsNotNone(path.read_text())
                self.assertIsNone(forbidden.search(path.read_text()))

    def test_new_install_layout_is_explicit(self):
        builder = (TOOLS / "build-deb.sh").read_text()
        self.assertIn("/usr/lib/ucandrop/client", builder)
        self.assertIn("/usr/lib/ucandrop/radio", builder)
        self.assertIn("/usr/bin/ucandrop", builder)
        self.assertIn("/usr/lib/ucandrop/receiver", builder)
        self.assertIn("/usr/lib/omdrop", builder)  # rejected legacy archive path
        self.assertIn("__pycache__", builder)
        self.assertIn("*.tmp", builder)

    def test_build_is_unprivileged_and_offline(self):
        build = (TOOLS / "build.sh").read_text()
        self.assertNotRegex(build, r"(?m)^\s*(?:apt-get|sudo)\b")
        self.assertNotRegex(build, r"(?m)^\s*git\s+clone\b")
        self.assertIn("CMAKE_C_FLAGS", build)
        self.assertIn("CMAKE_CXX_FLAGS", build)

    def test_build_dependency_flag_requires_install_mode(self):
        install = (TOOLS / "install.sh").read_text()
        self.assertIn("--install-build-deps requires --install", install)
        result = subprocess.run(
            [str(TOOLS / "install.sh"), "--check", "--install-build-deps"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--install-build-deps requires --install", result.stderr)

    def test_package_has_no_maintainer_start_hooks(self):
        package_files = list(PACKAGING.iterdir())
        self.assertFalse(any(path.name in {"postinst", "prerm", "postrm", "preinst"}
                             for path in package_files))
        readme = (PACKAGING / "README.Debian").read_text()
        self.assertIn("receiving is disabled", readme)
        self.assertIn("ucandrop setup", readme)
        self.assertIn("ucandrop on", readme)

    def test_vendored_build_inputs_are_present(self):
        self.assertTrue((ROOT / "vendor/owl/CMakeLists.txt").is_file())
        self.assertTrue((ROOT / "vendor/owl/daemon/CMakeLists.txt").is_file())
        self.assertTrue((ROOT / "vendor/owl/radiotap/radiotap.c").is_file())
        self.assertFalse((ROOT / "vendor/owl/.git").exists())

    def test_contacts_certificates_are_explicit_package_inputs(self):
        contacts = (ROOT / "client/bin/contacts.py").read_text()
        builder = (TOOLS / "build-deb.sh").read_text()
        assets = (
            ROOT / "client/share/certs/apple_root_ca.pem",
            ROOT / "client/bin/apple-ca/apple-aai-ca.pem",
            ROOT / "client/bin/apple-ca/apple-aai2-ca.pem",
        )
        for asset in assets:
            with self.subTest(asset=asset):
                self.assertTrue(asset.is_file())
                self.assertGreater(asset.stat().st_size, 0)
                self.assertIn(str(asset.relative_to(ROOT)), builder)

        # These paths are the runtime loader's actual locations: the root is
        # under client/share/certs and both intermediates are beside contacts.py.
        self.assertIn('parent.parent / "share" / "certs" / "apple_root_ca.pem"', contacts)
        self.assertIn('parent / "apple-ca"', contacts)
        for package_asset in (
            "usr/lib/ucandrop/client/share/certs/apple_root_ca.pem",
            "usr/lib/ucandrop/client/bin/apple-ca/apple-aai-ca.pem",
            "usr/lib/ucandrop/client/bin/apple-ca/apple-aai2-ca.pem",
        ):
            self.assertIn(package_asset, builder)


if __name__ == "__main__":
    unittest.main()
