#!/usr/bin/env python3
import argparse
import json
import os

from config import set_config
from utils.utils import connect_ssh, run_command, get_repo_folder_name, get_home_dir, write_env_file

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
        client = connect_ssh(ip_address)
    except Exception as err:
        raise SystemExit("There was an issue connecting to remote host: {}".format(err))

    prepare_testing_repo("https://github.com/konveyor/kantra-cli-tests", host_os, client=client)


def prepare_testing_repo(repo="", host_os="", client=None):
    repo_folder_name = get_repo_folder_name(repo)
    run_command(f"rm -rf {repo_folder_name}", client=client)
    run_command(f"git clone --recurse-submodules {repo} ", client=client)
    run_command(f"cd {repo_folder_name}; pip3 install -r requirements.txt", client=client)
    home_dir = get_home_dir(client=client)
    env_file=assemble_env_file(home_dir, repo_folder_name, host_os)

    write_env_file(os.path.join(home_dir, repo_folder_name, '.env'), env_file, client=client)

def assemble_env_file(user_home, repo_folder_name, os_type):
    def get(key, default=""):
        return os.environ.get(key) or default

    binary_name = "mta-cli"
    if os_type == "darwin":
        binary_name = "darwin-mta-cli"
    env = {
        "KANTRA_CLI_PATH": f"{user_home}/.kantra/{binary_name}",
        "REPORT_OUTPUT_PATH": f"{user_home}/reports",
        "PROJECT_PATH": f"{user_home}/{repo_folder_name}",
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
