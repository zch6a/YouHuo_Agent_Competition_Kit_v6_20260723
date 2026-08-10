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


_BOM = b"\xef\xbb\xbf"
_SKIP_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", "node_modules"}


def _scripts(suffix: str) -> list[Path]:
    return sorted(
        p for p in ROOT.rglob(f"*{suffix}")
        if not set(p.relative_to(ROOT).parts) & _SKIP_DIRS
    )


@pytest.mark.parametrize("script", _scripts(".ps1"), ids=lambda p: p.name)
def test_powershell_scripts_with_chinese_carry_a_bom(script):
    """PowerShell 5.1 读没有 BOM 的 .ps1 时，按系统 ANSI 代码页解码。

    这台机器是 CP936。中文注释被解错之后，误解出的字节里只要有一个 0x60 落在行尾，
    那就是**续行符**——下一行整行被吞进注释。`verify_heavy.ps1` 就是这样把
    `$Venv = Join-Path ...` 弄丢的，而报错出现在七行之后（"Test-Path: 参数为 null"），
    从堆栈里完全看不出原因是编码。

    `verify_all.ps1` 当时没坏，纯属它的中文恰好没产生行尾反引号——那不是安全，
    是运气。
    """
    raw = script.read_bytes()
    if not any(b > 127 for b in raw.lstrip(_BOM)):
        pytest.skip("纯 ASCII，不需要 BOM")
    assert raw.startswith(_BOM), (
        f"{script.name} 含非 ASCII 却没有 UTF-8 BOM；PowerShell 5.1 会按 CP936 解码它"
    )


@pytest.mark.parametrize("script", _scripts(".sh"), ids=lambda p: p.name)
def test_shell_scripts_never_carry_a_bom(script):
    """.sh 反过来：BOM 会挤在 `#!` 前面，shebang 直接失效。

    同一个字符，两个文件类型，要求正好相反——所以两条都要有。
    """
    assert not script.read_bytes().startswith(_BOM), f"{script.name} 带 BOM，shebang 会失效"


#: 重型验证的产物。它们不在 verify_all 里重跑，只被读取，所以必须能判断是否过期。
_HEAVY_REPORTS = [
    "reports/mass_audit_v5_1000000.json",
    "reports/chaos_v5_400.json",
    "reports/load_v6_5000.json",
    "reports/http_smoke_v6.json",
]


@pytest.mark.parametrize("report", _HEAVY_REPORTS, ids=lambda p: Path(p).stem)
def test_heavy_reports_were_produced_by_the_current_source(report):
    """读一份报告，不等于跑过一次验证。

    一百万条 v5 断言和 400 个 Saga 场景单次要好几分钟，所以结论留在 JSON 里给
    `check_artifacts_v6` 引用。曾经有两天，`mass_audit_v5_1000000.json` 是 08-08 的，
    而 `v5_services.py`（含 `PurposeBoundPolicy` 的字段规范化）和 `security.py` 在
    08-10 被改过——`verify_all` 每次都报"全部阶段通过"，依据却是改动之前的结论。

    这不是它说谎，是它断言的对象错了：一条记录，而不是当前的事实。同一个错误在这个
    项目里还表现为"页面登记在 JSON 里就算够得着"和"`node --check` 过了就算能跑"。
    """
    import json

    from youhuo.provenance import source_digest

    data = json.loads((ROOT / report).read_text(encoding="utf-8"))
    assert "source_digest" in data, f"{report} 没有盖指纹，无法判断是否过期"
    assert data["source_digest"] == source_digest(), (
        f"{report} 是用另一版 backend/youhuo 跑出来的，重跑 verify_heavy"
    )


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

    if shutil.which("git") is None:
        pytest.skip("git not available")
    # Ask git where the checkout is rather than guessing: this project has lived
    # both at the repo root and one level down inside it.
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
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
