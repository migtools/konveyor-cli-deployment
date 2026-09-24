#!/usr/bin/python
import argparse
import json
import os

from config import set_config
from utils.utils import (
    connect_ssh,
    run_command,
    get_repo_folder_name,
    get_home_dir,
    write_env_file,
    normalize_host_os,
    is_windows_client,
    remote_join,
    remote_remove_path,
    ps_quote,
)

CONFIG_FILE = "config.json"

def load_config():
    """Loads config from JSON-file."""
    with open(CONFIG_FILE, "r") as f:
        configuration = json.load(f)
    set_config(configuration)


def prepare_host(data):
    ip_address = data["args_ip_address"]
    host_os = data["args_os"]

    try:
        client = connect_ssh(ip_address, host_os=host_os)
    except Exception as err:
        raise SystemExit("There was an issue connecting to remote host: {}".format(err))

    prepare_testing_repo("https://github.com/konveyor/kantra-cli-tests", host_os, client=client)


def prepare_testing_repo(repo="", host_os="", client=None):
    repo_folder_name = get_repo_folder_name(repo)
    if is_windows_client(client):
        remote_remove_path(repo_folder_name, client)
        run_command(f"git clone --recurse-submodules {repo}", client=client)
        run_command(
            f"Set-Location {ps_quote(repo_folder_name)}; "
            f"python -m pip install -r requirements.txt",
            client=client,
        )
    else:
        run_command(f"rm -rf {repo_folder_name}", client=client)
        run_command(f"git clone --recurse-submodules {repo} ", client=client)
        run_command(f"cd {repo_folder_name}; pip3 install -r requirements.txt", client=client)

    resolved_os = normalize_host_os(host_os) or getattr(client, "host_os", "")
    home_dir = get_home_dir(client=client)
    env_file = assemble_env_file(home_dir, repo_folder_name, resolved_os)
    write_env_file(remote_join(home_dir, repo_folder_name, ".env"), env_file, client=client)

def assemble_env_file(user_home, repo_folder_name, os_type):
    def get(key, default=""):
        return os.environ.get(key) or default

    binary_name = "mta-cli"
    normalized = normalize_host_os(os_type)
    if normalized == "darwin":
        binary_name = "darwin-mta-cli"
    elif normalized == "windows":
        binary_name = "mta-cli.exe"

    home = str(user_home).replace("\\", "/")
    env = {
        "KANTRA_CLI_PATH": f"{home}/.kantra/{binary_name}",
        "REPORT_OUTPUT_PATH": f"{home}/reports",
        "PROJECT_PATH": f"{home}/{repo_folder_name}",
        "GIT_USERNAME": get("GIT_USERNAME", ""),
        "GIT_PASSWORD": get("GIT_PASSWORD", ""),
    }
    return env


if __name__ == "__main__":
    load_config()
    parser = argparse.ArgumentParser(
        description="Deploys and prepares MTA CLI either locally or remotely.")
    parser.add_argument('--ip_address', required=False,
                        help='Optional, IP address of target server where MTA CLI will be deployed')
    parser.add_argument('--os', required=False, help='Optional for remote deployment, OS of remote host (windows/linux/darwin)')

    args = parser.parse_args()
    prepare_host({"args_ip_address": args.ip_address,
                  "args_os": args.os})
