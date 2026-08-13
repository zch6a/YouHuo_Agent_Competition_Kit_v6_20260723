"""向本机（127.0.0.1）发 HTTP 请求，**绕开系统代理**。

## 为什么需要这个文件

这台机器上有 `HTTP_PROXY=http://127.0.0.1:7897`。`NO_PROXY` 里写了 `127.0.0.1`，
所以「应该」被绕开——但实测不是这样：

    服务器已经打印 `Uvicorn running on http://127.0.0.1:54567`
    而 wait_for_server 连打 15 次 /ping 全部 `urlopen error timed out`
    **服务器自己的日志里一条请求都没有**——请求根本没到它这儿
    第 16 次才通

也就是说那些请求被送去了代理、在那里挂到超时。而各个脚本的等待循环普遍是
「40s 上限、每次 2s 超时 + 0.5s 间隔」≈ 16 次，**正好卡在这个边界上**。
于是同一道闸门时绿时红，而它报出来的话是「服务未能启动」——把**代理配置**
说成**服务器起不来**。2026-08-14 这一天整条验证链两次报红都是它，两次都不是代码问题。

顺带说明为什么不是「把超时调大」：那只是把运气的窗口放宽，抖动还在。
`ProxyHandler({})` 是确定性的——它明确声明这一路不走任何代理。

## 用法

    from localhttp import open_local
    with open_local(f"{BASE}/ping", timeout=2) as response: ...

接受 URL 字符串或 `urllib.request.Request`，其余行为和 `urlopen` 一样。

**新写向 127.0.0.1 发请求的脚本一律用这个，不要直接用 `urllib.request.urlopen`。**
CDP 的 `/json/version`、`/json/list` 也算——它们同样是本机 HTTP。
"""

from __future__ import annotations

import urllib.request
from typing import Any

#: 一个不带任何代理的 opener。模块级只建一次。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def open_local(url_or_request: Any, timeout: float = 10.0, data: bytes | None = None):
    """`urlopen` 的替代品，只是保证不走代理。"""
    if data is not None:
        return _OPENER.open(url_or_request, data, timeout=timeout)
    return _OPENER.open(url_or_request, timeout=timeout)
