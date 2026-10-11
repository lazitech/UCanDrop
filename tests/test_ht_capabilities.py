"""Build and exercise the release's HT wire format without a physical radio."""
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'vendor/owl'
BUILD = ROOT / 'build/owl'


class HTCapabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name in ('cc', 'pkg-config'):
            if not shutil.which(name):
                raise unittest.SkipTest(f'build tool unavailable: {name}')
        flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'libnl-3.0',
                                'libnl-genl-3.0', 'libnl-route-3.0'],
                               capture_output=True, text=True)
        if flags.returncode:
            raise unittest.SkipTest('libnl development packages unavailable')
        cls.temporary = tempfile.TemporaryDirectory(prefix='ucandrop-ht-test-')
        cls.output = Path(cls.temporary.name)
        cls.normalizer = cls.output / 'normalize'
        command = ['cc', '-std=c11', '-D_DEFAULT_SOURCE', '-Wall', '-Wextra',
                   '-I', str(SOURCE / 'src'), '-I', str(SOURCE / 'daemon'),
                   str(ROOT / 'tests/ht_mcs_normalize_harness.c'),
                   str(SOURCE / 'daemon/netutils.c'), str(SOURCE / 'src/channel.c'),
                   str(SOURCE / 'src/log.c'), *shlex.split(flags.stdout),
                   '-o', str(cls.normalizer)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            cls.temporary.cleanup()
            raise AssertionError(result.stdout + result.stderr)
        cls.wire = cls.output / 'wire'
        cls.wire_available = (BUILD / 'src/libawdl.a').is_file()
        if cls.wire_available:
            command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                       '-DHT_EXPERIMENT_CANDIDATE', '-I', str(SOURCE / 'src'),
                       str(ROOT / 'tests/ht_caps_wire_harness.c'),
                       str(BUILD / 'src/libawdl.a'), str(BUILD / 'libradiotap.a'),
                       '-o', str(cls.wire)]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                cls.temporary.cleanup()
                raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_actual_normalizer_handles_stream_counts_and_invalid_capabilities(self):
        result = subprocess.run([str(self.normalizer)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for case in ('one-stream', 'two-stream', 'antenna-clamp', 'two-antenna',
                     'sparse', 'short', 'zero-antenna', 'four-stream-cap',
                     'preserve-masks'):
            self.assertIn(f'case={case} ', result.stdout)

    def test_actual_wire_encoder_keeps_lengths_padding_and_fallback(self):
        if not self.wire_available:
            self.skipTest('run tools/build.sh first to enable wire-library checks')
        for case in ('legacy', 'two-stream', 'four-stream', 'invalid-state'):
            with self.subTest(case=case):
                result = subprocess.run([str(self.wire), case],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('sentinel=cc', result.stdout)


if __name__ == '__main__':
    unittest.main()
