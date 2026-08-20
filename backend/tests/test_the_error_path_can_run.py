"""失败时说的那句话，自己不许先崩。

## 这道门从哪来

`elder.js` 的三个 catch 分支里写的是：

    remindersEl.textContent = window.YouHuo.window.YouHuo.errorWords(e, '待办').text;

`window.YouHuo.window` 是 `undefined`，再取 `.YouHuo` 当场 TypeError。
也就是说**后端一断，处理器自己先崩**，老人屏幕上一个字都不会出现——
而这三处正是待办、记录、事件经过，老人端三块主数据的失败路径。

三处一模一样，看形状是某次批量加 `window.YouHuo.` 前缀时在已经有前缀的行上
又替换了一次。

## 为什么绿的测试全都看不见它

它只在**请求失败**时才执行。语法检查过（`window.YouHuo.window.YouHuo.x` 是合法
成员表达式），控制台在成功路径上干净，截图正常，点击遍历也不会触发它。
这个仓库已经为同一类事栽过好几次：`node --check` 认证过两个完全死掉的页面。

## 判据

不去猜「哪些前缀是对的」，而是钉住：**每一处 `errorWords(` 的调用前缀，
只能是这一份文件里真的能取到那个函数的那几种写法。**
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"

#: 能真的取到 `errorWords` 的写法，只有这几种：
#:   ''                   文件顶部 `const {errorWords} = window.YouHuo` 解构过
#:   'window.YouHuo.'     全局对象上直接取
#:   'YH.'                `const YH = window.YouHuo` 之后
_OK_PREFIXES = {"", "window.YouHuo.", "YH.", "youhuo."}

_CALL = re.compile(r"([\w.$]*?)\berrorWords\s*\(")


def _js_files() -> list[Path]:
    return sorted(p for p in STATIC.rglob("*.js")
                  if "errorWords" in io.open(p, encoding="utf-8",
                                             errors="replace").read())


def _strip(text: str) -> str:
    """剥注释。这些文件的注释里逐字写着 `window.YouHuo.errorWords`。"""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", text, flags=re.M)


def test_there_are_error_paths_to_check() -> None:
    """先证明这把尺子有刻度。

    这一条不是凑数：`_js_files()` 靠字符串筛文件，改个函数名它就返回空列表，
    下面那条参数化会**一个用例都不生成**然后全绿。
    """
    files = _js_files()
    assert len(files) >= 5, f"只找到 {len(files)} 份用 errorWords 的脚本：{files}"


@pytest.mark.parametrize("path", _js_files(), ids=lambda p: p.name)
def test_every_error_message_can_actually_be_produced(path: Path) -> None:
    """`errorWords(` 前面的那串东西，必须真的能取到这个函数。

    `window.YouHuo.window.YouHuo.errorWords(...)` 语法合法、解析通过、
    只在请求失败时抛 TypeError——而那正是它唯一会被执行的时刻。
    """
    text = _strip(io.open(path, encoding="utf-8").read())
    bad = []
    for m in _CALL.finditer(text):
        prefix = m.group(1)
        if prefix not in _OK_PREFIXES:
            line = text[:m.start()].count("\n") + 1
            bad.append(f"{path.name}:{line} {prefix}errorWords(")
    assert not bad, (
        "这些地方取 `errorWords` 的路径是取不到的：\n  " + "\n  ".join(bad)
        + f"\n  能用的前缀只有：{sorted(_OK_PREFIXES) or '（空前缀 = 解构过）'}\n"
          "  它们只在请求失败时执行，所以语法检查、截图、点击遍历全都看不见——"
          "而那一刻屏幕上本该出现的正是这句话。")
