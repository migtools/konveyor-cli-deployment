#!/usr/bin/env python3
"""Podman readiness must ignore harmless stderr and detect real connection failures."""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from utils.utils import _podman_ready  # noqa: E402


class PodmanReadyTests(unittest.TestCase):
    def test_empty_image_list_is_ready(self):
        out = "REPOSITORY  TAG         IMAGE ID    CREATED     SIZE\n"
        self.assertTrue(_podman_ready(out, ""))

    def test_cannot_connect_not_ready(self):
        err = (
            "Cannot connect to Podman. Please verify your connection...\n"
            "Error: unable to connect to Podman socket: failed to connect: "
            "dial tcp 127.0.0.1:49706: connectex: No connection could be made "
            "because the target machine actively refused it.\n"
        )
        self.assertFalse(_podman_ready("", err))

    def test_harmless_stderr_still_ready_with_table(self):
        # Do not treat any non-empty stderr as failure.
        self.assertTrue(
            _podman_ready(
                "REPOSITORY  TAG         IMAGE ID    CREATED     SIZE\n",
                "time=\"...\" level=warning msg=\"something benign\"\n",
            )
        )

    def test_empty_both_not_ready(self):
        # Ambiguous remote result; keep waiting.
        self.assertFalse(_podman_ready("", ""))


if __name__ == "__main__":
    unittest.main()
