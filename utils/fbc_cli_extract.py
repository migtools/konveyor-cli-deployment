"""Assemble an OS/arch MTA CLI zip from the Konflux mta-cli container image.

Mirrors the layout produced by misc-downstream mta-cli-binary-extract-konflux.py
for a single platform/arch — used by pipeline --build fbc (no misc-downstream).
"""
from __future__ import annotations

import logging
import os
import shlex
import zipfile
from pathlib import Path

from utils.utils import _is_windows_ssh, run_command

BINARY_PATHS = {
    "linux": "/usr/local/bin/mta-cli",
    "windows": "/usr/local/bin/windows-mta-cli.exe",
    "darwin": "/usr/local/bin/darwin-mta-cli",
}

CLI_DEPENDENCIES = [
    "/jdtls",
    "/bin/fernflower.jar",
    "/usr/local/static-report",
    "/usr/local/etc/maven.default.index",
    "/usr/local/etc/maven-index.txt",
    "/usr/local/etc/task.gradle",
    "/usr/local/etc/task-v9.gradle",
    "/opt/rulesets",
]


def platform_binary_path(platform: str) -> str:
    key = (platform or "").lower()
    if key not in BINARY_PATHS:
        raise SystemExit(f"Unsupported CLI platform '{platform}' (expected linux|windows|darwin)")
    return BINARY_PATHS[key]


def provider_paths(platform: str) -> tuple[str, str]:
    key = (platform or "").lower()
    if key == "linux":
        return "/usr/local/bin/java-external-provider", "java-external-provider"
    if key == "windows":
        return "/usr/local/bin/windows-java-external-provider", "java-external-provider.exe"
    if key == "darwin":
        return "/usr/local/bin/darwin-java-external-provider", "java-external-provider"
    raise SystemExit(f"Unsupported CLI platform '{platform}' (expected linux|windows|darwin)")


def cli_zip_name(version: str, platform: str, arch: str) -> str:
    return f"mta-{version}-cli-{platform}-{arch}.zip"


def _nq(arg: str, windows: bool) -> str:
    """Quote for remote shell (bash vs cmd)."""
    if windows:
        if not arg or any(c in arg for c in ' \t&|<>^'):
            return '"' + arg.replace('"', '""') + '"'
        return arg
    return shlex.quote(arg)


def _posixish(path: str) -> str:
    return path.replace("\\", "/")


def extract_cli_zip(
    cli_image: str,
    version: str,
    platform: str,
    arch: str,
    output_dir: str,
    client=None,
) -> str:
    """
    Pull the CLI image (for arch), copy binaries + deps, and write
    mta-{version}-cli-{platform}-{arch}.zip under output_dir.

    When client is set, podman/zip work runs on the remote host and the returned
    path is the remote absolute path (for remote unzip). When client is None,
    work is local and the returned path is a local absolute path.
    """
    platform = (platform or "").lower()
    arch = (arch or "amd64").lower()
    windows = bool(client and _is_windows_ssh(client))
    binary_src = platform_binary_path(platform)
    provider_src, provider_dest = provider_paths(platform)
    zip_name = cli_zip_name(version, platform, arch)

    output_dir = _posixish(output_dir)
    work = _posixish(os.path.join(output_dir, f"fbc-cli-extract-{platform}-{arch}"))
    zip_path = _posixish(os.path.join(output_dir, zip_name))

    if windows:
        ps = (
            f"Remove-Item -LiteralPath '{work}' -Recurse -Force -ErrorAction SilentlyContinue; "
            f"New-Item -ItemType Directory -Force -Path '{work}' | Out-Null; "
            f"New-Item -ItemType Directory -Force -Path '{output_dir}' | Out-Null"
        )
        run_command(f"powershell -NoProfile -Command {_nq(ps, True)}", client=client)
    else:
        run_command(
            f"rm -rf {_nq(work, False)} && mkdir -p {_nq(work, False)} {_nq(output_dir, False)}",
            client=client,
        )

    # Container image arch is linux/amd64|arm64 even when extracting windows/darwin binaries.
    run_command(
        f"podman pull --arch {_nq(arch, windows)} {_nq(cli_image, windows)}",
        client=client,
    )

    create_out, _ = run_command(
        f"podman create --arch {_nq(arch, windows)} {_nq(cli_image, windows)} /bin/true",
        client=client,
    )
    container_id = create_out.strip().splitlines()[-1].strip()
    if not container_id:
        raise SystemExit(f"podman create returned empty container id for {cli_image}")

    try:
        binary_name = Path(binary_src).name
        run_command(
            f"podman cp {_nq(container_id, windows)}:{binary_src} "
            f"{_nq(_posixish(os.path.join(work, binary_name)), windows)}",
            client=client,
        )
        for dep in CLI_DEPENDENCIES:
            dep_name = Path(dep).name
            run_command(
                f"podman cp {_nq(container_id, windows)}:{dep} "
                f"{_nq(_posixish(os.path.join(work, dep_name)), windows)}",
                client=client,
            )
        run_command(
            f"podman cp {_nq(container_id, windows)}:{provider_src} "
            f"{_nq(_posixish(os.path.join(work, provider_dest)), windows)}",
            client=client,
        )

        if client is None:
            _zip_local_dir(work, zip_path)
        elif windows:
            # Prefer Windows python; fall back to Compress-Archive.
            py = (
                "import os, zipfile\n"
                f"work = r'''{work}'''\n"
                f"zip_path = r'''{zip_path}'''\n"
                "with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:\n"
                "    for root, dirs, files in os.walk(work):\n"
                "        for name in files:\n"
                "            fp = os.path.join(root, name)\n"
                "            zf.write(fp, os.path.relpath(fp, work))\n"
            )
            out, err = run_command(
                f"python -c {_nq(py, True)}",
                client=client,
                fail_on_failure=False,
            )
            check, _ = run_command(
                f'powershell -NoProfile -Command "if (Test-Path -LiteralPath \'{zip_path}\') '
                f'{{ Write-Output ok }}"',
                client=client,
                fail_on_failure=False,
            )
            if "ok" not in (check or ""):
                logging.warning(f"python zip failed on Windows; trying Compress-Archive. err={err!r} out={out!r}")
                run_command(
                    f"powershell -NoProfile -Command "
                    f"\"Compress-Archive -Path '{work}\\*' -DestinationPath '{zip_path}' -Force\"",
                    client=client,
                )
        else:
            py = (
                "import os, zipfile\n"
                f"work = {work!r}\n"
                f"zip_path = {zip_path!r}\n"
                "with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:\n"
                "    for root, dirs, files in os.walk(work):\n"
                "        for name in files:\n"
                "            fp = os.path.join(root, name)\n"
                "            zf.write(fp, os.path.relpath(fp, work))\n"
            )
            out, err = run_command(
                f"python3 -c {shlex.quote(py)}",
                client=client,
                fail_on_failure=False,
            )
            if run_command(
                f"test -f {shlex.quote(zip_path)} && echo ok",
                client=client,
                fail_on_failure=False,
            )[0].strip().endswith("ok"):
                pass
            else:
                logging.warning(f"python3 zip failed; trying zip(1). stderr={err!r} out={out!r}")
                run_command(
                    f"rm -f {shlex.quote(zip_path)} && "
                    f"(cd {shlex.quote(work)} && zip -r {shlex.quote(zip_path)} .)",
                    client=client,
                )
    finally:
        run_command(
            f"podman rm -f {_nq(container_id, windows)}",
            client=client,
            fail_on_failure=False,
        )
        if windows:
            run_command(
                f"powershell -NoProfile -Command "
                f"\"Remove-Item -LiteralPath '{work}' -Recurse -Force -ErrorAction SilentlyContinue\"",
                client=client,
                fail_on_failure=False,
            )
        else:
            run_command(f"rm -rf {shlex.quote(work)}", client=client, fail_on_failure=False)

    logging.info(f"FBC CLI zip ready: {zip_path}")
    if client is None:
        return os.path.abspath(zip_path)
    return zip_path


def _zip_local_dir(work: str, zip_path: str) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(work):
            for name in files:
                fp = os.path.join(root, name)
                zf.write(fp, os.path.relpath(fp, work))
