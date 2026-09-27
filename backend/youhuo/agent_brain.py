"""小优的大脑：大模型负责「听懂、决定查什么、决定交给谁」，引擎负责「拍板」。

## 为什么要有这一层

赛题（Agent 创新方向）的三大核心是个人日常生活陪伴、主动服务、自然交互。
在这一层之前，线上 `/health` 写的是 `semantic_mode: deterministic_only`——
队友手机上演示的整条对话里没有任何模型：认不出来的话一律回一句固定菜单，
无忧伴的陪聊是模板。

## 三条硬规矩（每一条都有判据钉着）

1. **模型不能授权。** 挂号、缴费、设提醒、填表这类有后果的事，模型只能调
   `start_errand` 把一句话交回确定性引擎；那边照旧走收集 -> 复述确认 -> 家人接力。
   模型拿不到任何能直接改状态的工具。
2. **事实走原话。** 模型一旦调了查询工具（今天的安排、药吃了没、账单……），
   她听到的就是工具返回的**原句**，不经模型转述。模型自己的措辞只用在不涉及
   事实的闲聊和陪伴上——它没有机会把「还差一次药」说成「药都吃过了」。
3. **挂了就退。** 没配、超时、熔断、返回空、输出不合规，一律返回 `None`，
   调用方照原来的路走。对话主链不许被这一层拖垮。

## 延迟

2026-09-23 实测：deepseek-flash + `thinking` 关掉、带工具定义，一轮 1.1 秒
（默认 2.2 秒）。所以每句话**最多只调一轮**模型：查询类的事实直接用工具原句，
不再回一轮让模型组织语言——既快，又落实了第 2 条。

## 隐私

发给模型的只有：这一句话、同一会话里最近几轮（**只在内存里，不落库**，
`YOUHUO_AGENT_HISTORY_TURNS=0` 可关）、以及她问到的那几条工具结果。
审计链里只记用了哪些工具、耗时、交给了哪类差事——**不记原话**。
`/health` 写明文本发往哪个服务商，不藏。

## 怎么打开

只认显式的 `YOUHUO_AGENT_API_KEY`。**刻意不读** `YOUHUO_LLM_KEY`（桌面小优用的
那个）和 `LLM_*`（旧的语义路由顾问）：前者在开发机上常驻，读它会让整套测试
悄悄去打真模型；后者一打开就会让**每一句**话都多等一轮模型。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

#: 模型可以交回引擎的四类差事，和 `models.TaskType` 的取值一一对应。
ERRAND_KINDS: tuple[str, ...] = (
    "hospital_registration", "bill_payment", "reminder", "form_assistance",
)

#: 查询类工具：名字 -> 给模型看的说明。执行者由调用方（引擎）提供。
#: 每一个都必须在引擎的 `_agent_fact` 里有实现——判据按这张表逐个核对。
FACT_TOOLS: dict[str, str] = {
    "schedule_today": "查她今天接下来有什么安排和提醒",
    "medication_today": "查她今天的药吃了没有、还差几次",
    "medication_list": "查她长期在吃哪些药",
    "medication_stock": "查她的药还够吃几天（可以说药名）",
    "health_recent": "查最近记下的血压、血糖等身体数据",
    "family_contacts": "查能联系上的家人是谁",
    "today_date": "查今天几月几号、星期几、现在几点",
    "unpaid_bills": "查还没缴的水费、电费、燃气费",
}

#: 可选参数：只有 `medication_stock` 收一个药名。
_FACT_PARAMS: dict[str, dict[str, Any]] = {
    "medication_stock": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "药名，可以不填"}},
    },
}

#: 陪聊时不许出现的**建议型**说法。这一层不做医疗判断，看到就退回模板。
_MEDICAL_ADVICE = ("服用", "剂量", "处方", "确诊", "诊断", "加量", "减量", "停药", "吃点药")

_ENGLISH = re.compile(r"[A-Za-z_]{4,}")
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF️‍]"
)
_SENTENCE = re.compile(r"[^。！？!?]+[。！？!?]?")


@dataclass(frozen=True)
class FactResult:
    """一条查询工具的结果。`message` 就是要**原样**念给她听的那句话。"""

    message: str


@dataclass(frozen=True)
class AgentReply:
    message: str | None
    handoff_kind: str | None = None
    handoff_utterance: str | None = None
    tools: tuple[str, ...] = ()
    latency_ms: int = 0
    #: model = 模型自己的话（闲聊/陪伴）；facts = 工具原句；handoff = 交回引擎
    source: str = "model"


@dataclass(frozen=True)
class AgentConfig:
    base_url: str
    api_key: str
    model: str
    timeout_s: float
    history_turns: int

    @classmethod
    def from_env(cls) -> "AgentConfig | None":
        key = os.getenv("YOUHUO_AGENT_API_KEY", "").strip()
        if not key:
            return None
        if os.getenv("YOUHUO_AGENT", "on").strip().casefold() in {"0", "off", "false", "no"}:
            return None
        try:
            timeout = float(os.getenv("YOUHUO_AGENT_TIMEOUT_S", "12"))
            turns = int(os.getenv("YOUHUO_AGENT_HISTORY_TURNS", "3"))
        except ValueError:
            timeout, turns = 12.0, 3
        return cls(
            base_url=os.getenv("YOUHUO_AGENT_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            api_key=key,
            model=os.getenv("YOUHUO_AGENT_MODEL", "deepseek-flash"),
            timeout_s=max(1.0, min(timeout, 60.0)),
            history_turns=max(0, min(turns, 10)),
        )

    @property
    def provider_host(self) -> str:
        return urlparse(self.base_url).hostname or self.base_url


Transport = Callable[[dict[str, Any]], dict[str, Any]]
RunFact = Callable[[str, dict[str, Any]], "FactResult | None"]


class AgentBrain:
    MAX_FAILURES = 3
    OPEN_SECONDS = 60.0
    MAX_REPLY_CHARS = 90
    HISTORY_SESSIONS = 512

    def __init__(self, config: AgentConfig, transport: Transport | None = None) -> None:
        self.config = config
        self._transport = transport or self._http_transport
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_until = 0.0
        self._history: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
        self.calls = 0
        self.fallbacks = 0
        self.retries = 0
        self.last_latency_ms: int | None = None

    @classmethod
    def from_env(cls) -> "AgentBrain | None":
        config = AgentConfig.from_env()
        return cls(config) if config else None

    # ------------------------------------------------------------------ 状态
    def status(self) -> dict[str, Any]:
        with self._lock:
            open_ = time.monotonic() < self._opened_until
        return {
            "enabled": True,
            "model": self.config.model,
            "provider_host": self.config.provider_host,
            "sends_text_to_provider": True,
            "history_turns_in_memory": self.config.history_turns,
            "circuit_open": open_,
            "calls": self.calls,
            "fallbacks": self.fallbacks,
            "empty_retries": self.retries,
            "last_latency_ms": self.last_latency_ms,
            "facts_verbatim": True,
            "model_can_authorize": False,
        }

    def forget(self, session_id: str) -> None:
        with self._lock:
            self._history.pop(session_id, None)

    # ------------------------------------------------------------------ 主入口
    def respond(
        self,
        *,
        session_id: str,
        text: str,
        companion: bool,
        now_text: str,
        display_name: str,
        run_fact: RunFact,
    ) -> AgentReply | None:
        """一句话进来，最多调一轮模型。返回 `None` 表示「照原来的路走」。"""
        if not self._circuit_ok():
            self.fallbacks += 1
            return None
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(companion, now_text, display_name)},
            *self._recall(session_id),
            {"role": "user", "content": text[:500]},
        ]
        body = {
            "model": self.config.model,
            "messages": messages,
            "tools": self._tool_defs(),
            "temperature": 0.4,
            "max_tokens": 400,
            # 推理模型默认先想一段；关掉之后一轮从 2.2 秒降到 1.1 秒（实测）。
            "thinking": {"type": "disabled"},
        }
        started = time.monotonic()
        self.calls += 1
        try:
            data = self._transport(body)
            message = data["choices"][0]["message"]
            # 回了个空：没话、也没调工具。09-24 实测一阵子 8 次里 7 次这样，同一脚本
            # 两天后 8/8 正常——是服务商那边一阵一阵的。赶上了老人就等几秒拿到固定菜单。
            # 原样再问**一次**；内容被 `_clean` 拦下的那种不重试（那是有意的拒绝）。
            if not message.get("tool_calls") and not str(message.get("content") or "").strip():
                self.retries += 1
                data = self._transport(body)
                message = data["choices"][0]["message"]
        except Exception:
            self._record_failure()
            self.fallbacks += 1
            return None
        latency = int((time.monotonic() - started) * 1000)
        self.last_latency_ms = latency
        self._record_success()

        facts: list[str] = []
        used: list[str] = []
        for call in (message.get("tool_calls") or [])[:4]:
            fn = call.get("function") or {}
            name = str(fn.get("name") or "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            if not isinstance(args, dict):
                args = {}
            if name == "start_errand":
                kind = args.get("kind")
                utterance = self._clean_utterance(args.get("utterance"))
                if kind in ERRAND_KINDS and utterance:
                    self._remember(session_id, text, None)
                    return AgentReply(
                        message=None, handoff_kind=str(kind), handoff_utterance=utterance,
                        tools=tuple(used + ["start_errand"]), latency_ms=latency,
                        source="handoff",
                    )
                continue
            if name not in FACT_TOOLS:
                continue
            try:
                result = run_fact(name, args)
            except Exception:
                result = None
            if result is not None and result.message:
                facts.append(result.message.strip())
                used.append(name)

        if facts:
            # 第 2 条规矩：查到的事实原样念，模型这一轮写的话不用。
            said = " ".join(dict.fromkeys(facts))
            self._remember(session_id, text, said)
            return AgentReply(message=said, tools=tuple(used), latency_ms=latency, source="facts")

        content = self._clean(message.get("content"))
        if content is None:
            self.fallbacks += 1
            return None
        self._remember(session_id, text, content)
        return AgentReply(message=content, tools=tuple(used), latency_ms=latency, source="model")

    # ------------------------------------------------------------------ 提示词与工具
    @staticmethod
    def _system_prompt(companion: bool, now_text: str, display_name: str) -> str:
        who = display_name or "老人"
        lines = [
            f"你是「小优」，{who}身边的生活助手，住在优活 App 里。现在是{now_text}。",
            "",
            "怎么说话：",
            "- 口语、温和、简短；一次最多两句话，不超过六十个字；称呼对方用「您」。",
            "- 不用英文，不用表情符号，不用列表、星号或标题。",
            "",
            "你能做的事：",
            "- 想知道她的安排、用药、身体数据、账单、家人、今天日期，就调用对应的查询工具。"
            "不要凭记忆或猜测说这些事实。",
            "- 挂号、缴费、设提醒、填表，调用 start_errand，把她的意思改写成一句她会说的话，"
            "保留日期、时间、名称。你不能替她确认或办理，也不能声称事情已经办好。",
            "- 区分查询和行动：问有什么账单才查询账单；说替我处理账单就是办理意图。"
            "想找大夫、想去医院看一看属于挂号意图，不要只查身体记录和联系人就结束。"
            "行动意图优先调用 start_errand；缺少医院、时间、账单种类，由办事流程追问，不能猜。"
            "utterance 应明确包含挂号、缴费、提醒或填表之一，但不得添加对方没说的科室、金额和授权。",
            "- 别的时候就陪她聊天：先接住她的话，再轻轻问一个问题。",
            "",
            "不能做的事：",
            "- 不给用药、诊断、剂量方面的建议；身体不舒服就请她告诉家里人或医生。",
            "- 不承诺你做不到的事，不编造没有查到的信息。",
        ]
        if companion:
            lines += [
                "",
                "现在是「无忧伴」陪伴模式：她想找人说说话。多听少说，别急着给建议，"
                "别把话题拉回办事；她说到的人和事，接下来的对话里要记得。",
            ]
        return "\n".join(lines)

    @staticmethod
    def _tool_defs() -> list[dict[str, Any]]:
        defs: list[dict[str, Any]] = [
            {"type": "function", "function": {
                "name": name, "description": desc,
                "parameters": _FACT_PARAMS.get(name, {"type": "object", "properties": {}}),
            }}
            for name, desc in FACT_TOOLS.items()
        ]
        defs.append({"type": "function", "function": {
            "name": "start_errand",
            "description": "把一件有后果的事交给办事流程（挂号/缴费/设提醒/填表），"
                           "由她本人确认后才会办。utterance 写成她会说的一句话。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(ERRAND_KINDS)},
                    "utterance": {"type": "string"},
                },
                "required": ["kind", "utterance"],
            },
        }})
        return defs

    # ------------------------------------------------------------------ 输出把关
    @classmethod
    def _clean(cls, content: Any) -> str | None:
        """模型自己的话：不合规就返回 None，让调用方退回模板。"""
        if not isinstance(content, str):
            return None
        s = re.sub(r"[*#`>~]", "", content)
        s = _EMOJI.sub("", s)
        s = re.sub(r"\s+", " ", s).strip()
        if not s:
            return None
        if _ENGLISH.search(s):
            return None
        if any(word in s for word in _MEDICAL_ADVICE):
            return None
        # 这个项目对老人一律用「您」。「你们」「迷你」不是称呼，留着。
        s = re.sub(r"(?<!迷)你(?!们)", "您", s)
        s = "".join(_SENTENCE.findall(s)[:2]).strip()
        if len(s) > cls.MAX_REPLY_CHARS:
            s = s[: cls.MAX_REPLY_CHARS].rstrip("，、,；; ")
        if s and s[-1] not in "。！？!?":
            s += "。"
        return s or None

    @staticmethod
    def _clean_utterance(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        s = re.sub(r"\s+", "", value)[:80]
        return s or None

    # ------------------------------------------------------------------ 短期记忆（只在内存）
    def _recall(self, session_id: str) -> list[dict[str, str]]:
        if self.config.history_turns <= 0:
            return []
        with self._lock:
            return list(self._history.get(session_id, []))

    def _remember(self, session_id: str, user_text: str, reply: str | None) -> None:
        if self.config.history_turns <= 0:
            return
        with self._lock:
            turns = self._history.pop(session_id, [])
            turns.append({"role": "user", "content": user_text[:500]})
            if reply:
                turns.append({"role": "assistant", "content": reply})
            self._history[session_id] = turns[-2 * self.config.history_turns:]
            while len(self._history) > self.HISTORY_SESSIONS:
                self._history.popitem(last=False)

    # ------------------------------------------------------------------ 熔断
    def _circuit_ok(self) -> bool:
        with self._lock:
            return time.monotonic() >= self._opened_until

    def _record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.MAX_FAILURES:
                self._opened_until = time.monotonic() + self.OPEN_SECONDS
                self._failures = 0

    def _record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_until = 0.0

    # ------------------------------------------------------------------ 传输
    def _http_transport(self, body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.config.timeout_s, trust_env=True) as client:
            response = client.post(
                f"{self.config.base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self.config.api_key}"},
            )
            response.raise_for_status()
            return response.json()
