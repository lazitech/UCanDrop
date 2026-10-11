"""Bounded, incremental DVZip/ODC completion detection.

Payload bytes are counted and skipped, never retained. A positive result is
only a signal to run the existing full strict archive check on the wire copy.
"""
import zlib

from cpio_completion import _InvalidArchive, _octal


OUTPUT_CHUNK = 64 * 1024


class OdcProgress:
    def __init__(self, byte_limit, max_members):
        self.byte_limit = byte_limit
        self.max_members = max_members
        self.total = 0
        self.members = 0
        self.media_members = 0
        self.media_bytes = 0
        self.invalid = False
        self.phase = "header"
        self.needed = 76
        self.buffer = bytearray()
        self.mode = 0
        self.file_size = 0

    @property
    def complete(self):
        return not self.invalid and self.phase == "padding"

    def feed(self, data):
        if self.invalid:
            return
        self.total += len(data)
        if self.total > self.byte_limit:
            self.invalid = True
            return
        offset = 0
        try:
            while offset < len(data):
                if self.phase == "padding":
                    if any(data[offset:]):
                        raise _InvalidArchive
                    return
                count = min(self.needed, len(data) - offset)
                if self.phase != "data":
                    self.buffer.extend(data[offset:offset + count])
                offset += count
                self.needed -= count
                if self.needed:
                    continue
                if self.phase == "header":
                    header = bytes(self.buffer)
                    self.buffer.clear()
                    if header[:6] != b"070707":
                        raise _InvalidArchive
                    fields = [_octal(header[a:b]) for a, b in (
                        (6, 12), (12, 18), (18, 24), (24, 30),
                        (30, 36), (36, 42), (42, 48), (48, 59),
                        (59, 65), (65, 76))]
                    self.mode, self.file_size = fields[2], fields[9]
                    if not 1 <= fields[8] <= 4096:
                        raise _InvalidArchive
                    self.phase, self.needed = "name", fields[8]
                elif self.phase == "name":
                    name = bytes(self.buffer)
                    self.buffer.clear()
                    if name[-1:] != b"\0" or b"\0" in name[:-1]:
                        raise _InvalidArchive
                    if name == b"TRAILER!!!\0":
                        if self.file_size:
                            raise _InvalidArchive
                        self.phase = "padding"
                        continue
                    self.members += 1
                    if self.members > self.max_members:
                        raise _InvalidArchive
                    if self.mode & 0o170000 == 0o100000:
                        if not name[:-1].rsplit(b"/", 1)[-1].startswith(b"._"):
                            self.media_members += 1
                            self.media_bytes += self.file_size
                    if self.file_size:
                        self.phase, self.needed = "data", self.file_size
                    else:
                        self.phase, self.needed = "header", 76
                else:
                    self.phase, self.needed = "header", 76
        except _InvalidArchive:
            self.invalid = True


class ArchiveProgress:
    def __init__(self, byte_limit, max_members):
        self.cpio = OdcProgress(byte_limit, max_members)
        self.mode = None
        self.header = bytearray()
        self.remaining = 0
        self.stored = False
        self.decoder = None
        self.invalid = False

    def _inflate(self, data):
        while True:
            output = self.decoder.decompress(data, OUTPUT_CHUNK)
            self.cpio.feed(output)
            if self.cpio.invalid or self.decoder.unused_data:
                self.invalid = True
                return
            data = self.decoder.unconsumed_tail
            if not data and len(output) < OUTPUT_CHUNK:
                return

    def feed(self, data):
        if self.invalid:
            return
        offset = 0
        try:
            if self.mode is None:
                count = min(2 - len(self.header), len(data))
                self.header.extend(data[:count])
                offset += count
                if len(self.header) < 2:
                    return
                self.mode = "gzip" if self.header == b"\x1f\x8b" else "blocks"
                if self.mode == "gzip":
                    self.decoder = zlib.decompressobj(31)
                    self._inflate(bytes(self.header))
                    self.header.clear()
            if self.mode == "gzip":
                self._inflate(data[offset:])
                return
            while offset < len(data):
                if not self.remaining:
                    count = min(4 - len(self.header), len(data) - offset)
                    self.header.extend(data[offset:offset + count])
                    offset += count
                    if len(self.header) < 4:
                        return
                    value = int.from_bytes(self.header, "big")
                    self.header.clear()
                    self.remaining = value & 0x7fffffff
                    self.stored = bool(value & 0x80000000)
                    self.decoder = None if self.stored else zlib.decompressobj()
                    # The original decoder rejects an empty compressed block.
                    if not self.remaining and not self.stored:
                        self.invalid = True
                        return
                    if not self.remaining:
                        continue
                count = min(self.remaining, len(data) - offset)
                piece = data[offset:offset + count]
                offset += count
                self.remaining -= count
                if self.stored:
                    self.cpio.feed(piece)
                else:
                    self._inflate(piece)
                    if not self.remaining and not self.decoder.eof:
                        self.invalid = True
                if self.cpio.invalid or self.invalid:
                    self.invalid = True
                    return
        except zlib.error:
            self.invalid = True

    def matches(self, announced):
        framing_complete = (self.decoder is not None and self.decoder.eof
                            if self.mode == "gzip"
                            else self.mode == "blocks" and not self.header
                            and not self.remaining)
        return bool(not self.invalid and framing_complete and self.cpio.complete
                    and self.cpio.media_members > 0
                    and self.cpio.media_bytes == announced)


class ProgressWriter:
    def __init__(self, writer, progress):
        self.writer = writer
        self.progress = progress

    def write(self, data):
        written = self.writer.write(data)
        self.progress.feed(data)
        return written
