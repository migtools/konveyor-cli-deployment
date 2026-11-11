import base64
import logging
import os
import random
import re
import shlex
import shutil
import string
import json
import sys
import time
import urllib

import paramiko
import requests
import platform

import config
from utils.const import zip_urls

# from utils.const import zip_urls

# Logging configuration
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers = [
        logging.StreamHandler(sys.stdout)  # Redirecting to stdout
    ]
)


import subprocess
import logging

def _is_windows_ssh(client):
    """True when the SSH peer is OpenSSH for Windows (no bash in PATH by default)."""
    if client is None:
        return False
    cached = getattr(client, "_mta_is_windows_ssh", None)
    if cached is not None:
        return cached
    transport = client.get_transport() if hasattr(client, "get_transport") else None
    ver = (transport.remote_version if transport else "") or ""
    is_win = "OpenSSH_for_Windows" in ver or "Windows" in ver
    try:
        client._mta_is_windows_ssh = is_win
    except Exception:
        pass
    return is_win


def _windows_remote_command(command):
    """
    Run a command on Windows OpenSSH with Machine+User PATH restored.

    Non-interactive OpenSSH sessions often get a stripped PATH, so tools installed
    for the interactive user (e.g. Podman under Program Files) are "not recognized".
    Avoid bash -lc (not present on stock OpenSSH_for_Windows).
    """
    # PowerShell single-quoted here-string keeps the payload literal (no escaping hell).
    script = (
        "$mp = [Environment]::GetEnvironmentVariable('Path','Machine'); "
        "$up = [Environment]::GetEnvironmentVariable('Path','User'); "
        "$env:Path = \"$mp;$up\"; "
        # Common Podman install dirs as a last-resort prepend.
        "$env:Path = \"C:\\Program Files\\RedHat\\Podman;C:\\Program Files\\Podman;$env:Path\"; "
        f"cmd.exe /c @'\n{command}\n'@\n"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return f"powershell.exe -NoProfile -EncodedCommand {encoded}"


def _wrap_remote_command(command, client):
    """
    Linux/macOS remotes: bash -lc for reliable quoting and shell features.
    Windows OpenSSH: restore Machine+User PATH via PowerShell (no bash).
    """
    if _is_windows_ssh(client):
        return _windows_remote_command(command)
    return f"bash -lc {shlex.quote(command)}"


def run_command(command, fail_on_failure=True, client=None):
    logging.info(f"Executing command: {command}")
    try:
        if client:
            remote_cmd = _wrap_remote_command(command, client)
            _stdin, stdout, _stderr = client.exec_command(remote_cmd)

            out = stdout.read().decode()
            err = _stderr.read().decode()
            exit_status = stdout.channel.recv_exit_status()

            # logging.info(f"[REMOTE] exit_code={exit_status}")
            if exit_status != 0 and fail_on_failure:
                raise SystemExit(
                    f"Remote command failed with exit code {exit_status}\nSTDOUT:\n{out}\nSTDERR:\n{err}"
                )

            return out, err
        else:
            result = subprocess.run(
                command,
                shell=True,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
            )
            if result.returncode != 0 and fail_on_failure:
                raise SystemExit(
                    f"Local command failed with exit code {result.returncode}\n"
                    f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                )
            return result.stdout, result.stderr
    except SystemExit:
        raise
    except Exception as err:
        raise SystemExit(f"There was an issue running a command: {err}")



def read_file(output_file):
    """
    Opens a file for reading
    :param output_file:
    :return: opened file's content
    """
    try:
        with open(output_file, 'r') as file:
            logging.info(f"File opened successfully: {output_file}")
            return file.read()
    except Exception as err:
        raise SystemExit(f"There was an error opening file: {err}")

def convert_to_json(file):
    """
    Converts incoming string to JSON format
    :param file: String to be converted
    :return: JSON
    """
    # print(f"Json got: {file}")
    try:
        match = re.search(r'\{.*\}', file, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in input.")

        json_str = match.group(0)
        parsed = json.loads(json_str)
        logging.info("String was converted to JSON successfully!")
        return parsed

    except Exception as err:
        raise SystemExit(f"There was an error converting string to JSON format: {err}")


def resolve_ssh_user(host_os=None):
    """SSH username for the remote host.

    Windows OpenSSH AMIs use ``administrator``; config ``ssh_user`` is ignored.
    Linux/Darwin (and unset OS) use ``config.SSH_USER``.
    """
    if host_os and str(host_os).strip().lower() == "windows":
        return "administrator"
    return config.SSH_USER


def connect_ssh(ip_address, host_os=None):
    SSH_HOST = ip_address
    SSH_USER = resolve_ssh_user(host_os)
    SSH_KEY = config.SSH_KEY
    client = paramiko.SSHClient()
    try:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(SSH_HOST, username=SSH_USER, key_filename=SSH_KEY)
        logging.info(f"Connected to host {ip_address} as {SSH_USER}")
        return client
    except Exception as err:
        client.close()
        raise SystemExit("There was an issue connecting to host by ssh: {}".format(err))


def get_target_dependency_path(client=None):
    """
    Gets home folder path of the user script is running from
    :param: client: SSH client for getting home dir from remote host
    :return: String contains folder name
    """
    home_dir = get_home_dir(client=client) if client else os.path.expanduser("~")
    # Prefer forward slashes for remote paths (OpenSSH/Windows + Linux).
    return f"{home_dir.rstrip('/').rstrip(chr(92))}/.kantra"


def clear_folder (path):
    """
    Clears folder by removing it with all content and creating it again
    :param path: Path of the folder to be cleared
    """
    if os.path.exists(path):
        try:
            shutil.rmtree(path)
            logging.info(f"Folder was removed successfully: {path}")
        except Exception as err:
            logging.error(f"Error {err} when trying to delete folder: {path}")

    try:
        os.makedirs(path, exist_ok=True)
        logging.info(f"Folder was created successfully: {path}")
    except Exception as err:
        logging.error(f"Couldn't create a folder: {path}")
        raise SystemExit ("There was an issue creating a folder: {}".format(err))


def create_random_folder(base_path):
    """
    Creates a random folder with a name of 8 characters inside the specified path.

    :param base_path: Path where the folder will be created
    :return: Full path to the created folder
    """
    # Ensure the base path exists
    os.makedirs(base_path, exist_ok=True)

    # Generate a random folder name with 8 characters
    folder_name = ''.join(random.choices(string.ascii_letters, k=8))
    full_path = os.path.join(base_path, folder_name)

    # Create the folder
    os.makedirs(full_path)

    return full_path


def get_latest_upstream_dependency(user, repo, asset_name):
    """
    Return the download URL for asset_name from the newest GitHub release that publishes it.

    Releases are walked newest-first. Drafts and releases that do not contain the asset
    are skipped. The prerelease flag is ignored: konveyor/kantra stopped marking releases
    as prereleases after v0.9.0-alpha.5, so filtering on that flag pinned installs to it.
    """
    url = f"https://api.github.com/repos/{user}/{repo}/releases"
    page = 1
    per_page = 100

    while True:
        response = requests.get(url, params={"per_page": per_page, "page": page}, timeout=60)
        if response.status_code != 200:
            logging.error(f"Error fetching releases: {response.status_code}")
            return None

        releases = response.json()
        if not releases:
            break

        for release in releases:
            if release.get("draft"):
                continue
            for asset in release.get("assets") or []:
                if asset.get("name") == asset_name:
                    tag = release.get("tag_name")
                    logging.info(f"Selected upstream release {tag} for asset {asset_name}")
                    return asset.get("browser_download_url")

        if len(releases) < per_page:
            break
        page += 1

    logging.error(f"No release in {user}/{repo} contains asset {asset_name}")
    return None


def pull_stage_ga_dependency_file(mta_version, repo, os_name=None, machine=None):
    if not os_name and not machine:
        os_name, machine = get_os_platform()
    dependency_file_name = f'mta-{mta_version}-cli-{os_name}-{machine}.zip'
    base_url = zip_urls.get(repo)
    if not base_url:
        raise SystemExit(f"Unknown stage/GA repo '{repo}' (expected one of: {', '.join(sorted(zip_urls))})")
    dependency_file_url = base_url.format(ver=mta_version) + dependency_file_name
    logging.info(f"Downloading dependency file from URL: {dependency_file_url}")
    download_file(dependency_file_url, dependency_file_name)
    return os.path.abspath(dependency_file_name)


def download_file(url, local_filename):
    response = requests.get(url, stream=True, verify=False)
    if response.status_code != 200:
        raise SystemExit(
            f"Failed to download {url} (HTTP {response.status_code}). "
            f"Stage/GA CLI zip must exist for this version before --build stage/ga E2E can run."
        )
    with open(local_filename, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    if not os.path.isfile(local_filename) or os.path.getsize(local_filename) == 0:
        raise SystemExit(f"Download of {url} produced an empty or missing file: {local_filename}")
    logging.info(f"File saved as {local_filename} ({os.path.getsize(local_filename)} bytes)")


def get_os_platform ():
    os_name = platform.system().lower()
    machine = platform.machine().lower()

    if "aarch64" in machine or "arm64" in machine:
        machine = "arm64"
    elif "x86_64" in machine or "amd64" in machine:
        machine = "amd64"
    else:
        machine = "unknown"
    return os_name, machine


def get_repo_folder_name(repo_url: str) -> str:
    """
    Extracts the folder name from a git repository URL, e.g.:
    https://github.com/konveyor/kantra-cli-tests → kantra-cli-tests
    """
    # Removing slash at the enf of string
    repo_url = repo_url.rstrip('/')
    # Parsing URL
    parsed = urllib.parse.urlparse(repo_url)
    # Delimiting segments
    path = parsed.path  # например: '/konveyor/kantra-cli-tests'
    # Getting last segment (actually path)
    folder = os.path.basename(path)
    return folder


def get_home_dir(client=None):
    if client and _is_windows_ssh(client):
        # cmd.exe expansion; avoid bash $HOME which prints literally on Windows OpenSSH.
        out, _ = run_command("echo %USERPROFILE%", client=client)
        home = out.strip().splitlines()[-1].strip() if out.strip() else ""
        if not home or home.upper() == "%USERPROFILE%":
            out, _ = run_command(
                "powershell -NoProfile -Command \"Write-Output $env:USERPROFILE\"",
                client=client,
            )
            home = out.strip().splitlines()[-1].strip()
        return home.replace("\\", "/")
    return run_command("echo $HOME", client=client)[0].strip()


def write_env_file(env_path, env_dict, client=None):
    """
    Write or update .env file on a local or remote host.

    :param env_path: Path to the .env file
    :param env_dict: Dictionary of environment variables {KEY: VALUE}
    :param client: Optional paramiko.SSHClient for remote host
    """
    logging.info(f"Writing .env file at {env_path}")

    # Prepare the file content
    lines = [f"{key}={value}" for key, value in env_dict.items()]
    content = "\n".join(lines) + "\n"

    if client:
        # Remote write
        sftp = client.open_sftp()
        try:
            # Ensure directory exists (optional)
            dir_path = "/".join(env_path.split("/")[:-1])
            try:
                sftp.stat(dir_path)
            except FileNotFoundError:
                if _is_windows_ssh(client):
                    run_command(
                        f"powershell -NoProfile -Command "
                        f"\"New-Item -ItemType Directory -Force -Path '{dir_path}' | Out-Null\"",
                        client=client,
                        fail_on_failure=False,
                    )
                else:
                    run_command(f"mkdir -p {dir_path}", client=client, fail_on_failure=False)

            # Write file
            with sftp.file(env_path, "w") as f:
                f.write(content)
            logging.info(f"✅ Remote .env file written to {env_path}")
        finally:
            sftp.close()
    else:
        # Local write
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)
        logging.info(f"✅ Local .env file written to {env_path}")

def _podman_ready(out, err):
    text = f"{out or ''}{err or ''}"
    return not (
        err
        or "Error:" in text
        or "Cannot connect" in text
        or "Error:" in (out or "")
    )


def ensure_podman_running(client=None):
    """
    Ensures that Podman is running (either locally or remotely).
    Inits the default machine if missing, then starts it and waits.
    On Windows EC2 this requires NestedVirtualization (WSL2/Hyper-V).
    """
    print("Checking Podman status...")

    out, err = run_command("podman images", fail_on_failure=False, client=client)
    if _podman_ready(out, err):
        print("Podman is already running.")
        return

    print("Podman is not ready. Ensuring default machine exists, then starting it...")
    # Avoid bash-only `||` / redirects — Windows OpenSSH has no bash by default.
    inspect_out, inspect_err = run_command(
        "podman machine inspect podman-machine-default",
        fail_on_failure=False,
        client=client,
    )
    inspect_text = f"{inspect_out or ''}{inspect_err or ''}"
    if "Error" in inspect_text or "no such machine" in inspect_text.lower() or not inspect_out.strip():
        run_command(
            "podman machine init --cpus 2 --memory 4096 --disk-size 60",
            fail_on_failure=False,
            client=client,
        )
    start_out, start_err = run_command(
        "podman machine start",
        fail_on_failure=False,
        client=client,
    )
    print(f"podman machine start stdout:\n{start_out}")
    print(f"podman machine start stderr:\n{start_err}")
    if start_err and "not recognized" in start_err.lower():
        where_out, where_err = run_command("where podman", fail_on_failure=False, client=client)
        raise SystemExit(
            "podman is not on PATH for this Windows OpenSSH session "
            "(even after restoring Machine+User PATH). "
            f"where podman => out={where_out!r} err={where_err!r}\n"
            f"machine start stderr:\n{start_err}"
        )

    # WSL2/Hyper-V boot can take well over a few seconds on a fresh VM.
    for attempt in range(1, 31):
        time.sleep(6)
        out2, err2 = run_command("podman images", fail_on_failure=False, client=client)
        if _podman_ready(out2, err2):
            print(f"Podman machine started successfully (attempt {attempt}).")
            return
        print(f"Waiting for Podman (attempt {attempt}/30)...")

    print("❌ Failed to start Podman machine.")
    print(
        "On Windows EC2, Podman needs WSL2/Hyper-V and NestedVirtualization "
        "(use m7i/c7i+ with --cpu-options NestedVirtualization=enabled; "
        "c4/t3 will not work)."
    )
    raise SystemExit(1)

def normalise_url(version, url):
    if not url:
        raise ValueError("--image argument cannot be empty since MTA 8.1.0+")
    docker_config = os.path.expanduser("~/.docker/config.json")
    if platform.system() == "Windows":
        docker_config = os.path.normpath(docker_config).replace("\\", "/")
    inner_cmd = (
        'opm alpha list bundles "$OPM_URL" | grep -F "$OPM_VERSION" | '
        "grep -oE 'registry\.[^[:space:]]+' | sed 's/registry.redhat.io/registry.stage.redhat.io/'"
    )
    cmd = [
        "podman", "run", "--rm",
        "-e", f"OPM_URL={url}",
        "-e", f"OPM_VERSION={version}",
        "--entrypoint", "/bin/sh",
        "quay.io/migqe/migqe-base:latest",
        "-c", inner_cmd,
    ]
    print (cmd)
    # Mount registry auth only if present; skip mount to avoid "no such file" and
    # to allow public registries to work without any login config.
    if os.path.isfile(docker_config):
        volume_suffix = ":Z" if platform.system() == "Linux" else ""
        volume = f"{docker_config}:/root/.docker/config.json{volume_suffix}"
        cmd[3:3] = ["-v", volume, "-e", "HOME=/root"]
    logging.info(f"Executing command: opm (in container) for url={url!r}, version={version}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"opm container command failed with exit code {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout.strip()
