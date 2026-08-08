# YouHuo Emergency Break-Glass Skill

## Purpose
在明确紧急、老人无法响应时，允许绑定家属获得短时、最小范围的救援信息。

## Allowed scopes
`location`、`health_summary`、`emergency_contacts`、`active_tasks`。

## Forbidden scopes
无忧伴聊天原文、支付凭据、身份秘密、完整医疗档案。

## Policy
- 仅绑定家属可发起；必须填写理由和有效期。
- 默认 15 分钟，最长 60 分钟，自动过期且全程审计。
- 老人端和其他家属会收到破窗访问通知。
- 破窗只提供救援信息，不能代替支付或身份认证。
