#!/usr/bin/python3
"""Start one owned radio child with ordinary signal dispositions."""

from __future__ import annotations

import os
import signal
import sys


def main() -> int:
    if len(sys.argv) < 2:
        return 2

    # Python resets ignored signals only for handlers installed by Python.
    # Explicitly restore every signal the caller may have ignored before the
    # privileged helper launched this child.
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM,
                   signal.SIGQUIT, signal.SIGPIPE):
        signal.signal(signum, signal.SIG_DFL)

    try:
        os.close(9)
    except OSError:
        pass

    # `setsid` normally creates the session for this process.  The fallback
    # keeps the shim correct when it is invoked directly in an isolated test.
    try:
        os.setsid()
    except OSError:
        pass

    os.execv(sys.argv[1], sys.argv[1:])
    return 127


if __name__ == '__main__':
    raise SystemExit(main())
