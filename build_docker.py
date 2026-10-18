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

IMAGE_NAME = "ai-harness-sandbox"
# Rebuild automatically when the last successful build is older than this.
BUILD_MAX_AGE_SECONDS = 2 * 24 * 60 * 60

HOME = Path.home()
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local" / "state")
BUILD_STAMP = STATE_HOME / IMAGE_NAME / "last_build"


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


# Host config mounted into the container, per --config-* flag. Directories end
# in "/"; host paths are created if missing so docker doesn't create
# root-owned ones in their place.
CONFIGS = {
    "git": {
        "mounts": [".gitconfig:ro", ".gitconfig_local:ro"],
        "env": [],
    },
    "claude": {
        "mounts": [".claude/", ".claude.json"],
        "env": ["ANTHROPIC_API_KEY"],
    },
    "gemini": {
        "mounts": [".config/antigravity/", ".gemini/"],
        "env": ["GEMINI_API_KEY"],
    },
}


def workspace_mounts(paths, ro_paths):
    if not paths and not ro_paths:
        return ["-v", f"{Path.cwd()}:/workspace:z"]

    mounts = []
    seen_names = {}
    for arg, mode in [(p, "z") for p in paths] + [(p, "ro,z") for p in ro_paths]:
        if not os.path.exists(arg):
            fail(f"no such file or directory: {arg}")
        host_path = Path(arg).resolve()
        if host_path == Path("/"):
            fail("refusing to mount /")
        name = host_path.name
        if name in seen_names:
            fail(f"'{arg}' and '{seen_names[name]}' would both mount at /workspace/{name}")
        seen_names[name] = arg
        mounts += ["-v", f"{host_path}:/workspace/{name}:{mode}"]
    return mounts


def config_args(name):
    args = []
    for mount in CONFIGS[name]["mounts"]:
        rel, _, mode = mount.partition(":")
        host_path = HOME / rel.rstrip("/")
        if rel.endswith("/"):
            host_path.mkdir(parents=True, exist_ok=True)
        else:
            host_path.parent.mkdir(parents=True, exist_ok=True)
            host_path.touch()
        opts = f"{mode},z" if mode else "z"
        args += ["-v", f"{host_path}:/home/developer/{rel.rstrip('/')}:{opts}"]
    for var in CONFIGS[name]["env"]:
        args += ["-e", f"{var}={os.environ.get(var, '')}"]
    return args


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
    parser.add_argument("paths", nargs="*", metavar="PATH", help="files or directories to mount read-write (repeatable)")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent  # past symlink
    mounts = workspace_mounts(args.paths, args.ro)

    if args.build or not image_exists() or build_is_stale():
        build(script_dir)

    (HOME / ".cargo/registry").mkdir(parents=True, exist_ok=True)
    configs = []
    for name in CONFIGS:
        if getattr(args, f"config_{name}"):
            configs += config_args(name)

    shell = ["/bin/bash"]
    if args.exec:
        # Run the command, then hand over to an interactive shell.
        shell += ["-c", f'{args.exec}\nexec /bin/bash']

    cmd = [
        "docker", "run", "--rm", "-it",
        "--user", "1000:1000",
        "--network=bridge",
        *mounts,
        *configs,
        "-v", f"{HOME}/.cargo/registry:/home/developer/.cargo/registry:z",
        "-w", "/workspace",
        IMAGE_NAME,
        *shell,
    ]  # fmt: skip
    # Replace this process so docker owns the terminal and signals directly.
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
