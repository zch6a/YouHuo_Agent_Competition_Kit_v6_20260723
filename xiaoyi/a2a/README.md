# 小艺端A2A语义映射

本目录不是官方平台导出文件，而是根据公开端A2A概念整理的接入蓝图。

- Context：一次连续老人会话；
- Task：一个挂号、缴费、提醒、文档或陪伴任务；
- Artifact：任务摘要、确认卡、家属接力、完成证明、安全通知；
- Part：文本、卡片、状态胶囊或接管指令；
- input_required：等待老人补充/确认或家属审批；
- working：执行和核验；
- completed：Proof of Completion通过；
- failed：工具或证据失败；
- cancelled：老人明确取消。

正式接入时必须按官方最新协议、应用身份、contextId/taskId生命周期、异常码和签名要求实现。

## v5 映射

- Context：同一家庭/老人会话；登录变化时失效。
- Task：一个可恢复 Saga；`TASK_STATE_INPUT_REQUIRED` 用于老人澄清、老人确认、家属批准和高敏感同步冲突。
- Artifact：语音澄清卡、目的绑定决策卡、Saga 进度、破窗通知、完成证明。
- Part：文本、状态胶囊、确认按钮、错误码和最小化数据摘要。

通用 A2A/MCP 客户端不拥有支付、身份秘密或无条件远程接管能力。高风险状态变化只允许权威后端在验证家庭绑定、角色、版本和确认后执行。

## `capabilities` 这四条是硬断言，逐条量过

`artifacts` 那一串是概念标签（这份是接入蓝图，不是平台导出件），
而 `capabilities` 不是标签——它是对协议能力的是/否断言，A2A 对端会据此
决定要不要按流式去收。所以四条逐条驱动量过：

| 宣布 | 实测 |
|---|---|
| `streaming` | **`false`**。全仓 0 个流式端点、0 个 WebSocket 路由，源码里没有 `StreamingResponse` / `EventSourceResponse` / `text/event-stream` |
| `long_running_tasks` | 真。`/v5/sagas` 在契约里，可恢复长事务是实现了的 |
| `user_intervention` | 真。一笔缴费实测停在 `need_elder_confirmation` |
| `ui_companion` | 真。说「我想找人说说话」之后 `mode` 实测变成 `companion` |

`streaming` 原先写的是 `true`。那是一句**代码并不具备的能力**，而且
这个仓库自己在另一处早就把它否掉了——`backend/youhuo/v4_models.py`
那段说明「远程协助这一版交付不了」的理由第一条就是：

    **没有服务端到老人设备的通道。** …全仓运行时没有 WebSocket、
    没有 SSE、没有推送（`websocket` 只出现在 CDP 巡检脚本里）。

两份文档互相矛盾，而对端会信名片那一份：它会去订阅一个永远不来的流。

判据 `test_the_agent_card_only_claims_what_it_can_do.py` 把这四条各钉到
一次**实测**上——哪天真的做了流式，把这里改回 `true`，那条判据会跟着变绿；
在那之前改回去就会红。
