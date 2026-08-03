from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGE_PACK_SCRIPT = (
    REPO_ROOT / "hatsume/plugins/hatsume-plugin/virtual/image_pack.sh"
)
DOCKERFILE = (
    REPO_ROOT / "hatsume/plugins/hatsume-plugin/virtual/image/Dockerfile"
)


def _prepare_pack_tree(tmp_path: Path, env_contents: str) -> tuple[Path, Path, Path]:
    repo_root = tmp_path / "repo"
    virtual_dir = repo_root / "hatsume/plugins/hatsume-plugin/virtual"
    image_dir = virtual_dir / "image"
    image_dir.mkdir(parents=True)

    script_path = virtual_dir / "image_pack.sh"
    shutil.copy2(IMAGE_PACK_SCRIPT, script_path)
    (repo_root / ".env.prod").write_text(env_contents, encoding="utf-8")
    (repo_root / ".venv").symlink_to(REPO_ROOT / ".venv", target_is_directory=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_path = fake_bin / "docker"
    docker_path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
    build)
        [[ "${DOCKER_BUILDKIT:-}" == "1" ]]
        [[ "${CLAWMAIL_API_KEY:-}" == "synthetic claw secret" ]]
        [[ "${DS_API_KEY:-}" == "synthetic ds secret" ]]
        printf '%s\n' "$@" > "${DOCKER_ARGS_FILE:?}"
        ;;
    save)
        printf 'packed-image'
        ;;
    *)
        exit 64
        ;;
esac
""",
        encoding="utf-8",
    )
    docker_path.chmod(0o755)

    zstd_path = fake_bin / "zstd"
    zstd_path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
cat
""",
        encoding="utf-8",
    )
    zstd_path.chmod(0o755)

    docker_args_file = tmp_path / "docker-args.txt"
    return script_path, fake_bin, docker_args_file


def test_image_pack_passes_prod_values_as_buildkit_secrets(tmp_path: Path) -> None:
    script_path, fake_bin, docker_args_file = _prepare_pack_tree(
        tmp_path,
        "PORT = 8080\n"
        "CLAWMAIL_API_KEY='synthetic claw secret'\n"
        "DS_API_KEY='synthetic ds secret'\n",
    )
    caller_dir = tmp_path / "caller"
    caller_dir.mkdir()
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["DOCKER_ARGS_FILE"] = str(docker_args_file)

    result = subprocess.run(
        ["bash", str(script_path)],
        cwd=caller_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    docker_args = docker_args_file.read_text(encoding="utf-8").splitlines()
    assert docker_args == [
        "build",
        "--no-cache",
        "--secret",
        "id=clawmail_api_key,env=CLAWMAIL_API_KEY",
        "--secret",
        "id=ds_api_key,env=DS_API_KEY",
        "-t",
        "hatsume-space:1.0",
        str(script_path.parent / "image"),
    ]
    combined_output = result.stdout + result.stderr
    assert "synthetic claw secret" not in combined_output
    assert "synthetic ds secret" not in combined_output
    archive_path = script_path.parent / "hatsume-space-image.tar.zst"
    assert archive_path.read_text(encoding="utf-8") == "packed-image"


def test_image_pack_stops_before_docker_when_a_secret_is_missing(
    tmp_path: Path,
) -> None:
    script_path, fake_bin, docker_args_file = _prepare_pack_tree(
        tmp_path,
        "DS_API_KEY='synthetic ds secret'\n",
    )
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["DOCKER_ARGS_FILE"] = str(docker_args_file)

    result = subprocess.run(
        ["bash", str(script_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "CLAWMAIL_API_KEY" in result.stderr
    assert not docker_args_file.exists()


def test_dockerfile_consumes_secrets_without_build_args_or_plaintext_env() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "ARG CLAWMAIL_API_KEY" not in dockerfile
    assert "ARG DS_API_KEY" not in dockerfile
    assert "${CLAWMAIL_API_KEY}" not in dockerfile
    assert "${DS_API_KEY}" not in dockerfile
    assert "id=clawmail_api_key,required=true" in dockerfile
    assert "id=ds_api_key,required=true" in dockerfile
    assert "/run/secrets/ds_api_key" in dockerfile
    assert 'BASH_ENV="/etc/hatsume/bash_env"' in dockerfile
