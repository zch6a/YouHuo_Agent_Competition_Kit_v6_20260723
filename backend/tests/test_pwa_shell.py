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


def test_service_worker_refuses_to_cache_api_responses():
    source = (STATIC / "sw.js").read_text(encoding="utf-8")
    # The guard exists and covers every state-bearing prefix.
    assert "isApi" in source
    for prefix in ("v2", "v4", "v5", "v6", "health"):
        assert prefix in source, f"sw.js 的 API 判定没有覆盖 /{prefix}"
    # And it bails out before responding, rather than caching then filtering.
    assert re.search(r"if \(isApi\(url\)\) return;", source), "必须在 respondWith 之前直接放行"


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
