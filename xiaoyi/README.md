# 小艺开放平台接入蓝图 v6

本目录提供可审查的接入依据，不冒充从小艺后台导出的官方工程。

## 内容

- `plugin_openapi_v6.generated.json`：由运行中的FastAPI自动生成，89个路径；
- `workflows/youhuo_workflow.json`：v6平台中立工作流；
- `skills/*/SKILL.md`：13个任务、隐私、安全、健康、位置、语音、策略、Saga、认知负荷、信任卡和安全预演Skill；
- `a2a/agent_card.json`：Context/Task/Artifact/Part能力声明；
- `prompts/`：办事和陪伴角色提示；
- `prompts/evaluation_cases.jsonl`：平台评测样例。

## v6控制顺序

```text
N-best语音共识
→ 紧急/诈骗预检
→ 受约束语义网关
→ 适老认知负荷治理
→ 模式与任务锁
→ 目的绑定策略
→ 安全动作预演
→ 老人/家属人工门
→ 权威工具与Saga
→ 最终状态证明
→ 玻璃盒信任卡
→ 语音输出与知情同意评测记录
```

## 推荐正式接入顺序

1. 在小艺开放平台创建测试态Agent；
2. 使用队伍HTTPS服务导入/重建插件；
3. 按v6工作流逐节点实现，不能把权限判断只写在Prompt；
4. 创建并组合13个Skill；
5. 按端A2A规范映射长时任务状态、用户干预和伴随态；
6. 接入Core Speech等官方能力；
7. 覆盖语音冲突、OCR冲突、越权、工具失败和恢复；
8. 保存平台调试日志、审核截图和真机视频。

高风险支付、身份秘密和陪聊披露在通用MCP/插件层默认禁止。正式上线前必须替换演示认证和沙箱服务。
