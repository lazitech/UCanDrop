"""The release gate must reject actual leaks, not merely run successfully."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_audit', ROOT / 'tools/verify-release.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ucandrop-audit-fixture-')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name, data):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def test_accepts_protocol_constants_and_relative_user_resolution(self):
        self.write('settings.py', b'port = 8771\niface = "awdl0"\nroot = Path.home()\n')
        self.assertEqual(audit.inspect_tree(self.root), [])

    def test_project_named_account_is_not_mistaken_for_a_private_identity(self):
        self.write('README.md', b'UCanDrop is based on Omdrop.\n')
        with patch.object(audit.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='ucandrop')), \
                patch.object(audit.socket, 'gethostname', return_value='omdrop'):
            self.assertEqual(audit.inspect_tree(self.root), [])

    def test_rejects_account_path(self):
        self.write('script.sh', b'cd ' + b'/home/' + b'fixture-account/project\n')
        self.assertTrue(any('home path' in error for error in audit.inspect_tree(self.root)))

    def test_rejects_private_artifacts_and_binary(self):
        self.write('transfer.pcap', b'capture fixture')
        self.write('owl', b'\x7fELFfixture')
        errors = audit.inspect_tree(self.root)
        self.assertEqual(len(errors), 2)

    def test_rejects_private_key(self):
        self.write('secret.txt', b'-----BEGIN ' + b'PRIVATE KEY-----\nfixture\n')
        self.assertTrue(any('private key' in error for error in audit.inspect_tree(self.root)))

    def test_rejects_external_symlink(self):
        (self.root / 'escape').symlink_to('/etc/passwd')
        self.assertTrue(any('external' in error for error in audit.inspect_tree(self.root)))

    def test_ignores_build_outputs_that_are_excluded_from_source_export(self):
        self.write('build/owl', b'\x7fELFfixture')
        self.assertEqual(audit.inspect_tree(self.root), [])


if __name__ == '__main__':
    unittest.main()
