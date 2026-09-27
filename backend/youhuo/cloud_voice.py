r"""云端神经语音：微软「晓晓」（zh-CN-XiaoxiaoNeural）。

为什么要它
    公网那台服务器上没有离线语音模型（几百 MB，不进交付包），于是手机上念给老人听的
    一直是手机自带的系统声音。用户原话：「太难听了……彻底改成那种很像人声的温柔女生」。
    2026-09-24 用户从四条试听里挑了「晓晓，慢一点（-15%）」。

它是什么
    Edge 浏览器「大声朗读」用的那条在线神经语音（speech.platform.bing.com）。协议是
    一条 websocket：发一段配置、一段 SSML，收回若干二进制音频帧，直到 `turn.end`。
    `edge-tts` 这个包做的是同一件事；这里不引它（它拖进 aiohttp 一整串），只用
    `uvicorn[standard]` 本来就带的 `websockets` 写一个同步小客户端。

它**不是**什么
    - 不是权威。念的是已经定下来的话，改不了任何一件事。
    - 不是依赖。断网、被限流、协议变了——一律抛 RuntimeError，端点回 503，
      页面退回手机自己的声音，照样把话念完。连续失败三次就歇 60 秒，
      不让每一句都先等一次超时。

只出 MP3
    实测（2026-09-24）这条免费通道只认 MP3：要 `riff-24khz-16bit-mono-pcm` 时服务端
    回 1007「Unsupported Edge output format」。所以它**只接手机网页那条**
    （`/v6/speech/synthesize`）；板子那条（`/api/v1/speech`，ESP32 读掉 44 字节 WAV 头
    直接灌 I2S）仍然只用离线模型——给板子 MP3 就是一段噪声。

隐私
    要念的那句话（优活的回复）会发到微软的语音服务合成。老人自己说的话**不经过这里**。
    `status()` 与 `/health` 写明这一点；`YOUHUO_CLOUD_VOICE=off` 关掉。

协议常量与 edge-tts 7.2.8 对齐（`Sec-MS-GEC` 是按五分钟取整的时间戳做的 SHA-256，
服务端拿它挡掉时钟不对的请求；403 时按服务器的 `Date` 校一次时钟再试）。
"""

from __future__ import annotations

import email.utils
import hashlib
import math
import os
import re
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable
from xml.sax.saxutils import escape

VOICE = "zh-CN-XiaoxiaoNeural"
#: SSML 里要写全名——Edge 自己发的就是这个形式。
_VOICE_FULL = "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)"

#: 用户挑的「慢一点」。
BASE_RATE_PERCENT = -15
#: 老人档的默认语速（`v6_models.InteractionProfileUpdate.speech_rate` 的默认值、
#: `/api/v1/settings` 的 `voiceSpeed` 默认值）。这个速度下念出来的就是用户挑的那一条。
DEFAULT_SPEED = 0.88

HOST = "speech.platform.bing.com"
_TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
_WSS = f"wss://{HOST}/consumer/speech/synthesize/readaloud/edge/v1"
_GEC_VERSION = "1-143.0.3650.75"
_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0")
_ORIGIN = "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold"
_WIN_EPOCH = 11644473600

OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
CONTENT_TYPE = "audio/mpeg"
SAMPLE_RATE = 24000

MAX_TEXT_CHARS = 300
CACHE_ENTRIES = 256
MAX_FAILURES = 3
OPEN_SECONDS = 60.0
#: 没连上过时，隔多久再试一次（由 `available` 顺手触发，后台跑，不挡请求）。
REPROBE_SECONDS = 120.0
#: 启动时顺手合成的一句：既是连通性探针，也是最常听到的一句（切到办事模式的开场白）。
PROBE_TEXT = "我在，您请说。"

#: 连接复用。实测（国内到微软）：新开一条握手 1.3 秒、合成 0.6–0.9 秒；同一条连接上
#: 连发第二句只要合成那一段。所以说完一句把连接留着，下一句接着用。
#: 闲太久的不用——实测**闲 60 秒服务端就断了**（ConnectionClosedError），
#: 而一条半开的连接会让 recv 一直等到超时。所以只复用 30 秒内的。
IDLE_REUSE_SECONDS = 30.0
POOL_SIZE = 2
#: 复用的连接上，第一帧（turn.start）通常 0.1–0.3 秒就到；3 秒没到就当它死了，换新的重来。
REUSED_FIRST_FRAME_SECONDS = 3.0

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def rate_for(speed: Any) -> str:
    """把客户端的语速系数换成 SSML 的百分比。

    基准：默认语速 0.88 → -15%（用户挑的那一条）。其余按比例：

        0.60 → -42%    0.80 → -23%    1.00 → -3%    1.20 → +16%

    夹在 [-50%, +50%]：再慢就拖腔，再快老人跟不上。
    非数、无穷、非正一律按默认——比较式守卫会让 NaN 从两边都溜过去。
    """
    try:
        s = float(speed)
    except (TypeError, ValueError):
        s = DEFAULT_SPEED
    if not math.isfinite(s) or s <= 0:
        s = DEFAULT_SPEED
    factor = s / DEFAULT_SPEED * (1 + BASE_RATE_PERCENT / 100)
    pct = max(-50, min(50, round((factor - 1) * 100)))
    return f"{pct:+d}%"


def sec_ms_gec(unix_seconds: float) -> str:
    """Edge 的时间令牌：Windows 纪元下、取整到五分钟的 100ns 计数，接上客户端令牌做 SHA-256。

    用整数算。edge-tts 用浮点算出来的是同一个数（取整后是 3e9 的倍数，浮点能精确表示），
    但整数不需要这段论证。
    """
    ticks = int(unix_seconds) + _WIN_EPOCH
    ticks -= ticks % 300
    return hashlib.sha256(
        f"{ticks * 10_000_000}{_TRUSTED_CLIENT_TOKEN}".encode("ascii")
    ).hexdigest().upper()


def _stamp(unix_seconds: float) -> str:
    """`Thu Sep 24 2026 08:00:00 GMT+0000 (Coordinated Universal Time)`。

    不用 `strftime('%a %b')`：那两个取决于进程的区域设置，中文系统上可能出中文。
    """
    t = time.gmtime(unix_seconds)
    return (f"{_DAYS[t.tm_wday]} {_MONTHS[t.tm_mon - 1]} {t.tm_mday:02d} {t.tm_year} "
            f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d} GMT+0000 (Coordinated Universal Time)")


def ssml_for(text: str, rate: str) -> str:
    cleaned = _CONTROL_CHARS.sub(" ", text)
    return ("<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>"
            f"<voice name='{_VOICE_FULL}'><prosody pitch='+0Hz' rate='{rate}' volume='+0%'>"
            f"{escape(cleaned)}</prosody></voice></speak>")


def _header(block: str, name: str) -> str | None:
    for line in block.split("\r\n"):
        key, sep, value = line.partition(":")
        if sep and key.strip() == name:
            return value.strip()
    return None


def media_type_of(audio: bytes) -> str:
    """按字节认格式。端点据此写 Content-Type，而不是写死 `audio/wav`。

    WAV 以 `RIFF` 开头；MP3 以 `ID3` 标签或帧同步字（11 个 1）开头。
    认不出的按 WAV 报——那是这个接口一直以来的承诺，离线模型给的就是它。
    """
    if audio[:3] == b"ID3" or (len(audio) > 1 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    return "audio/wav"


class CloudVoice:
    """晓晓。同步调用；结果按（语速, 文本）缓存，连接说完一句留着给下一句用。"""

    kind = "cloud"
    num_speakers = 1
    default_sid = 0

    def __init__(
        self,
        *,
        enabled: bool = True,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        transport: Callable[[str, str], bytes] | None = None,
    ) -> None:
        self.enabled = enabled
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        #: 测试缝：`(文本, SSML 语速) -> MP3 字节`。默认走真 websocket。
        self._transport = transport or self._over_websocket
        self._lock = threading.Lock()          # 只护内存状态，网络 I/O 期间不持有
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._idle: list[tuple[Any, float]] = []
        self._failures = 0
        self._open_until = 0.0
        self._reachable = False                # 有没有**真合成成功过**一次
        self._probing = False
        self._warming = False
        self._last_probe_at = 0.0
        self._last_error: str | None = None
        self._skew = 0.0
        self.counters = {"requests": 0, "cache_hits": 0, "failures": 0,
                         "connections_opened": 0, "connections_reused": 0, "prewarmed": 0}

    @classmethod
    def from_env(cls) -> "CloudVoice":
        raw = os.getenv("YOUHUO_CLOUD_VOICE", "on").strip().casefold()
        return cls(enabled=raw not in {"0", "off", "false", "no", "disabled"})

    # ------------------------------------------------------------------ 状态
    @property
    def available(self) -> bool:
        """开着、真合成成功过、且没在歇。

        **没连上过就报不可用**，而不是乐观地报可用：页面据此决定整段对话用哪个声音，
        报了可用却连不上，老人每一句话前面都要先等一次超时才听到系统声音。
        没连上时顺手在后台再试（隔 `REPROBE_SECONDS`），不挡这次调用。
        """
        if not self.enabled:
            return False
        if time.monotonic() < self._open_until:
            return False
        if not self._reachable:
            self._maybe_reprobe()
            return False
        return True

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "engine": "cloud",
            "kind": "cloud",
            "model": VOICE,
            "voice": VOICE,
            "speakers": 1,
            "speaker": 0,
            "enabled": self.enabled,
            "reachable": self._reachable,
            "resting": time.monotonic() < self._open_until,
            "base_rate": f"{BASE_RATE_PERCENT:+d}%",
            "format": CONTENT_TYPE,
            "provider_host": HOST,
            "sends_text_to_provider": self.enabled,
            "last_error": self._last_error,
            "counters": dict(self.counters),
            "fallback": "browser_speech_synthesis",
            "note": (f"念给老人听的话会发到微软语音服务（{HOST}）合成，老人自己说的话不经过这里；"
                     "连不上时自动回落到手机自带的声音。YOUHUO_CLOUD_VOICE=off 关闭。"),
        }

    # ------------------------------------------------------------------ 合成
    def synthesize(self, text: str, speed: float = DEFAULT_SPEED,
                   sid: int | None = None) -> tuple[bytes, int]:
        """回 `(MP3 字节, 采样率)`；不可用或失败抛 RuntimeError。`sid` 忽略——只有一个声音。"""
        del sid
        if not self.enabled:
            raise RuntimeError("云端语音已关闭")
        cleaned = (text or "").strip()[:MAX_TEXT_CHARS]
        if not cleaned:
            raise RuntimeError("待合成文本为空")
        if time.monotonic() < self._open_until:
            raise RuntimeError(f"云端语音暂停中（上次：{self._last_error}）")
        rate = rate_for(speed)
        key = f"{rate}|{cleaned}"
        with self._lock:
            self.counters["requests"] += 1
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                self.counters["cache_hits"] += 1
                return hit, SAMPLE_RATE
        try:
            audio = self._transport(cleaned, rate)
            if not audio:
                raise RuntimeError("没有收到音频")
        except Exception as exc:  # noqa: BLE001 - 任何失败都只是「这句用手机的声音念」
            self._record_failure(exc)
            raise RuntimeError(f"云端语音失败：{self._last_error}") from exc
        with self._lock:
            self._failures = 0
            self._reachable = True
            self._last_error = None
            self._cache[key] = audio
            while len(self._cache) > CACHE_ENTRIES:
                self._cache.popitem(last=False)
        return audio, SAMPLE_RATE

    def _record_failure(self, exc: BaseException) -> None:
        with self._lock:
            self.counters["failures"] += 1
            self._failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"[:300]
            if self._failures >= MAX_FAILURES:
                self._open_until = time.monotonic() + OPEN_SECONDS
                self._failures = 0

    # ------------------------------------------------------------------ 探针
    def warm_up_async(self) -> None:
        """启动时后台合成一句：连得上就标记可用，顺便把最常听到的那句缓存好。"""
        self._maybe_reprobe(force=True)

    def _maybe_reprobe(self, *, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            if self._probing or (not force and now - self._last_probe_at < REPROBE_SECONDS):
                return
            self._probing = True
            self._last_probe_at = now

        def _probe() -> None:
            try:
                self.synthesize(PROBE_TEXT, DEFAULT_SPEED)
            except RuntimeError:
                pass                              # 失败已记在 _last_error，available 仍为 False
            finally:
                with self._lock:
                    self._probing = False

        threading.Thread(target=_probe, name="youhuo-cloud-voice-probe", daemon=True).start()

    # ------------------------------------------------------------------ 预热
    def prewarm(self) -> bool:
        """她刚说完一句、优活还在想的时候，先把连接开好。不挡调用方，回「开没开」。

        连接闲 60 秒就会被服务端断掉，留不住；但从她说完到回答出来，中间有大模型
        想的那一两秒——握手放进这段时间里，第一句就不用再等那 1.3 秒。
        已经有新鲜的空闲连接、没开、在歇、还没连上过、或者传输层是测试塞的假货，都不开。
        """
        if (not self.enabled or not self._reachable or time.monotonic() < self._open_until
                or self._transport != self._over_websocket):
            return False
        now = time.monotonic()
        with self._lock:
            if self._warming or any(now - since <= IDLE_REUSE_SECONDS - 5 for _ws, since in self._idle):
                return False
            self._warming = True

        def _warm() -> None:
            try:
                self._give_back(self._open())
                with self._lock:
                    self.counters["prewarmed"] += 1
            except Exception:  # noqa: BLE001 - 预热失败无所谓，念的时候照常新开
                pass
            finally:
                with self._lock:
                    self._warming = False

        threading.Thread(target=_warm, name="youhuo-cloud-voice-prewarm", daemon=True).start()
        return True

    # ------------------------------------------------------------------ 连接
    def _take_idle(self) -> Any:
        """拿一条还新鲜的空闲连接；过期的顺手关掉。拿到的归调用方独占。"""
        now = time.monotonic()
        stale = []
        chosen = None
        with self._lock:
            while self._idle:
                ws, since = self._idle.pop()
                if now - since <= IDLE_REUSE_SECONDS:
                    chosen = ws
                    break
                stale.append(ws)
        for ws in stale:
            self._close_quietly(ws)
        return chosen

    def _give_back(self, ws: Any) -> None:
        """放回池子。**先清掉过期的，满了挤掉最老的——新的这条永远留下。**

        原先是「池子满了就关掉手上这条」，而过期的连接只在取的时候才清。实测后果：
        池子里躺着两条早已被服务端断掉的旧连接，预热刚开好的新连接一放回来就被关了，
        念第一句反而更慢（3.9 秒，比不预热还慢 1.9 秒）。
        """
        now = time.monotonic()
        evicted = []
        with self._lock:
            keep = []
            for item in self._idle:
                (keep if now - item[1] <= IDLE_REUSE_SECONDS else evicted).append(item)
            keep.append((ws, now))
            while len(keep) > POOL_SIZE:
                evicted.append(keep.pop(0))
            self._idle = keep
        for old, _since in evicted:
            self._close_quietly(old)

    @staticmethod
    def _close_quietly(ws: Any) -> None:
        try:
            ws.close()
        except Exception:  # noqa: BLE001 - 已经不要它了
            pass

    # ------------------------------------------------------------------ 协议
    def _over_websocket(self, text: str, rate: str) -> bytes:
        # 预热那条正在开：等它（最多 3 秒），别并排再开一条。实测回答常常 0.05 秒就回来了，
        # 比握手快——不等的话预热开的那条永远用不上，还白白多开一条。
        deadline = time.monotonic() + 3.0
        while self._warming and time.monotonic() < deadline:
            time.sleep(0.02)
        ws = self._take_idle()
        if ws is not None:
            try:
                audio = self._exchange(ws, text, rate, first_frame_timeout=REUSED_FIRST_FRAME_SECONDS)
            except Exception:  # noqa: BLE001 - 旧连接死了，换新的重来一次
                self._close_quietly(ws)
            else:
                with self._lock:
                    self.counters["connections_reused"] += 1
                self._give_back(ws)
                return audio
        ws = self._open()
        try:
            audio = self._exchange(ws, text, rate)
        except BaseException:
            self._close_quietly(ws)
            raise
        self._give_back(ws)
        return audio

    def _open(self) -> Any:
        try:
            from websockets.exceptions import InvalidStatus
            from websockets.sync.client import connect
        except ImportError as exc:                # uvicorn[standard] 带它；精简环境里可能没有
            raise RuntimeError("websockets 未安装") from exc

        for attempt in (1, 2):
            url = (f"{_WSS}?TrustedClientToken={_TRUSTED_CLIENT_TOKEN}"
                   f"&ConnectionId={uuid.uuid4().hex}"
                   f"&Sec-MS-GEC={sec_ms_gec(time.time() + self._skew)}"
                   f"&Sec-MS-GEC-Version={_GEC_VERSION}")
            headers = {
                "Pragma": "no-cache",
                "Cache-Control": "no-cache",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Accept-Language": "en-US,en;q=0.9",
                "Cookie": f"muid={secrets.token_hex(16).upper()};",
            }
            try:
                ws = connect(url, origin=_ORIGIN, additional_headers=headers,
                             user_agent_header=_USER_AGENT,
                             open_timeout=self.connect_timeout, close_timeout=2,
                             max_size=1 << 22)
            except InvalidStatus as exc:
                # 403 多半是本机时钟偏了五分钟以上：按服务器的 Date 校一次再试。
                if attempt == 1 and exc.response.status_code == 403 and self._adjust_skew(exc):
                    continue
                raise
            with self._lock:
                self.counters["connections_opened"] += 1
            return ws
        raise RuntimeError("校准时钟后仍被拒绝")

    def _adjust_skew(self, exc: Any) -> bool:
        date = exc.response.headers.get("Date")
        if not date:
            return False
        try:
            server = email.utils.parsedate_to_datetime(date).timestamp()
        except (TypeError, ValueError):
            return False
        self._skew = server - time.time()
        return True

    def _exchange(self, ws: Any, text: str, rate: str, *,
                  first_frame_timeout: float | None = None) -> bytes:
        now = time.time() + self._skew
        ws.send(
            f"X-Timestamp:{_stamp(now)}\r\n"
            "Content-Type:application/json; charset=utf-8\r\n"
            "Path:speech.config\r\n\r\n"
            '{"context":{"synthesis":{"audio":{"metadataoptions":{'
            '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},'
            f'"outputFormat":"{OUTPUT_FORMAT}"'
            "}}}}\r\n"
        )
        ws.send(
            f"X-RequestId:{uuid.uuid4().hex}\r\n"
            "Content-Type:application/ssml+xml\r\n"
            f"X-Timestamp:{_stamp(now)}Z\r\n"
            "Path:ssml\r\n\r\n" + ssml_for(text, rate)
        )
        audio = bytearray()
        deadline = time.monotonic() + self.read_timeout
        first = True
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{self.read_timeout:.0f} 秒内没有收完")
            if first and first_frame_timeout is not None:
                remaining = min(remaining, first_frame_timeout)
            message = ws.recv(timeout=remaining)
            first = False
            if isinstance(message, str):
                if _header(message.partition("\r\n\r\n")[0], "Path") == "turn.end":
                    break
                continue
            if len(message) < 2:
                raise RuntimeError("二进制帧缺头长度")
            head_len = int.from_bytes(message[:2], "big")
            if head_len > len(message) - 2:
                raise RuntimeError("头长度超过帧长")
            head = message[2:2 + head_len].decode("utf-8", "replace")
            body = message[2 + head_len:]
            if _header(head, "Path") != "audio":
                raise RuntimeError("二进制帧不是音频")
            ctype = _header(head, "Content-Type")
            if ctype is None:
                if body:
                    raise RuntimeError("没有类型却带了数据")
                continue                          # 流末尾那一帧：没类型、没数据，正常
            if ctype != CONTENT_TYPE:
                raise RuntimeError(f"音频类型不对：{ctype}")
            audio.extend(body)
        if not audio:
            raise RuntimeError("没有收到音频")
        return bytes(audio)


class VoiceChain:
    """先晓晓，不行再离线模型；都不行 `available` 为 False，页面用手机自己的声音。

    接口与 `NeuralVoice` 一样（`available` / `status()` / `synthesize()` /
    `default_sid` / `num_speakers` / `warm_up_async()`），路由原样接着用。

    云端关掉时它是离线模型的**透明外壳**——状态原样转交，测试塞进来的假引擎也照常工作。
    """

    def __init__(self, local: Any, cloud: CloudVoice | None = None) -> None:
        self.local = local
        self.cloud = cloud if (cloud is not None and cloud.enabled) else None

    def _cloud_ready(self) -> bool:
        return self.cloud is not None and self.cloud.available

    @property
    def available(self) -> bool:
        # 先问云端：离线那一侧的 `available` 第一次会导入原生库（几秒），能不碰就不碰。
        return self._cloud_ready() or bool(self.local.available)

    @property
    def default_sid(self) -> int:
        if self._cloud_ready():
            return 0
        return int(getattr(self.local, "default_sid", 0) or 0)

    @property
    def num_speakers(self) -> int:
        if self._cloud_ready():
            return 1
        return int(getattr(self.local, "num_speakers", 1) or 1)

    def status(self) -> dict[str, Any]:
        if self._cloud_ready():
            st = self.cloud.status()
            st["where"] = "cloud"
            return st
        st = dict(self.local.status())
        st.setdefault("where", "local" if st.get("available") else "none")
        if self.cloud is not None:
            # 云端开着但现在用不上：说清楚为什么，别让人以为没装。
            st["cloud"] = {k: v for k, v in self.cloud.status().items()
                           if k in ("enabled", "reachable", "resting", "last_error", "provider_host")}
        return st

    def synthesize(self, text: str, speed: float = 1.0, sid: int | None = None) -> tuple[bytes, int]:
        if self._cloud_ready():
            try:
                return self.cloud.synthesize(text, speed)
            except RuntimeError:
                if not self.local.available:
                    raise
        return self.local.synthesize(text, speed, sid=sid)

    def warm_up_async(self) -> None:
        self.local.warm_up_async()
        if self.cloud is not None:
            self.cloud.warm_up_async()
