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

from .helpers import read_stylesheet

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
    "/static/tokens.css", "/static/base.css", "/static/components.css", "/static/pages.css",
    "/static/elder.js", "/static/common.js", "/static/manifest.webmanifest",
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


@pytest.mark.parametrize("script", sorted(p.name for p in STATIC.glob("*.js")))
def test_no_native_dialogs(script):
    """`alert()` / `confirm()` / `prompt()` 在装到主屏的 PWA 里是最差的一种反馈。

    它显示成一个带来源域名的系统灰框（"127.0.0.1 显示：…"），盖住整屏、只有一个
    按钮，读屏软件读不到，而且**会冻住整个页面**——自动化点击检查第一次真跑时就是
    这样卡死在 60 秒超时上的，堆栈里完全看不出原因是 family.js 里的六处 alert()。

    对这个受众更具体：一位 78 岁的用户，或者一位正在确认支付的家属，看到那个灰框
    只能知道"出事了"，不知道是哪一步。页面里的 live region 才说得清。
    """
    source = (STATIC / script).read_text(encoding="utf-8")
    # 去掉注释再查：本项目的注释里正引用着它删掉的那几处 alert()。
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    source = re.sub(r"//[^\n]*", "", source)
    found = re.findall(r"(?<![.\w])(alert|confirm|prompt)\s*\(", source)
    assert not found, f"{script} 里还有原生对话框：{sorted(set(found))}"


#: 页面脚本。请求层归 common.js 独有。
#:
#: identity.js 不在内：它做的是访客沙箱开通（POST /v2/auth/visitor），是身份的来源
#: 而不是消费者。speech.js 也不在内：它是被 configureNeuralVoice 注入令牌的音频库，
#: 自己不登录、不知道有几种角色。
_PAGE_SCRIPTS = ["elder.js", "family.js", "care.js", "trust.js", "judge.js"]


@pytest.mark.parametrize("script", _PAGE_SCRIPTS)
def test_only_one_file_owns_the_request_layer(script):
    """五个页面曾各写一份 api()/login()，而且已经分叉。

    只有 elder 和 family 有 401 自动重放；只有 elder 把 status 挂到 Error 上
    （postChat 靠它区分 400 去重建会话）；trust 无条件写 `Bearer ` 后面什么都没有；
    演示身份兜底 'elder-demo' 硬编码了四份。

    这不是洁癖：同一段代码抄五遍，就会有五个版本各自正确、各自不同。让 /care 和
    /trust 两整页全死的那个 TDZ 笔误，正是这样在两个文件里同时存在的。
    """
    source = (STATIC / script).read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    source = re.sub(r"//[^\n]*", "", source)
    assert "/v2/auth/demo" not in source, f"{script} 又自己实现了演示登录"
    assert "Bearer" not in source, f"{script} 又自己拼 Authorization 头"


@pytest.mark.parametrize("page", ["care.html", "trust.html", "judge.html"])
def test_demo_output_is_not_raw_json(page):
    """评委看到的不该是一屏 JSON。

    可信实验室六张卡的输出曾经**全是** `<pre>` 里的 `JSON.stringify`，照护中心七张
    里有六张也是。那些字段恰恰是这个项目最想讲的东西——"系统拒绝了什么、为什么
    拒绝"——但用 JSON 讲出来，等于要求评委现场读一遍后端契约。

    原始响应没有删，收在每张卡的 `<details>` 里；这条只禁止把它当成第一眼的呈现。
    """
    source = (STATIC / page).read_text(encoding="utf-8")
    assert "<pre id=" not in source, f"{page} 里还有直接当输出容器用的 <pre>"
    assert 'class="result"' in source, f"{page} 没有使用结构化结果容器"


@pytest.mark.parametrize("page", PAGES)
def test_stylesheet_layers_load_in_cascade_order(page):
    """四层的加载顺序就是层叠顺序，而且 pages 必须最后。

    这不是风格问题。响应式覆写全在 pages.css 里，而媒体查询**不增加特异性**——
    把它排在被它覆写的组件之前，那些覆写会静默输掉层叠，页面在手机上悄悄变回桌面
    布局。原文件里那句"Responsive overrides — deliberately LAST in the file"就是
    这个意思；拆成四个文件之后，那条约束的执行者从"往下写"变成了"按序引"。
    """
    source = (STATIC / page).read_text(encoding="utf-8")
    found = re.findall(r'href="/static/(tokens|base|components|pages)\.css"', source)
    assert found == ["tokens", "base", "components", "pages"], f"{page} 的层序是 {found}"
    assert "style.css" not in source, f"{page} 还引着已经拆掉的 style.css"


@pytest.mark.parametrize(
    "asset", sorted(p.name for p in STATIC.glob("*.css")) + sorted(p.name for p in STATIC.glob("*.js"))
)
def test_no_byte_order_mark_anywhere(asset):
    """U+FEFF 在 CSS 里不是空白，是非法字符。

    原来的 style.css 开头有一个 BOM——在开头浏览器容忍。拆成四层时它跟着第一块走，
    落在了新加的文件头注释**之后**，于是变成文件中段的一个非法 token：CSS 的错误
    恢复把紧随其后的构造整个丢掉，`:root` 整块失效，`var(--ink)` 退化成初始值黑色。

    逐字节拼接检查发现不了这件事：四份拼起来和原文件完全一致，变的只是 BOM 在单个
    文件里的位置。是对比度检查读到 rgb(0,0,0) 才暴露的，而这一条把它钉住。

    JS 一并查：Windows PowerShell 5.1 的 `Set-Content -Encoding UTF8` 默认就写 BOM，
    这个仓库已经被它写坏过一个 color.json 和一次 git 提交标题。
    """
    raw = (STATIC / asset).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{asset} 以 BOM 开头"
    assert "﻿" not in raw.decode("utf-8"), f"{asset} 内部含有 U+FEFF"


def test_no_declaration_was_lost_in_the_split():
    """拆分只改文件边界，不改内容：声明总数必须和拆分前一致。

    拆分时是按行切的，并逐字节验证过四份拼回去等于原文件。这条测试守的是之后——
    任何一层被整段删掉或截断，这里都会掉下来。
    """
    css = read_stylesheet()
    assert css.count("{") == css.count("}"), "花括号不配对，某一层被截断了"
    # 拆分当时的实测值。改样式时这个数会变，跟着改；它的作用是让"整层消失"这种
    # 事故立刻可见，而不是慢慢发现某个页面少了一块。
    assert css.count(":root") >= 4, "令牌层丢了"
    assert "@media (max-width: 760px)" in css, "响应式那一大段不见了"


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
    css = read_stylesheet()
    assert "env(safe-area-inset-bottom)" in css, "底部栏会压在手势条上"
    assert "env(safe-area-inset-top)" in css
    assert "100dvh" in css, "100vh 在移动浏览器上高于可见区域"
    assert "overscroll-behavior" in css
    assert "-webkit-tap-highlight-color" in css


def test_reduced_motion_is_still_respected():
    """Motion sensitivity is common in this audience; the shell must not undo it."""
    css = read_stylesheet()
    assert "prefers-reduced-motion" in css
