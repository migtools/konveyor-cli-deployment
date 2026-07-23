"""
This file defines repositories, related images, basic images, and zip file URLs
for different repository types in the Red Hat Migration Toolkit for Applications (MTA).

Attributes:
    repositories (dict): Maps repository types (e.g., "ga", "stage") to their respective registry URLs.
    related_images (list): Related MTA provider images for versions before 8.2.0 (includes generic).
    related_images_8_2 (list): Related MTA provider images for 8.2.0+ (python/go/nodejs instead of generic).
    basic_images (list): A list of fundamental MTA images required for operation.
    zip_urls (dict): URLs for downloading MTA zip files, formatted per repository type.
"""

repositories = {
    "ga": "registry.redhat.io",
    "candidate": "registry.redhat.io",
    "stage": "registry.stage.redhat.io"
    # Add more repositories as needed
}

# Pre-8.2 uses a single generic provider for non-Java languages.
related_images = ["mta-java-external-provider-rhel9", "mta-generic-external-provider-rhel9",
                  "mta-dotnet-external-provider-rhel9"]
# 8.2.0+ ships language-specific providers instead of generic.
related_images_8_2 = ["mta-java-external-provider-rhel9", "mta-python-external-provider-rhel9",
                      "mta-go-external-provider-rhel9", "mta-nodejs-external-provider-rhel9",
                      "mta-dotnet-external-provider-rhel9"]
basic_images = ['mta-cli-rhel9']

# Define the URLs for the zip files based on repository types
zip_urls = {
    "stage": "http://download.devel.redhat.com/rcm-guest/staging/jboss-migrationtoolkit/MTA-{ver}.GA/",
    "candidate": "http://download.eng.brq.redhat.com/devel/candidates/middleware/migrationtoolkit/MTA-{ver}.GA/",
    "ga": "https://download.devel.redhat.com/released/middleware/mta/{ver}/"
}
