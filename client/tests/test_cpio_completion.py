import io
import sys
import tempfile
import unittest
from pathlib import Path

import libarchive

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "receiver"))
from cpio_completion import inspect_odc_archive


def _octal(value, width):
    return f"{value:0{width}o}".encode("ascii")


def _header(name, size=0, mode=0o100644):
    encoded_name = name if isinstance(name, bytes) else name.encode("utf-8")
    encoded_name += b"\x00"
    header = b"070707" + b"".join((
        _octal(0, 6),       # device
        _octal(0, 6),       # inode
        _octal(mode, 6),
        _octal(0, 6),       # uid
        _octal(0, 6),       # gid
        _octal(1, 6),       # links
        _octal(0, 6),       # rdev
        _octal(0, 11),      # mtime
        _octal(len(encoded_name), 6),
        _octal(size, 11),
    ))
    assert len(header) == 76
    return header


def _entry(name, data=b"", mode=0o100644):
    encoded_name = name if isinstance(name, bytes) else name.encode("utf-8")
    name_with_nul = encoded_name + b"\x00"
    return _header(encoded_name, len(data), mode) + name_with_nul + data


def _archive(entries, padding=b""):
    return b"".join(entries) + _entry(b"TRAILER!!!", b"", 0) + padding


def _libarchive_archive(files):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "payload.cpio"
        with libarchive.file_writer(str(path), "cpio") as archive:
            for name, data in files:
                archive.add_file_from_memory(name, len(data), data)
        return path.read_bytes()


class OdcCompletionTests(unittest.TestCase):
    def inspect(self, data, *, byte_limit=None, max_members=32):
        if byte_limit is None:
            byte_limit = len(data)
        stream = io.BytesIO(data)
        result = inspect_odc_archive(stream, byte_limit, max_members)
        self.assertEqual(stream.tell(), 0)
        return result

    def test_real_libarchive_odc_counts_regular_media_and_ignores_appledouble(self):
        data = _libarchive_archive([
            ("photo.jpg", b"photo"),
            ("._photo.jpg", b"appledouble"),
            ("notes.txt", b"notes"),
        ])

        self.assertEqual(data[:6], b"070707")
        self.assertEqual(self.inspect(data), {
            "media_bytes": 10,
            "media_members": 2,
            "members": 3,
        })

    def test_fake_trailer_inside_file_data_does_not_end_archive(self):
        data = _archive([_entry("photo.jpg", b"prefixTRAILER!!!\x00suffix")])

        self.assertEqual(self.inspect(data), {
            "media_bytes": 23,
            "media_members": 1,
            "members": 1,
        })

    def test_missing_trailer_is_rejected(self):
        self.assertIsNone(self.inspect(_entry("photo.jpg", b"data")))

    def test_truncated_payload_is_rejected(self):
        data = _header(b"photo.jpg", 4) + b"photo.jpg\x00abc"

        self.assertIsNone(self.inspect(data))

    def test_nonzero_trailing_data_is_rejected(self):
        data = _archive([_entry("photo.jpg", b"data")], b"\x00\x00x")

        self.assertIsNone(self.inspect(data))

    def test_zero_padding_after_trailer_is_allowed(self):
        data = _archive([_entry("photo.jpg", b"data")], b"\x00" * 17)

        self.assertEqual(self.inspect(data), {
            "media_bytes": 4,
            "media_members": 1,
            "members": 1,
        })

    def test_member_limit_is_enforced_before_success(self):
        data = _archive([
            _entry("one", b"1"),
            _entry("two", b"22"),
        ])

        self.assertIsNone(self.inspect(data, max_members=1))
        self.assertEqual(self.inspect(data, max_members=2)["members"], 2)

    def test_byte_limit_is_enforced_on_the_complete_decoded_archive(self):
        data = _archive([_entry("photo.jpg", b"data")])

        self.assertIsNone(self.inspect(data, byte_limit=len(data) - 1))
        self.assertIsNotNone(self.inspect(data, byte_limit=len(data)))

    def test_header_must_be_complete_and_all_fields_octal(self):
        data = _archive([_entry("photo.jpg", b"data")])

        self.assertIsNone(self.inspect(data[:75]))
        malformed = bytearray(data)
        malformed[6:12] = b"00000x"
        self.assertIsNone(self.inspect(bytes(malformed)))
        self.assertIsNone(self.inspect(b"070701" + data[6:]))

    def test_name_size_and_termination_are_strict(self):
        oversized = bytearray(_header(b"photo.jpg", 0))
        oversized[59:65] = _octal(4097, 6)
        self.assertIsNone(self.inspect(bytes(oversized)))

        missing_nul = _header(b"photo.jpg", 0) + b"photo.jpg"
        self.assertIsNone(self.inspect(missing_nul))

        embedded_nul = _header(b"a\x00b", 0) + b"a\x00b\x00"
        self.assertIsNone(self.inspect(embedded_nul))

    def test_trailer_name_and_size_are_exact(self):
        bad_size = _archive([_entry("photo.jpg", b"data")])
        trailer_offset = len(bad_size) - 87
        mutated = bytearray(bad_size)
        mutated[trailer_offset + 65:trailer_offset + 76] = _octal(1, 11)
        self.assertIsNone(self.inspect(bytes(mutated)))

        bad_name = _archive([_entry("photo.jpg", b"data")])
        mutated = bytearray(bad_name)
        mutated[trailer_offset + 76:trailer_offset + 87] = b"TRAILER!!X\x00"
        self.assertIsNone(self.inspect(bytes(mutated)))

    def test_nonregular_members_count_toward_total_but_not_media(self):
        data = _archive([
            _entry("directory", mode=0o040755),
            _entry("photo.jpg", b"data"),
        ])

        self.assertEqual(self.inspect(data), {
            "media_bytes": 4,
            "media_members": 1,
            "members": 2,
        })


if __name__ == "__main__":
    unittest.main()
