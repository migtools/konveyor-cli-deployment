import logging
import os

import config
from utils.images import remove_old_images, generate_images_list, pull_tag_images, pull_stage_ga_images, \
    generate_konflux_images_list, pull_images_by_list
from utils.utils import connect_ssh, read_file, get_target_dependency_path, ensure_podman_running, \
    pull_stage_ga_dependency_file, normalise_url, get_latest_upstream_dependency, download_file
from utils.zip import generate_zip, get_zip_folder_name, get_zip_name, unpack_zip, generate_konflux_zip


def run_remote_deployment(data):
    version = data["version"]
    build = data["build"]
    url = data["image"]
    image_output_file = data["args_image_output_file"]
    arg_dependency_file = data["args_dependency_file"]
    ip_address = data["args_ip_address"]
    host_os = data["args_os"]
    host_platform = data["args_platform"]
    full_zip_name = ""

    if data["args_upstream"]:
        upstream = True
    else:
        upstream = False

    try:
        client = connect_ssh(ip_address)
    except Exception as err:
        raise SystemExit("There was an issue connecting to remote host: {}".format(err))

    try:
        ensure_podman_running(client=client)
        if version and not upstream:
            version_tuple = tuple(map(int, version.split('.')))
            remove_old_images(version, client=client)
            if version_tuple < (8, 1, 0):
                if build == "stage" or build == "candidate" or build == "ga":
                    pull_stage_ga_images(version, build, client=client)
                    full_zip_name = pull_stage_ga_dependency_file(version, build, host_os, host_platform)
                else:
                    if not image_output_file:
                        logging.info(f"Generating images list for {version}-{build}")
                        image_list, stdout_err = generate_images_list(version, build)
                    else:
                        logging.info(f"Using images list provided as CLI argument: {image_output_file}")
                        image_list = read_file(image_output_file)
                    pull_tag_images(version, image_list, client)
                    if not arg_dependency_file:
                        logging.info(f"Generating dependencies zip for {version}-{build}")
                        generate_zip(version, build)
                        zip_folder_name = get_zip_folder_name(image_list)
                        zip_name = get_zip_name(zip_folder_name.split("-")[1], host_os, host_platform )
                        full_zip_name = os.path.join(config.MISC_DOWNSTREAM_PATH, zip_folder_name, zip_name)
                        logging.info(f"Using generated zip dependency file: {full_zip_name}")
                    else:
                        full_zip_name = arg_dependency_file
                        logging.info(f"Using existing dependencies zip: {full_zip_name}")
            else:
                logging.info(f"Deploying MTA Version: {version}, image: {url}")
                normalised_url = normalise_url(version, url)
                if not image_output_file:
                    logging.info(f"Generating images list for {version}, image: {url}")
                    image_list = generate_konflux_images_list(normalised_url)
                else:
                    logging.info(f"Using images list provided as CLI argument: {image_output_file}")
                    image_list = read_file(image_output_file)
                pull_images_by_list(version, image_list, client=client)
                if not arg_dependency_file:
                    logging.info(f"Generating dependencies zip for {version}, image: {url}")
                    zip_folder_name = generate_konflux_zip(normalised_url)
                    zip_name = get_zip_name(version, host_os, host_platform)
                    full_zip_name = os.path.join(config.MISC_DOWNSTREAM_PATH, zip_folder_name, zip_name)
                else:
                    full_zip_name = arg_dependency_file
                    logging.info(f"Using existing dependencies zip: {full_zip_name}")
        else:
            logging.info("Deploying Kantra latest")
            if not arg_dependency_file:
                full_zip_name = get_zip_name("upstream", host_os, host_platform)
                url = get_latest_upstream_dependency('konveyor', 'kantra', full_zip_name)
                logging.info("Downloading dependencies zip for upstream")
                download_file(url, full_zip_name)
                full_zip_name = os.path.abspath(full_zip_name)
            else:
                full_zip_name = arg_dependency_file

        unpack_zip(full_zip_name, get_target_dependency_path(client), client)
    finally:
        client.close()