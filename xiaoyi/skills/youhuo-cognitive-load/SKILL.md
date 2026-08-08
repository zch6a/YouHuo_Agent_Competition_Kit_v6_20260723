# youhuo-cognitive-load

## Purpose
把复杂办事信息改写成老人易理解的一次一问交互。根据风险、语音置信度、重试次数和个人设置，限制每轮句长与选项数量。

## Inputs
- elder_id
- message
- options
- risk_level
- asr_confidence
- recent_retries
- reversible

## Outputs
- speak_text / visual_text
- visible_options
- require_teach_back
- cognitive_load_score
- next_expected_response

## Invariants
- 高风险任务不得仅以“是/否”完成确认，应要求复述关键对象、金额或时间。
- 语音置信度不足时先澄清，不能猜测。
- 每轮最多展示三个选项；高风险或连续失败时最多一个。

## Policy
- 本Skill只改变表达负荷，不改变权限、风险等级或工具参数。
- 家属不能替老人关闭高风险复述确认。
