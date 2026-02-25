import logging
import os
import shutil
import subprocess

import yaml

import config
from utils.const import related_images, repositories, basic_images
from utils.utils import run_command, convert_to_json


def pull_tag_images(mta_version, output_file, client=None):
    """
    Pulls and tags images from the list it gets
    :param mta_version: MTA version to be deployed
    :param output_file: Output with list of images to be pulled. Can be generated and forwarded here or provided as CLI parameter
    :param client: SSH client, optional parameter. Will be used to connect to remote host and pull images there if present.
    """
    related_images = convert_to_json(output_file).get('related_images_pullspecs', None)
    required_version_tuple = (7, 3, 0)
    current_version_tuple = tuple(map(int, mta_version.split('.')))
    if related_images:  # If related images are present then proceed
        keywords = ['java', 'generic', 'dotnet', 'cli']
        for image in related_images:
            if any(keyword in image for keyword in keywords):  # Check if the image contains any of the keywords.
                logging.info(f"Image : {image}")
                # Pull image from registry-proxy.engineer.redhat.com
                proxy_image_url = 'brew.registry.redhat.io/rh-osbs/mta-{}'.format(image.split('/')[-1])
                pull_command = f'podman pull {proxy_image_url} --tls-verify=false'
                logging.info(f'Pulling image: {proxy_image_url}')
                run_command(pull_command, True, client)
                logging.info('Pull successful')
                tag_image = image.split('@sha')[-2]
                if 'dotnet' in tag_image and current_version_tuple < required_version_tuple :
                    tag_image = tag_image.replace("rhel9", "rhel8")
                logging.info(f'Tagging image {proxy_image_url} to {tag_image}:{mta_version}')
                tag_command = f'podman tag {proxy_image_url} {tag_image}:{mta_version}'  #Tag image to correct version
                run_command(tag_command, True, client)
                logging.info(f'Tagging {image} is completed...')


def pull_stage_ga_images(mta_version, repo, client=None):
    """
    Pulls images for Stage / GA
    :param mta_version: MTA version to be pulled
    :param repo: either ga or stage to be pulled
    :param client: SSH client for remote deployment
    :return:
    """
    required_version_tuple = (7, 3, 0)
    current_version_tuple = tuple(map(int, mta_version.split('.')))
    images = basic_images + related_images

    for image in images:
        if 'dotnet' in image and current_version_tuple < required_version_tuple:
            image = image.replace("rhel9", "rhel8")
        image_url = repositories.get(repo) + f'/mta/{image}:{mta_version}'
        logging.info(f"Processing repository: {repo} (url: {image_url})")
        # Pull the image
        pull_command = f"podman pull {image_url} --tls-verify=false"
        run_command(pull_command, client=client)
        logging.info(f"Pulled image from {repo}")
        # Tag the image based on the repository type
        tag_command = f"podman tag {image_url} {repositories.get('ga') + f'/mta/{image}:{mta_version}'}"
        if repo != 'ga' and repo != 'candidate':
            run_command(tag_command, client=client)
            logging.info(f"Tagged image {image} to ga")


def pull_images_by_list(mta_version, image_list, client=None):
    # Keywords to filter images
    keywords = ['java', 'generic', 'dotnet', 'cli']

    for image in image_list:
        # Check if the image name contains any of the required keywords
        if not any(key in image for key in keywords):
            logging.debug(f"Skipping image {image} as it does not match keywords")
            continue

        # 1. Pull the image
        pull_command = f"podman pull {image}"
        run_command(pull_command, client=client)
        logging.info(f"Successfully pulled image: {image}")

        # 2. Extract short name for tagging (optional but recommended)
        # Example: registry.stage.redhat.io/mta/mta-java-app@sha256:... -> mta-java-app
        image_short_name = image.split('/')[-1].split('@')[0]

        # 3. Tag the image based on the repository type (GA repository)
        ga_repo = repositories.get('ga')
        target_tag = f"{ga_repo}/mta/{image_short_name}:{mta_version}"

        tag_command = f"podman tag {image} {target_tag}"
        run_command(tag_command, client=client)
        logging.info(f"Tagged image {image_short_name} as {target_tag}")

def remove_old_images(version="upstream", client=None):
    """
    Removes old images before pulling new
    :param version: MTA version to be cleaned up
    :param client: SSH client, optional parameter to run cleanup remotely
    """
    try:
        result, result_err = run_command("podman images", client=client)
        # logging.info(f"List of images: {result}")

        # Filtering lines that contain "registry" and version
        images = []

        for line in result.splitlines():  # result is already a string
            columns = line.split()
            if "registry" in line and version in line:
                # Third column - IMAGE ID
                if len(columns) >= 3:
                    images.append(columns[2])

        # Deleting images gotten after filtering
        for image in images:
            run_command(f"podman rmi {image} --force", client=client)
            logging.info(f"Image {image} was removed successfully")
    except subprocess.CalledProcessError as e:
        logging.error(f"Error while performing command: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")


def generate_images_list(version, build):
    """
    Generates list of images and pulls them
    :param version: MTA version, for example 7.2.0
    :param build: build number
    :return: String containing list of images. Can be converted to JSON after that.
    """
    get_images_output_command = f'cd {config.MISC_DOWNSTREAM_PATH}; ./{config.GET_IMAGES_OUTPUT}{config.BUNDLE}{version}-{build}'
    return run_command(get_images_output_command)


def generate_konflux_images_list(url=None, file=None):
    container_name = "tmp-bundle"
    manifests_dir = "./manifests"
    file_path = os.path.join(manifests_dir, "konveyor-operator.clusterserviceversion.yaml")
    images_list = []
    created_container = False

    try:
        if url:
            # 1. Create the container (run_command raises on failure)
            get_images_command = f"podman create --name {container_name} {url} /bin/true"
            run_command(get_images_command)
            created_container = True

            # 2. Copy manifests from the container to the local filesystem
            run_command(f"podman cp {container_name}:/manifests ./")

        elif file:
            file_path = file

        # 3. Parse the CSV YAML file
        if not os.path.exists(file_path):
            print(f"Error: Target file not found at {file_path}")
            return []

        with open(file_path, 'r') as f:
            data = yaml.safe_load(f) or {}

        related_images = data.get('spec', {}).get('relatedImages', [])

        # 4. Extract and transform image URLs
        images_list = [
            item['image'].replace("registry.redhat.io", "registry.stage.redhat.io")
            for item in related_images if 'image' in item
        ]

    except yaml.YAMLError as ye:
        print(f"Error: Failed to parse YAML file. Details: {ye}")
    except Exception as e:
        print(f"Unexpected error occurred: {e}")
    finally:
        # 5. Cleanup: only remove container and manifests when we created them (url path)
        if created_container:
            run_command(f"podman rm -f {container_name}")
            if os.path.exists(manifests_dir):
                shutil.rmtree(manifests_dir, ignore_errors=True)
    print(images_list)
    return images_list
