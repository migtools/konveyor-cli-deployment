#!/usr/bin/env python3
"""Windows OpenSSH must not wrap remote commands in bash -lc."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from utils.utils import _is_windows_ssh, _wrap_remote_command  # noqa: E402


class _FakeTransport:
    def __init__(self, remote_version):
        self.remote_version = remote_version


class _FakeClient:
    def __init__(self, remote_version):
        self._transport = _FakeTransport(remote_version)

    def get_transport(self):
        return self._transport


class WindowsSshRunCommandTests(unittest.TestCase):
    def test_detect_windows_openssh(self):
        client = _FakeClient("SSH-2.0-OpenSSH_for_Windows_8.1")
        self.assertTrue(_is_windows_ssh(client))
        # cached
        self.assertTrue(_is_windows_ssh(client))

    def test_detect_linux_openssh(self):
        client = _FakeClient("SSH-2.0-OpenSSH_8.7")
        self.assertFalse(_is_windows_ssh(client))

    def test_wrap_linux_uses_bash(self):
        client = _FakeClient("SSH-2.0-OpenSSH_8.7")
        wrapped = _wrap_remote_command("podman images", client)
        self.assertTrue(wrapped.startswith("bash -lc "))
        self.assertIn("podman images", wrapped)

    def test_wrap_windows_no_bash(self):
        client = _FakeClient("SSH-2.0-OpenSSH_for_Windows_8.1")
        wrapped = _wrap_remote_command("podman images", client)
        self.assertEqual(wrapped, "podman images")
        self.assertNotIn("bash", wrapped)


if __name__ == "__main__":
    unittest.main()
