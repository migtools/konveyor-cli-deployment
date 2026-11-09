import logging
import os
import tempfile

import config
from utils.fbc_cli_extract import extract_cli_zip
from utils.images import remove_old_images, generate_images_list, pull_tag_images, pull_stage_ga_images, \
    generate_konflux_images_list, pull_images_by_list, load_image_list, find_cli_image
from utils.utils import read_file, get_target_dependency_path, get_latest_upstream_dependency, download_file, \
    pull_stage_ga_dependency_file, ensure_podman_running, normalise_url
from utils.zip import generate_zip, get_zip_folder_name, get_zip_name, unpack_zip, generate_konflux_zip


def _deploy_from_fbc(version, image_output_file, arg_dependency_file, host_os, host_platform, target_path):
    """Local FBC-native path (parity with remote --build fbc)."""
    if not image_output_file:
        raise SystemExit("--build fbc requires --image_output_file (related-images.json from FBC)")
    logging.info(f"FBC deploy: loading related images from {image_output_file}")
    image_list = load_image_list(image_output_file)
    pull_images_by_list(version, image_list)

    if not target_path:
        target_path = get_target_dependency_path()

    if arg_dependency_file:
        logging.info(f"FBC deploy: using provided dependency zip {arg_dependency_file}")
        unpack_zip(arg_dependency_file, target_path)
        return

    cli_image = find_cli_image(image_list)
    logging.info(f"FBC deploy: extracting CLI zip from {cli_image}")
    with tempfile.TemporaryDirectory(prefix="mta-fbc-cli-") as out_dir:
        zip_path = extract_cli_zip(
            cli_image=cli_image,
            version=version,
            platform=host_os or "linux",
            arch=host_platform or "amd64",
            output_dir=out_dir,
            client=None,
        )
        unpack_zip(zip_path, target_path)


def run_local_deployment(data):
    version = data["version"]
    build = data["build"]
    image = data["image"]
    normalized_url = data["normalized_url"]
    target_path = data["install_path"]
    if data["args_upstream"]:
        upstream = True
    else:
        upstream = False
    image_output_file = data["args_image_output_file"]
    arg_dependency_file = data["args_dependency_file"]
    host_os = data.get("args_os")
    host_platform = data.get("args_platform")
    full_zip_name = ""
    ensure_podman_running()

    if build == "fbc":
        _deploy_from_fbc(
            version, image_output_file, arg_dependency_file, host_os, host_platform, target_path
        )
        return

    if version and not upstream:
        version_tuple = tuple(map(int, version.split('.')))
        remove_old_images(version)
        if version_tuple < (8, 1, 0):
            logging.info(f"Deploying MTA Version: {version} {build}")
            if build == "stage" or build == "candidate" or build == "ga":
                pull_stage_ga_images(version, build)
                full_zip_name = pull_stage_ga_dependency_file(version, build)
            else:
                if not image_output_file:
                    logging.info(f"Generating images list for {version}-{build}")
                    image_list, stdout_err = generate_images_list(version, build)
                else:
                    logging.info(f"Using images list provided as CLI argument: {image_output_file}")
                    image_list = read_file(image_output_file)
                pull_tag_images(version, image_list)
                if not arg_dependency_file:
                    logging.info(f"Generating dependencies zip for {version}-{build}")
                    generate_zip(version, build)
                    zip_folder_name = get_zip_folder_name(image_list)
                    zip_name = get_zip_name(zip_folder_name.split("-")[1])
                    full_zip_name = os.path.join(config.MISC_DOWNSTREAM_PATH, zip_folder_name, zip_name)
                    logging.info (f"Using generated zip dependency file: {full_zip_name}")
                else:
                    full_zip_name=arg_dependency_file
                    logging.info(f"Using existing dependencies zip: {full_zip_name}")
        else:
            if build == "ga":
                pull_stage_ga_images(version, build)
                full_zip_name = pull_stage_ga_dependency_file(version, build)
            else:
                logging.info(f"Deploying MTA Version: {version}, image: {image}")
                if not normalized_url or normalized_url == "":
                    normalized_url = normalise_url(version, image)
                if not image_output_file:
                    logging.info(f"Generating images list for {version}, image: {image}")
                    image_list = generate_konflux_images_list(url=normalized_url)
                else:
                    logging.info(f"Using images list provided as CLI argument: {image_output_file}")
                    image_list = generate_konflux_images_list(file=image_output_file)
                pull_images_by_list(version, image_list)
                if not arg_dependency_file:
                    logging.info(f"Generating dependencies zip for {version}, image: {image}")
                    zip_folder_name = generate_konflux_zip(normalized_url)
                    zip_name = get_zip_name(version)
                    full_zip_name = os.path.join(config.MISC_DOWNSTREAM_PATH, zip_folder_name, zip_name)
                else:
                    full_zip_name=arg_dependency_file
                    logging.info(f"Using existing dependencies zip: {full_zip_name}")

    else:
        print("Deploying Kantra latest")
        if not arg_dependency_file:
            full_zip_name = get_zip_name()
            image = get_latest_upstream_dependency('konveyor', 'kantra', full_zip_name)
            logging.info(f"Downloading dependencies zip for upstream")
            download_file(image, full_zip_name)
    if not target_path:
        target_path = get_target_dependency_path()
    unpack_zip(full_zip_name, target_path)
