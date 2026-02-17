import logging
import os
import re
import zipfile

import config
from utils.utils import convert_to_json, clear_folder, run_command, get_os_platform


def get_zip_folder_name(image_list):
    """
    Gets folder name where dependency zip should be located. Name depends on version.
    :param image_list: List of images to be parsed
    :return: String containing folder name
    """
    if isinstance(image_list, str):
        image_list = convert_to_json(image_list)

    for item in image_list["related_images"]:
        for key, value in item.items():
            if "mta-cli-rhel9" in key:
                _, major, minor = value["nvr"].rsplit("-", 2)
                return f"MTA-{major}-{minor}"
    return None


def get_zip_name(version="upstream", os_name=None, machine=None):
    """
    Gets ZIP filename according to OS and CPU type
    :param os_name: Name of the OS: Linux, Windows or Darwin
    :param machine: amd64 or arm64
    :param version: MTA version, for example 7.2.0 or 7.1.1
    :return: String containing file name
    """
    if not os_name and not machine:
        os_name, machine = get_os_platform()

    if version != "upstream":
        zip_name = f"mta-{version}-cli-{os_name}-{machine}.zip"
        logging.info(f"Expecting {zip_name} to be available...")
    else:
        zip_name = f"kantra.{os_name}.{machine}.zip"
        logging.info(f"Expecting {zip_name} to be available...")

    return zip_name


def unpack_zip(zip_file, target_path, client=None):
    """
    Unpacks a ZIP file into the specified target directory.
    :param zip_file: Path to the ZIP file to be unpacked.
    :param target_path: Directory where the contents of the ZIP file will be extracted.
    :param client: Paramiko SSH client (optional)
    """
    if not client:
        clear_folder(target_path)

        with zipfile.ZipFile(zip_file, "r") as zip_ref:
            try:
                zip_ref.extractall(target_path)
                logging.info(f"Zip {zip_file} unpacked successfully to {target_path}")
            except Exception as err:
                raise SystemExit("There was an issue with unpacking zip file: {}".format(err))
    else:
        try:
            remote_home_dir = run_command("pwd", client=client)[0].strip()
            remote_zip = os.path.join(remote_home_dir, os.path.basename(zip_file))
            logging.info(f"Local zip path: {zip_file}")
            logging.info(f"Remote zip path: {remote_zip}")
            sftp = client.open_sftp()
            sftp.put(zip_file, remote_zip)

            # Cleanup folder on remote host
            logging.info(f"Clearing target path: {target_path}")
            # run_command_ssh(client, f"rm -rf {target_path}/*")
            run_command( f"rm -rf {target_path}/*", client=client)[0]

            # Unpacking zip on remote host
            logging.info(f"Unpacking {remote_zip} to {target_path} on remote host")
            run_command(f"unzip -o {remote_zip} -d {target_path}", client=client)

            logging.info(f"Zip {zip_file} unpacked successfully to {target_path} on remote host")

            # Cleaning up archive
            run_command(f"rm -f {remote_zip}", client)

        except Exception as err:
            logging.error("Remote unpack failed:")
            raise SystemExit("{}".format(err))


def generate_zip(version, build):
    """Generates zip with dependencies for local run"""
    extract_binary_command = f"{config.MISC_DOWNSTREAM_PATH}{config.EXTRACT_BINARY} {config.BUNDLE}{version}-{build} {config.NO_BREW}"
    run_command(extract_binary_command)


def generate_konflux_zip(image_url):
    """Generates zip with dependencies for local run and returns the output path"""
    # Use os.path.join for safety
    binary_path = os.path.join(config.MISC_DOWNSTREAM_PATH, config.EXTRACT_BINARY_KONFLUX)
    extract_binary_command = f"{binary_path} {image_url}"

    stdout, stderr = run_command(extract_binary_command)

    # Check for success marker in stdout
    if "success" in stdout.lower():
        match = re.search(r"Success! Output in:\s*(.*)", stdout)
        if match:
            # .group(1) extracts the actual path string, .strip() removes \n
            output_path = match.group(1).strip()
            logging.info(f"Binary extraction successful. Path: {output_path}")
            return output_path
        else:
            logging.error("Success marker found, but failed to parse output path.")

    # Log stderr if it exists, even if we don't return None immediately
    if stderr:
        logging.warning(f"Extraction command generated stderr: {stderr}")

    return None