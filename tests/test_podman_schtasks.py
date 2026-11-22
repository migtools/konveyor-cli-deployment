#!/usr/bin/env python3
"""Windows Podman start via scheduled task helpers."""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from utils.utils import (  # noqa: E402
    PODMAN_READY_ATTEMPTS_WINDOWS,
    PODMAN_READY_SLEEP_SEC,
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

    def test_windows_ready_wait_covers_hyperv_cold_start(self):
        # Observed: Hyper-V VM ready ~4 min after schtasks; old budget was ~3 min.
        self.assertGreaterEqual(
            PODMAN_READY_ATTEMPTS_WINDOWS * PODMAN_READY_SLEEP_SEC,
            600,
        )


if __name__ == "__main__":
    unittest.main()
