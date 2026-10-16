FROM debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251

ENV DEBIAN_FRONTEND=noninteractive

# 1. System toolchain dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    neovim \
    curl \
    git \
    gnupg \
    libssl-dev \
    libcairo2-dev \
    libglib2.0-dev \
    pkg-config \
    procps \
    python3 \
    python3-pip \
    python3-venv \
    bat \
    direnv \
    exa \
    fzf \
    jq \
    kakoune \
    p7zip-full \
    ripgrep \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# 2. Node.js LTS (v20) for Claude Code
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 3. Create non-root developer user
ARG USERNAME=developer
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

USER $USERNAME
WORKDIR /home/$USERNAME

# 4. Global environment paths for binary discovery
ENV VIRTUAL_ENV=/home/$USERNAME/.venv
ENV NPM_CONFIG_PREFIX=/home/$USERNAME/.npm-global
ENV RUSTUP_HOME=/home/$USERNAME/.rustup
ENV CARGO_HOME=/home/$USERNAME/.cargo

# Combine all binary locations into PATH
ENV PATH="/home/$USERNAME/.local/bin:$VIRTUAL_ENV/bin:$NPM_CONFIG_PREFIX/bin:$CARGO_HOME/bin:$PATH"

# 5. Install Python virtual environment & Google Antigravity SDK / CLI
RUN python3 -m venv $VIRTUAL_ENV \
    && pip install --no-cache-dir google-antigravity

RUN curl -fsSL https://antigravity.google/cli/install.sh | bash

# 7. Install Rust Stable
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable

# 8. Install Claude Code (kept last so re-pulling the latest version
#    only invalidates this cheap layer, not the toolchain above).
#    Pass --build-arg CLAUDE_CODE_VERSION=latest (or a specific version) and
#    rebuild to pick up a new release; bumping the value busts just this layer.
ARG CLAUDE_CODE_VERSION=^2.1.280
RUN mkdir -p $NPM_CONFIG_PREFIX \
    && npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && claude --version

# Pre-create /workspace owned by the developer user, so it stays writable when
# only individual paths are mounted inside it.
RUN sudo install -d -o $USERNAME -g $USERNAME /workspace
WORKDIR /workspace

CMD ["/bin/bash"]
