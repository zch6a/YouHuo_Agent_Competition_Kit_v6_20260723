# HarmonyOS ArkTS 工程壳 v6

本目录包含老人端会话屏，以及家属协同台、全景照护中心、可信实验室三个标签页；
照护中心内含居家安全与健康档案两个子视图，可信实验室内含工具治理、实验室与
v6 决赛导览三节。

## 导航结构

`main_pages.json` 只登记 `pages/Index` 一个路由页面，其余全部是被它引入并渲染的
`@Component`。这是刻意的：此前有五个页面登记在册却没有任何一处 import 或 push
到它们，标签栏挂的是占位文字，`ApiClient` 21 个 public 方法里有 16 个在运行时
永远发不出去。"登记了"不等于"到得了"——现在由
`backend/tests/test_arkts_app.py` 的入口传递闭包断言把这件事钉住。

全工程不再使用已废弃的 `router`。

## 真正接了 SDK 的三个文件

- `services/AudioCapture.ets`：`@kit.AudioKit`，16kHz/单声道/16bit PCM，
  `SOURCE_TYPE_VOICE_RECOGNITION`，运行时申请 MICROPHONE 权限；
- `services/SpeechInput.ets`：`@kit.CoreSpeechKit` 端侧识别。**全工程唯一引用
  Core Speech Kit 的文件**；该 kit 不在公开 OpenHarmony SDK 中，本机无法离线核实
  符号归属，因此单独隔离在一个文件里；
- `services/Haptics.ets`：`@kit.SensorServiceKit` 振动反馈。

## 关于"接入边界"

早前这里放过五个 `*Adapter.ets`（CoreSpeech / PushSafety / DistributedProfile /
AgentCompanion / LocationSafety），本意是声明官方能力的接入边界。它们已被删除，
理由是它们没有做到自己声称的事：五个文件加起来 119 行，**零 `@kit.` 引用**，没有
任何一处 import，而 `CoreSpeechAdapter.startNBestRecognition` 只是翻转一个布尔量
然后回调一个空候选数组——它和真正在用的 `SpeechInput.ets` 是两套互不引用、结论
相反的东西。

一份看起来像已接入、实际是空壳的代码，比明确写下"尚未接入"更容易让人误判。
尚未接入的能力列在下面，不用代码假装。

## 队伍必须完成

1. 使用目标版本 DevEco Studio 和 HarmonyOS SDK 同步工程；
2. 将 `ApiClient.ets` 中的 `BASE_URL` 替换为真机可访问的 HTTPS 服务；
3. 接入 Account Kit、Push Kit、Location Kit、Map Kit 与目标多设备能力
   （当前均未接入，无桩代码）；
4. 正式环境关闭演示登录并使用安全凭据存储；
5. 编译、签名、安装 HAP，保存版本、日志和截图；
6. 进行手机—家属端双设备和端 A2A 联调；
7. 录制真机演示，Web 备份不得冒充鸿蒙真机。

当前容器没有 DevEco Studio 和目标 SDK，因此没有虚构"HAP 已编译""Core Speech 已
联调"或"小艺审核已通过"。
