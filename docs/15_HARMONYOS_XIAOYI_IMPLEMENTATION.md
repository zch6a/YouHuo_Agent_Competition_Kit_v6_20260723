# 15｜HarmonyOS 与小艺落地路线

## 1｜应用形态

- HarmonyOS 老人端：大字、语音、任务进度、取消/求助、信任中心；
- HarmonyOS 家属端：待办、审批、共识、通知；
- 小艺 Agent：自然语言入口；
- Skill：任务安全、陪伴隐私、文档防火墙可组合；
- 端A2A：长时任务伴随、状态胶囊、用户干预和界面操控伴随。

## 2｜端A2A映射

| 官方概念 | 优活 |
|---|---|
| Context | 老人一次连续会话 |
| Task | 挂号/缴费/提醒/陪伴单元 |
| input_required | 等待老人补充或家属批准 |
| working | 工具执行/核验 |
| completed | 完成证明通过 |
| failed | 工具/证据失败 |
| cancelled | 老人主动取消 |
| Artifact | 确认卡、进度、完成证明、家属接管通知 |

## 3｜Skill组合

- `youhuo-task-guard`：风险、确认、工具和核验；
- `wuyou-companion-privacy`：陪伴角色、隐私和安全切换；
- `youhuo-document-firewall`：OCR/VLM白名单抽取和注入阻断。

这些文件是平台重建依据，不冒充官方导出包。

## 4｜真机联调清单

1. 在队伍本机创建匹配SDK的工程；
2. 复制ArkTS页面和资源，修复API差异；
3. Account Kit登录和家庭绑定；
4. 官方ASR/TTS；
5. Push Kit和日历；
6. HTTPS后端及证书；
7. 小艺Agent/Skill/A2A测试态；
8. 手机/平板/手表测试；
9. 关闭演示令牌；
10. 保存构建日志、HAP和真机录像。
