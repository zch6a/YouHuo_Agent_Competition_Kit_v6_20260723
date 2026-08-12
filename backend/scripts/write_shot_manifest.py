"""给一批截图盖上「它是用哪一版前端拍的」。

上一轮的视觉审查就是对着**改前**的批次做的，两条 P0 颜色结论因此失效——而当时
没有任何东西能看出那批图过期了。这和重型报告那个坑是同一个：
**读一份产物，不等于看到了当前的事实。**

所以每一批截图旁边放一份 manifest，带前端源码指纹。下次审查之前先比一次指纹：
对不上就重拍，别对着旧图下结论。

指纹取 `backend/static` 下所有 `.html/.css/.js/.svg` 的内容——那正是截图长什么样
的全部输入。后端改了不影响像素（数据变化会，但那是另一回事，由 seed 开关控制）。

用法：
    python backend/scripts/write_shot_manifest.py <截图目录> [基址]
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
FRONTEND_SUFFIXES = {".html", ".css", ".js", ".svg", ".webmanifest"}


def frontend_digest() -> tuple[str, int]:
    """`backend/static` 的内容指纹，以及参与计算的文件数。

    文件名也进哈希：只哈希内容的话，改名不会被发现，而改名会换掉页面加载的东西。
    排序后再喂，保证跨平台稳定（目录遍历顺序不保证）。
    """
    hasher = hashlib.sha256()
    files = sorted(
        p for p in STATIC.rglob("*")
        if p.is_file() and p.suffix.lower() in FRONTEND_SUFFIXES
    )
    for path in files:
        hasher.update(path.relative_to(STATIC).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest(), len(files)


def _devices() -> list[str]:
    """设备名从 `shoot_pages.py` 自己的 `VIEWPORTS` 读，不在这里抄一份。

    抄一份就会漂：那边加一档视口，这边解析不了，而这个脚本**照样报 PASS**。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from shoot_pages import VIEWPORTS                            # noqa: PLC0415

    # 长的排前面：`fold-open` 必须先于 `fold`，否则前缀匹配会切错。
    return sorted(VIEWPORTS, key=len, reverse=True)


def parse(name: str, devices: list[str]) -> dict[str, str] | None:
    """从文件名反推 viewport / route / scheme / 变体。

    真实命名是 `<device>-<page>-<scheme>[-full].png`，而**设备名自己带连字符**
    （`narrow-320`、`fold-closed`、`tablet-landscape`），页面还可能是空的
    （`desktop--dark` 就是 `/` 那一条路由）。所以不能 split，只能按已知设备名
    前缀匹配 + 已知配色后缀匹配，中间剩下的才是页面。

    认不出来就返回 `None`，由调用处**报失败**。
    第一版在这里返回 `{"route": "unknown", …}`，结果 252 张全部落进 unknown，
    而脚本照样打印「PASS manifest: 252 张」——一份把猜测写成事实、还宣布自己通过的
    manifest，比没有 manifest 更糟：它看起来是权威的。
    """
    stem = name.removesuffix(".png")
    variant = "full-page" if stem.endswith("-full") else "viewport"
    stem = stem.removesuffix("-full")

    scheme = next((s for s in ("light", "dark") if stem.endswith("-" + s)), None)
    if not scheme:
        return None
    stem = stem[: -(len(scheme) + 1)]

    device = next((d for d in devices if stem == d or stem.startswith(d + "-")), None)
    if device is None:
        return None
    page = stem[len(device):].lstrip("-")
    return {"viewport": device, "route": "/" + page, "scheme": scheme, "variant": variant}


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：write_shot_manifest.py <截图目录> [基址]")
        return 2
    shots = Path(sys.argv[1])
    if not shots.is_dir():
        print(f"FAIL manifest: {shots} 不是一个目录")
        return 1

    images = sorted(shots.rglob("*.png"))
    if not images:
        print(f"FAIL manifest: {shots} 里一张 PNG 都没有——没拍到东西，这不是通过")
        return 1

    digest, file_count = frontend_digest()
    devices = _devices()
    entries, unparsed = [], []
    for image in images:
        meta = parse(image.name, devices)
        if meta is None:
            unparsed.append(image.name)
            continue
        meta["file"] = image.relative_to(shots).as_posix()
        meta["bytes"] = image.stat().st_size
        # 空图是拍失败最常见的表现，而它和"拍到了一个很干净的页面"在目录里长得一样。
        meta["suspect_blank"] = image.stat().st_size < 6000
        entries.append(meta)

    if unparsed:
        print(f"FAIL manifest: {len(unparsed)} 张文件名解析不了，manifest 会是假的：")
        for name in unparsed[:8]:
            print(f"  {name}")
        print("  命名规则变了就改 parse()，不要让它填 unknown 然后报 PASS。")
        return 1

    payload = {
        "frontend_digest": digest,
        "frontend_files_hashed": file_count,
        "shot_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "base_url": sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8041",
        "count": len(entries),
        "shots": entries,
    }
    (shots / "MANIFEST.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    routes = sorted({e["route"] for e in entries})
    viewports = sorted({e["viewport"] for e in entries})
    schemes = sorted({e["scheme"] for e in entries})
    blank = [e["file"] for e in entries if e["suspect_blank"]]

    # 自检：解析出来的维度不能塌成一个。
    #
    # 全部落进同一个值，几乎一定是解析错了而不是真的只拍了一档——而那样的 manifest
    # 看起来完全正常。第一版就是这样报出「1 路由 × 1 视口 × 1 配色」还宣布 PASS 的。
    if len(entries) > 8 and min(len(routes), len(viewports), len(schemes)) < 2:
        print(f"FAIL manifest: {len(entries)} 张图却只解析出 "
              f"{len(routes)} 路由 / {len(viewports)} 视口 / {len(schemes)} 配色"
              "——维度塌了，解析规则和文件名对不上。")
        return 1

    lines = [
        "# 截图批次 manifest",
        "",
        "**审查之前先比指纹。** 对不上说明这批图是用另一版前端拍的——重拍，不要对着它下结论。",
        "（上一轮的视觉审查就是对着改前的批次做的，两条 P0 颜色结论因此失效。）",
        "",
        f"| 前端指纹 | `{digest[:16]}…` |",
        "|---|---|",
        f"| 参与哈希的文件 | {file_count} 个（`backend/static` 下的 html/css/js/svg） |",
        f"| 拍摄时间 | {payload['shot_at']} |",
        f"| 基址 | {payload['base_url']} |",
        f"| 张数 | {len(entries)} |",
        f"| 路由 | {'、'.join(routes)} |",
        f"| 视口 | {'、'.join(viewports)} |",
        f"| 配色 | {'、'.join(schemes)} |",
        "",
    ]
    if blank:
        lines += ["## ⚠ 可疑的空图（< 6 KB）", "",
                  "一张拍失败的图和一张很干净的页面在目录里长得一样，所以这里点名：", ""]
        lines += [f"- `{f}`" for f in blank]
        lines.append("")
    else:
        lines += ["没有可疑空图（全部 ≥ 6 KB）。", ""]

    (shots / "MANIFEST.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"PASS manifest: {len(entries)} 张，指纹 {digest[:16]}…，"
          f"{len(routes)} 路由 × {len(viewports)} 视口 × {len(schemes)} 配色"
          + (f"，**{len(blank)} 张可疑空图**" if blank else ""))
    return 1 if blank else 0


if __name__ == "__main__":
    raise SystemExit(main())
