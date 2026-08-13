r"""Service worker 的外壳清单必须覆盖每一个被 import 的模块。

## 这道闸门是补一个真实的漏洞，不是预防性的

`task-space.js` 是这个会话里加的，`elder.js` 用 `import` 拉它。它**从加进来那一刻
起就不在 `sw.js` 的 SHELL 里**，而整套测试（1289 条）没有一条抓到。

后果不是"少一个功能"。`elder.js` 是 `type="module"`，而 ES module 的 import 失败会让
**整个模块图不执行**——离线时老人端不是降级，是白屏。而这个 worker 的存在理由，
按 `sw.js` 自己的注释，正是"移动数据下也能用"。

`sw.js` 里那条注释还记着同一个错误的上一次：「上一版只列了 elder 一条路线，
family/care/trust/judge/index 及其脚本都不在里面，断网时那四页直接白屏」。
修过一次，没有留下守它的东西，于是它以新模块的形式回来了。

## 判据

从 `backend/static` 的每个 `.js` 里抽 `from '/static/x.js'`，再抽每个 HTML 的
`<script src="/static/x.js">`，两者的并集都必须出现在 SHELL 里。
按**图的传递闭包**取——A import B、B import C，C 也得在。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
SW = STATIC / "sw.js"

IMPORT_RE = re.compile(r"""(?:from|import)\s*\(?\s*['"]/static/([A-Za-z0-9_.-]+\.js)['"]""")
SCRIPT_RE = re.compile(r"""<script[^>]*\ssrc=['"]/static/([A-Za-z0-9_.-]+\.js)['"]""")


def _shell_entries() -> set[str]:
    """SHELL 数组里的 `/static/*.js`。

    只在 `const SHELL = [` 到它的 `];` 之间找——`sw.js` 别处也出现路径字面量
    （`isApi()` 的判断、注释里的例子），把整个文件当输入会让这道闸门在
    「清单里没有但文件里提到过」的情况下误判为通过。
    """
    source = SW.read_text(encoding="utf-8")
    block = re.search(r"const SHELL = \[(.*?)\n\];", source, re.S)
    assert block, "sw.js 里找不到 `const SHELL = [...]`——结构变了，这道闸门要跟着改"
    return set(re.findall(r"'/static/([A-Za-z0-9_.-]+\.js)'", block.group(1)))


def _imported_modules() -> dict[str, set[str]]:
    """每个 js/html 文件 → 它引用的 `/static/*.js`。"""
    refs: dict[str, set[str]] = {}
    for path in sorted(STATIC.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        refs[path.name] = set(IMPORT_RE.findall(text))
    for path in sorted(STATIC.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        refs[path.name] = set(SCRIPT_RE.findall(text))
    return refs


def _reachable_from_pages() -> set[str]:
    """从每个 HTML 出发，按 import 图取传递闭包。

    传递闭包而不是一层：A import B、B import C 时，C 一样会被浏览器请求，
    漏了它照样白屏。
    """
    refs = _imported_modules()
    seen: set[str] = set()
    queue = [m for name, targets in refs.items() if name.endswith(".html")
             for m in targets]
    while queue:
        module = queue.pop()
        if module in seen:
            continue
        seen.add(module)
        queue.extend(refs.get(module, set()))
    return seen


def test_the_scan_found_the_import_graph() -> None:
    """先证明扫到了东西。

    一个"跑了但一条 import 都没找到"的检查，和没有这个检查一样绿。
    实测 `elder.js` 至少 import 三个模块（glassbox / task-space / task-detail）。
    """
    refs = _imported_modules()
    assert refs.get("elder.js"), "elder.js 一个 import 都没扫到——正则或路径写法变了"
    assert len(refs["elder.js"]) >= 3, (
        f"elder.js 只扫到 {refs['elder.js']}，预期至少三个"
    )
    assert _reachable_from_pages(), "从 HTML 出发一个模块都到不了"


@pytest.mark.parametrize("module", sorted(_reachable_from_pages()))
def test_the_shell_covers_every_module_it_imports(module: str) -> None:
    shell = _shell_entries()
    assert module in shell, (
        f"`{module}` 被页面（直接或间接）import，但不在 sw.js 的 SHELL 里。\n"
        "ES module 的 import 失败会让**整个模块图不执行**——离线时那一页白屏，"
        "不是少个功能。\n"
        "把 '/static/" + module + "' 加进 SHELL，**并且升 VERSION**："
        "不升的话已安装的设备会继续用旧清单。"
    )


def test_every_module_in_the_shell_actually_exists() -> None:
    """反方向：SHELL 里列的文件必须真的在。

    `cache.add()` 的失败被 `.catch(() => {})` 吞掉了（那是对的——一个文件缺失
    不该让整个 install 失败），于是清单里一个拼错的名字**完全无声**。
    """
    missing = [m for m in _shell_entries() if not (STATIC / m).exists()]
    assert not missing, (
        f"SHELL 里这些文件不存在：{missing}。"
        "`cache.add()` 的失败被 catch 吞掉了，所以拼错名字不会有任何报错。"
    )


def test_the_version_string_changed_when_the_shell_did() -> None:
    """外壳清单变了就得升 VERSION，这一条用注释里的记录钉住。

    `activate` 只删除 key ≠ VERSION 的缓存。清单变了而 VERSION 没变，
    已安装的设备会一直用旧清单——而这正是 `sw.js` 顶部那段注释记下的上一次教训
    （v7 的 `/v7/*` 污染条目）。

    判据只能是弱的（无法从静态文件知道"清单是否刚变过"），所以钉住两件可查的事：
    VERSION 是 `youhuo-shell-vN` 的形状，且 N 至少到了引入这两个模块的那一版。
    """
    source = SW.read_text(encoding="utf-8")
    match = re.search(r"const VERSION = 'youhuo-shell-v(\d+)'", source)
    assert match, "VERSION 不是 `youhuo-shell-vN` 的形状了"
    assert int(match.group(1)) >= 9, (
        f"VERSION 是 v{match.group(1)}，但 task-space.js / task-detail.js 是在 v9 "
        "才进外壳清单的。低于 v9 意味着已安装的设备拿不到这两个模块。"
    )
