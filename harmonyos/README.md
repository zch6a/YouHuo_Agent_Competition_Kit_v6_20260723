# HarmonyOS ArkTS 工程壳 v6

本目录包含老人端、家属端、照护中心、健康、安全、可信实验室和v6决赛导览页面。

## v6新增

- `FinalistWalkthroughPage.ets`：依次展示受约束语义、认知负荷治理、可信/不可信值冲突和竞赛证据；
- `ApiClient.ets`：新增 `/v6/semantic/parse`、`/v6/interaction/plan`、`/v6/actions/preview` 和 `/v6/competition/evidence` 映射；
- `CoreSpeechAdapter.ets`：正式ASR/TTS/N-best候选接入边界；
- `PushSafetyAdapter.ets`：家属接力和安全事件推送边界；
- `DistributedProfileAdapter.ets`：跨设备适老档案同步边界；
- `AgentCompanionAdapter.ets`：端A2A长任务和用户干预边界。

## 队伍必须完成

1. 使用目标版本DevEco Studio和HarmonyOS SDK同步工程；
2. 将`ApiClient.ets`中的`BASE_URL`替换为真机可访问的HTTPS服务；
3. 接入Account Kit、Core Speech、Push、Location和目标多设备能力；
4. 正式环境关闭演示登录并使用安全凭据存储；
5. 编译、签名、安装HAP，保存版本、日志和截图；
6. 进行手机—家属端双设备和端A2A联调；
7. 录制真机演示，Web备份不得冒充鸿蒙真机。

当前容器没有DevEco Studio和目标SDK，因此没有虚构“HAP已编译”“Core Speech已联调”或“小艺审核已通过”。
