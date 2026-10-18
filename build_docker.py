#!/usr/bin/env python3
"""Build (when stale) and run the AI harness sandbox container.

With no paths, $PWD is mounted as /workspace. Otherwise each path (file or
directory) is mounted as /workspace/<basename>; paths given with --ro are
mounted read-only.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

IMAGE_NAME = "ai-harness-sandbox"
# Rebuild automatically when the last successful build is older than this.
BUILD_MAX_AGE_SECONDS = 2 * 24 * 60 * 60
# Share of host CPU and memory any one container may use.
RESOURCE_FRACTION = 0.75

HOME = Path.home()
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local" / "state")
BUILD_STAMP = STATE_HOME / IMAGE_NAME / "last_build"

CONTAINER_HOME = Path("/home/developer")
WORKSPACE = Path("/workspace")


class HomeMount(NamedTuple):
    """A path under $HOME, mounted at the same place in the container's home."""

    path: str
    is_dir: bool = False
    read_only: bool = False


# Host config mounted into the container, per --config-* flag, along with the
# environment variables passed through with it.
CONFIGS = {
    "git": {
        "mounts": [
            HomeMount(".gitconfig", read_only=True),
            HomeMount(".gitconfig_local", read_only=True),
        ],
        "env": [],
    },
    "claude": {
        "mounts": [HomeMount(".claude", is_dir=True), HomeMount(".claude.json")],
        "env": ["ANTHROPIC_API_KEY"],
    },
    "gemini": {
        "mounts": [HomeMount(".config/antigravity", is_dir=True), HomeMount(".gemini", is_dir=True)],
        "env": ["GEMINI_API_KEY"],
    },
}

# Caches shared with the host regardless of flags.
CACHE_MOUNTS = [HomeMount(".cargo/registry", is_dir=True)]


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def volume(host_path, container_path, read_only=False):
    mode = "ro,z" if read_only else "z"
    return ["-v", f"{host_path}:{container_path}:{mode}"]


def home_mount_args(mount):
    host_path = HOME / mount.path
    # Create it if missing, so docker doesn't create a root-owned one in its place.
    if mount.is_dir:
        host_path.mkdir(parents=True, exist_ok=True)
    else:
        host_path.parent.mkdir(parents=True, exist_ok=True)
        host_path.touch()
    return volume(host_path, CONTAINER_HOME / mount.path, mount.read_only)


def config_args(name):
    args = []
    for mount in CONFIGS[name]["mounts"]:
        args += home_mount_args(mount)
    for var in CONFIGS[name]["env"]:
        args += ["-e", f"{var}={os.environ.get(var, '')}"]
    return args


def workspace_mounts(paths, ro_paths):
    if not paths and not ro_paths:
        return volume(Path.cwd(), WORKSPACE)

    mounts = []
    seen_names = {}
    for arg, read_only in [(p, False) for p in paths] + [(p, True) for p in ro_paths]:
        if not os.path.exists(arg):
            fail(f"no such file or directory: {arg}")
        host_path = Path(arg).resolve()
        if host_path == Path("/"):
            fail("refusing to mount /")
        name = host_path.name
        if name in seen_names:
            fail(f"'{arg}' and '{seen_names[name]}' would both mount at {WORKSPACE / name}")
        seen_names[name] = arg
        mounts += volume(host_path, WORKSPACE / name, read_only)
    return mounts


def resource_limits():
    cpus = (os.cpu_count() or 1) * RESOURCE_FRACTION
    mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    mem_mb = int(mem_bytes * RESOURCE_FRACTION) // (1024 * 1024)
    # Match --memory-swap to --memory so swap can't be used to exceed the cap.
    return ["--cpus", f"{cpus:g}", "--memory", f"{mem_mb}m", "--memory-swap", f"{mem_mb}m"]


def shell_command(exec_cmd):
    if not exec_cmd:
        return ["/bin/bash"]
    # Run the command, then hand over to an interactive shell.
    return ["/bin/bash", "-c", f"{exec_cmd}\nexec /bin/bash"]


def image_exists():
    result = subprocess.run(
        ["docker", "image", "inspect", IMAGE_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def build_is_stale():
    try:
        age = time.time() - BUILD_STAMP.stat().st_mtime
    except FileNotFoundError:
        return True
    return age >= BUILD_MAX_AGE_SECONDS


def build(context_dir):
    result = subprocess.run(["docker", "build", "-t", IMAGE_NAME, str(context_dir)])
    if result.returncode != 0:
        sys.exit(result.returncode)
    BUILD_STAMP.parent.mkdir(parents=True, exist_ok=True)
    BUILD_STAMP.touch()


def ensure_image(force):
    if force or not image_exists() or build_is_stale():
        build(Path(__file__).resolve().parent)  # past symlink


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-b", "--build", action="store_true", help="force a rebuild of the image before running"
    )
    parser.add_argument(
        "--ro",
        action="append",
        default=[],
        metavar="PATH",
        help="file or directory to mount read-only (repeatable)",
    )
    parser.add_argument(
        "-e",
        "--exec",
        metavar="CMD",
        help="command to run in the shell before it becomes interactive",
    )
    for name in CONFIGS:
        parser.add_argument(
            f"--config-{name}",
            action=argparse.BooleanOptionalAction,
            default=True,
            help=f"mount host {name} config into the container (default: on)",
        )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="files or directories to mount read-write (repeatable)",
    )
    return parser.parse_args()


def docker_run_command(args):
    mounts = workspace_mounts(args.paths, args.ro)
    for mount in CACHE_MOUNTS:
        mounts += home_mount_args(mount)
    for name in CONFIGS:
        if getattr(args, f"config_{name}"):
            mounts += config_args(name)

    return [
        "docker", "run", "--rm", "-it",
        "--user", "1000:1000",
        "--network=bridge",
        *resource_limits(),
        *mounts,
        "-w", str(WORKSPACE),
        IMAGE_NAME,
        *shell_command(args.exec),
    ]  # fmt: skip


def main():
    args = parse_args()
    # Build the command first, so bad paths fail before a slow image build.
    cmd = docker_run_command(args)
    ensure_image(args.build)
    # Replace this process so docker owns the terminal and signals directly.
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
