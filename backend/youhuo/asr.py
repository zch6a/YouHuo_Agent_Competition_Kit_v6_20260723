r"""Optional offline speech recognition —— 声音**进来**的那一侧。

出去那一侧（`tts.py`）早就通了：一句话进去，一段 WAV 出来。
反过来一直不存在——后端里没有任何端点收音频字节，网页端和山水版的识别
全靠浏览器的 `SpeechRecognition`（`elder.js` 3 处、`elder3.js` 2 处、
`app/assets/js/speech.js` 2 处）。

在网页上这不算缺口，浏览器自带识别。**在一块板子上是缺口**：
ESP32-S3 上那颗 INMP441 采到的是 I2S PCM，板子上没有浏览器，
这段音频此前无处可送。

规矩和 `tts.py` 完全一样：

    装了包 + 有模型  → 真的认
    缺任何一样        → 503 并说清楚缺什么，**绝不回一个空字符串假装听见了**

后一条是有分量的。识别失败回 `{"text": ""}` 和识别出一句空话，
在调用方那里长得一模一样，而两者该做的事相反（一个重试，一个别重试）。

开启：

    pip install sherpa-onnx
    set YOUHUO_ASR_MODEL_DIR=D:\youhuo-asr\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17

模型同样以百 MB 计，**不进交付包**（`check_artifacts_v6` 会把仓库里多出来的
大文件当成泄漏）。放仓库外面，用上面那个环境变量指过去。
"""

from __future__ import annotations

import array
import os
import struct
import threading
from pathlib import Path
from typing import Any

#: 模型要的采样率。**不替调用方重采样**——不带低通的线性插值降采样会混叠，
#: 识别率掉下来之后，第一个被怀疑的是麦克风而不是这里。
#: 板子上这是一个常量，配一次的事。
REQUIRED_RATE = 16000

#: 一次最多认多长。16k/16bit/单声道下 30 秒 = 960 000 字节。
#: 识别是同步的，会占住这个进程；没有上限的话，一块坏掉的板子能把服务顶住。
MAX_SECONDS = 30
MAX_BYTES = REQUIRED_RATE * 2 * MAX_SECONDS

#: WAV 的 `fmt ` 段布局：audio_fmt, channels, rate, byte_rate,
#: block_align, bits。**一处定义**——下面那道长度检查和解包用的是同一个，
#: 各写一份迟早分叉成「检查了 16 字节、解包读 20 字节」。
_FMT_LAYOUT = "<HHIIHH"
_FMT_BYTES = struct.calcsize(_FMT_LAYOUT)

#: 声道数的上界。这条端点是给 INMP441 这种**单麦**板子写的（见下面
#: `decode` 里取第一路那段注释），2 路已经在规格之外，8 是给「将来换个
#: 阵列麦」留的余量。设上界的理由不是洁癖：`samples[0::channels]` 对一个
#: 很大的 channels 会**静默地只留一个样本**，然后去识别它。
_MAX_CHANNELS = 8


class UnsupportedAudio(ValueError):
    """音频本身不对（格式 / 采样率 / 长度）。给调用方的是 400，不是 503。

    分开是要紧的：503 的意思是「这台服务没这个能力，别重试」，
    400 的意思是「你给的东西不对，改了再来」。混成一个，板子上
    一个配错的采样率会被当成服务器没装模型，然后没人去看固件。
    """


class NeuralEars:
    """Lazily loaded offline ASR. 和 `NeuralVoice` 一样，永远是可选项。"""

    def __init__(self, root: Path, model_dir: str | None = None) -> None:
        configured = model_dir or os.getenv("YOUHUO_ASR_MODEL_DIR") or ""
        self.model_dir: Path | None
        if configured:
            path = Path(configured)
            self.model_dir = path if path.is_absolute() else root / path
        else:
            self.model_dir = None
        self._engine: Any = None
        self._load_error: str | None = None
        self._kind_loaded: str | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------- availability
    @property
    def model_present(self) -> bool:
        """目录里有没有一个能用的声学模型。

        和 `tts.py` 同一个原则：**按目录里实际有什么判断，不靠名字**。
        名字是人起的，一个改过目录名的模型照样能跑，而一个名字对的空目录不能。
        """
        d = self.model_dir
        if d is None or not d.is_dir():
            return False
        if not (d / "tokens.txt").is_file():
            # 四种架构都要 tokens.txt。没有它，下面任何一个构造器都会抛。
            return False
        return bool(self._candidates())

    def _candidates(self) -> list[str]:
        """这个目录看起来像哪几种架构，按可能性排序。

        SenseVoice 和 Paraformer 的文件名都是 `model.onnx`，光看文件名分不开，
        所以这里回的是**候选列表**，加载时逐个试。试错比猜名字可靠：
        构造器不匹配会直接抛，而猜错名字会安静地跑出一堆乱码。
        """
        d = self.model_dir
        if d is None or not d.is_dir():
            return []
        names = {p.name.lower() for p in d.glob("*.onnx")}
        out: list[str] = []
        if any("joiner" in n for n in names):
            out.append("transducer")
        if any("encoder" in n for n in names) and any("decoder" in n for n in names):
            out.append("whisper")
        if "model.onnx" in names or any(n.startswith("model.int8") for n in names):
            # 先 sense_voice 后 paraformer：sense-voice 是这个项目实际推荐的那个
            # （中英日韩粤，带标点），排前面能少试一次。
            out.extend(("sense_voice", "paraformer"))
        return out

    _package_cache: bool | None = None

    @classmethod
    def _package_present(cls) -> bool:
        """探一次就好——import sherpa_onnx 会拉起一个很大的原生库。

        **不要在启动路径上调它**，那会把整个服务的启动拖慢几秒。
        """
        if cls._package_cache is None:
            try:
                import sherpa_onnx  # noqa: F401
            except Exception:
                cls._package_cache = False
            else:
                cls._package_cache = True
        return cls._package_cache

    @property
    def available(self) -> bool:
        return self._package_present() and self.model_present and self._load_error is None

    def status(self) -> dict[str, Any]:
        """给 `/api/v1/listen/status`。**拿不到的就说拿不到，不填假值。**"""
        pkg = self._package_present()
        present = self.model_present
        if not pkg:
            note = "这台服务没装 sherpa-onnx，认不了话。"
        elif self.model_dir is None:
            note = "没有配 YOUHUO_ASR_MODEL_DIR，认不了话。"
        elif not present:
            note = f"{self.model_dir} 下没有可用的识别模型。"
        elif self._load_error:
            note = self._load_error
        else:
            note = None
        return {
            "available": bool(pkg and present and not self._load_error),
            "engine": "sherpa-onnx" if pkg else None,
            # 加载之前是不知道的。**这里回 None 而不是猜一个**——
            # 「不知道」和「是 sense_voice」是两件事，客户端该能分开。
            "kind": self._kind_loaded,
            "model": str(self.model_dir) if self.model_dir else None,
            "rate": REQUIRED_RATE,
            "max_seconds": MAX_SECONDS,
            "fallback": "browser_speech_recognition",
            "note": note,
        }

    # ------------------------------------------------------------------ loading
    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is not None:
                return self._engine
            if self._load_error:
                raise RuntimeError(self._load_error)
            import sherpa_onnx

            d = self.model_dir
            assert d is not None                       # available 已经挡过
            tokens = str(d / "tokens.txt")
            errors: list[str] = []
            for kind in self._candidates():
                try:
                    self._engine = self._build(sherpa_onnx, kind, d, tokens)
                except Exception as exc:               # noqa: BLE001 - 逐个试
                    errors.append(f"{kind}: {type(exc).__name__} {exc}")
                    continue
                self._kind_loaded = kind
                return self._engine
            self._load_error = "识别模型加载不起来：" + "；".join(errors[:3])
            raise RuntimeError(self._load_error)

    @staticmethod
    def _build(sherpa_onnx: Any, kind: str, d: Path, tokens: str) -> Any:
        """按架构造 recognizer。**线程数固定 1**——识别在请求线程里跑，

        给它多线程会和 uvicorn 的线程池抢核，在一台四核机器上反而更慢。
        """
        first = lambda pat: str(next(iter(sorted(d.glob(pat)))))     # noqa: E731
        if kind == "sense_voice":
            return sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=first("model*.onnx"), tokens=tokens,
                num_threads=1, use_itn=True,
            )
        if kind == "paraformer":
            return sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=first("model*.onnx"), tokens=tokens, num_threads=1,
            )
        if kind == "whisper":
            return sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=first("*encoder*.onnx"), decoder=first("*decoder*.onnx"),
                tokens=tokens, num_threads=1, language="zh", task="transcribe",
            )
        if kind == "transducer":
            return sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=first("*encoder*.onnx"), decoder=first("*decoder*.onnx"),
                joiner=first("*joiner*.onnx"), tokens=tokens,
                num_threads=1, model_type="",
            )
        raise ValueError(f"不认识的模型架构：{kind}")

    # ---------------------------------------------------------------- 音频解码
    @staticmethod
    def decode(blob: bytes, rate_hint: int | None = None) -> tuple[array.array, int]:
        """把请求体变成 16 位单声道样本。接受 WAV，也接受裸 PCM。

        为什么两种都收：板子上最省事的是把 I2S 读到的**裸 PCM** 直接 POST 上来，
        不必在 ESP32 上拼 WAV 头；而调试时用 `curl --data-binary @x.wav` 最顺手。
        WAV 自带采样率，裸 PCM 得由 `?rate=` 给——所以裸 PCM 那条路要求显式声明。
        """
        if len(blob) < 2:
            raise UnsupportedAudio("没有音频数据。")
        if len(blob) > MAX_BYTES:
            raise UnsupportedAudio(
                f"一次最多认 {MAX_SECONDS} 秒（{MAX_BYTES} 字节），这段有 {len(blob)} 字节。"
            )

        if blob[:4] == b"RIFF" and blob[8:12] == b"WAVE":
            fmt_at = blob.find(b"fmt ")
            data_at = blob.find(b"data")
            if fmt_at < 0 or data_at < 0:
                raise UnsupportedAudio("WAV 头不完整。")
            #: **标记在，不等于后面那 16 个字节也在。**
            #:
            #: 原先直接解包，而缺字节时 `unpack_from` 抛的是
            #: `struct.error: unpack_from requires a buffer of at least
            #: 36 bytes…`——**一句英文**，而这个函数其它每一条出口都是
            #: 中文的 `UnsupportedAudio`。实测 28 字节的
            #: `RIFF....WAVE` + `fmt ` + 长度 + `data` + 长度 就走得到。
            #: 请求体是外面来的字节（那块板子直接 POST），不是我们自己拼的。
            if len(blob) < fmt_at + 8 + _FMT_BYTES:
                raise UnsupportedAudio("WAV 头不完整。")
            audio_fmt, channels, rate, _br, _ba, bits = struct.unpack_from(
                _FMT_LAYOUT, blob, fmt_at + 8
            )
            if audio_fmt != 1 or bits != 16:
                raise UnsupportedAudio(
                    f"只认 16 位 PCM 的 WAV，这段是 {bits} 位、编码 {audio_fmt}。"
                )
            #: 声道数原先**一个字都没校**。0 不大于 1，所以下面那句
            #: `if channels > 1` 不切片，一个物理上不存在的头就被当成
            #: 单声道收下了（实测 `channels=0` 回了 50 个样本）。
            if not 1 <= channels <= _MAX_CHANNELS:
                raise UnsupportedAudio(
                    f"声道数说的是 {channels}，这里只认 1 到 {_MAX_CHANNELS} 路。"
                )
            body = blob[data_at + 8:]
        else:
            if rate_hint is None:
                raise UnsupportedAudio(
                    "裸 PCM 要带上采样率，例如 ?rate=16000；"
                    "或者发一段带头的 16 位 WAV。"
                )
            channels, rate, body = 1, int(rate_hint), blob

        if rate != REQUIRED_RATE:
            # 不在这里重采样，理由见 REQUIRED_RATE 上面那段。
            raise UnsupportedAudio(
                f"要 {REQUIRED_RATE} Hz 的音频，这段是 {rate} Hz。板子上把 I2S 配成 "
                f"{REQUIRED_RATE} 就行。"
            )
        if not body:
            raise UnsupportedAudio("音频是空的。")

        samples = array.array("h")
        samples.frombytes(body[: len(body) // 2 * 2])
        if sys_is_big_endian():
            samples.byteswap()
        if channels > 1:
            # 取第一路。混下来要除以声道数，而 INMP441 那种单麦的第二路是静音，
            # 混完整体幅度减半——识别率会莫名其妙地差一截。
            samples = samples[0::channels]
        return samples, rate

    # ------------------------------------------------------------------- 认它
    def _recognise(self, engine: Any, rate: int, floats: list[float]) -> str:
        """只有这一小段真的碰 sherpa。

        单独切出来是为了让测试能替掉它而**仍然跑真的 `transcribe`**——
        真模型几百 MB，不进仓库也不进 CI，但 `heard` 怎么算、`seconds` 怎么算、
        解码那一层挡不挡得住，都必须是被测过的真代码。

        写这个文件时把整个 `transcribe` 替掉过一次，结果是「静音也说听见了」
        这个变异改坏了代码而门全绿——门测的是替身，不是它自己。
        """
        stream = engine.create_stream()
        stream.accept_waveform(rate, floats)
        engine.decode_stream(stream)
        return (stream.result.text or "").strip()

    def transcribe(self, blob: bytes, rate_hint: int | None = None) -> dict[str, Any]:
        """认一段音频。**认不出来就说认不出来，不回空串。**"""
        if not self.available:
            raise RuntimeError(self.status()["note"] or "这台服务上没有离线识别。")
        samples, rate = self.decode(blob, rate_hint)
        seconds = len(samples) / float(rate)

        engine = self._ensure_engine()
        text = self._recognise(engine, rate, [s / 32768.0 for s in samples])
        return {
            "text": text,
            "seconds": round(seconds, 2),
            "kind": self._kind_loaded,
            # 认了但一个字都没出来，是**真的没听到话**（静音 / 只有环境噪声），
            # 和「服务不可用」不是一回事。让调用方能分开这两种。
            "heard": bool(text),
        }


def sys_is_big_endian() -> bool:
    """`array('h')` 用的是本机字节序，而 WAV 和 I2S 上的 PCM 都是小端。

    在小端机器上这是恒 False，所以这个函数看起来是多余的——它不是。
    没有它，同一份代码在大端机器上会把每个样本的高低字节读反，
    出来是一段噪声，而**不会报任何错**。
    """
    return struct.pack("=H", 1) != struct.pack("<H", 1)
