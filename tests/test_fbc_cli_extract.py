#!/usr/bin/env python3
"""FBC CLI extract helpers: platform binary mapping and zip naming."""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from utils.fbc_cli_extract import (  # noqa: E402
    BINARY_PATHS,
    CLI_DEPENDENCIES,
    cli_zip_name,
    platform_binary_path,
    provider_paths,
)


class FbcCliExtractTests(unittest.TestCase):
    def test_platform_binary_paths(self):
        self.assertEqual(platform_binary_path("linux"), "/usr/local/bin/mta-cli")
        self.assertEqual(platform_binary_path("windows"), "/usr/local/bin/windows-mta-cli.exe")
        self.assertEqual(platform_binary_path("darwin"), "/usr/local/bin/darwin-mta-cli")

    def test_unknown_platform(self):
        with self.assertRaises(SystemExit):
            platform_binary_path("solaris")

    def test_cli_zip_name(self):
        self.assertEqual(cli_zip_name("8.3.4", "linux", "amd64"), "mta-8.3.4-cli-linux-amd64.zip")
        self.assertEqual(cli_zip_name("8.3.4", "windows", "amd64"), "mta-8.3.4-cli-windows-amd64.zip")

    def test_provider_paths(self):
        self.assertEqual(
            provider_paths("linux"),
            ("/usr/local/bin/java-external-provider", "java-external-provider"),
        )
        self.assertEqual(
            provider_paths("windows"),
            ("/usr/local/bin/windows-java-external-provider", "java-external-provider.exe"),
        )

    def test_binary_paths_cover_all_platforms(self):
        self.assertEqual(set(BINARY_PATHS), {"linux", "windows", "darwin"})

    def test_dependencies_non_empty(self):
        self.assertTrue(any("/jdtls" == d or d.endswith("jdtls") or d == "/jdtls" for d in CLI_DEPENDENCIES))


if __name__ == "__main__":
    unittest.main()
