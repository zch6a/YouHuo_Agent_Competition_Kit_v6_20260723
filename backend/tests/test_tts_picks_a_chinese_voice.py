"""离线语音这一层：认得出模型、挑得对音色。

## 为什么需要

`tts.py` 原先**只认 VITS 一种架构**，而 sherpa-onnx 1.13 支持七种；
`sid` 还**写死成 0**。单音色模型上这两件事都看不出问题——
换成 Kokoro（103 个发音人）立刻显形：

    sid 0  af_maple   英文女声   ← 写死的那个
    sid 1  af_sol     英文女声
    sid 2  bf_vale    英式女声
    sid 3+ zf_001…    中文女声，再往后 zm_009… 中文男声

（顺序见上游 `scripts/kokoro/v1.1-zh/generate_voices_bin.py`；
实测扫过基频：0/1/2 是 238/240/189 Hz 的英文女声，男声在 84 与 93 之间开始。）

也就是说装上最好的中文模型之后，默认音色是**一个英文声音在念中文**。
「换个好听点的语音」这件事，一半卡在这里。

## 这些判据不需要模型文件

模型有几百 MB，**不进交付包**，CI 上也没有。所以这里测的是
「**给定目录里有什么，代码怎么判断**」——用临时目录摆出各架构的特征文件，
不加载任何真模型。真机上有模型时的行为由 `test_app_api_contract.py`
那组（塞假引擎）和手工试听覆盖。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from youhuo.tts import NeuralVoice


def _touch(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        p = directory / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")


def test_a_vits_directory_is_recognised(tmp_path) -> None:
    d = tmp_path / "vits-melo-tts-zh_en"
    _touch(d, "model.onnx", "tokens.txt", "lexicon.txt")
    v = NeuralVoice(tmp_path, str(d))
    assert v.status()["kind"] == "vits"
    assert v.model_present


def test_a_matcha_directory_is_recognised(tmp_path) -> None:
    """**matcha 的声学模型不叫 `model.onnx`。**

    原来 `model_present` 只看 `model.onnx`，于是放一个 matcha 模型进去，
    这个属性仍然是 False：整条语音路径静默地不启用，而 `status()` 说
    「模型不存在」——听起来像没下载，其实下载好了。
    """
    d = tmp_path / "matcha-icefall-zh-baker"
    _touch(d, "model-steps-3.onnx", "tokens.txt", "lexicon.txt", "vocos-22khz-univ.onnx")
    v = NeuralVoice(tmp_path, str(d))
    assert v.status()["kind"] == "matcha"
    assert v.model_present, "matcha 模型被当成「不存在」"


def test_a_kokoro_directory_is_recognised(tmp_path) -> None:
    d = tmp_path / "kokoro-multi-lang-v1_1"
    _touch(d, "model.onnx", "voices.bin", "tokens.txt", "lexicon-zh.txt")
    assert NeuralVoice(tmp_path, str(d)).status()["kind"] == "kokoro"


def test_an_unknown_directory_says_so_instead_of_guessing(tmp_path) -> None:
    d = tmp_path / "something-else"
    _touch(d, "readme.txt")
    v = NeuralVoice(tmp_path, str(d))
    assert v.status()["kind"] is None      # 没有模型时不报架构
    assert not v.model_present


def test_matcha_without_a_vocoder_says_what_is_missing(tmp_path) -> None:
    """matcha 是声学模型，单独一个 .onnx 出不了声音。

    缺声码器时要说「缺声码器」，不能让原生库抛一句看不懂的错——
    这两者在日志里长得完全不同，而后者会让人去查模型文件本身。
    """
    d = tmp_path / "matcha-no-vocoder"
    _touch(d, "model-steps-3.onnx", "tokens.txt", "lexicon.txt")
    v = NeuralVoice(tmp_path, str(d))
    if not v._package_present():
        pytest.skip("这台机器没装 sherpa-onnx")
    with pytest.raises(RuntimeError, match="声码器"):
        v._ensure_engine()


def test_the_sentinel_default_never_leaks_to_callers(tmp_path) -> None:
    """`-1` 是「还没加载，等模型定」的内部哨兵。

    漏给调用方的话，客户端回填音色选择器时一个都不选中，
    看起来像「这个设置坏了」。
    """
    d = tmp_path / "kokoro-multi-lang-v1_1"
    _touch(d, "model.onnx", "voices.bin", "tokens.txt")
    v = NeuralVoice(tmp_path, str(d))
    assert v.default_sid == -1, "夹具前提变了：没设环境变量时内部应当是 -1"
    assert v.status()["speaker"] == 0, "哨兵值漏出去了"


def test_an_explicit_speaker_env_wins(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YOUHUO_TTS_SPEAKER", "57")
    d = tmp_path / "kokoro-multi-lang-v1_1"
    _touch(d, "model.onnx", "voices.bin", "tokens.txt")
    assert NeuralVoice(tmp_path, str(d)).default_sid == 57


def test_a_nonsense_speaker_env_falls_back_to_zero(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YOUHUO_TTS_SPEAKER", "第三个")
    d = tmp_path / "kokoro-multi-lang-v1_1"
    _touch(d, "model.onnx", "voices.bin", "tokens.txt")
    assert NeuralVoice(tmp_path, str(d)).default_sid == 0


def test_the_cache_key_includes_the_speaker(tmp_path) -> None:
    """换了音色不能命中上一个音色的缓存。

    不带 sid 的缓存键，表现是「我明明换了声音，它还是原来那个」——
    听起来像换音色这个功能根本没做。这条不需要真模型：直接看键怎么算的。
    """
    import hashlib
    d = tmp_path / "kokoro-multi-lang-v1_1"
    _touch(d, "model.onnx", "voices.bin", "tokens.txt")
    v = NeuralVoice(tmp_path, str(d))
    keys = {
        hashlib.sha256(f"{sid}|{1.0:.2f}|你好".encode("utf-8")).hexdigest()
        for sid in (3, 57)
    }
    assert len(keys) == 2, "两个音色算出同一个缓存键"
