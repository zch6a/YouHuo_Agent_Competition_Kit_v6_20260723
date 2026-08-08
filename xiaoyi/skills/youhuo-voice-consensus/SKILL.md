# YouHuo Voice Consensus Skill

## Purpose
将多个 ASR N-best 候选合并为一个可审计结果；对支付、挂号、身份等副作用场景采用更高阈值，候选冲突时必须澄清。

## Inputs
- `elder_id`
- 1–8 个带置信度、引擎和语言标识的转写候选
- 当前任务与是否可能产生副作用

## Outputs
- accepted / clarify / blocked
- 语义意图、歧义度、安全标志、共识摘要

## Policy
- 紧急表达优先保留并进入安全流程。
- 确认与取消、金额或日期发生冲突时不得猜测。
- 该 Skill 只解析语音，不直接调用支付、挂号或身份工具。
