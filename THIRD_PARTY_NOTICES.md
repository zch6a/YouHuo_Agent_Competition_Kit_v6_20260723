# Third-party notices

本包的比赛原型代码为独立实现，没有复制或 vendor 下列项目源码。相关工作仅用于架构、威胁模型、评测和人本设计借鉴：

- LangGraph：durable execution、human-in-the-loop 和状态恢复；
- LiveKit Agents：实时、多模态语音 Agent 的工程接口思路；
- Open Policy Agent：policy-as-code 与策略/执行分离；
- Temporal：长流程工作流、重试、幂等和补偿思想；
- CaMeL：不可信数据与控制流隔离、能力约束；
- AgentDojo / Agent-SafetyBench：提示注入、工具越权和系统化安全评测；
- HarmonyOS AI / 小艺 Skill / 端 A2A：系统级入口与长时任务协议映射；
- 老年语音助手共创研究：自主权、隐私、解释、低认知负担和社会支持。

## 已锁定依赖

| Package | Version | License family |
|---|---:|---|
| FastAPI | 0.128.2 | MIT |
| Uvicorn | 0.48.0 | BSD-3-Clause |
| Pydantic | 2.13.4 | MIT |
| HTTPX | 0.28.1 | BSD-3-Clause |
| pytest | 9.0.2 | MIT |
| coverage.py | 7.13.3 | Apache-2.0 |
| PyYAML | 6.0.3 | MIT |

`mcp/optional_fastmcp_server.py` 是可选示例，不属于验证核心。启用任何MCP/语音/模型/HarmonyOS SDK前，应单独核查版本、许可证、数据处理条款和权限，不能静默扩大高风险工具能力。

公开提交前必须重新生成精确部署镜像的软件成分报告。不得把真实身份证、支付、医疗、位置、声纹、照片、认证令牌或用户研究原始数据放入公开压缩包。
