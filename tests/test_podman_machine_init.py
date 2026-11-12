#!/usr/bin/env python3
"""Windows Podman machine init must force Hyper-V provider."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from utils.utils import podman_machine_init_command  # noqa: E402


class _FakeTransport:
    def __init__(self, remote_version):
        self.remote_version = remote_version


class _FakeClient:
    def __init__(self, remote_version):
        self._transport = _FakeTransport(remote_version)

    def get_transport(self):
        return self._transport


class PodmanMachineInitTests(unittest.TestCase):
    def test_windows_ssh_uses_hyperv_provider(self):
        client = _FakeClient("SSH-2.0-OpenSSH_for_Windows_8.1")
        cmd = podman_machine_init_command(client=client)
        self.assertEqual(cmd, "podman machine init --provider hyperv")
        self.assertNotIn("--cpus", cmd)
        self.assertNotIn("--memory", cmd)
        self.assertNotIn("--disk-size", cmd)

    def test_linux_ssh_omits_hyperv_provider(self):
        client = _FakeClient("SSH-2.0-OpenSSH_8.7")
        cmd = podman_machine_init_command(client=client)
        self.assertEqual(cmd, "podman machine init")

    def test_local_windows_uses_hyperv(self):
        with mock.patch("utils.utils.platform.system", return_value="Windows"):
            cmd = podman_machine_init_command(client=None)
        self.assertEqual(cmd, "podman machine init --provider hyperv")


if __name__ == "__main__":
    unittest.main()
