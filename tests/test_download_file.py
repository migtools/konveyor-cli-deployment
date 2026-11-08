#!/usr/bin/env python3
"""download_file / pull_stage_ga_dependency_file must fail loud on HTTP errors."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from utils.utils import download_file, pull_stage_ga_dependency_file  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self._content = content

    def iter_content(self, chunk_size=8192):
        if self._content:
            yield self._content


class DownloadFileTests(unittest.TestCase):
    def test_download_file_raises_on_http_error(self):
        with mock.patch("utils.utils.requests.get", return_value=_FakeResponse(404)):
            with self.assertRaises(SystemExit) as ctx:
                download_file("http://example.test/missing.zip", "missing.zip")
        self.assertIn("HTTP 404", str(ctx.exception))
        self.assertIn("missing.zip", str(ctx.exception))

    def test_download_file_writes_body_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ok.zip")
            with mock.patch(
                "utils.utils.requests.get",
                return_value=_FakeResponse(200, b"zip-bytes"),
            ):
                download_file("http://example.test/ok.zip", path)
            self.assertTrue(os.path.isfile(path))
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), b"zip-bytes")

    def test_pull_stage_ga_returns_abspath(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with mock.patch(
                    "utils.utils.requests.get",
                    return_value=_FakeResponse(200, b"zip-bytes"),
                ):
                    path = pull_stage_ga_dependency_file("8.3.3", "stage", "linux", "amd64")
                self.assertTrue(os.path.isabs(path))
                self.assertTrue(path.endswith("mta-8.3.3-cli-linux-amd64.zip"))
                self.assertTrue(os.path.isfile(path))
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
