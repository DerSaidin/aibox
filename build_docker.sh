SCRIPTPATH="$(realpath $0)"                     # past symlink
SCRIPTPATH="`dirname \"$SCRIPTPATH\"`"          # relative
SCRIPTPATH="`( cd \"${SCRIPTPATH}\" && pwd )`"  # absolutized and normalized
if [ -z "${SCRIPTPATH}" ] ; then
    # script path is not accessible
    # permissions? deleted in race?
    exit 1  # fail
fi
echo "${SCRIPTPATH}"

WORKSPACE_PATH="${1:-$PWD}"
WORKSPACE_PATH="`( cd \"${WORKSPACE_PATH}\" && pwd )`"
if [ -z "${WORKSPACE_PATH}" ] ; then
    exit 1  # fail
fi

docker build -t ai-harness-sandbox "${SCRIPTPATH}"

mkdir -p "$HOME/.cargo/registry"

mkdir -p "$HOME/.claude"
touch "$HOME/.claude.json"

mkdir -p "$HOME/.config/antigravity"
mkdir -p "$HOME/.gemini"

touch "$HOME/.gitconfig"

docker run --rm -it \
  --user 1000:1000 \
  --network=bridge \
  -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
  -e GEMINI_API_KEY="${GEMINI_API_KEY:-}" \
  -v "$WORKSPACE_PATH:/workspace:z" \
  -v "$HOME/.cargo/registry:/home/developer/.cargo/registry:z" \
  -v "$HOME/.claude:/home/developer/.claude:z" \
  -v "$HOME/.claude.json:/home/developer/.claude.json:z" \
  -v "$HOME/.config/antigravity:/home/developer/.config/antigravity:z" \
  -v "$HOME/.gemini:/home/developer/.gemini:z" \
  -v "$HOME/.gitconfig:/home/developer/.gitconfig:ro,z" \
  -w /workspace \
  ai-harness-sandbox \
  /bin/bash
