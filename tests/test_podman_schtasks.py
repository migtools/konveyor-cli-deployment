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
    podman_machine_missing,
    podman_start_task_command,
    podman_start_task_query_command,
    schtasks_is_running,
    schtasks_run_failed,
)


class PodmanSchtasksTests(unittest.TestCase):
    def test_start_task_command(self):
        self.assertEqual(
            podman_start_task_command(),
            f'schtasks /Run /TN "{PODMAN_START_TASK_NAME}"',
        )

    def test_query_task_command(self):
        self.assertEqual(
            podman_start_task_query_command(),
            f'schtasks /Query /TN "{PODMAN_START_TASK_NAME}" /FO LIST',
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

    def test_schtasks_is_running(self):
        self.assertTrue(
            schtasks_is_running("Status:                               Running\r\n", "")
        )
        self.assertFalse(
            schtasks_is_running("Status:                               Ready\r\n", "")
        )

    def test_machine_missing_vm_does_not_exist(self):
        self.assertTrue(
            podman_machine_missing(
                "",
                "Error: podman-machine-default: VM does not exist\r\n",
            )
        )

    def test_machine_present_json(self):
        self.assertFalse(
            podman_machine_missing('[{"Name": "podman-machine-default"}]\r\n', "")
        )

    def test_windows_ready_wait_covers_hyperv_cold_start(self):
        # Observed: Hyper-V VM ready ~4 min after schtasks; old budget was ~3 min.
        self.assertGreaterEqual(
            PODMAN_READY_ATTEMPTS_WINDOWS * PODMAN_READY_SLEEP_SEC,
            600,
        )


if __name__ == "__main__":
    unittest.main()
