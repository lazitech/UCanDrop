"""Check actual Debian archive metadata and default installed backend discovery."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = sorted((ROOT / 'dist').glob('ucandrop_1.1.0_*.deb'))


@unittest.skipUnless(PACKAGES, 'build a native release package first')
class PackageMetadataTests(unittest.TestCase):
    def test_extracted_command_discovers_the_packaged_backend(self):
        for package in PACKAGES:
            with self.subTest(package=package.name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                extracted = root / "package % Δ"
                extracted.mkdir()
                subprocess.run(['dpkg-deb', '-x', str(package), str(extracted)], check=True)
                radio = extracted / 'usr/lib/ucandrop/radio/omdrop-discoverable'
                marker = root / 'probed'
                probe = {'backend': 'owl', 'hardware': True,
                         'missing': [{'id': 'radio', 'say': 'Fixture radio is disconnected.'}]}
                radio.write_text(
                    '#!/bin/sh\n[ "$*" = "probe --json" ] || exit 2\n'
                    f'touch {shlex.quote(str(marker))}\n'
                    f'printf \'%s\\n\' {shlex.quote(json.dumps(probe))}\n'
                )
                radio.chmod(0o755)
                home = root / 'home'
                home.mkdir()
                sysfs = root / 'sys'
                (sysfs / 'bus/pci/devices').mkdir(parents=True)
                fakebin = root / 'bin'
                fakebin.mkdir()
                systemctl = fakebin / 'systemctl'
                systemctl.write_text('#!/bin/sh\nexit 3\n')
                systemctl.chmod(0o755)
                env = os.environ.copy()
                for name in ('UCANDROP_DISCOVERABLE', 'OMDROP_DISCOVERABLE'):
                    env.pop(name, None)
                env.update(
                    HOME=str(home), XDG_CONFIG_HOME=str(root / 'config'),
                    XDG_RUNTIME_DIR=str(root / 'run'), OMDROP_SYSFS=str(sysfs),
                    PATH=f"{fakebin}:{env['PATH']}",
                )
                result = subprocess.run(
                    [str(extracted / 'usr/bin/ucandrop'), 'doctor', '--json'],
                    env=env, text=True, capture_output=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(marker.is_file(), 'packaged radio helper was not probed')
                missing = json.loads(result.stdout)['missing']
                self.assertIn(probe['missing'][0], missing)
                self.assertNotIn('hardware', {item['id'] for item in missing})

    def test_outer_archive_metadata_matches_the_declared_release_epoch(self):
        for package in PACKAGES:
            with self.subTest(package=package.name), tempfile.TemporaryDirectory() as temporary:
                subprocess.run(['dpkg-deb', '-x', str(package), temporary], check=True)
                provenance = (Path(temporary) / 'usr/share/doc/ucandrop/source-provenance.txt').read_text()
                fields = dict(line.split('=', 1) for line in provenance.splitlines())
                epoch = int(fields['source-date-epoch'])
                archive = package.read_bytes()
                self.assertTrue(archive.startswith(b'!<arch>\n'))
                offset = 8
                members = []
                while offset < len(archive):
                    header = archive[offset:offset + 60]
                    self.assertEqual(len(header), 60)
                    self.assertEqual(header[58:], b'`\n')
                    name = header[:16].decode().strip().rstrip('/')
                    members.append(name)
                    self.assertEqual(int(header[16:28]), epoch, name)
                    self.assertEqual(int(header[28:34]), 0, name)
                    self.assertEqual(int(header[34:40]), 0, name)
                    size = int(header[48:58])
                    offset += 60 + size + (size % 2)
                self.assertEqual(offset, len(archive))
                self.assertIn('debian-binary', members)


if __name__ == '__main__':
    unittest.main()
