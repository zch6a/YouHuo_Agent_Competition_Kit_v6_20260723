r"""打交付包。

**只复制 git 跟踪的文件。** 这不是图省事，是这个仓库唯一可靠的"哪些算交付内容"
的定义：运行数据库、生成的审计密钥、`.env`、`.venv`、`__pycache__`、TTS 模型全都
在 `.gitignore` 里，按跟踪列表复制，它们就一个也进不来。

按目录遍历再手工排除的做法这个项目已经栽过一次：排除规则锚在 `data/`，而应用实际
写的是 `backend/data/`，于是一个真实的审计密钥被打进了包并推上了公开仓库。跟踪列表
不会有这种偏差——它就是 `git status` 干净时的那份内容。

用法：
    python backend/scripts/make_release.py [输出目录]

默认输出到 `F:\优活\交付包`。会做三件事：
  1. 复制成一个可直接查看的文件夹
  2. 生成 MANIFEST.sha256（逐文件散列）
  3. 压缩成 .zip 并生成 .zip.sha256

发布策略：第三方 `.claude/skills` 与 `.agents` 不随包发布；它们由 `.gitignore` 排除，
可按仓库的技能登记重新安装。仓库自有的 `.claude/skills/youhuo-ui-constraints/SKILL.md`
属于项目约束，会随 Git 跟踪文件进入包。脚本输出的包内 MANIFEST 是实际交付内容的唯一清单。

最后自己检查一遍包里有没有敏感文件——打包脚本自己也可能有 bug。
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = Path(r"F:\优活\交付包")

#: 无论如何都不该出现在交付包里的东西。打包脚本自己也可能出错，所以打完再验一遍。
FORBIDDEN_SUFFIXES = (".db", ".db-wal", ".db-shm", ".audit.key", ".onnx", ".pyc")
FORBIDDEN_NAMES = (".env",)
FORBIDDEN_DIRS = (".venv", "__pycache__", ".pytest_cache", "node_modules", ".git")

#: git 跟踪、但**不进交付包**的可再生产物。
#:
#: 实测：交付包 195.9 MB，其中 185.1 MB（94%）是 PNG，而 173.5 MB 是
#: `frontend_audit/screenshots/` 里 384 张**这一轮重构之前**那个界面的照片。评委解开
#: 包，看到的是一个已经不存在的 UI 的 384 张截图。
#:
#: 它们仍然留在 git 里——那是审计轮的"改之前"证据，删掉就是抹掉记录。但它们是
#: `shoot_pages.py` 每次运行都重新生成的东西，不是源码，没有理由占交付包 94% 的体积。
#: 怎么自己生成写在 frontend_redesign/README.md 里。
#:
#: 这一条是**排除**，不是禁止：`audit()` 不查它，因为往包里放截图并不危险，只是没必要。
REGENERABLE_DIRS = ("shots/", "frontend_audit/screenshots/")


def tracked_files() -> list[str]:
    """git 跟踪的全部文件。

    `core.quotepath=false` + 显式 utf-8：这个仓库里有中文文件名，默认设置下 git 会
    把它们转义成 `\\346\\210\\220...`，而 Windows 控制台是 CP936——两件事叠加，
    文件名会解码成乱码然后复制失败。这个坑本项目踩过。
    """
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def is_clean() -> bool:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "status", "--porcelain"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return not result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(folder: Path) -> list[str]:
    """打完包再查一遍。脚本自己也可能有 bug。"""
    problems: list[str] = []
    for path in folder.rglob("*"):
        if path.is_dir():
            if path.name in FORBIDDEN_DIRS:
                problems.append(f"目录不该在包里：{path.relative_to(folder)}")
            continue
        rel = path.relative_to(folder)
        if any(part in FORBIDDEN_DIRS for part in rel.parts):
            problems.append(f"路径经过被排除的目录：{rel}")
        if path.name in FORBIDDEN_NAMES or path.name.endswith(FORBIDDEN_SUFFIXES):
            problems.append(f"敏感或运行产物：{rel}")
    return problems


def main() -> int:
    out_root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    stamp = datetime.now().strftime("%Y%m%d")
    name = f"优活Agent_v6_交付_{stamp}"
    folder = out_root / name

    if not is_clean():
        print("⚠ 工作树不干净。交付包按 git 跟踪列表打，未提交的改动**不会**进包。")
        print("  如果那是有意的，继续；否则先提交。\n")

    files = tracked_files()
    if not files:
        print("git ls-files 返回空，无法打包")
        return 1

    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    copied = 0
    missing: list[str] = []
    skipped_bytes = 0
    skipped = 0
    for rel in files:
        src = ROOT / rel
        if not src.is_file():
            # 跟踪但磁盘上没有（例如刚被删除还没提交）。记下来，不要静默跳过。
            missing.append(rel)
            continue
        if rel.startswith(REGENERABLE_DIRS):
            skipped += 1
            skipped_bytes += src.stat().st_size
            continue
        dst = folder / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1

    # MANIFEST：逐文件散列，收包方可以逐个核对。
    manifest = folder / "MANIFEST.sha256"
    lines = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path != manifest:
            lines.append(f"{sha256(path)}  {path.relative_to(folder).as_posix()}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    problems = audit(folder)
    if problems:
        print(f"FAIL 包里有不该有的东西（{len(problems)} 项）：")
        for item in problems[:20]:
            print(f"  {item}")
        return 1

    # 压缩包 + 它自己的散列。
    archive = out_root / f"{name}.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, f"{name}/{path.relative_to(folder).as_posix()}")
    (out_root / f"{name}.zip.sha256").write_text(
        f"{sha256(archive)}  {archive.name}\n", encoding="utf-8"
    )

    total_mb = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"文件夹  {folder}")
    print(f"压缩包  {archive}  ({archive.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"散列    {archive.name}.sha256")
    print(f"内容    {copied} 个文件，{total_mb:.1f} MB，MANIFEST 覆盖 {len(lines)} 项")
    if skipped:
        # 明说跳过了什么、省了多少。一个静默瘦身的打包脚本，和一个漏文件的打包脚本
        # 在输出里长得一模一样。
        print(f"跳过    {skipped} 个可再生截图（{skipped_bytes / 1024 / 1024:.1f} MB）："
              f"{'、'.join(REGENERABLE_DIRS)}——用 shoot_pages.py 现生成")
    if missing:
        print(f"⚠ {len(missing)} 个已跟踪但磁盘上不存在的文件被跳过：{missing[:5]}")
    print("检查    未发现运行库、审计密钥、.env、虚拟环境或缓存")
    return 0


if __name__ == "__main__":
    sys.exit(main())
