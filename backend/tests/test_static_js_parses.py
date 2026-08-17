"""`backend/static` 下每个 JS 都得能解析。

## 为什么有这一条

`sw.js` 里有三行注释漏了 `//`，只写了 `: v10 → v11…`。
后果不是「注释格式不好看」——**整个文件语法错误，service worker 没装上过**：

    getRegistrations() → 0
    register() → ServiceWorker script evaluation failed

而 `register-sw.js` 结尾是 `.catch(() => {})`，把这个错完整吃掉，控制台一声不响。
离线外壳没有、PWA 装不上，而 `sw.js` 里每一句关于缓存版本的话都成了空话。

**它是被一次独立审计翻出来的，不是被测试。** 这个仓库有 1786 条判据，
没有一条会读这些文件——它们不进 Python 的导入图，pytest 看不见它们。

一秒钟就能查出来的事，不该等人去看。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
JS_FILES = sorted(p for p in STATIC.rglob("*.js") if "__pycache__" not in p.parts)


def _checker() -> list[str] | None:
    """能用什么查语法。node 优先；没有就退回浏览器。"""
    node = shutil.which("node")
    return [node, "--check"] if node else None


def test_there_are_javascript_files_to_check() -> None:
    """阳性对照：真的扫到了文件。

    没有这一条，`JS_FILES` 为空时下面那条参数化判据会**一个用例都不生成**，
    然后整份文件报绿——而它什么都没测。
    """
    assert len(JS_FILES) >= 10, f"只扫到 {len(JS_FILES)} 个 JS，路径大概是错的：{STATIC}"
    names = {p.name for p in JS_FILES}
    for expected in ("sw.js", "art-cards.js", "elder.js"):
        assert expected in names, f"{expected} 不在扫描结果里"


@pytest.mark.skipif(_checker() is None, reason="这台机器上没有 node")
@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_every_static_javascript_file_parses(path: Path) -> None:
    cmd = [*_checker(), str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    assert proc.returncode == 0, (
        f"{path.relative_to(STATIC)} 语法错误——浏览器会整个文件不执行，"
        f"而如果它的调用方有 catch，你不会看到任何报错：\n"
        f"{(proc.stderr or proc.stdout).strip()[:600]}"
    )


def test_the_service_worker_registration_does_not_swallow_evaluation_errors() -> None:
    """`register-sw.js` 不许把注册失败静默吃掉。

    这一条守的是**为什么上面那个语法错误活了这么久**：
    `.catch(() => {})` 让「service worker 根本没装上」和「一切正常」
    在控制台里完全一样。
    """
    src = (STATIC / "register-sw.js").read_text(encoding="utf-8")
    assert "catch" in src, "没有 catch，注册失败会变成未处理的 rejection"
    # 空的 catch 体：`catch(() => {})` / `catch(e => {})` / `.catch(function(){})`
    empty = ("catch(() => {})", "catch(()=>{})",
             "catch(() => { })", "catch(function () {})")
    for pattern in empty:
        assert pattern not in src.replace(" =>", " =>"), (
            f"`{pattern}` 会把 ServiceWorker 的评估错误完整吃掉。"
            f"至少 console.warn 一句——这个仓库已经因为它损失过一次："
            f"sw.js 语法错误了好几个提交，没有任何地方报过。"
        )
