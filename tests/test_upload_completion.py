"""Run the candidate receiver's real TLS completion regressions in the root suite.

The source-tree README uses ``python3 -m unittest discover -s tests`` as its
portable verification entrypoint. Keep the end-to-end upload tests there so
that entrypoint exercises the bundled receiver rather than only static checks.
"""

import unittest

from client.tests import test_upload_completion as completion


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromModule(completion)


if __name__ == "__main__":
    unittest.main()
