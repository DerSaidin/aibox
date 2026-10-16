#!/usr/bin/env bash
SCRIPTPATH="$(realpath $0)"                     # past symlink
SCRIPTPATH="`dirname \"$SCRIPTPATH\"`"          # relative
SCRIPTPATH="`( cd \"${SCRIPTPATH}\" && pwd )`"  # absolutized and normalized
if [ -z "${SCRIPTPATH}" ] ; then
    # script path is not accessible
    # permissions? deleted in race?
    exit 1  # fail
fi
echo "${SCRIPTPATH}"

IMAGE_NAME="ai-harness-sandbox"
# Rebuild automatically when the last successful build is older than this.
BUILD_MAX_AGE_MINUTES=$((2 * 24 * 60))
BUILD_STAMP="${XDG_STATE_HOME:-$HOME/.local/state}/${IMAGE_NAME}/last_build"

usage() {
    echo "usage: $(basename "$0") [-b|--build] [--] [PATH...]" >&2
    echo "  -b, --build  force a rebuild of the image before running" >&2
}

FORCE_BUILD=0
while [ "$#" -gt 0 ] ; do
    case "$1" in
        -b|--build) FORCE_BUILD=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        -*) echo "error: unknown option: $1" >&2; usage; exit 1 ;;
        *) break ;;
    esac
done

# With no arguments, mount $PWD as /workspace. Otherwise mount each argument
# (file or directory) as /workspace/<basename>.
WORKSPACE_MOUNTS=()
if [ "$#" -eq 0 ] ; then
    WORKSPACE_MOUNTS+=(-v "$PWD:/workspace:z")
else
    declare -A SEEN_NAMES=()
    for ARG in "$@" ; do
        if [ ! -e "${ARG}" ] ; then
            echo "error: no such file or directory: ${ARG}" >&2
            exit 1
        fi
        HOST_PATH="$(realpath "${ARG}")"
        NAME="$(basename "${HOST_PATH}")"
        if [ "${HOST_PATH}" = "/" ] ; then
            echo "error: refusing to mount /" >&2
            exit 1
        fi
        if [ -n "${SEEN_NAMES[$NAME]:-}" ] ; then
            echo "error: '${ARG}' and '${SEEN_NAMES[$NAME]}' would both mount at /workspace/${NAME}" >&2
            exit 1
        fi
        SEEN_NAMES[$NAME]="${ARG}"
        WORKSPACE_MOUNTS+=(-v "${HOST_PATH}:/workspace/${NAME}:z")
    done
fi

NEEDS_BUILD="${FORCE_BUILD}"
if ! docker image inspect "${IMAGE_NAME}" > /dev/null 2>&1 ; then
    NEEDS_BUILD=1
elif [ -z "$(find "${BUILD_STAMP}" -mmin "-${BUILD_MAX_AGE_MINUTES}" 2> /dev/null)" ] ; then
    # Stamp is missing or older than BUILD_MAX_AGE_MINUTES.
    NEEDS_BUILD=1
fi

if [ "${NEEDS_BUILD}" -eq 1 ] ; then
    docker build -t "${IMAGE_NAME}" "${SCRIPTPATH}" || exit 1
    mkdir -p "$(dirname "${BUILD_STAMP}")"
    touch "${BUILD_STAMP}"
fi

mkdir -p "$HOME/.cargo/registry"

mkdir -p "$HOME/.claude"
touch "$HOME/.claude.json"

mkdir -p "$HOME/.config/antigravity"
mkdir -p "$HOME/.gemini"

touch "$HOME/.gitconfig"
touch "$HOME/.gitconfig_local"

docker run --rm -it \
  --user 1000:1000 \
  --network=bridge \
  -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
  -e GEMINI_API_KEY="${GEMINI_API_KEY:-}" \
  "${WORKSPACE_MOUNTS[@]}" \
  -v "$HOME/.cargo/registry:/home/developer/.cargo/registry:z" \
  -v "$HOME/.claude:/home/developer/.claude:z" \
  -v "$HOME/.claude.json:/home/developer/.claude.json:z" \
  -v "$HOME/.config/antigravity:/home/developer/.config/antigravity:z" \
  -v "$HOME/.gemini:/home/developer/.gemini:z" \
  -v "$HOME/.gitconfig:/home/developer/.gitconfig:ro,z" \
  -v "$HOME/.gitconfig_local:/home/developer/.gitconfig_local:ro,z" \
  -w /workspace \
  "${IMAGE_NAME}" \
  /bin/bash
