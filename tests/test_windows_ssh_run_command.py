#!/usr/bin/env python3
"""Windows OpenSSH must not wrap remote commands in bash -lc; restore PATH for podman."""
import base64
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from utils.utils import _is_windows_ssh, _wrap_remote_command, _windows_remote_command  # noqa: E402


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
        self.assertTrue(_is_windows_ssh(client))

    def test_detect_linux_openssh(self):
        client = _FakeClient("SSH-2.0-OpenSSH_8.7")
        self.assertFalse(_is_windows_ssh(client))

    def test_wrap_linux_uses_bash(self):
        client = _FakeClient("SSH-2.0-OpenSSH_8.7")
        wrapped = _wrap_remote_command("podman images", client)
        self.assertTrue(wrapped.startswith("bash -lc "))
        self.assertIn("podman images", wrapped)

    def test_wrap_windows_no_bash_restores_path(self):
        client = _FakeClient("SSH-2.0-OpenSSH_for_Windows_8.1")
        wrapped = _wrap_remote_command("podman images", client)
        self.assertNotIn("bash -lc", wrapped)
        self.assertTrue(wrapped.startswith("powershell.exe -NoProfile -EncodedCommand "))
        encoded = wrapped.split("EncodedCommand ", 1)[1]
        script = base64.b64decode(encoded).decode("utf-16le")
        self.assertIn("GetEnvironmentVariable('Path','Machine')", script)
        self.assertIn("GetEnvironmentVariable('Path','User')", script)
        self.assertIn("RedHat\\Podman", script)
        self.assertIn("podman images", script)

    def test_windows_remote_command_preserves_payload(self):
        cmd = 'powershell -NoProfile -Command "Write-Output $env:TEMP"'
        wrapped = _windows_remote_command(cmd)
        script = base64.b64decode(wrapped.split("EncodedCommand ", 1)[1]).decode("utf-16le")
        self.assertIn(cmd, script)


if __name__ == "__main__":
    unittest.main()
