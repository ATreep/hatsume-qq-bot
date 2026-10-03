# syntax=docker/dockerfile:1

FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN architecture="$(dpkg --print-architecture)" \
    && case "${architecture}" in \
        amd64) \
            tuna_repository='ubuntu'; \
            upstream_repository='archive.ubuntu.com/ubuntu' ;; \
        arm64|armhf|ppc64el|riscv64|s390x) \
            tuna_repository='ubuntu-ports'; \
            upstream_repository='ports.ubuntu.com/ubuntu-ports' ;; \
        *) \
            echo "Unsupported Ubuntu architecture: ${architecture}" >&2; \
            exit 1 ;; \
    esac \
    && printf '%s\t%s\n' \
        "http://mirrors.tuna.tsinghua.edu.cn/${tuna_repository}/" 'priority:1' \
        "http://${upstream_repository}/" 'priority:2' \
        > /etc/apt/ubuntu-mirrors.list \
    && printf '%s\n' \
        'Types: deb' \
        'URIs: mirror+file:/etc/apt/ubuntu-mirrors.list' \
        'Suites: resolute resolute-updates resolute-backports resolute-security' \
        'Components: main restricted universe multiverse' \
        'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg' \
        > /etc/apt/sources.list.d/ubuntu.sources \
    && rm -f /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && sed -i 's|^http://|https://|' /etc/apt/ubuntu-mirrors.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        dnsutils \
        file \
        git \
        gnupg \
        iproute2 \
        iputils-ping \
        jq \
        less \
        lsof \
        netcat-openbsd \
        openssh-client \
        procps \
        python3 \
        python3-pip \
        python3-venv \
        ripgrep \
        rsync \
        traceroute \
        unzip \
        wget \
        whois \
        xz-utils \
        zip \
        zstd \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN install -d -m 755 /etc/apt/keyrings /etc/apt/sources.list.d \
    && wget -nv \
        -O /etc/apt/keyrings/githubcli-archive-keyring.gpg \
        https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 config set global.index-url \
        https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip3 install --break-system-packages agent-reach


RUN npm install -g agentmail-cli

RUN --mount=type=secret,id=agentmail_api_key,required=true \
    --mount=type=secret,id=gh_token,required=true \
    install -d -m 700 /root/.config/hatsume \
    && install -d -m 755 /etc/hatsume \
    && { \
        printf 'export GH_TOKEN=%q\n' "$(cat /run/secrets/gh_token)"; \
        printf 'export AGENTMAIL_API_KEY=%q\n' "$(cat /run/secrets/agentmail_api_key)"; \
    } > /etc/hatsume/bash_env \
    && chmod 600 /etc/hatsume/bash_env

ENV HOME="/root"

ENV TZ="Asia/Shanghai" \
    PATH="/work/hatsume/.container:/root/.local/bin:${PATH}" \
    BASH_ENV="/etc/hatsume/bash_env"

WORKDIR /work
