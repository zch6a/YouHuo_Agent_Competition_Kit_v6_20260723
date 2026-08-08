# 14｜ElderBench-v3

## 目标

评估一个适老办事Agent是否同时满足：办成事、不中断、不过权、能恢复、保护隐私、结果可验证。

## 数据格式

`evaluation/elderbench_v3.jsonl` 每行包含：

- `case_id/category/input`
- `expected` 安全或状态不变量
- `rationale` 场景原因

运行：

```bash
PYTHONPATH=backend python backend/scripts/run_elderbench.py
```

## 类别

- `task_interleaving`：办事与闲聊；
- `safety`：诈骗、紧急、注入；
- `document`：账单/预约/药品；
- `delegation`：自主等级和家属数量；
- `ambiguity`：缺失信息和自我修正。

## 300k 大规模审计组成

包含完整状态化支付、挂号、提醒、任务锁、同意记忆，以及任务混合、风险策略、完成证明、工具模式、文档、注入、Unicode、时间、幂等、HMAC和DAG性质测试。原始分类和数量以 `reports/mass_audit_v3_300000.json` 为准。

## 不能替代的测试

ElderBench不能证明真实方言ASR、真机权限、真实医院/支付API、长期陪伴效果或真实老人信任。它用于回归核心机制，不用于夸大现实效果。
