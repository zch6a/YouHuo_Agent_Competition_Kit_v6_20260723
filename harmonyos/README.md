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

## 与 Web 端「四 Tab」的差异：本轮**没有**对齐，原因如下

Web 端老人端（`elder.html`）这一轮改成四个 Tab：首页 / 记录 / 家人 / 我的，对话与
输入行移进 Focus Mode（首页的一个**态**，不是第五个分区）。鸿蒙端**没有**跟着改。
这是一个判断，不是遗漏，所以写在这里而不是留白。

三条阻塞：

1. **两端的这一层标签栏不是同一个东西。** 鸿蒙端底部四个标签是
   对话 / 家人 / 照护 / 可信——它们跨的是**受众**（老人、家属、演示、评委），
   在 Web 端对应的是四个**独立页面**（`elder.html` / `family.html` / `care.html` /
   `trust.html`）。Web 端的四 Tab 跨的是老人端**一个页面内部**的分区。
   把后者套到前者上，第一个撞车的就是「家人」：鸿蒙端的 `FamilyPage` 是家属协同台
   （批准/拒绝接力，用家属令牌），Web 端老人端的「家人」是一张只读的亲人卡
   （"谁能帮我、能帮什么、怎么找她"，明确不做社交系统）。同名、同图标、不同受众、
   不同令牌——硬对齐会造出两个都叫「家人」的标签。
   要真对齐，得先有两级标签栏或一个角色切换入口，那是结构改动。
2. **另外三个 Tab 在 ArkTS 端没有数据源。** Web 端四 Tab 消费
   `/v2/reminders`（首页的「今天」与「下一件」）、`/v2/elder/activity`（记录）、
   `/v6/profiles/{elder_id}` 的 GET 与 PUT（我的）。`ApiClient.ets` 这三个都没有。
   只有「家人」那张卡是便宜的——Web 端它就是静态文案加一个
   `send('帮我联系家人')`。所以四个新 Tab 里三个要先补客户端方法。
3. **现有契约钉住了当前那四个标签。**
   `backend/tests/test_arkts_app.py::test_every_tab_shows_a_real_screen` 要求
   `FamilyPage()` / `CareHubPage()` / `TrustTab()` 都真的被渲染；
   `::test_every_api_client_method_is_reachable_from_a_screen` 要求每个 `ApiClient`
   public 方法都能从入口走到——21 个里有 16 个只住在照护中心和可信实验室里。
   也就是说不能靠"腾掉三个标签"来给新的四个让位。

在这三条解决之前造四个 Tab，只能造出**带占位文字的壳**——而这个工程刚为
"三个死 Tab 挂着占位文字"和"五个空壳 Adapter"付过一次代价。宁可两端此处不一致
并写明原因，也不要再交一份看起来完整的死代码。

配色、触控两档、紫色与 mesh 这三项本轮**已经**对齐（见
`entry/src/main/ets/theme/Theme.ets` 文件头）。

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
