"""Local receive compatibility for a complete archive with a lost HTTP tail.

The original radio and receiver still do the work. This hook only shortens
the wait at a chunk boundary after strict archive validation has succeeded.
"""
import functools
import logging
import tempfile
import threading

from cpio_completion import inspect_odc_archive
from archive_progress import ArchiveProgress, ProgressWriter


# Once the archive has decoded, passed strict ODC inspection, and matched the
# sender's TotalBytes, a missing chunk terminator is only a lost framing tail.
# Keep a short grace period for a delayed marker without adding a full second
# to every completed upload.
COMPLETE_ARCHIVE_WAIT_SECONDS = 0.25


def install(receiver):
    handler_class = receiver["Handler"]
    original_chunked = receiver["_read_chunked"]
    original_upload = handler_class.handle_upload
    original_end_headers = handler_class.end_headers
    current = threading.local()

    @functools.wraps(original_upload)
    def handle_upload(handler):
        current.handler = handler
        try:
            return original_upload(handler)
        finally:
            del current.handler

    @functools.wraps(original_end_headers)
    def end_headers(handler):
        if getattr(handler, "_omdrop_verified_content_eof", False):
            handler.send_header("Connection", "close")
        return original_end_headers(handler)

    def archive_matches(writer, announced):
        position = writer.target.tell()
        try:
            with tempfile.TemporaryFile(dir=receiver["DEST"]) as decoded:
                receiver["decode_dvzip"](
                    writer.target, decoded, writer.limit)
                decoded.seek(0)
                info = inspect_odc_archive(
                    decoded, writer.limit, receiver["MAX_ARCHIVE_MEMBERS"])
            return bool(info and info["media_members"] > 0
                        and info["media_bytes"] == announced)
        except (ValueError, OSError, receiver["UploadLimitError"]):
            return False
        finally:
            writer.target.seek(position)

    @functools.wraps(original_chunked)
    def read_chunked(rfile, writer, deadline):
        handler = getattr(current, "handler", None)
        if handler is None:
            return original_chunked(rfile, writer, deadline)
        value = handler.headers.get("TotalBytes", "")
        try:
            announced = int(value) if value.isascii() and value.isdecimal() else 0
        except ValueError:
            announced = 0
        if not 0 < announced <= writer.limit:
            return original_chunked(rfile, writer, deadline)

        complete = False
        progress = ArchiveProgress(writer.limit, receiver["MAX_ARCHIVE_MEMBERS"])
        sink = ProgressWriter(writer, progress)
        validation_done = False
        verified = False

        def boundary_line():
            old_timeout = handler.connection.gettimeout()
            if complete:
                timeout = COMPLETE_ARCHIVE_WAIT_SECONDS
                if old_timeout is not None:
                    timeout = min(timeout, old_timeout)
                handler.connection.settimeout(timeout)
            try:
                return rfile.readline(receiver["MAX_CHUNK_LINE_BYTES"] + 1)
            except TimeoutError:
                if not complete:
                    raise
                # A timed-out buffered reader cannot be reused. Close this
                # HTTP connection after the normal successful upload reply.
                handler.close_connection = True
                handler._omdrop_verified_content_eof = True
                logging.info(
                    "upload completed after strict archive validation; "
                    "HTTP end marker did not arrive")
                return None
            finally:
                if complete:
                    handler.connection.settimeout(old_timeout)

        while True:
            line = boundary_line()
            if line is None:
                return
            deadline.note(len(line), body=False)
            if (not line or len(line) > receiver["MAX_CHUNK_LINE_BYTES"]
                    or not line.endswith(b"\n")):
                raise receiver["RequestBodyError"](
                    "invalid or overlong chunk-size line")
            token = line.split(b";", 1)[0].strip()
            try:
                size = int(token, 16)
            except ValueError:
                raise receiver["RequestBodyError"]("invalid chunk size") from None
            if size < 0:
                raise receiver["RequestBodyError"]("negative chunk size")
            if size == 0:
                trailers = 0
                while True:
                    line = boundary_line()
                    if line is None:
                        return
                    deadline.note(len(line), body=False)
                    trailers += len(line)
                    if (not line or len(line) > receiver["MAX_CHUNK_LINE_BYTES"]
                            or trailers > receiver["MAX_TRAILER_BYTES"]):
                        raise receiver["RequestBodyError"](
                            "invalid or overlong chunk trailers")
                    if line in (b"\r\n", b"\n"):
                        return
            complete = False
            if size > writer.remaining:
                raise receiver["BodyTooLarge"](
                    f"request body exceeds {writer.limit}-byte limit")
            receiver["_copy_exact"](
                rfile, sink, size, "truncated chunk data", deadline)
            ending = rfile.read(2)
            deadline.note(len(ending), body=False)
            if ending != b"\r\n":
                raise receiver["RequestBodyError"]("chunk data missing CRLF")
            # TotalBytes describes the unpacked files, not the compressed
            # HTTP body. Detect the actual archive end while streaming.
            complete = progress.matches(announced)
            if complete and not validation_done:
                verified = archive_matches(writer, announced)
                validation_done = True
            complete = complete and verified

    handler_class.handle_upload = handle_upload
    handler_class.end_headers = end_headers
    receiver["_read_chunked"] = read_chunked
