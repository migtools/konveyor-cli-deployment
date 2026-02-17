# config.py
VERSION = None
BUILD = None
MISC_DOWNSTREAM_PATH = None
EXTRACT_BINARY = None
EXTRACT_BINARY_KONFLUX = None
GET_IMAGES_OUTPUT = None
BUNDLE = None
NO_BREW = None
SSH_USER = None
SSH_KEY = None

def set_config(config):
    """Loads config from JSON file and assigns constants"""
    global VERSION, BUILD, MISC_DOWNSTREAM_PATH, EXTRACT_BINARY, EXTRACT_BINARY_KONFLUX, GET_IMAGES_OUTPUT, BUNDLE, NO_BREW, SSH_USER, SSH_KEY

    MISC_DOWNSTREAM_PATH = config["misc_downstream_path"]
    EXTRACT_BINARY = config["extract_binary"]
    EXTRACT_BINARY_KONFLUX = config["extract_binary_konflux"]
    GET_IMAGES_OUTPUT = config["get_images_output"]
    BUNDLE = config["bundle"]
    NO_BREW = config["no_brew"]
    SSH_USER = config["ssh_user"]
    SSH_KEY = config["ssh_key"]

def validate_config():
    """Ensures that required configuration variables are set."""
    required_vars = {
        "MISC_DOWNSTREAM_PATH": MISC_DOWNSTREAM_PATH,
        "EXTRACT_BINARY": EXTRACT_BINARY,
        "EXTRACT_BINARY_KONFLUX": EXTRACT_BINARY_KONFLUX,
        "GET_IMAGES_OUTPUT": GET_IMAGES_OUTPUT,
        "BUNDLE": BUNDLE,
        "NO_BREW": NO_BREW
    }

    missing_vars = [var for var, value in required_vars.items() if not value]
    if missing_vars:
        raise SystemExit(f"Missing required configuration values: {', '.join(missing_vars)}")