"""鸿蒙原生端：结构与适老约束。

这台开发机上没有 HarmonyOS SDK，`harmonyos/` 编译不了。这不是"可以不检查"的理由，
恰恰相反——没有编译器兜底时，一个拼错的资源名会一路活到评委手机上，而且表现为
**静默的空白**而不是报错。

`check_arkts.py` 负责编译期那一类（$r 模板字符串、资源名、废弃 API、import 路径）；
这个文件负责它抓不到的那一类：**产品约束**。它们不是语法问题，坏掉时代码照样跑，
只是这个产品不再适合它的用户了。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HM = ROOT / "harmonyos" / "entry" / "src" / "main"
ETS = HM / "ets"

pytestmark = pytest.mark.skipif(not ETS.is_dir(), reason="没有 harmonyos/ 工程")


def read(rel: str) -> str:
    return (ETS / rel).read_text(encoding="utf-8")


def _code(source: str) -> str:
    """去掉注释，只留代码。

    这个项目的注释里经常引用它修掉的那段旧代码，按位置判断顺序的检查如果不去注释，
    量到的就是散文。长度用空格补齐，保持偏移可比。
    """
    source = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), source, flags=re.S)
    return re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), source)


# --- 编译期那一类，直接复用脚本 -------------------------------------------


def test_static_check_passes():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "backend" / "scripts" / "check_arkts.py")],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- 语音产品必须有麦克风 ---------------------------------------------------


def test_the_conversation_screen_has_a_microphone():
    """替换掉的旧版本没有麦克风，主控件是一个 TextInput。

    一个语音助手把主控件做成输入框，等于要求一位可能不会拼音、看不清小键盘的老人
    先学会打字，才能用上"说一句话就办事"的产品。
    """
    assert (ETS / "components" / "MicButton.ets").is_file(), "没有麦克风组件"
    assert "MicButton(" in read("pages/Index.ets"), "会话屏没有用上麦克风"


def test_the_microphone_is_the_largest_control_on_the_screen():
    mic = read("components/MicButton.ets")
    size = re.search(r"\.width\((\d+)\)\s*\n\s*\.height\(\1\)", mic)
    assert size and int(size.group(1)) >= 96, "麦克风应当是屏幕上最大的控件"


def test_voice_input_is_tap_to_start_not_press_and_hold():
    """长按需要持续用力。帕金森、关节炎和握力下降都会让手中途松开，

    而松开就等于话说到一半被切断。点一下开始、再点一下结束，两个动作都不需要维持。
    """
    mic = read("components/MicButton.ets")
    assert "LongPressGesture" not in mic, "不要用长按说话"
    assert ".onClick(" in mic


def test_the_microphone_actually_listens():
    """按钮曾经只会变色。一个只会变色的麦克风，和一个坏掉的麦克风体验上没有区别。"""
    assert (ETS / "services" / "AudioCapture.ets").is_file(), "没有音频采集"
    assert (ETS / "services" / "SpeechInput.ets").is_file(), "没有语音识别接入"
    index = read("pages/Index.ets")
    assert "SpeechInput" in index and "this.speech.start(" in index, "麦克风没有接到识别上"


def test_capture_format_matches_what_the_recogniser_requires():
    """16kHz/单声道/16bit 是 Core Speech 端侧识别唯一接受的格式。

    采集这一步做错，识别端只会返回空结果，而且不会说为什么——这是最难查的一类。
    每个常量都已对照 SDK 声明文件核实过。
    """
    capture = read("services/AudioCapture.ets")
    for token in ("SAMPLE_RATE_16000", "CHANNEL_1", "SAMPLE_FORMAT_S16LE",
                  "ENCODING_TYPE_RAW"):
        assert token in capture, f"采集参数缺少 {token}"
    speech = read("services/SpeechInput.ets")
    assert "sampleRate: 16000" in speech and "soundChannel: 1" in speech
    assert "sampleBit: 16" in speech


def test_capture_uses_the_speech_tuned_source():
    """SOURCE_TYPE_VOICE_RECOGNITION 会启用为识别调校的回声消除和降噪。

    对着电视说话的独居老人，这个差别就是能不能识别出来的差别。
    """
    assert "SOURCE_TYPE_VOICE_RECOGNITION" in read("services/AudioCapture.ets")


def test_recognition_runs_on_device():
    """陪伴与办事内容不该为了识别而离开这台设备。"""
    assert "online: 0" in read("services/SpeechInput.ets")


def test_the_capturer_is_registered_before_it_is_started():
    """`start()` 抛错时必须还找得到采集器。

    原来是 `await capturer.start()` 成功之后才赋值给 `this.capturer`，于是一旦
    start 抛错，这个持有原生音频流的采集器就永远留在那里——`stop()` 只看
    `this.capturer`，看到 null 直接返回，局部变量在 catch 里甚至不在作用域内。
    而 start 失败是常态不是意外：音频焦点被抢、别的应用在用麦克风、来电。
    """
    # 先去注释再量位置。这条测试第一版就栽在这里：注释里引用了
    # `await capturer.start()` 来说明旧 bug，于是它比真正的调用先被找到，
    # 顺序判断量的是散文而不是代码。
    capture = _code(read("services/AudioCapture.ets"))
    body = capture[capture.index("async start("):]
    create_at = body.index("createAudioCapturer")
    register_at = body.index("this.capturer = capturer")
    start_at = body.index("await capturer.start()")
    assert create_at < register_at < start_at, (
        "必须在 createAudioCapturer 之后、capturer.start() 之前登记"
    )


@pytest.mark.parametrize("service", ["AudioCapture", "SpeechInput"])
def test_stop_during_start_is_not_a_no_op(service: str):
    """`stop()` 落在 `start()` 的两个 await 之间时，不能什么都不做。

    那一刻 `this.capturer` 还是 null，`stop()` 直接返回，随后 `start()` 把麦克风
    打开——**在停止请求之后**。这正是老人在权限弹窗上按返回时走的路径。
    一个 `starting` 布尔量挡不住它，要靠一个会被 `stop()` 作废的号。
    """
    source = read(f"services/{service}.ets")
    assert "this.generation" in source, f"{service} 没有代次守卫"
    assert "++this.generation" in source, f"{service} 的 start 没有领号"
    assert re.search(r"mine !== this\.generation", source), (
        f"{service} 的 start 在 await 之后没有检查号是否已作废"
    )


def test_the_ui_only_reports_listening_after_the_await():
    """权限弹窗会让 start() 停留数秒。在 await **之前**就把 listening 置 true，

    第二次点击会看到 true、改回 false、await 一个还没开始的 stop()；第一次点击
    随后拿到权限并真的打开麦克风。最终麦克风在录、按钮显示未开启、读屏念的是
    "点一下开始说话"。对这个受众这是隐私缺陷，不是界面瑕疵。
    """
    index = read("pages/Index.ets")
    body = index[index.index("private async toggleListening"):]
    assert "this.startingVoice" in body, "缺少与 listening 分开的启动中标志"
    assert re.search(r"this\.listening = ok", body), (
        "listening 必须在 await 返回之后按真实结果赋值"
    )


def test_leaving_the_conversation_screen_releases_the_microphone():
    """切标签页时 Index 这个 struct 还活着，aboutToDisappear 不触发；

    按 Home 键同理。少了这两条，麦克风会在一个连录音指示都没有的屏幕上继续录。
    """
    index = read("pages/Index.ets")
    assert "onPageHide" in index, "缺少 onPageHide，按 Home 后麦克风不会停"
    assert re.search(r"if \(index !== 0\)[\s\S]{0,120}releaseVoice", index), (
        "切换标签页时没有释放麦克风"
    )


def test_recognition_finishing_also_closes_the_microphone():
    """识别结束不等于麦克风已关。"""
    index = read("pages/Index.ets")
    final = index[index.index("onFinal:"):]
    final = final[: final.index("onError:")]
    assert "this.speech.stop()" in final, "onFinal 没有关闭麦克风"


def test_the_window_listener_is_unregistered():
    """匿名回调是取消不掉的，而闭包会一直抓着这个页面。"""
    index = read("pages/Index.ets")
    assert "this.insetListener" in index
    assert re.search(r"off\('avoidAreaChange'", index), "avoidAreaChange 从未反注册"


def test_host_context_is_checked_before_use():
    """`getHostContext()` 的返回类型是 `Context | undefined`。不判空的话

    undefined 会一路传到 requestPermissionsFromUser 抛出，被采集层吞成
    "还没有麦克风权限"——一句错误的解释。
    """
    index = read("pages/Index.ets")
    body = index[index.index("private async toggleListening"):]
    assert "common.UIAbilityContext | undefined" in body
    assert re.search(r"if \(!context\)", body), "拿到 host context 后没有判空"


def test_vibration_uses_named_types_not_a_bare_object_literal():
    """`startVibration` 的第一个参数是联合类型 `VibrateEffect`，而 ArkTS 的

    `arkts-no-untyped-obj-literals` 要求对象字面量的上下文类型是**单个**明确声明的
    类或接口——联合类型不算，直接写字面量是编译错误。
    """
    haptics = read("services/Haptics.ets")
    assert "vibrator.VibratePreset" in haptics
    assert "vibrator.VibrateAttribute" in haptics


def test_the_microphone_is_always_released():
    """老人会连点、会中途返回、会锁屏。任何一条路径漏了释放，下一次录音就会

    失败得毫无线索——而那种失败没有任何提示可以告诉老人该怎么办。
    """
    capture = read("services/AudioCapture.ets")
    assert "release()" in capture, "采集器从不释放"
    index = read("pages/Index.ets")
    assert "aboutToDisappear" in index and "this.speech.stop()" in index, (
        "离开页面时没有释放麦克风"
    )


def test_every_voice_failure_explains_itself_to_the_elder():
    """降级必须是"说清楚然后退回打字"，不是一个安静地什么也不做的按钮。"""
    speech = read("services/SpeechInput.ets")
    assert "onError" in speech
    for phrase in ("先打字", "再说一遍"):
        assert phrase in speech, f"缺少面向老人的降级说明：{phrase}"


def test_microphone_permission_is_requested_not_assumed():
    speech = read("services/SpeechInput.ets")
    assert "ensurePermission" in speech
    module = json.loads(
        re.sub(r"//[^\n]*", "", (HM / "module.json5").read_text(encoding="utf-8"))
    )
    names = {p["name"] for p in module["module"]["requestPermissions"]}
    assert "ohos.permission.MICROPHONE" in names
    mic = next(p for p in module["module"]["requestPermissions"]
               if p["name"] == "ohos.permission.MICROPHONE")
    assert "reason" in mic and "usedScene" in mic, "user_grant 权限必须写明用途"


def test_the_unverifiable_kit_is_isolated_to_one_file():
    """本机的 OpenHarmony SDK 没有 Core Speech Kit，那是 HarmonyOS 闭源部分。

    无法核实的 import 必须只有一处，而且写明为什么——散落各处就没人记得哪些是
    核实过的、哪些是猜的。
    """
    users = [p.name for p in ETS.rglob("*.ets")
             if "@kit.CoreSpeechKit" in p.read_text(encoding="utf-8")]
    assert users == ["SpeechInput.ets"], f"CoreSpeechKit 被多处引用：{users}"
    assert "无法核实" in read("services/SpeechInput.ets")


def test_the_microphone_state_is_not_colour_only():
    """色觉障碍者、单色屏、阳光下的屏幕——只靠颜色的状态就是没有状态。"""
    mic = read("components/MicButton.ets")
    assert "我在听" in mic, "正在录音必须有文字说明，不能只靠配色"
    assert "accessibilityText" in mic, "读屏软件要能报出当前状态"


# --- 适老与无障碍 -----------------------------------------------------------


def test_touch_targets_never_go_below_the_floor():
    theme = read("theme/Theme.ets")
    floor = re.search(r"TOUCH_MIN:\s*number\s*=\s*(\d+)", theme)
    assert floor and int(floor.group(1)) >= 48, (
        "触控下限不得低于 48vp：这是 WCAG 2.2 的目标尺寸下限，"
        "也是老人手指在晃动的公交车上还能稳定命中的尺寸"
    )


def test_body_text_is_large_enough_to_read():
    theme = read("theme/Theme.ets")
    chat = re.search(r"TEXT_CHAT:\s*number\s*=\s*(\d+)", theme)
    assert chat and int(chat.group(1)) >= 20, "对话正文对这个受众不能小于 20vp"


def test_motion_never_overshoots():
    """回弹对前庭敏感的人读起来是"不稳"，而会过冲的控件就是会从手指底下跑掉的控件。

    `springMotion(response, dampingFraction)` 里 dampingFraction >= 1 才不回弹。
    """
    theme = read("theme/Theme.ets")
    for match in re.finditer(r"springMotion\(([\d.]+),\s*([\d.]+)\)", theme):
        damping = float(match.group(2))
        assert damping >= 1.0, f"阻尼比 {damping} < 1 会过冲；这个受众不能有回弹"


def test_the_tab_bar_cannot_be_swiped_between():
    """这个受众滑动时手抖得比想象中多；误触横滑不该换页。"""
    assert ".scrollable(false)" in read("pages/Index.ets")


# --- 隔离：公网演示的正确性 -------------------------------------------------


def test_each_device_gets_its_own_household():
    """固定用 elder-demo 登录，意味着所有评委的手机落在同一户人家。

    彼此看得见对方的待办，也能改掉对方的数据。Web 端早就改用
    `POST /v2/auth/visitor` 了，原生端一直没跟上。
    """
    api = read("services/ApiClient.ets")
    assert "/v2/auth/visitor" in api, "原生端必须为每台设备申请独立演示家庭"


def test_request_bodies_use_the_provisioned_elder_id():
    """令牌是每户独立的，请求体里却写死 elder-demo，比原来的 bug 更糟：

    令牌授权 A 户而请求体指名 B 户，要么 403，要么把一位访客的健康档案写进另一位
    访客的家庭。两者必须来自同一个身份。
    """
    api = read("services/ApiClient.ets")
    # provision() 里的兜底身份是**故意**写死的，那就是共享家庭本身。
    after_fallback = api[api.index("private static async readCached("):]
    assert "'elder-demo'" not in after_fallback, (
        "请求体里仍有写死的 elder-demo；应使用 ApiClient.elderId()"
    )


def test_the_backend_is_reached_over_https():
    """这条链路上会走审计凭据和账单摘要，明文承载它们在任何咖啡店 Wi-Fi 上都可读。"""
    api = read("services/ApiClient.ets")
    base = re.search(r"const BASE_URL:\s*string\s*=\s*'([^']+)'", api)
    assert base, "找不到 BASE_URL"
    url = base.group(1)
    assert url.startswith("https://"), f"BASE_URL 必须是 HTTPS，当前是 {url}"
    assert not re.match(r"https?://(192\.168|10\.|127\.|localhost)", url), (
        f"BASE_URL 指向一个只在某台开发机网段里存在的地址：{url}"
    )


# --- 深色模式 ---------------------------------------------------------------


def test_dark_mode_has_its_own_palette():
    dark = HM / "resources" / "dark" / "element" / "color.json"
    assert dark.is_file(), "缺少深色模式配色"
    names = {c["name"] for c in json.loads(dark.read_text(encoding="utf-8"))["color"]}
    assert {"bg", "surface", "ink", "youhuo_blue_deep"} <= names


def _lum(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _colours(name: str) -> dict[str, str]:
    path = HM / "resources" / name / "element" / "color.json"
    return {c["name"]: c["value"] for c in json.loads(path.read_text(encoding="utf-8"))["color"]}


# 强调色会给 13vp 的当前标签文字上色。13vp 是小字号，没有豁免：4.5:1。
# 它必须在两种可能落脚的表面上都达标——页面底色和卡片。
ACCENTS = ("youhuo_blue_deep", "wuyou_orange_deep")


@pytest.mark.parametrize("mode", ["base", "dark"])
@pytest.mark.parametrize("accent", ACCENTS)
def test_accent_is_readable_as_small_text(mode: str, accent: str):
    """两种模式都测。

    最初这里只测了深色模式——而缺陷在**浅色**模式：我给 wuyou_orange_deep 随手取了
    一个 #B96F04，在白底上是 3.93:1，低于 4.5。只测一半的检查会让人以为测过了。
    """
    colours = _colours(mode)
    for surface_name in ("surface", "bg"):
        ratio = _ratio(colours[accent], colours[surface_name])
        assert ratio >= 4.5, (
            f"{mode} 模式下 {accent} 在 {surface_name} 上只有 {ratio:.2f}:1，"
            f"低于 AA 小字号的 4.5:1（它给 13vp 的标签文字上色）"
        )


def test_dark_mode_lifts_the_accent_instead_of_reusing_it():
    """浅色模式的 deep 变体是给浅色表面用的；深色模式需要相反的方向。

    实测：把 #2F6FB5 直接搬到深色表面 #141B2E 上是 3.31:1，#B96F04 是 4.35:1，
    两个都不过 AA。
    """
    base, dark = _colours("base"), _colours("dark")
    for name in ACCENTS:
        assert _lum(dark[name]) > _lum(base[name]), (
            f"{name} 在深色模式下应当更亮，而不是沿用浅色模式的深色变体"
        )
