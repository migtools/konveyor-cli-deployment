#!/usr/bin/env python3
"""prepare_remote_host must use Windows-compatible shell commands on Windows remotes."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from prepare_remote_host import assemble_env_file, prepare_testing_repo_commands  # noqa: E402


class PrepareRemoteHostWindowsTests(unittest.TestCase):
    def test_linux_commands_use_unix_shell(self):
        cmds = prepare_testing_repo_commands(
            "https://github.com/konveyor/kantra-cli-tests",
            "kantra-cli-tests",
            "linux",
        )
        self.assertEqual(cmds[0], "rm -rf kantra-cli-tests")
        self.assertIn("git clone", cmds[1])
        self.assertIn("pip3 install", cmds[2])
        self.assertIn("cd kantra-cli-tests;", cmds[2])

    def test_windows_commands_avoid_unix_rm_and_pip3(self):
        cmds = prepare_testing_repo_commands(
            "https://github.com/konveyor/kantra-cli-tests",
            "kantra-cli-tests",
            "windows",
        )
        self.assertNotIn("rm -rf", cmds[0])
        self.assertIn("rmdir", cmds[0].lower())
        self.assertIn("git clone", cmds[1])
        self.assertIn("python -m pip install", cmds[2])
        self.assertIn("cd /d kantra-cli-tests", cmds[2])
        self.assertNotIn("pip3", cmds[2])

    def test_assemble_env_windows_binary(self):
        env = assemble_env_file("C:/Users/Administrator", "kantra-cli-tests", "windows")
        self.assertEqual(
            env["KANTRA_CLI_PATH"],
            "C:/Users/Administrator/.kantra/windows-mta-cli.exe",
        )

    def test_prepare_testing_repo_runs_windows_commands(self):
        client = mock.MagicMock()
        client.get_transport.return_value.remote_version = "SSH-2.0-OpenSSH_for_Windows_8.1"
        with mock.patch("prepare_remote_host.run_command") as run_cmd, mock.patch(
            "prepare_remote_host.get_home_dir", return_value="C:/Users/Administrator"
        ), mock.patch("prepare_remote_host.write_env_file"):
            from prepare_remote_host import prepare_testing_repo

            prepare_testing_repo(
                "https://github.com/konveyor/kantra-cli-tests",
                host_os="windows",
                client=client,
            )
        executed = [c.args[0] for c in run_cmd.call_args_list]
        self.assertTrue(any("rmdir" in c.lower() for c in executed))
        self.assertFalse(any(c.startswith("rm -rf") for c in executed))
        self.assertTrue(any("python -m pip install" in c for c in executed))


if __name__ == "__main__":
    unittest.main()
