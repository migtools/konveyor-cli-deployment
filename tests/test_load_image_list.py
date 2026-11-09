#!/usr/bin/env python3
"""load_image_list must accept CSV YAML and Konflux related-images.json."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from utils.images import find_cli_image, load_image_list  # noqa: E402


class LoadImageListTests(unittest.TestCase):
    def test_related_images_json_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "related-images.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(
                    '["registry.redhat.io/mta/mta-cli-rhel9@sha256:aaa",'
                    '"registry.redhat.io/mta/mta-java-external-provider-rhel9@sha256:bbb"]\n'
                )
            images = load_image_list(path)
        self.assertEqual(
            images,
            [
                "registry.stage.redhat.io/mta/mta-cli-rhel9@sha256:aaa",
                "registry.stage.redhat.io/mta/mta-java-external-provider-rhel9@sha256:bbb",
            ],
        )

    def test_csv_yaml_related_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "csv.yaml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(
                    "spec:\n"
                    "  relatedImages:\n"
                    "    - name: mta-cli\n"
                    "      image: registry.redhat.io/mta/mta-cli-rhel9@sha256:ccc\n"
                )
            images = load_image_list(path)
        self.assertEqual(images, ["registry.stage.redhat.io/mta/mta-cli-rhel9@sha256:ccc"])

    def test_find_cli_image(self):
        images = [
            "registry.stage.redhat.io/mta/mta-java-external-provider-rhel9@sha256:1",
            "registry.stage.redhat.io/mta/mta-cli-rhel9@sha256:2",
        ]
        self.assertEqual(find_cli_image(images), images[1])

    def test_find_cli_image_missing(self):
        with self.assertRaises(SystemExit):
            find_cli_image(["registry.stage.redhat.io/mta/mta-java-external-provider-rhel9@sha256:1"])


if __name__ == "__main__":
    unittest.main()
