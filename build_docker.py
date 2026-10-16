#!/usr/bin/env python3
"""Build (when stale) and run the AI harness sandbox container.

With no paths, $PWD is mounted as /workspace. Otherwise each path (file or
directory) is mounted as /workspace/<basename>.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

IMAGE_NAME = "ai-harness-sandbox"
# Rebuild automatically when the last successful build is older than this.
BUILD_MAX_AGE_SECONDS = 2 * 24 * 60 * 60

HOME = Path.home()
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local" / "state")
BUILD_STAMP = STATE_HOME / IMAGE_NAME / "last_build"


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def workspace_mounts(paths):
    if not paths:
        return ["-v", f"{Path.cwd()}:/workspace:z"]

    mounts = []
    seen_names = {}
    for arg in paths:
        if not os.path.exists(arg):
            fail(f"no such file or directory: {arg}")
        host_path = Path(arg).resolve()
        if host_path == Path("/"):
            fail("refusing to mount /")
        name = host_path.name
        if name in seen_names:
            fail(f"'{arg}' and '{seen_names[name]}' would both mount at /workspace/{name}")
        seen_names[name] = arg
        mounts += ["-v", f"{host_path}:/workspace/{name}:z"]
    return mounts


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-b", "--build", action="store_true", help="force a rebuild of the image before running"
    )
    parser.add_argument("paths", nargs="*", metavar="PATH", help="files or directories to mount")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent  # past symlink
    mounts = workspace_mounts(args.paths)

    if args.build or not image_exists() or build_is_stale():
        build(script_dir)

    # Make sure mounted config exists on the host, so docker doesn't create
    # root-owned directories in its place.
    for d in [".cargo/registry", ".claude", ".config/antigravity", ".gemini"]:
        (HOME / d).mkdir(parents=True, exist_ok=True)
    for f in [".claude.json", ".gitconfig", ".gitconfig_local"]:
        (HOME / f).touch()

    cmd = [
        "docker", "run", "--rm", "-it",
        "--user", "1000:1000",
        "--network=bridge",
        "-e", f"ANTHROPIC_API_KEY={os.environ.get('ANTHROPIC_API_KEY', '')}",
        "-e", f"GEMINI_API_KEY={os.environ.get('GEMINI_API_KEY', '')}",
        *mounts,
        "-v", f"{HOME}/.cargo/registry:/home/developer/.cargo/registry:z",
        "-v", f"{HOME}/.claude:/home/developer/.claude:z",
        "-v", f"{HOME}/.claude.json:/home/developer/.claude.json:z",
        "-v", f"{HOME}/.config/antigravity:/home/developer/.config/antigravity:z",
        "-v", f"{HOME}/.gemini:/home/developer/.gemini:z",
        "-v", f"{HOME}/.gitconfig:/home/developer/.gitconfig:ro,z",
        "-v", f"{HOME}/.gitconfig_local:/home/developer/.gitconfig_local:ro,z",
        "-w", "/workspace",
        IMAGE_NAME,
        "/bin/bash",
    ]  # fmt: skip
    # Replace this process so docker owns the terminal and signals directly.
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
