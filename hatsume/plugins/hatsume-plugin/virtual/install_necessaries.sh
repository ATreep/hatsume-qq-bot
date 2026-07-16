#!/usr/bin/env bash

set -e

# Use TUNA mirror
cat >/etc/apt/sources.list <<'EOF'
deb https://mirrors.tuna.tsinghua.edu.cn/kali kali-rolling main contrib non-free non-free-firmware
EOF

apt update && apt install -y \
    kali-linux-headless \
    curl \
    wget \
    git \
    python3 \
    python3-pip \
    netcat-traditional \
    iputils-ping \
    whois

# Install nodejs and npm
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt install -y nodejs

# Install minimal deps needed to add GitHub CLI repo, then install all packages
(type -p wget >/dev/null || (apt update && apt install wget -y)) \
    && mkdir -p -m 755 /etc/apt/keyrings \
    && out=$(mktemp) && wget -nv -O"$out" https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    && cat "$out" | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && mkdir -p -m 755 /etc/apt/sources.list.d \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list >/dev/null \
    && apt update \
    && apt install gh -y

# Use Tsinghua mirror for pip
pip3 config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# Install Python packages
pip3 install agent-reach

# Install Claude Code
curl -fsSL https://claude.ai/install.sh | bash

# Install agently-cli
npm install -g @tencent-qqmail/agently-cli

# Configure non-secret Claude Code defaults. Authentication must be injected
# when the container starts; never bake credentials into the image.
echo 'export PATH="/root/.local/bin:$PATH"' >>/root/.bashrc
echo 'export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic' >>/root/.bashrc
echo 'export ANTHROPIC_MODEL=deepseek-v4-pro[1m]' >>/root/.bashrc
echo 'export ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]' >>/root/.bashrc
echo 'export ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]' >>/root/.bashrc
echo 'export ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash' >>/root/.bashrc
echo 'export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0' >>/root/.bashrc
