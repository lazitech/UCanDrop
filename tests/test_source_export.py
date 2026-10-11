"""Release archives must not retain exporting-user metadata or build outputs."""
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_export', ROOT / 'tools/export-release.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class SourceExportTests(unittest.TestCase):
    def test_archive_uses_generic_metadata_and_excludes_build_artifacts(self):
        with tempfile.TemporaryDirectory(prefix='ucandrop-export-test-') as temporary:
            root = Path(temporary) / 'source'
            root.mkdir()
            (root / 'VERSION').write_text('1.1.0\n')
            (root / 'tool.sh').write_text('#!/bin/sh\nexit 0\n')
            (root / 'tool.sh').chmod(0o755)
            (root / 'build').mkdir()
            (root / 'build/owl').write_bytes(b'\x7fELFfixture')
            archive = exporter.export(root, Path(temporary) / 'output')
            first = archive.read_bytes()
            archive = exporter.export(root, Path(temporary) / 'output')
            self.assertEqual(first, archive.read_bytes())
            with tarfile.open(archive) as stream:
                members = stream.getmembers()
                self.assertFalse(any('/build/' in member.name for member in members))
                for member in members:
                    self.assertEqual((member.uid, member.gid), (0, 0))
                    self.assertEqual((member.uname, member.gname), ('', ''))
                script = stream.getmember('ucandrop-1.1.0/tool.sh')
                self.assertEqual(script.mode, 0o755)


if __name__ == '__main__':
    unittest.main()
