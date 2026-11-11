import logging
import os

import config
from utils.fbc_cli_extract import extract_cli_zip
from utils.images import remove_old_images, generate_images_list, pull_tag_images, pull_stage_ga_images, \
    generate_konflux_images_list, pull_images_by_list, load_image_list, find_cli_image
from utils.utils import connect_ssh, read_file, get_target_dependency_path, ensure_podman_running, \
    pull_stage_ga_dependency_file, normalise_url, get_latest_upstream_dependency, download_file, \
    run_command
from utils.zip import generate_zip, get_zip_folder_name, get_zip_name, unpack_zip, unpack_remote_zip, \
    generate_konflux_zip


def _deploy_from_fbc(version, image_output_file, arg_dependency_file, host_os, host_platform,
                     target_path, client):
    """Pipeline FBC-native path: related-images + zip from CLI image (no stage URL / misc-downstream)."""
    if not image_output_file:
        raise SystemExit("--build fbc requires --image_output_file (related-images.json from FBC)")
    logging.info(f"FBC deploy: loading related images from {image_output_file}")
    image_list = load_image_list(image_output_file)
    pull_images_by_list(version, image_list, client=client)

    if not target_path:
        target_path = get_target_dependency_path(client)

    if arg_dependency_file:
        logging.info(f"FBC deploy: using provided dependency zip {arg_dependency_file}")
        unpack_zip(arg_dependency_file, target_path, client)
        return

    cli_image = find_cli_image(image_list)
    logging.info(f"FBC deploy: extracting CLI zip from {cli_image} for {host_os}/{host_platform}")
    from utils.utils import _is_windows_ssh, get_home_dir

    if _is_windows_ssh(client):
        # %TEMP% via PowerShell; forward slashes for podman/OpenSSH friendliness.
        temp_out, _ = run_command(
            "powershell -NoProfile -Command \"Write-Output $env:TEMP\"",
            client=client,
        )
        temp_root = temp_out.strip().splitlines()[-1].strip().replace("\\", "/")
        if not temp_root:
            temp_root = f"{get_home_dir(client=client)}/AppData/Local/Temp"
        out_dir = f"{temp_root}/mta-fbc-cli-{host_os}-{host_platform or 'amd64'}"
        run_command(
            f"powershell -NoProfile -Command "
            f"\"Remove-Item -LiteralPath '{out_dir}' -Recurse -Force -ErrorAction SilentlyContinue; "
            f"New-Item -ItemType Directory -Force -Path '{out_dir}' | Out-Null\"",
            client=client,
        )
    else:
        out_dir = f"/tmp/mta-fbc-cli-{host_os}-{host_platform or 'amd64'}"
        run_command(f"rm -rf {out_dir} && mkdir -p {out_dir}", client=client)
    remote_zip = extract_cli_zip(
        cli_image=cli_image,
        version=version,
        platform=host_os,
        arch=host_platform or "amd64",
        output_dir=out_dir,
        client=client,
    )
    unpack_remote_zip(remote_zip, target_path, client)


def run_remote_deployment(data):
    version = data["version"]
    build = data["build"]
    image = data["image"]
    normalized_url = data["normalized_url"]
    image_output_file = data["args_image_output_file"]
    arg_dependency_file = data["args_dependency_file"]
    ip_address = data["args_ip_address"]
    host_os = data["args_os"]
    host_platform = data["args_platform"]
    target_path = data.get("install_path")

    if data["args_upstream"]:
        upstream = True
    else:
        upstream = False

    try:
        client = connect_ssh(ip_address, host_os=host_os)
    except Exception as err:
        raise SystemExit("There was an issue connecting to remote host: {}".format(err))

    try:
        ensure_podman_running(client=client)
        if build == "fbc":
            _deploy_from_fbc(
                version, image_output_file, arg_dependency_file, host_os, host_platform,
                target_path, client,
            )
            return

        if version and not upstream:
            version_tuple = tuple(map(int, version.split('.')))
            remove_old_images(version, client=client)
            if version_tuple < (8, 1, 0):
                if build == "stage" or build == "candidate" or build == "ga":
                    # pull_stage_ga_images(version, build, client=client)
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
                if build == "stage" or build == "candidate" or build == "ga":
                    pull_stage_ga_images(version, build, client=client)
                    full_zip_name = pull_stage_ga_dependency_file(version, build, host_os, host_platform)
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
                    pull_images_by_list(version, image_list, client=client)
                    if not arg_dependency_file:
                        logging.info(f"Generating dependencies zip for {version}, image: {image}")
                        zip_folder_name = generate_konflux_zip(normalized_url)
                        zip_name = get_zip_name(version, host_os, host_platform)
                        full_zip_name = os.path.join(config.MISC_DOWNSTREAM_PATH, zip_folder_name, zip_name)
                    else:
                        full_zip_name = arg_dependency_file
                        logging.info(f"Using existing dependencies zip: {full_zip_name}")
        else:
            logging.info("Deploying Kantra latest")
            if not arg_dependency_file:
                full_zip_name = get_zip_name("upstream", host_os, host_platform)
                image = get_latest_upstream_dependency('konveyor', 'kantra', full_zip_name)
                logging.info("Downloading dependencies zip for upstream")
                download_file(image, full_zip_name)
                full_zip_name = os.path.abspath(full_zip_name)
            else:
                full_zip_name = arg_dependency_file

        if not target_path:
            target_path = get_target_dependency_path(client)
        unpack_zip(full_zip_name, target_path, client)
    finally:
        client.close()
