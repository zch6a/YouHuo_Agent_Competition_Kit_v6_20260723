"""Optional offline neural voice.

The service never requires this. When `sherpa-onnx` and a model directory are
both present the elder client gets a natural Chinese voice; otherwise it falls
back to the browser's own speech synthesis and everything else is unchanged.
That mirrors how the language model is treated: an upgrade when configured,
never a dependency, never a source of authority.

Enable it with:

    pip install sherpa-onnx
    set YOUHUO_TTS_MODEL_DIR=D:\youhuo-tts\kokoro-multi-lang-v1_1
    set YOUHUO_TTS_SPEAKER=3          # 可选，见下

支持三种架构，**按目录里实际有什么判断**，不靠名字：

    vits     model.onnx + tokens/lexicon          清楚但偏平
    matcha   model-steps-N.onnx + 一个声码器      中文女声自然得多
    kokoro   model.onnx + voices.bin              多音色，目前最好

模型体积以百 MB 计，**不进交付包**（`check_artifacts_v6` 会把仓库里多出来的
大文件当成泄漏）。放仓库外面，用上面那个环境变量指过去。

实测下过两个，都在 `D:\youhuo-tts\`：

    matcha-icefall-zh-baker    139 MB   单音色女声（要配 vocos-22khz-univ.onnx，
                                        声码器在 **vocoder-models** 那个 release 下，
                                        不在 tts-models）
    kokoro-multi-lang-v1_1     407 MB   103 个音色

**Kokoro 的前三个音色是英文的**（af_maple / af_sol / bf_vale），中文从 sid 3 起，
所以这里不会默认用 0——那等于让一个英文声音念中文。详见 `__init__`。

Deliberately no `rule_fsts`: the client already rewrites dates, amounts and
times into spoken Chinese (see backend/static/speech.js), and kaldifst cannot
open files under a path containing non-ASCII characters on Windows - which the
project's own directory name does.
"""

from __future__ import annotations

import array
import hashlib
import io
import os
import sys
import threading
import wave
from collections import OrderedDict
from pathlib import Path
from typing import Any

DEFAULT_MODEL_DIR = "data/tts/vits-melo-tts-zh_en"
MAX_TEXT_CHARS = 300
CACHE_ENTRIES = 128


class NeuralVoice:
    """Lazily loaded offline TTS with a small result cache."""

    def __init__(self, root: Path, model_dir: str | None = None) -> None:
        configured = model_dir or os.getenv("YOUHUO_TTS_MODEL_DIR") or DEFAULT_MODEL_DIR
        path = Path(configured)
        self.model_dir = path if path.is_absolute() else root / path
        #: 默认发音人。多音色模型上这是「用哪个声音」，环境变量可改。
        #: 单音色模型只有 0，超范围会在合成时被夹回来。
        #:
        #: **不能一律用 0。** kokoro v1.1-zh 的打包顺序是（见上游
        #: `scripts/kokoro/v1.1-zh/generate_voices_bin.py`）：
        #:
        #:     sid 0  af_maple   英文女声
        #:     sid 1  af_sol     英文女声
        #:     sid 2  bf_vale    英式女声
        #:     sid 3+ zf_001…    中文女声，再往后 zm_009… 中文男声
        #:
        #: 也就是说 sid=0 拿英文音色念中文——听起来是外国人说中文。
        #: 实测扫过一遍基频：0/1/2 是 238/240/189 Hz 的英文女声，
        #: 中文女声从 3 开始，男声在 84 与 93 之间某处开始。
        env = os.getenv("YOUHUO_TTS_SPEAKER")
        if env:
            try:
                self.default_sid = max(0, int(env))
            except ValueError:
                self.default_sid = 0
        else:
            self.default_sid = -1        # -1 = 没指定，加载后按模型定
        self._engine: Any = None
        self._load_error: str | None = None
        self._kind_loaded: str | None = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[bytes, int]] = OrderedDict()

    # ------------------------------------------------------------- availability
    @property
    def model_present(self) -> bool:
        """目录里有没有一个能用的声学模型。

        原先只看 `model.onnx`——那对 VITS 和 Kokoro 成立，但 **matcha 的声学模型
        叫 `model-steps-3.onnx`**，于是放了一个 matcha 模型进去，
        `model_present` 仍然是 False，整条语音路径静默地不启用，
        而 `status()` 会说「模型不存在」——听起来像没下载，其实下载了。
        """
        d = self.model_dir
        if not d.is_dir():
            return False
        return (d / "model.onnx").is_file() or any(d.glob("model-steps-*.onnx"))

    _package_cache: bool | None = None

    @classmethod
    def _package_present(cls) -> bool:
        """Importing sherpa-onnx pulls in a large native library, so probe once.

        Never call this on the startup path: the import can take seconds and
        would delay the whole service coming up.
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

    @property
    def num_speakers(self) -> int:
        """这个模型有几个发音人。引擎没加载起来时回 1（保守，不谎报能挑）。"""
        engine = self._engine
        if engine is None:
            return 1
        return int(getattr(engine, "num_speakers", 1) or 1)

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "engine": "sherpa-onnx" if self._package_present() else None,
            "model": self.model_dir.name if self.model_present else None,
            # 哪一种架构。三种音质差得很远，出了问题第一件事就是问「装的是哪个」。
            "kind": self._kind() if self.model_present else None,
            "speakers": self.num_speakers,
            # `-1` 是「还没加载，等模型定」的内部哨兵，**不许漏给调用方**：
            # 客户端拿到一个不存在的音色号，回填选择器时会一个都不选中，
            # 看起来像「这个设置坏了」。没定下来之前一律报 0。
            "speaker": max(0, self.default_sid),
            "package_installed": self._package_present(),
            "model_present": self.model_present,
            "load_error": self._load_error,
            "fallback": "browser_speech_synthesis",
            "note": "离线本地合成，不联网、不上传文本；未启用时自动回落到浏览器语音。",
        }

    # ------------------------------------------------------------- 架构判定
    def _kind(self) -> str:
        """这个目录里放的是哪一种模型。

        原先这里**只认 VITS**，配置写死。而 sherpa-onnx 1.13 支持七种架构，
        中文可用的至少三种，音质差得很远：

            vits    单音色，清楚但偏平
            matcha  声学模型 + 独立声码器，中文女声自然得多
            kokoro  多音色（中文有男女多个发音人），目前最好

        按**目录里实际有什么**判断，不靠名字：模型目录是人手放的，
        改个名字很常见，而按名字猜的后果是加载一个不匹配的配置然后报
        一句看不懂的原生库错误。
        """
        d = self.model_dir
        if (d / "voices.bin").is_file():
            return "kokoro"
        if any(d.glob("model-steps-*.onnx")):
            return "matcha"
        if (d / "model.onnx").is_file():
            return "vits"
        return "unknown"

    def _first(self, *names: str) -> str:
        """按顺序找第一个存在的文件，都没有就回空串。

        sherpa-onnx 的配置项对「不存在的路径」和「空串」处理不同：
        传一个不存在的路径会在原生层报错，传空串是「这一项没有」。
        所以宁可空串。
        """
        for name in names:
            for hit in sorted(self.model_dir.glob(name)):
                if hit.exists():
                    return str(hit)
        return ""

    # ------------------------------------------------------------- synthesis
    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        import sherpa_onnx

        d = self.model_dir
        threads = max(1, min(4, (os.cpu_count() or 2) // 2))
        kind = self._kind()

        if kind == "kokoro":
            model = sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=self._first("model.onnx"),
                    voices=self._first("voices.bin"),
                    tokens=self._first("tokens.txt"),
                    data_dir=self._first("espeak-ng-data"),
                    dict_dir=self._first("dict"),
                    # 中文那一版靠词典把汉字转音素；没有它中文会被逐字念成拼音。
                    lexicon=",".join(
                        p for p in (self._first("lexicon-zh.txt"),
                                    self._first("lexicon-us-en.txt"),
                                    self._first("lexicon.txt")) if p
                    ),
                ),
                num_threads=threads,
            )
        elif kind == "matcha":
            vocoder = self._first("vocos-*.onnx", "hifigan*.onnx", "*vocoder*.onnx")
            if not vocoder:
                raise RuntimeError(
                    f"matcha 模型缺声码器：{d} 下没有 vocos-*.onnx / hifigan*.onnx。"
                    "matcha 是声学模型，单独一个 .onnx 出不了声音。"
                )
            model = sherpa_onnx.OfflineTtsModelConfig(
                matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                    acoustic_model=self._first("model-steps-*.onnx"),
                    vocoder=vocoder,
                    lexicon=self._first("lexicon.txt"),
                    tokens=self._first("tokens.txt"),
                    dict_dir=self._first("dict"),
                ),
                num_threads=threads,
            )
        elif kind == "vits":
            model = sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=self._first("model.onnx"),
                    lexicon=self._first("lexicon.txt"),
                    tokens=self._first("tokens.txt"),
                    dict_dir=self._first("dict"),
                ),
                num_threads=threads,
            )
        else:
            raise RuntimeError(
                f"认不出 {d} 里是什么模型。"
                f"目录里有：{sorted(p.name for p in d.iterdir())[:10] if d.is_dir() else '（目录不存在）'}"
            )

        self._engine = sherpa_onnx.OfflineTts(
            sherpa_onnx.OfflineTtsConfig(model=model, max_num_sentences=1)
        )
        self._kind_loaded = kind
        if self.default_sid < 0:
            # 没人指定过，按模型挑一个**说中文的**。
            # kokoro 的前三个是英文音色（见 `__init__` 那段），所以从 3 起；
            # 其它模型第一个就是它唯一/主要的声音。
            self.default_sid = 3 if (kind == "kokoro" and self.num_speakers > 3) else 0
        return self._engine

    @staticmethod
    def _to_wav(samples: Any, sample_rate: int) -> bytes:
        # array.tobytes() converts the whole block in C; building one bytes
        # object per sample instead cost seconds on a few seconds of audio.
        pcm = array.array("h", (max(-32768, min(32767, int(value * 32767))) for value in samples))
        if sys.byteorder == "big":
            pcm.byteswap()
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())
        return buffer.getvalue()

    def warm_up_async(self) -> None:
        """Load the model in the background so the first spoken turn is not slow.

        Loading costs several seconds; doing it lazily would put that delay in
        front of the elder's first reply. No-op when the voice is unavailable.
        """
        # Only the cheap filesystem check runs here. Probing for the package
        # imports a native library, so that happens inside the thread too.
        if self._engine is not None or not self.model_present:
            return

        def _load() -> None:
            try:
                if not self.available:
                    return
                with self._lock:
                    self._ensure_engine()
            except Exception as exc:  # noqa: BLE001 - stay optional, never fatal
                self._load_error = str(exc)[:300]

        threading.Thread(target=_load, name="youhuo-tts-warmup", daemon=True).start()

    def synthesize(self, text: str, speed: float = 1.0, sid: int | None = None) -> tuple[bytes, int]:
        """Return (wav_bytes, sample_rate). Raises RuntimeError when unavailable.

        `sid` 是发音人编号。原先这里**写死 `sid=0`**——单音色模型上看不出问题，
        换成多音色模型（Kokoro 中文有男女多个发音人）就等于永远只能听第一个，
        而「换个好听点的声音」恰恰是要换这个。
        """
        if not self._package_present():
            raise RuntimeError("sherpa-onnx 未安装")
        if not self.model_present:
            raise RuntimeError(f"未找到语音模型：{self.model_dir}")
        cleaned = (text or "").strip()[:MAX_TEXT_CHARS]
        if not cleaned:
            raise RuntimeError("待合成文本为空")
        speed = max(0.5, min(2.0, float(speed)))
        speaker = max(0, self.default_sid) if sid is None else int(sid)

        # 缓存键要带上发音人。不带的话换了音色还会命中上一个音色的缓存——
        # 而那个错误的表现是「我明明换了声音，它还是原来那个」，
        # 听起来像是换音色这个功能根本没做。
        key = hashlib.sha256(
            f"{speaker}|{speed:.2f}|{cleaned}".encode("utf-8")
        ).hexdigest()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
            try:
                engine = self._ensure_engine()
                total = getattr(engine, "num_speakers", 1) or 1
                if not 0 <= speaker < total:
                    speaker = self.default_sid if 0 <= self.default_sid < total else 0
                audio = engine.generate(cleaned, sid=speaker, speed=speed)
            except Exception as exc:  # noqa: BLE001 - degrade instead of failing the turn
                self._load_error = str(exc)[:300]
                raise RuntimeError(f"语音合成失败：{self._load_error}") from exc
            result = (self._to_wav(audio.samples, audio.sample_rate), audio.sample_rate)
            self._cache[key] = result
            while len(self._cache) > CACHE_ENTRIES:
                self._cache.popitem(last=False)
            return result
