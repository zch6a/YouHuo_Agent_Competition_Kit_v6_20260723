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
import urllib.parse
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
    # 裸调用。`(?<![.\w])` 排除掉带点的接收者，本意是别把 `obj.prompt(...)` 这种
    # 同名方法当成原生对话框。
    found = re.findall(r"(?<![.\w])(alert|confirm|prompt)\s*\(", source)
    # 但那条反向断言把**全局对象上的**调用一起放过了，而它们冻页面的效果一模一样：
    #   window.alert('缴费失败') / globalThis.confirm(...) / self.prompt(...)
    #   window['alert'](...) —— 方括号形式连函数名都不在正则视野里
    # 四种写法此前全部通过。这一条守的是"这个受众看到系统灰框只知道出事了"，而不是
    # "源码里不许出现某五个字符"。
    _GLOBAL = r"(?:window|globalThis|self|top|parent)"
    found += re.findall(rf"\b{_GLOBAL}\s*\.\s*(alert|confirm|prompt)\s*\(", source)
    found += re.findall(
        rf"""\b{_GLOBAL}\s*\[\s*['"](alert|confirm|prompt)['"]\s*\]""", source
    )
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
    # 大小写不能敏感：RFC 7235 的 auth-scheme 是大小写不敏感的，`'bearer ' + tok`
    # 这个头照样工作，而原来那条大小写敏感的子串断言看不见它。
    assert "bearer" not in source.lower(), f"{script} 又自己拼 Authorization 头"


#: 有"按一下看响应"这种卡片的页面。`care.html` 和 `trust.html` 不再在这个名单里：
#: 那些卡片整体搬到了 `/stage`（照护页现在进页面就加载，可信页只剩一份凭证），
#: 而不是它们的输出变回了 `<pre>`。
RESULT_PAGES = ["stage.html", "judge.html"]


@pytest.mark.parametrize("page", RESULT_PAGES)
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


def test_the_phone_frame_has_no_press_a_button_to_see_a_response_cards():
    """反向：手机框里不许再出现"按一下看响应"这种卡片。

    上面那条断言只说 `/stage` 和 `/judge` 得用结构化容器。它不阻止有人把一张
    `<div class="result">` 加回照护页——那正是这一轮花了 17531 个字符搬出去的东西。

    `.result` 是这类卡片的唯一标记（common.js 的 renderResult 往它里面写），
    所以它在四个 App 页面里出现一次就是一次回流。
    """
    for page in ("elder.html", "family.html", "care.html", "trust.html"):
        source = (STATIC / page).read_text(encoding="utf-8")
        source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
        assert 'class="result"' not in source, (
            f"{page} 里又出现了「按一下看响应」的输出容器。手机框里只放产品——"
            "这种卡片属于 /stage 的「演示」「证明」「工程」三层。"
        )


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
    # 逐层要有下限。
    #
    # 上面那三条断言在**整层被删掉**时全都还成立：把 components.css 清空，花括号仍然
    # 配对（它自己也配对）、`:root` 那四个全在 tokens.css、那条 media 在 pages.css。
    # 而这条测试的 docstring 说的就是"任何一层被整段删掉，这里都会掉下来"——它守的
    # 意图是对的，判据不到位。现在按层数声明。
    #
    # 数字是当前实测的保守下限（真实值分别约为 78 / 63 / 470 / 480），改样式时不会
    # 频繁碰到；它的作用是让"这一层没了"立刻可见。
    for layer, floor in (("tokens.css", 60), ("base.css", 40),
                         ("components.css", 300), ("pages.css", 300)):
        raw = (STATIC / layer).read_text(encoding="utf-8")
        body = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
        count = len(re.findall(r"[-a-zA-Z]+\s*:\s*[^;{}]+(?=[;}])", body))
        assert count >= floor, f"{layer} 只剩 {count} 条声明（下限 {floor}）——这一层被删了吗？"


#: 老人端与家属端是真实产品，不是工程演示。这些词不得出现在它们的可见文本里。
#:
#: 老人不需要知道什么是 Saga、什么是目的绑定策略，也不该在首屏看到「演示挂号」。
#: 这些概念属于 /trust 和 /judge——那是另一个世界，给要求看清边界的人看的。
_ENGINEERING_WORDS = [
    "Saga", "N-best", "OpenAPI", "dry-run", "dry run",
    "目的绑定", "自主权包络", "证明式完成", "C4-AI",
]


@pytest.mark.parametrize("page", ["index.html", "elder.html", "family.html"])
def test_no_demo_scaffolding_on_the_consumer_first_screen(page):
    """按钮上的字必须是用户想做的事，不是"这是一个演示"。

    `elder.html` 曾在首屏放三个按钮，标签的字面就是「演示挂号」「演示缴费」
    「演示提醒」——演示脚手架留在了产品里。而同一个文件下面抽屉里那四个反而是对的
    写法（「我今天吃药了吗」），是老人真会说的话。两种做法在同一页并存，说明前者是
    没清理干净的东西。
    """
    source = (STATIC / page).read_text(encoding="utf-8")
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)      # 注释里会引用旧标签
    labels = re.findall(r"<button[^>]*>(.*?)</button>", source, re.S)
    offenders = [
        re.sub(r"<[^>]+>", "", label).strip()
        for label in labels
        if "演示" in re.sub(r"<[^>]+>", "", label)
    ]
    assert not offenders, f"{page} 的按钮上还有演示脚手架：{offenders}"


@pytest.mark.parametrize("page", ["index.html", "elder.html", "family.html"])
def test_no_engineering_vocabulary_in_the_consumer_pages(page):
    source = (STATIC / page).read_text(encoding="utf-8")
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    found = [word for word in _ENGINEERING_WORDS if word in source]
    assert not found, f"{page} 出现了工程术语：{found}"


def test_the_family_page_never_prints_a_raw_event_code():
    """家属看到的是"谁做了什么"，不是一条能 grep 的日志。

    `/family` 的操作记录原先直接把审计事件码和执行者 id 印出来：
    `FAMILY_APPROVED_AND_EXECUTED`、`system-vc8693dfcd970`、`DEMO_LOGIN`。那是
    工程标识，属于可信中心，不属于一个来看爸爸今天怎么样的人。

    这一条钉的是**渲染代码**而不是页面文本：事件码是运行时才从接口来的，静态
    HTML 里根本不会出现，只查 HTML 等于什么都没查。所以查的是"family.js 有没有
    把 event_type / actor_id 直接写进 textContent"。
    """
    js = (STATIC / "family.js").read_text(encoding="utf-8")
    body = re.sub(r"//.*", "", js)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    assert "actorName(" in body and "auditLabel(" in body, "翻译层不见了"
    # 把三种**正当**用法先剪掉：翻译函数的入参，和查表的下标。剩下的每一处
    # `.event_type` / `.actor_id` 都是原始码在往界面上走。
    body = re.sub(r"\b(?:actorName|auditLabel)\([^()]*\)", "«译»", body)
    body = re.sub(r"\b[A-Z_]+\[[^\]]*\.event_type\]", "«查表»", body)
    leaks = re.findall(r".{0,40}\.(?:event_type|actor_id).{0,20}", body)
    assert not leaks, f"家人端把原始事件码印给了家属：{leaks}"


@pytest.mark.parametrize("page,least", [("family.html", 4), ("care.html", 5)])
def test_every_section_button_has_a_panel_to_show(page, least):
    """页内分区：几个按钮，几块内容，一一对应。

    分区靠 `hidden` 切换。一个按不出任何东西的分区按钮不会报错、不会在截图里
    露馅——它只会让人点一下，然后什么也没发生。

    两页参数化而不是各写一份：它们共用 common.js 的 `initSections`，也共用
    `check_page_runtime` 里"`.seg` 会换屏、留到最后按"那条规则。哪天有人给第三页
    加分区却换了一套类名，那条规则会静默漏掉它，而检查照样报绿。
    """
    source = (STATIC / page).read_text(encoding="utf-8")
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    sections = re.findall(r'class="seg[^"]*"[^>]*data-section="([a-z]+)"', source)
    sections += re.findall(r'data-section="([a-z]+)"[^>]*class="seg[^"]*"', source)
    panels = re.findall(r'data-panel="([a-z]+)"', source)
    assert len(sections) >= least, f"{page} 的分区按钮少于 {least} 个：{sections}"
    assert sorted(set(sections)) == sorted(set(panels)), f"按钮 {sections} 与内容 {panels} 对不上"
    # 恰好一个分区默认展开，否则首屏会同时铺开两段。
    #
    # 判据必须是 `hidden` **这个属性**，不是子串 "hidden"：`aria-hidden="true"` 里也含
    # 它，于是把第二个分区的 `hidden` 换成 `aria-hidden="true"` 就能骗过这一条——首屏
    # 同时铺开两段，而 `aria-hidden` 只对读屏隐藏、视觉上照样在。
    open_panels = [
        tag for tag in re.findall(r"<section[^>]*data-panel=[^>]*>", source)
        if not re.search(r"(?<![-\w])hidden(?=[\s/>=])", tag)
    ]
    assert len(open_panels) == 1, f"{page} 默认展开的分区不是一个：{len(open_panels)}"


@pytest.mark.parametrize(
    "page", ["index.html", "elder.html", "family.html", "care.html", "trust.html", "judge.html"]
)
def test_no_page_labels_itself_with_all_caps_english(page):
    """`.eyebrow` 里不许是一串大写英文加版本号。

    六个页面里有五个曾经这样开场：`C4-AI · HARMONYOS AGENT INNOVATION · V6.0`、
    `YOUHUO FAMILY CONSOLE · V6.0`、`YOUHUO CARE HUB · V4.0`、
    `YOUHUO TRUST LAB · V5.0`、`YOUHUO FINALIST WALKTHROUGH · V6.0`，加上评委页末尾
    一个 `ONE SENTENCE`。这些是产品自我介绍的位置，而它被赛事元数据占了——一个中文
    用户看到的第一行字，读不出任何意思。

    `.eyebrow` 本身是有用的：它现在承载每一步的论点（「老人表达不标准，也不能让系统
    猜」）。所以这一条不禁 `.eyebrow`，只禁"纯大写 ASCII"这一种内容。
    """
    source = (STATIC / page).read_text(encoding="utf-8")
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    # 判据不能挂在 `.eyebrow` 这个类上。
    #
    # 重构把 `.eyebrow` 全部移到了 judge.html，于是这条为六页参数化的规则在另外五页上
    # `re.findall` 返回空列表、for 体一次都不执行——**实际只守一页**，而它列名的五个
    # 违规样本恰好都在那五页上。而且原正则要求 class 值恰好是 `eyebrow`，
    # `class="eyebrow foo"` 也会漏掉。
    #
    # 现在查的是"任何一段可见文本是不是纯大写 ASCII 标语"，与它用什么类无关。
    body = re.search(r"<body[^>]*>(.*)</body>", source, re.S)
    text_only = re.sub(r"<[^>]+>", "\n", body.group(1) if body else source)
    offenders = [
        line.strip() for line in text_only.splitlines()
        if len(line.strip()) >= 8
        and re.fullmatch(r"[A-Z0-9 ·.·\-–—/&+]+", line.strip())
        # 单个全大写英文词（OPENAPI、SOS）不是标语；连着两个词才是。
        and len(line.strip().split()) >= 2
    ]
    assert not offenders, f"{page} 用一串大写英文介绍自己：{offenders}"


def test_every_manifest_shortcut_actually_does_something():
    """manifest 里的快捷方式必须真的做到它承诺的事。

    「找无忧伴聊聊」指向 `/elder?mode=companion`——长按主屏图标直接进陪伴模式。而
    全站曾经**没有任何地方读这个参数**：点它落到普通首页，和主图标毫无区别。
    快捷方式承诺了一个不存在的功能，而这是评委最可能顺手试的一个入口。

    这一条查的是"参数有人读"，读得对不对由 `probe_shortcut` 在真浏览器里验（模式
    切换是运行时行为，静态文件里看不出差别）。
    """
    manifest = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    shortcuts = manifest.get("shortcuts", [])
    assert shortcuts, "manifest 没有快捷方式"
    scripts = "\n".join(
        (STATIC / name).read_text(encoding="utf-8")
        for name in ("elder.js", "family.js", "landing.js", "common.js")
    )
    for item in shortcuts:
        query = urllib.parse.urlparse(item["url"]).query
        for key in urllib.parse.parse_qs(query):
            assert f"'{key}'" in scripts or f'"{key}"' in scripts, (
                f"快捷方式「{item['name']}」带的参数 {key}= 全站没有人读——"
                "它承诺了一个不存在的功能"
            )


def test_visitor_provisioning_is_serialised_across_tabs():
    """开通访客家庭必须跨标签页互斥。

    `provision()` 的 memo 是 document 级的。两个标签页同时冷启动，各自 POST
    /v2/auth/visitor，服务端得到**两个不同的 family_id**；localStorage 后写覆盖先写，
    而两个标签页的内存常量和 sessionStorage 令牌各自指向自己那一个。后果不是"多了
    一个家庭"：女儿在家属端批准的高风险动作写进家庭 B，老人端在家庭 A，家庭接力
    永远等不到——表现是"点了批准，老人端没反应"。

    这条只查**形状**：锁在不在、降级路径在不在。"两个标签页真的落在同一个家庭"
    是运行时性质，由 `check_page_runtime.py` 的 `check_multi_tab_identity` 真开两个
    标签页验——变异测过：把 `if (navigator.locks?.request)` 改成 `if (false)`，
    子串断言照样绿（`navigator.locks` 在这个文件里出现两次），只有跑起来才看得出。
    """
    source = (STATIC / "identity.js").read_text(encoding="utf-8")
    body = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", source, flags=re.S))
    guard = re.search(r"if \(navigator\.locks\??\.?\w*\)?", body)
    assert guard, "开通没有跨标签页互斥的入口"
    assert "navigator.locks.request(" in body, "拿到了判断却没有真的申请锁"
    # 降级路径也要在：拿到锁之后必须再查一次缓存，否则无 Web Locks 的环境照旧双开。
    once = re.search(r"async function provisionOnce\(.*?\n\}", body, re.S)
    assert once, "provisionOnce 不见了"
    assert once.group(0).count("readCached()") >= 2, (
        "开通之后没有再查一次缓存——另一个标签页刚写好的身份会被覆盖"
    )


def test_the_today_line_counts_only_today():
    """「今天有 N 件事」里的 N 必须真的是今天的件数。

    这一行原先统计的是**全部**未完成待办：三条待办（今天 16:00 复诊、8 月 19 日体检、
    9 月 4 日缴水费）渲染成"今天有 3 件事"，而今天只有一件。把今天那条办掉之后更荒唐
    ——"今天有 2 件事 · 下一件 8月19日 09:00 体检"，标题说今天，紧接着自己报了一个
    九天后的日期。`/v2/reminders` 没有按日筛选的参数，所以筛选必须在前端做。

    钉渲染代码而不是页面文本：这一行的内容运行时才从接口来，静态 HTML 里只有一个
    空的 `<p hidden>`，查 HTML 等于什么都没查。
    """
    js = (STATIC / "elder.js").read_text(encoding="utf-8")
    body = re.sub(r"//.*", "", js)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    render = re.search(r"function renderTodayLine\(.*?\n\}", body, re.S)
    assert render, "renderTodayLine 不见了"
    inner = render.group(0)
    assert "isToday" in inner, "「今天有 N 件事」没有按日筛选"
    # 计数用的必须是筛过的那个数组，不是全部未完成的 open。
    count = re.search(r"今天有 \$\{(\w+)\.length\}", inner)
    assert count, "找不到那句「今天有 N 件事」"
    assert count.group(1) != "open", f"N 取自未筛选的 {count.group(1)}.length"

    # isToday 必须按本地日期比，不能用 toISOString/getUTC*——那会在 UTC+8 把一天
    # 切在早上八点，和后端 baseline_api 的 _local_today 打架。
    helper = re.search(r"function isToday\(.*?\n\}", body, re.S)
    assert helper, "isToday 不见了"
    assert "getUTC" not in helper.group(0) and "toISOString" not in helper.group(0), \
        "isToday 用了 UTC 字段，等于把一天切在早上八点"


def test_relative_dates_are_resolved_in_the_elders_timezone():
    """老人说的"今天/明天"是**他所在时区**的今天和明天。

    两个调用点原先传的是 `clock.now().date()`，也就是 UTC 的日期。在 UTC+8，每天
    00:00–08:00 这八小时里 UTC 还停在前一天：老人早上七点说"提醒我明天上午九点吃药"，
    解析出来是今天，提醒早一天。同一个仓库里 `baseline_api` 的 `_local_today` 早就
    按 Asia/Shanghai 算了——v7 日报的"今天"和 v2 提醒的"今天"是两个不同的日子。
    """
    engine = (ROOT / "backend/youhuo/engine.py").read_text(encoding="utf-8")
    body = re.sub(r"#.*", "", engine)
    leaks = re.findall(r".{0,50}clock\.now\(\)\.date\(\).{0,20}", body)
    assert not leaks, f"engine 还在用 UTC 的日期当\"今天\"：{leaks}"
    assert "local_today" in body, "engine 没有引用本地日期"

    utils = (ROOT / "backend/youhuo/utils.py").read_text(encoding="utf-8")
    assert "LOCAL_TIMEZONE" in utils and "def local_today" in utils, "本地时区助手不见了"
    # combine_date_time 必须带上偏移，否则调用方又会去 replace(tzinfo=UTC)。
    # 取到下一个顶层 def 或文件末尾。`.*?\n\n` 会在 docstring 里的空行就停下——
    # 那样断言只看到函数签名和第一行文档，永远失败（第一次写就是这样）。
    combine = re.search(r"def combine_date_time\(.*?(?=\ndef |\Z)", utils, re.S)
    assert combine and "tzinfo=local_zone()" in combine.group(0), \
        "combine_date_time 又回到了无时区的裸串"
    services = (ROOT / "backend/youhuo/services.py").read_text(encoding="utf-8")
    assert "combine_date_time(due_date, due_time)).replace(tzinfo=UTC)" not in services, \
        "又把老人说的墙上时间盖成了 UTC"


def test_judge_steps_report_failures_where_the_user_clicked():
    """每一步失败时，错误要写进那一步自己的输出区，不只是页面顶部的状态行。

    原先五个处理器都是 `.catch(e => statusEl.textContent = e.message)`。状态行在页面
    顶部，而评委的眼睛在他刚点的那个按钮上——于是一次失败的观感是"点了没反应"。

    顺带把 `.onclick =` 换成 `addEventListener`：这些按钮写在 judge.html 里，
    `.onclick` 是覆盖而不是叠加，哪天有人再挂一件事，先挂的那件会无声消失。
    （elder.js / family.js 里剩下的 `.onclick` 是在刚 createElement 的按钮上赋值，
    那里没有既有处理器可覆盖，不算同一件事。）

    五步改成七拍之后，绑定从 `STEPS.forEach` 换成了按 `[data-run]` 遍历，落点表
    换成了 `BEATS`。这条断言跟着改，守的性质一个字没变：**每一拍都要有自己的落点，
    而失败要写到那里去**。原先钉的是"存在一个叫 STEPS.forEach 的东西"——那是在钉
    实现的形状，不是钉性质；换个写法它就红，而红的原因和用户看到什么无关。
    """
    js = (STATIC / "judge.js").read_text(encoding="utf-8")
    body = re.sub(r"//.*", "", js)
    assert ".onclick" not in body, "judge.js 又用回了 .onclick ="
    assert body.count("addEventListener('click'") >= 1, "没有一拍挂上 click"

    # 每一拍都要在落点表里登记一个自己的输出区，而且七拍一个都不能少。
    beats = re.search(r"const BEATS = \[(.*?)\];", body, re.S)
    assert beats, "找不到七拍的落点表"
    outs = re.findall(r"'(#[\w-]+)'\]", beats.group(1))
    assert len(outs) == 7, f"落点表里只有 {len(outs)} 个输出区：{outs}"
    assert len(set(outs)) == 7, f"有两拍共用同一个输出区：{outs}"
    # 证据板不在七拍里，但它同样要有落点。
    assert "'#evidenceBoard'" in body, "证据板没有被登记为失败时的落点"

    # 失败要同时落在状态行和那一拍自己的输出区。
    report = re.search(r"function report\(error, outSelector\) \{(.*?)\n\}", body, re.S)
    assert report, "找不到统一的失败上报"
    assert "statusEl.textContent" in report.group(1), "失败没有写进状态行"
    assert "out.textContent" in report.group(1), "失败没有写进这一拍自己的输出区"


def test_every_trust_promise_points_at_something_that_proves_it():
    """四条底线的「→」必须落在一段**按得动**的证明上。

    这一条原先读 `trust.html`。四条底线现在在 `/stage` 的「证明」层：
    「自主权包络」「证明式完成」这样的名字是给评委的，一位 78 岁的用户从这四个字里
    得到的信息量是零，所以手机框里那四条改成了普通话（下一条断言守它），
    四个原名连同验证它们的按钮一起搬到了桌面。它守的性质一个字没变。

    判据比原来严一档。原来是"目标必须是一个 data-panel"；现在是"目标必须是一篇
    **带按钮**的卡片"——因为四条底线的整个论点是"每一条都能当场验证"，而一个指向
    纯文字段落的锚点同样把这句话变成空话，却照样满足"目标存在"。

    还有一个新的失效方式要堵：`initSections` 用 `hidden` 切分区，指向某篇卡片的
    hash 必须能把**它所在的那一层**打开。common.js 里的 `resolve()` 干这件事；
    没有它，点一条底线的效果是跳回产品介绍——不报错、不在截图里露馅。

    `check_page_runtime` 的点击遍历只按 `<button>`，这四条是 `<a>`，它不会碰。
    """
    source = (STATIC / "stage.html").read_text(encoding="utf-8")
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    targets = re.findall(r'<a class="promise" href="#([\w-]+)"', source)
    assert len(targets) == 4, f"底线不是四条：{targets}"
    assert len(set(targets)) == 4, f"有两条底线指向同一段：{targets}"

    # 每个目标都必须是一篇真实存在、而且**有按钮**的卡片。
    for target in targets:
        card = re.search(
            rf'<article class="panel feature-panel" id="{re.escape(target)}">(.*?)</article>',
            source, re.S,
        )
        assert card, f"底线指向的 #{target} 不是一篇 .feature-panel 卡片"
        assert "<button" in card.group(1), (
            f"#{target} 里没有任何按钮——一条按不动的底线和一句宣传没有区别"
        )
        # 它还必须待在某个分区里，否则 hash 打不开它所在那一层。
        before = source[: source.index(f'id="{target}"')]
        assert re.search(r'data-panel="[\w-]+"', before), f"#{target} 不在任何分区里"

    # `resolve()` 必须还在：它是"hash 指向分区**里面**一个元素"这件事的唯一实现。
    common = (STATIC / "common.js").read_text(encoding="utf-8")
    assert "function resolve(" in common and "closest('[data-panel]')" in common, (
        "common.js 里没有把「分区内部的 id」解析成分区的那一段——"
        "四条底线点下去会跳回第一段"
    )


def test_the_phone_frame_states_the_same_four_promises_in_plain_words():
    """搬走名字不等于搬走内容：手机框里那四条必须还在，而且是人话。

    没有这一条，上面那条断言就为"把四条底线整体删掉、只留桌面"背书——而设计稿的
    要求是"手机框里只放产品"，不是"手机框里少放东西"。这四条**是**产品，
    它们是这一页对一位老人最重要的四句话。
    """
    source = (STATIC / "trust.html").read_text(encoding="utf-8")
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    items = re.findall(r'<li class="promise">(.*?)</li>', source, re.S)
    assert len(items) == 4, f"手机框里的四条底线不是四条：找到 {len(items)} 条"

    # 工程名字不许回来。这四个词在 /stage 上，那里是它们的位置。
    for word in ("自主权包络", "家庭共识", "证明式完成", "同意记忆"):
        assert word not in source, f"「{word}」是给评委的名字，不该出现在手机框里"

    for item in items:
        strong = re.search(r"<strong>([^<]+)</strong>", item)
        span = re.search(r"<span>([^<]+)</span>", item)
        assert strong and span, f"这一条缺标题或说明：{item[:60]!r}"
        # 一句能被听懂的话。10 个汉字是这四条里最短那句的长度下限——
        # 「记什么、记多久，您说了算」是 12 个字。
        assert len(re.findall(r"[一-鿿]", strong.group(1))) >= 8, (
            f"这一条的标题短到不像一句话：{strong.group(1)!r}"
        )


def test_care_cards_sit_below_their_section_heading():
    """分区标题是 h2，卡片标题必须降到 h3。

    这条原先读 `care.html`。那十九张卡（照护七张 + 可信六张 + 后来加的）现在都在
    `/stage` 的四层里，照护页改成了进页面就加载、一张 `.feature-panel` 都没有。
    卡片搬到哪里，这条断言就跟到哪里——它守的是"读屏软件听得出包含关系"，
    和卡片住在哪一页无关。

    原委：那些卡的标题曾经是 h2（那时它们确实和分区平级）。加上分区之后分区标题成了
    h2，如果卡片还是 h2，读屏软件读到的是两个平级标题，而它们现在是包含关系：
    听的人不知道这张卡属于哪一段。

    `check_page_runtime` 的标题层级检查只查"有没有跳级"（h1 → h3 会报），查不出
    "该嵌套的却是平级"——那一种在层级上完全合法。
    """
    source = (STATIC / "stage.html").read_text(encoding="utf-8")
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    # 两处判据原先都是脆的，变异一测就穿：
    #   * 卡片靠 `class="panel feature-panel` 这个**确切词序**匹配——写成
    #     `class="feature-panel panel"`（完全等效）就一条都匹配不到，for 体不执行；
    #   * 分区靠 `\n    </section>` 这个**确切缩进**结尾——把闭合标签的缩进从四个空格
    #     改成两个，同样一条都匹配不到。
    # 两种情况下 `re.findall` 返回空列表，两个 for 循环双双空转，测试照样绿。
    # 所以先断言"找到了东西"，再断言"东西是对的"。
    cards = re.findall(r'<article\b[^>]*class="[^"]*\bfeature-panel\b[^"]*"[^>]*>.*?</article>',
                       source, re.S)
    assert len(cards) >= 7, f"桌面舞台只匹配到 {len(cards)} 张卡——class 词序变了吗？"
    for card in cards:
        assert "<h2" not in card, f"有卡片仍在用 h2：{card[:90]}"
        assert "<h3" in card, f"有卡片没有标题：{card[:90]}"
    # 每个分区恰好一个 h2（它自己的标题）。缩进不参与判据：按下一个同级 <section
    # 或 </main> 断句。
    panels = re.split(r'(?=<section\b[^>]*class="[^"]*\bpage-section\b)', source)[1:]
    assert len(panels) >= 4, f"桌面舞台只匹配到 {len(panels)} 个分区"
    for panel in panels:
        head = panel.split("</section>")[0]
        assert head.count("<h2") == 1, f"分区里的 h2 不是一个：{head[:90]}"

    # 照护页现在**一张卡都不该有**。它改成了进页面就自动加载五段真实数据，
    # 而"没有卡片"正是那次改动的形状——少了这一条，把卡片加回去不会有任何东西变红。
    care = re.sub(r"<!--.*?-->", "", (STATIC / "care.html").read_text(encoding="utf-8"), flags=re.S)
    assert "feature-panel" not in care, (
        "照护页又出现了 .feature-panel。这一页是一份档案，进来就该有内容，"
        "不是一排「点了才出数据」的演示卡。"
    )


def test_a_failed_family_load_lands_somewhere_visible():
    """加载失败不能写进一个默认折叠起来的地方。

    这个 catch 罩着四个并发请求加一次登录，原先统一写进 `#chain`——那是"记录
    完好"的位置，日历加载失败会显示成记录出了问题。分区改版之后 `#chain` 默认
    是折叠的，再写那里，整条失败就彻底没人看得见了。
    """
    js = (STATIC / "family.js").read_text(encoding="utf-8")
    # 先切到 load() 里面再找 catch。直接在整份文件上找"第一个 catch (e)"会命中
    # approve() 的那个——测试于是永远绿，而它以为自己在守 load()。
    start = js.index("async function load()")
    load_body = js[start:js.index("\n}\n", start)]
    catch = re.search(r"\}\s*catch\s*\(e\)\s*\{(.*)", load_body, re.S)
    assert catch, "load() 的 catch 分支不见了"
    assert "notify(" in catch.group(1), "加载失败没有走 #familyNotice"
    assert "chainEl" not in catch.group(1), "加载失败又写回了折叠区里的 #chain"

    html = (STATIC / "family.html").read_text(encoding="utf-8")
    notice = re.search(r'<p id="familyNotice"[^>]*>', html)
    assert notice, "#familyNotice 不见了"
    assert 'aria-live' in notice.group(0), "#familyNotice 没有 aria-live"
    # 它必须在任何 data-panel 分区之外，否则一样会被折叠掉。
    assert html.index('id="familyNotice"') < html.index("data-panel="), "#familyNotice 被放进了某个分区里"


def test_the_elder_first_screen_says_what_today_holds():
    """老人打开这一屏，第一件想知道的事是"今天有什么事"。

    此前那句话藏在底部抽屉里，要点开才看得到。
    """
    source = (STATIC / "elder.html").read_text(encoding="utf-8")
    assert 'id="todayLine"' in source, "首屏没有「今天」那一行"
    js = (STATIC / "elder.js").read_text(encoding="utf-8")
    assert "renderTodayLine" in js, "没有人去填它"


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
    """六个页面都要有同一条严格 CSP，而且 script-src 里不许有别的来源。

    原先只查一页，而且只禁 `unsafe-inline` / `unsafe-eval`：
    `script-src 'self' https://cdn.example *` 三个断言全部通过——通配符和外部主机
    比内联脚本更宽，一个被投毒的 CDN 就能在这个应用里执行任意代码。这条测试是
    "无构建步骤、无 CDN、无网络字体"那条硬约束的守卫，判据必须覆盖来源本身。
    """
    for route in ("/", "/elder", "/family", "/care", "/trust", "/judge"):
        csp = client.get(route).headers["content-security-policy"]
        assert "script-src 'self'" in csp, f"{route} 的 CSP 不是 script-src 'self'"
        assert "unsafe-inline" not in csp, f"{route} 放开了内联脚本"
        assert "unsafe-eval" not in csp, f"{route} 放开了 eval"
        # script-src 那一段的来源列表：只允许 'self' 与关键字，不许主机、不许通配符。
        directive = next(
            (part.strip() for part in csp.split(";") if part.strip().startswith("script-src")),
            "",
        )
        sources = directive.split()[1:]
        bad = [s for s in sources if s != "'self'" and not s.startswith("'")]
        assert not bad, f"{route} 的 script-src 允许了外部来源：{bad}"


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
