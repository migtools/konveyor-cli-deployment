#!/usr/bin/env python3
"""Windows remotes must SSH as administrator regardless of config ssh_user."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from utils.utils import resolve_ssh_user  # noqa: E402


class ResolveSshUserTests(unittest.TestCase):
    def setUp(self):
        config.SSH_USER = "ec2-user"

    def test_windows_forces_administrator(self):
        self.assertEqual(resolve_ssh_user("windows"), "administrator")
        self.assertEqual(resolve_ssh_user("Windows"), "administrator")
        self.assertEqual(resolve_ssh_user("WINDOWS"), "administrator")

    def test_linux_uses_config(self):
        self.assertEqual(resolve_ssh_user("linux"), "ec2-user")
        self.assertEqual(resolve_ssh_user(None), "ec2-user")
        self.assertEqual(resolve_ssh_user(""), "ec2-user")

    def test_darwin_uses_config(self):
        self.assertEqual(resolve_ssh_user("darwin"), "ec2-user")

    def test_connect_ssh_passes_resolved_user(self):
        from utils import utils as utils_mod

        fake_client = mock.MagicMock()
        with mock.patch.object(utils_mod.paramiko, "SSHClient", return_value=fake_client):
            with mock.patch.object(config, "SSH_KEY", "/tmp/fake.pem"):
                with mock.patch.object(config, "SSH_USER", "ec2-user"):
                    client = utils_mod.connect_ssh("1.2.3.4", host_os="windows")
        self.assertIs(client, fake_client)
        fake_client.connect.assert_called_once()
        kwargs = fake_client.connect.call_args.kwargs
        self.assertEqual(kwargs["username"], "administrator")
        self.assertEqual(kwargs["key_filename"], "/tmp/fake.pem")


if __name__ == "__main__":
    unittest.main()
