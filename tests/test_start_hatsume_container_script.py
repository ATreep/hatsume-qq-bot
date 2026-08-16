"""Contract tests for the one-click container startup script."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = ROOT / "start_hatsume_container.sh"
VIRTUAL_LAUNCH_SCRIPT = (
    ROOT / "hatsume/plugins/hatsume-plugin/virtual/launch_image.sh"
)
SUPERVISOR_SCRIPT = ROOT / ".container/supervise.sh"
DOCKERFILE = ROOT / "hatsume/plugins/hatsume-plugin/virtual/image/Dockerfile"


def test_one_click_script_targets_hatsume_containerization() -> None:
    script = START_SCRIPT.read_text(encoding="utf-8")

    assert 'readonly CONTAINER_NAME="hatsume-containerization"' in script
    assert 'readonly CONTAINER_DEFAULT_WORKDIR="/work"' in script
    assert 'readonly CONTAINER_HOME="/root"' in script
    assert '--name "${CONTAINER_NAME}"' in script
    assert '--network "${NETWORK_NAME}"' in script
    assert '--workdir "${CONTAINER_DEFAULT_WORKDIR}"' in script
    assert '--env "HOME=${CONTAINER_HOME}"' in script
    assert 'dst=${CONTAINER_WORKDIR}' in script
    assert '--entrypoint "${CONTAINER_ENTRYPOINT}"' in script
    assert '--env "PATH=${CONTAINER_PATH}"' in script


def test_virtual_launcher_accepts_hatsume_containerization() -> None:
    script = VIRTUAL_LAUNCH_SCRIPT.read_text(encoding="utf-8")

    assert '"${CONTAINER_NAME}" != "hatsume-containerization"' in script
    assert '--workdir /work' in script
    assert '--env "HOME=/root"' in script


def test_all_container_start_paths_configure_shanghai_timezone() -> None:
    start_script = START_SCRIPT.read_text(encoding="utf-8")
    virtual_script = VIRTUAL_LAUNCH_SCRIPT.read_text(encoding="utf-8")
    supervisor = SUPERVISOR_SCRIPT.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert 'readonly CONTAINER_TIMEZONE="Asia/Shanghai"' in start_script
    assert '--env "TZ=${CONTAINER_TIMEZONE}"' in start_script
    assert '--env "TZ=Asia/Shanghai"' in virtual_script
    assert 'export TZ="Asia/Shanghai"' in supervisor
    assert 'ENV TZ="Asia/Shanghai"' in dockerfile
