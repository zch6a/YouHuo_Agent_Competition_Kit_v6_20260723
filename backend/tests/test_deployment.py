"""容器部署：镜像里是不是真的能起来。

Dockerfile 只 `COPY backend` 和 `COPY xiaoyi`，然后 `mkdir -p /app/data`。
`MedicationKnowledgeBase` 在 `create_app()` 里读 `data/medication_interactions_demo.json`，
而那个目录是空的——镜像一启动就 `FileNotFoundError`，crash-loop。
docker-compose 又把一个卷挂在 `/app/data` 上，就算把文件拷进去也会被卷遮住。

这些用例按 Dockerfile 声明的 COPY 集合搭出镜像的文件树再启动应用，所以任何
"应用需要但镜像没带"的文件都会让测试失败，而不是让部署失败。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"


def _copy_sources() -> list[str]:
    """Repo-relative paths the Dockerfile copies into the image."""
    sources: list[str] = []
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*COPY\s+(?:--\S+\s+)*(.+)", line)
        if not match:
            continue
        parts = match.group(1).split()
        sources.extend(parts[:-1])  # last token is the destination
    return sources


@pytest.fixture(scope="module")
def staged_image(tmp_path_factory) -> Path:
    stage = tmp_path_factory.mktemp("image") / "app"
    stage.mkdir()
    for source in _copy_sources():
        src = ROOT / source
        if not src.exists():
            pytest.fail(f"Dockerfile COPY 了不存在的路径：{source}")
        if src.is_dir():
            shutil.copytree(
                src,
                stage / source,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "data"),
            )
        else:
            (stage / source).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, stage / source)
    # RUN mkdir -p /app/data — and docker-compose mounts an empty volume here,
    # so the image must never depend on anything inside it. Assert the staged
    # tree really is empty before any test runs: the app writes its database
    # here, so checking afterwards would only find its own output.
    data = stage / "data"
    data.mkdir(exist_ok=True)
    assert list(data.iterdir()) == [], "镜像不应把任何文件放进 data/（部署时会被卷遮住）"
    return stage


def test_the_image_can_actually_start(staged_image: Path):
    result = subprocess.run(
        [sys.executable, "-c", "import youhuo.api as m; m.app; print('OK')"],
        cwd=staged_image,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env={
            **os.environ,
            "PYTHONPATH": str(staged_image / "backend"),
            "YOUHUO_DB_PATH": str(staged_image / "data" / "youhuo.db"),
        },
    )
    assert result.returncode == 0, (
        "镜像文件树下应用启动失败——部署时会 crash-loop：\n"
        + "\n".join(result.stderr.strip().splitlines()[-8:])
    )
    assert "OK" in result.stdout


def test_reference_data_ships_inside_the_package():
    """data/ is a mounted volume in every deployment; read-only data cannot live there."""
    packaged = ROOT / "backend/youhuo/reference/medication_interactions_demo.json"
    assert packaged.is_file(), "用药参考数据必须随包发布"
    assert not (ROOT / "data/medication_interactions_demo.json").exists(), (
        "参考数据不能留在 data/：容器会把卷挂在这里并遮住它"
    )


def test_cmd_honours_the_injected_port():
    """Render/Railway/Fly/Cloud Run all inject $PORT and health-check it."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    cmd = [line for line in text.splitlines() if line.startswith("CMD")]
    assert cmd, "Dockerfile 缺少 CMD"
    assert "${PORT" in cmd[0], f"CMD 必须使用注入的 $PORT，实际为：{cmd[0]}"
    assert not re.search(r"--port\s+8000\b", cmd[0]), "端口不能写死成 8000"


def test_healthcheck_uses_the_same_port():
    text = DOCKERFILE.read_text(encoding="utf-8")
    healthcheck = [line for line in text.splitlines() if "urlopen" in line]
    assert healthcheck, "Dockerfile 缺少 HEALTHCHECK"
    assert "PORT" in healthcheck[0], "健康检查必须跟随 $PORT，否则平台上永远不健康"


def test_compose_volume_does_not_shadow_packaged_data():
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    mounts = compose["services"]["youhuo"].get("volumes", [])
    targets = {str(m).split(":")[1] for m in mounts if ":" in str(m)}
    for target in targets:
        assert not target.rstrip("/").endswith("/backend"), (
            f"卷 {target} 会遮住随包发布的参考数据"
        )
