#!/usr/bin/env python3
"""Windows Podman start via scheduled task helpers."""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from utils.utils import (  # noqa: E402
    PODMAN_START_TASK_NAME,
    podman_start_task_command,
    schtasks_run_failed,
)


class PodmanSchtasksTests(unittest.TestCase):
    def test_start_task_command(self):
        self.assertEqual(
            podman_start_task_command(),
            f'schtasks /Run /TN "{PODMAN_START_TASK_NAME}"',
        )

    def test_detects_error_on_stdout(self):
        self.assertTrue(
            schtasks_run_failed(
                'ERROR: The system cannot find the file specified.\r\n',
                "",
            )
        )

    def test_success_output_ok(self):
        self.assertFalse(
            schtasks_run_failed("SUCCESS: Attempted to run the scheduled task.\r\n", "")
        )


if __name__ == "__main__":
    unittest.main()
