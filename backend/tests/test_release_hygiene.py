"""发布卫生：不该进仓库的东西，检查器必须真的能发现。

`check_artifacts_v6.py` 曾把运行库和审计密钥写死成 `data/youhuo.db` 三条路径，
而应用实际写到启动目录——`uvicorn --app-dir backend` 时是 `backend/data/`。
于是交付检查报告"干净"，同时一份真实数据库和一把生成的 HMAC 审计密钥就躺在
隔壁目录里，被提交并推送到了公开仓库。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_artifacts_v6", ROOT / "backend/scripts/check_artifacts_v6.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "relative",
    [
        "data/youhuo.db",                 # the original hard-coded location
        "backend/data/youhuo.db",         # where uvicorn --app-dir backend writes
        "backend/data/youhuo.db.audit.key",
        "somewhere/else/ui.db-wal",       # a WAL sidecar holds committed rows
        "nested/deep/model.onnx",
    ],
)
def test_leaked_artifacts_found_anywhere_in_the_tree(tmp_path, relative):
    checker = _load_checker()
    planted = tmp_path / relative
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_bytes(b"x")
    found = {p.name for p in checker._leaked_artifacts(tmp_path)}
    assert planted.name in found


def test_virtualenv_and_git_are_not_scanned(tmp_path):
    """A venv legitimately contains .db fixtures; scanning it would never pass."""
    checker = _load_checker()
    for noise in (".venv/lib/sample.db", ".git/objects/pack/x.db", "__pycache__/c.db"):
        path = tmp_path / noise
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    assert checker._leaked_artifacts(tmp_path) == []


def test_clean_tree_reports_nothing(tmp_path):
    checker = _load_checker()
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend/data").mkdir()
    (tmp_path / "backend/data/.gitkeep").write_text("", encoding="utf-8")
    assert checker._leaked_artifacts(tmp_path) == []


def test_gitignore_matches_by_name_not_by_directory():
    """Anchoring to data/ is what let backend/data/ through."""
    patterns = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    for required in ("*.db", "*.db-wal", "*.db-shm", "*.audit.key", "*.onnx", ".env"):
        assert required in patterns, f".gitignore 缺少 {required}"


def test_nothing_dangerous_is_tracked_by_git():
    """The invariant is about what is *committed*, not what is on disk.

    A developer who ran the demo has a live data/youhuo.db, and that is fine.
    The same file in `git ls-files` is the defect — that is what reached GitHub.
    """
    import shutil
    import subprocess

    if shutil.which("git") is None or not (ROOT.parent / ".git").exists():
        pytest.skip("not a git checkout")
    # encoding must be explicit: git emits UTF-8, and this repo has Chinese
    # filenames that the Windows CP936 default cannot decode.
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()
    bad = [
        name
        for name in tracked
        if name.endswith((".db", ".db-wal", ".db-shm", ".audit.key", ".onnx"))
    ]
    assert bad == [], f"这些运行产物被 git 跟踪，会进入公开仓库：{bad}"


def test_importing_the_api_module_creates_no_database(tmp_path, monkeypatch):
    """Importing must not touch the filesystem.

    `app = create_app()` at module scope seeded a database wherever the process
    started, which is how a live db and an audit key got committed.
    """
    import subprocess
    import sys

    script = "import youhuo.api, pathlib, sys; sys.stdout.write(str(sorted(p.name for p in pathlib.Path('data').glob('*'))) if pathlib.Path('data').exists() else '[]')"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "backend")},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", f"导入 youhuo.api 就创建了文件：{result.stdout}"
