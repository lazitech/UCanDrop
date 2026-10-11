"""Strict, side-effect-free inspection of old ASCII cpio (ODC) archives."""

from __future__ import annotations


_MAGIC = b"070707"
_HEADER_BYTES = 76
_MAX_NAME_BYTES = 4096
_TRAILER = b"TRAILER!!!\x00"
_READ_BYTES = 64 * 1024


class _InvalidArchive(Exception):
    pass


def _octal(field):
    if not field or any(byte < ord("0") or byte > ord("7") for byte in field):
        raise _InvalidArchive
    return int(field, 8)


def _read_exact(stream, size, end):
    if size < 0:
        raise _InvalidArchive
    try:
        position = stream.tell()
    except (OSError, ValueError, TypeError):
        raise _InvalidArchive
    if position < 0 or position + size > end:
        raise _InvalidArchive

    parts = []
    remaining = size
    while remaining:
        try:
            part = stream.read(remaining)
        except (OSError, ValueError, TypeError):
            raise _InvalidArchive
        if not isinstance(part, (bytes, bytearray)) or not part:
            raise _InvalidArchive
        if len(part) > remaining:
            raise _InvalidArchive
        parts.append(bytes(part))
        remaining -= len(part)
    return b"".join(parts)


def _skip_exact(stream, size, end):
    remaining = size
    while remaining:
        count = min(remaining, _READ_BYTES)
        _read_exact(stream, count, end)
        remaining -= count


def _inspect(stream, start, end, byte_limit, max_members):
    magic = _read_exact(stream, len(_MAGIC), end)
    if magic != _MAGIC:
        return None
    try:
        stream.seek(start)
    except (OSError, ValueError, TypeError):
        raise _InvalidArchive

    members = 0
    media_members = 0
    media_bytes = 0

    while True:
        header = _read_exact(stream, _HEADER_BYTES, end)
        if header[:6] != _MAGIC:
            raise _InvalidArchive

        fields = (
            _octal(header[6:12]),       # device
            _octal(header[12:18]),      # inode
            _octal(header[18:24]),      # mode
            _octal(header[24:30]),      # uid
            _octal(header[30:36]),      # gid
            _octal(header[36:42]),      # links
            _octal(header[42:48]),      # rdev
            _octal(header[48:59]),      # mtime
            _octal(header[59:65]),      # name size
            _octal(header[65:76]),      # file size
        )
        mode = fields[2]
        namesize = fields[8]
        filesize = fields[9]
        if not 1 <= namesize <= _MAX_NAME_BYTES:
            raise _InvalidArchive

        name = _read_exact(stream, namesize, end)
        if name[-1:] != b"\x00" or b"\x00" in name[:-1]:
            raise _InvalidArchive

        if name == _TRAILER:
            if filesize != 0:
                raise _InvalidArchive
            # ODC has no inter-member alignment. Once the exact trailer has
            # appeared, only zero padding may remain through the decoded EOF.
            while True:
                try:
                    position = stream.tell()
                except (OSError, ValueError, TypeError):
                    raise _InvalidArchive
                if position == end:
                    return {
                        "media_bytes": media_bytes,
                        "media_members": media_members,
                        "members": members,
                    }
                if position < start or position > end:
                    raise _InvalidArchive
                padding = _read_exact(stream, min(_READ_BYTES, end - position), end)
                if any(padding):
                    raise _InvalidArchive

        members += 1
        if members > max_members:
            raise _InvalidArchive

        if mode & 0o170000 == 0o100000:
            basename = name[:-1].rsplit(b"/", 1)[-1]
            if not basename.startswith(b"._"):
                media_members += 1
                media_bytes += filesize

        _skip_exact(stream, filesize, end)


def inspect_odc_archive(stream, byte_limit, max_members):
    """Inspect a complete seekable ODC archive without extracting it.

    The stream is read from its current position and is restored to that
    position before returning.  ``None`` means the stream is unsupported,
    incomplete, malformed, or exceeds either supplied limit.  Successful
    metadata contains only aggregate counts and byte totals; member names are
    deliberately never returned or logged.
    """
    original = None
    try:
        if (isinstance(byte_limit, bool) or not isinstance(byte_limit, int)
                or byte_limit < 0):
            return None
        if (isinstance(max_members, bool) or not isinstance(max_members, int)
                or max_members < 0):
            return None

        original = stream.tell()
        if not isinstance(original, int) or original < 0:
            return None
        stream.seek(0, 2)
        end = stream.tell()
        if not isinstance(end, int) or end < original:
            return None
        if end - original > byte_limit:
            return None
        stream.seek(original)
        return _inspect(stream, original, end, byte_limit, max_members)
    except (OSError, ValueError, TypeError, OverflowError, EOFError,
            _InvalidArchive):
        return None
    finally:
        if original is not None:
            try:
                stream.seek(original)
            except (OSError, ValueError, TypeError):
                pass
