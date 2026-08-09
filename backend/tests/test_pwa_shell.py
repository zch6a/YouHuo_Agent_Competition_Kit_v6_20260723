"""手机 App 外壳：装到桌面能不能真的当 App 用。

交付的原生端是 HarmonyOS ArkTS；这个 Web 端是同一个产品在手机浏览器上的形态，
装到主屏后没有浏览器界面。这批用例盯住三件容易坏又不容易发现的事：

1. Service worker 必须从站点根提供，否则它的作用域只能覆盖 /static/；
2. **绝不能缓存任何权威数据**——把缓存里的"水费已缴"念给老人听，
   正是这个产品存在的意义所反对的；
3. CSP 仍然严格，PWA 不能成为放宽 script-src 的借口。
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
PAGES = ["index.html", "elder.html", "family.html", "care.html", "trust.html", "judge.html"]


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "pwa.db", demo_mode=True))


# --- serving ---------------------------------------------------------------


def test_manifest_is_served_with_the_right_type(client):
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert "manifest" in response.headers["content-type"]
    manifest = response.json()
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/elder"


def test_service_worker_is_served_from_the_origin_root(client):
    """A worker cannot control a scope above its own path."""
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers.get("Service-Worker-Allowed") == "/"


def test_icons_are_real_pngs_of_the_declared_size():
    manifest = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["icons"], "manifest 没有声明图标"
    for icon in manifest["icons"]:
        path = ROOT / "backend" / icon["src"].removeprefix("/")
        assert path.is_file(), f"缺少图标 {icon['src']}"
        raw = path.read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} 不是 PNG"
        width, height = struct.unpack(">II", raw[16:24])
        assert f"{width}x{height}" == icon["sizes"], f"{path.name} 尺寸与 manifest 声明不符"


def test_a_maskable_icon_is_declared():
    """Android crops to a circle; without a maskable icon the mark gets clipped."""
    manifest = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"])


def test_every_icon_file_is_reachable_over_http(client):
    manifest = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200, icon["src"]
    assert client.get("/static/icons/apple-touch-icon.png").status_code == 200


# --- the cache must never hold authoritative state ------------------------


#: 必须永远走网络的路径，和必须能进外壳缓存的路径。
#:
#: `/v7/*` 单列出来是有来由的：它是生活基线、生活日报、关怀动作和环境采样，也就是
#: 整个个性化基线面。它曾经因为不在 isApi() 的手写版本号列表里而落进
#: stale-while-revalidate ——家属可能被展示昨天的日报，然后被告知一切正常。
MUST_BYPASS_CACHE = [
    "/v2/auth/demo", "/v4/routines", "/v5/actions/authorize", "/v6/tasks/x/glass-box",
    "/v7/baseline/elder-demo", "/v7/daily-report/elder-demo", "/v7/care/elder-demo",
    "/v7/environment/samples", "/v8/anything-a-future-version-adds",
    "/health", "/ping", "/docs", "/openapi.json",
]
MUST_BE_CACHEABLE = [
    "/", "/elder", "/family", "/care", "/trust", "/judge",
    "/static/style.css", "/static/elder.js", "/static/manifest.webmanifest",
    "/static/icons/icon-192.png",
]


def _is_api_matcher():
    """把 sw.js 里 isApi() 真正用的那条正则取出来。

    上一版这个测试写的是 `for prefix in ("v2", "v4", …): assert prefix in source`
    ——全文子串匹配。它无法区分"API 判定覆盖了 /v7"和"文件里某处出现过 v7 这两个
    字符"，事实上 `VERSION = 'youhuo-shell-v2'` 一个字符串就能让 "v2" 那一条永远
    通过。断言这个函数的**行为**，不是它的源码长什么样。
    """
    source = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert re.search(r"function isApi\(url\)", source), "sw.js 里找不到 isApi()"
    body = re.search(r"function isApi\(url\)\s*\{(.*?)\n\}", source, re.S)
    assert body, "isApi() 的函数体解析不出来"
    literal = re.search(r"/(\^.*?)/\.test\(url\.pathname\)", body.group(1))
    assert literal, "isApi() 不再是一条对 url.pathname 的正则判定，这个测试需要跟着改"
    # 这条正则在 JS 和 Python 下语义相同（只有字符类、交替和锚点）。
    return re.compile(literal.group(1))


@pytest.mark.parametrize("path", MUST_BYPASS_CACHE)
def test_service_worker_never_caches_authoritative_state(path):
    assert _is_api_matcher().search(path), f"sw.js 会把 {path} 存进外壳缓存"


@pytest.mark.parametrize("path", MUST_BE_CACHEABLE)
def test_service_worker_still_caches_the_shell(path):
    assert not _is_api_matcher().search(path), f"{path} 被误判成 API，外壳缓存会失效"


def test_service_worker_bails_out_before_responding():
    source = (STATIC / "sw.js").read_text(encoding="utf-8")
    # 直接放行，而不是先缓存再过滤。
    assert re.search(r"if \(isApi\(url\)\) return;", source), "必须在 respondWith 之前直接放行"


def test_shell_covers_every_page_not_just_the_elder_route():
    """外壳只列 elder 一条路线时，断网下另外四页直接白屏。"""
    source = (STATIC / "sw.js").read_text(encoding="utf-8")
    shell = re.search(r"const SHELL = \[(.*?)\];", source, re.S)
    assert shell, "sw.js 里找不到 SHELL"
    listed = set(re.findall(r"'([^']+)'", shell.group(1)))
    for route in ("/", "/elder", "/family", "/care", "/trust", "/judge"):
        assert route in listed, f"外壳没有包含 {route}，断网时这一页会白屏"
    for asset in ("/static/family.js", "/static/care.js", "/static/trust.js", "/static/judge.js"):
        assert asset in listed, f"外壳缓存了页面却没缓存它的脚本：{asset}"


def test_service_worker_only_handles_get_and_same_origin():
    source = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert "request.method !== 'GET'" in source
    assert "url.origin !== self.location.origin" in source


# --- phone-app head tags --------------------------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_page_declares_the_phone_app_viewport(page):
    text = (STATIC / page).read_text(encoding="utf-8")
    # Without viewport-fit=cover every safe-area-inset-* resolves to 0 and the
    # layout sits in the notch on a real phone.
    assert "viewport-fit=cover" in text, f"{page} 缺少 viewport-fit=cover"
    assert 'rel="manifest"' in text, f"{page} 没有引用 manifest"
    assert "apple-mobile-web-app-capable" in text, f"{page} iOS 上不会全屏"
    assert "register-sw.js" in text, f"{page} 没有注册 service worker"


@pytest.mark.parametrize("page", PAGES)
def test_no_inline_script_or_style_survives(page):
    """The CSP is script-src 'self'; an inline block would silently not run."""
    text = (STATIC / page).read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>\s*\S", text), f"{page} 含内联脚本"
    assert "<style" not in text, f"{page} 含内联样式"
    assert not re.search(r'\sstyle="', text), f"{page} 含 style 属性"


def test_csp_is_still_strict(client):
    csp = client.get("/elder").headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp


# --- safe areas and the mobile shell -------------------------------------


def test_stylesheet_uses_safe_areas_and_dynamic_viewport():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "env(safe-area-inset-bottom)" in css, "底部栏会压在手势条上"
    assert "env(safe-area-inset-top)" in css
    assert "100dvh" in css, "100vh 在移动浏览器上高于可见区域"
    assert "overscroll-behavior" in css
    assert "-webkit-tap-highlight-color" in css


def test_reduced_motion_is_still_respected():
    """Motion sensitivity is common in this audience; the shell must not undo it."""
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css
