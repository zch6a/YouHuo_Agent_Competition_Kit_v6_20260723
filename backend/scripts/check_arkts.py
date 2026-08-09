r"""ArkTS 静态检查：在没有 DevEco Studio 的机器上，把编译期才会暴露的错误提前抓住。

这台开发机上没有 HarmonyOS SDK，所以 `harmonyos/` 下的代码无法编译。无法编译不是
"可以不检查"的理由——恰恰相反：没有编译器兜底时，一个拼错的资源名或一个不存在的
图标名会一路活到评委的手机上，而且表现为**静默的空白**而不是报错。

这里检查的每一条，都是官方文档或本项目踩过的真实编译/运行期失败：

1. `$r()` 只接受字面量。`$r(\`sys.symbol.${name}\`)` 是 ArkTS 严格模式的编译错误，
   而它写起来非常自然——本轮就写错过一次。
2. 引用了但没定义的 `app.color.*`：资源找不到时组件按透明/黑色渲染，不报错。
3. 只在 `resources/dark/` 里定义、`base/` 里没有的颜色：浅色模式下解析失败。
   base 是唯一的兜底限定符，dark 只能覆盖不能新增。
4. 不存在的 `sys.symbol.*`：图标位置渲染成空白，同样不报错。官方图标集里
   `photo`/`image`/`sparkles`/`doc_richtext` 这几个常被想当然地用上，它们都不存在。
5. `getContext(this)` 已废弃，应为 `this.getUIContext().getHostContext()`。
6. `main_pages.json` 里登记了但文件不存在的页面：运行时跳转直接白屏。
7. 相对 import 指向不存在的文件。
8. 资源 JSON 里的 UTF-8 BOM：鸿蒙资源编译器和 `json.loads` 都会拒绝它，而
   Windows PowerShell 5.1 的 `Set-Content -Encoding UTF8` **默认就写 BOM**——本轮
   就是这样把 color.json 写坏的。这条检查很便宜，而症状（"资源找不到"）离原因很远。

用法：python backend/scripts/check_arkts.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HM = ROOT / "harmonyos"
ETS_ROOT = HM / "entry" / "src" / "main" / "ets"
RES = HM / "entry" / "src" / "main" / "resources"

# 官方 Symbol 图标集里确认存在的名字（SDK 6.x）。宁可维护一份白名单，也不要让一个
# 拼错的名字变成界面上一块沉默的空白。新增图标时请对照官方图标库补进来。
KNOWN_SYMBOLS = {
    "xmark", "plus", "minus", "checkmark", "chevron_right", "chevron_left",
    "star", "star_fill", "bell", "bell_fill", "doc", "video", "mic", "mic_fill",
    "clock", "trash", "pencil", "camera", "person", "house",
}
# 反复被误用、但官方图标集里并不存在的名字。
ABSENT_SYMBOLS = {"photo", "image", "sparkles", "doc_richtext", "checklist", "location_fill"}


def load_colors(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {entry["name"] for entry in data["color"]}


def main() -> int:
    if not ETS_ROOT.is_dir():
        print("跳过：没有 harmonyos/ 工程")
        return 0

    sources = sorted(ETS_ROOT.rglob("*.ets"))
    problems: list[str] = []

    # 8. BOM 必须最先查，并且查到就立刻返回。
    # 带 BOM 的文件 `json.loads` 直接抛异常，后面每一条依赖解析的检查都会以一个
    # 无关的 traceback 收场——那正是最难从现象反推回原因的失败方式。
    for path in sorted(HM.rglob("*.json")) + sorted(HM.rglob("*.json5")):
        if path.read_bytes().startswith(b"\xef\xbb\xbf"):
            problems.append(
                f"{path.relative_to(ROOT).as_posix()} 带 UTF-8 BOM；"
                "鸿蒙资源编译器会拒绝它（多半是被 PowerShell 的 Set-Content 写坏的）"
            )
    if problems:
        print(f"FAIL check_arkts: {len(problems)} 个问题")
        for item in problems:
            print(f"  {item}")
        return 1

    base_colors = load_colors(RES / "base" / "element" / "color.json")
    dark_colors = load_colors(RES / "dark" / "element" / "color.json")

    # 3. dark 只能覆盖 base，不能新增。
    for name in sorted(dark_colors - base_colors):
        problems.append(
            f"resources/dark/element/color.json 定义了 base 里没有的 '{name}'——"
            "浅色模式下这个资源解析不到"
        )

    for path in sources:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        # 注释里会举反例，去掉后再匹配，否则文档自己会让检查失败。
        code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        code = re.sub(r"^\s*//.*$", "", code, flags=re.M)

        # 1. $r() 里的模板字符串
        for match in re.finditer(r"\$r\(\s*`", code):
            line = code[: match.start()].count("\n") + 1
            problems.append(f"{rel}:{line} `$r()` 用了模板字符串；它只接受字面量")

        # 2. 引用了但没定义的颜色
        for match in re.finditer(r"\$r\(\s*'app\.color\.([A-Za-z0-9_]+)'\s*\)", code):
            name = match.group(1)
            if name not in base_colors:
                line = code[: match.start()].count("\n") + 1
                problems.append(f"{rel}:{line} 引用了未定义的颜色 app.color.{name}")

        # 4. 不存在的系统图标
        for match in re.finditer(r"'sys\.symbol\.([A-Za-z0-9_]+)'", code):
            name = match.group(1)
            line = code[: match.start()].count("\n") + 1
            if name in ABSENT_SYMBOLS:
                problems.append(f"{rel}:{line} sys.symbol.{name} 在官方图标集中不存在")
            elif name not in KNOWN_SYMBOLS:
                problems.append(
                    f"{rel}:{line} sys.symbol.{name} 不在已确认清单里；"
                    "请对照官方图标库确认后加入 KNOWN_SYMBOLS"
                )

        # 5. 已废弃的 getContext
        for match in re.finditer(r"\bgetContext\(\s*this\s*\)", code):
            line = code[: match.start()].count("\n") + 1
            problems.append(
                f"{rel}:{line} `getContext(this)` 已废弃，"
                "应为 `this.getUIContext().getHostContext()`"
            )

        # 7. 相对 import 必须指向真实文件
        for match in re.finditer(r"from\s+'(\.[^']+)'", code):
            target = (path.parent / match.group(1)).resolve()
            if not (target.with_suffix(".ets").is_file() or target.with_suffix(".ts").is_file()):
                line = code[: match.start()].count("\n") + 1
                problems.append(f"{rel}:{line} import 指向不存在的文件 {match.group(1)}")

    # 6. 登记的页面必须存在
    pages_file = RES / "base" / "profile" / "main_pages.json"
    if pages_file.is_file():
        for page in json.loads(pages_file.read_text(encoding="utf-8"))["src"]:
            if not (ETS_ROOT / f"{page}.ets").is_file():
                problems.append(f"main_pages.json 登记了不存在的页面 {page}")

    if problems:
        print(f"FAIL check_arkts: {len(problems)} 个问题")
        for item in problems:
            print(f"  {item}")
        return 1

    print(f"PASS check_arkts: {len(sources)} 个 .ets 文件，"
          f"{len(base_colors)} 个颜色令牌，无问题")
    return 0


if __name__ == "__main__":
    sys.exit(main())
