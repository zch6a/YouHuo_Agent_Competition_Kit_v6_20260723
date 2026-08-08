"""Optional offline neural voice.

The service never requires this. When `sherpa-onnx` and a model directory are
both present the elder client gets a natural Chinese voice; otherwise it falls
back to the browser's own speech synthesis and everything else is unchanged.
That mirrors how the language model is treated: an upgrade when configured,
never a dependency, never a source of authority.

Enable it with:

    pip install sherpa-onnx
    # download a model, e.g. vits-melo-tts-zh_en, into data/tts/
    export YOUHUO_TTS_MODEL_DIR=data/tts/vits-melo-tts-zh_en

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
        self._engine: Any = None
        self._load_error: str | None = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[bytes, int]] = OrderedDict()

    # ------------------------------------------------------------- availability
    @property
    def model_present(self) -> bool:
        return (self.model_dir / "model.onnx").is_file()

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

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "engine": "sherpa-onnx" if self._package_present() else None,
            "model": self.model_dir.name if self.model_present else None,
            "package_installed": self._package_present(),
            "model_present": self.model_present,
            "load_error": self._load_error,
            "fallback": "browser_speech_synthesis",
            "note": "离线本地合成，不联网、不上传文本；未启用时自动回落到浏览器语音。",
        }

    # ------------------------------------------------------------- synthesis
    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        import sherpa_onnx

        directory = self.model_dir
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(directory / "model.onnx"),
                    lexicon=str(directory / "lexicon.txt"),
                    tokens=str(directory / "tokens.txt"),
                    dict_dir=str(directory / "dict"),
                ),
                num_threads=max(1, min(4, (os.cpu_count() or 2) // 2)),
            ),
            max_num_sentences=1,
        )
        self._engine = sherpa_onnx.OfflineTts(config)
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

    def synthesize(self, text: str, speed: float = 1.0) -> tuple[bytes, int]:
        """Return (wav_bytes, sample_rate). Raises RuntimeError when unavailable."""
        if not self._package_present():
            raise RuntimeError("sherpa-onnx 未安装")
        if not self.model_present:
            raise RuntimeError(f"未找到语音模型：{self.model_dir}")
        cleaned = (text or "").strip()[:MAX_TEXT_CHARS]
        if not cleaned:
            raise RuntimeError("待合成文本为空")
        speed = max(0.5, min(2.0, float(speed)))

        key = hashlib.sha256(f"{speed:.2f}|{cleaned}".encode("utf-8")).hexdigest()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
            try:
                engine = self._ensure_engine()
                audio = engine.generate(cleaned, sid=0, speed=speed)
            except Exception as exc:  # noqa: BLE001 - degrade instead of failing the turn
                self._load_error = str(exc)[:300]
                raise RuntimeError(f"语音合成失败：{self._load_error}") from exc
            result = (self._to_wav(audio.samples, audio.sample_rate), audio.sample_rate)
            self._cache[key] = result
            while len(self._cache) > CACHE_ENTRIES:
                self._cache.popitem(last=False)
            return result
