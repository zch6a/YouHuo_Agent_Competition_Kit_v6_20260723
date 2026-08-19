# 优活 Agent v6.0 交付索引

最后更新：2026-08-19（两套设计二上线、首页加四个对比入口、后端补九个门面端点之后）。

## 首先查看

| 文件 | 内容 |
|---|---|
| `README.md` | 运行、功能、验证结果与能力边界 |
| **`KNOWN_ISSUES.md`** | **已经知道但没修的东西。交付前请先读它，不要只读上面那份** |
| `ONBOARDING.md` | 给下一个接手的人：位置、十分钟跑起来、硬约束、前人栽过的跟头 |
| `reports/TEST_REPORT.md` | 最终测试证据和准确解释 |
| **`docs/33_FOUR_DESIGNS_WALKTHROUGH.md`** | **四套设计各自的定位、路由、差异、答辩时各讲什么** |
| `docs/ELDER_DESIGN2_WIRING.md` | 老人端设计二的接线施工图（23 个缺失 id 分类到落点） |
| `docs/28_V6_CHAMPIONSHIP_PLAN.md` | 决赛主线、三项创新与线下Go/No-Go门槛 |
| `docs/29_V6_RESEARCH_GROUNDING.md` | 官方赛事、鸿蒙、老年交互与Agent工程依据 |
| `docs/30_V6_USER_STUDY_PROTOCOL.md` | 待执行的知情同意老人—家属实验 |
| `docs/31_V6_DEMO_SCRIPT.md` | 五分钟决赛演示脚本 |
| `docs/32_V6_JUDGE_QA.md` | 评委高频问题与边界回答 |

## 十条路由（唯一事实源：`backend/youhuo/surfaces.py` 的 `SURFACES`）

`run_demo.ps1` / `run_demo.sh` 开的是 **8041**，不是 8000。

| 路由 | 文档 | 样式层 | 业务逻辑 |
|---|---|---|---|
| `/` | `index.html` | `landing.css` ＋ 全局四层 | `landing.js` |
| `/elder` | `elder.html` | 六层（含 `art-cards.css`、`elder-family-v3.css`） | `elder.js` |
| `/elder2` | `elder-v6.html` | `elder-v6.css`，单一样式表 | **同一份** `elder.js` |
| `/family` | `family.html` | 五层（视觉层 `art-cards-family.css`） | `family.js` |
| `/family2` | `family-v6.html` | `family-v6.css`，单一样式表 | **同两份** `family.js` + `care.js` |
| `/care` | `care.html` | 同 `/family` | `care.js` |
| `/trust` | `trust.html` | 同上 | `trust.js` |
| `/app` | `app/pages/home.html` | `app/assets/css/app.css` | `app/assets/js/*`（走 `YouhuoAPI`） |
| `/stage` | `stage.html` | 全局四层 | `proof-demos.js` |
| `/judge` | `judge.html` | 全局四层 | `judge.js` |

`/elder2` 与 `/family2` 是本轮新增的**设计二**，和设计一并行，**共用同一份业务逻辑**
——差的只是版式和美术。首页 `/` 上四个对照入口的 id 是
`designElderOne` / `designElderTwo` / `designFamilyOne` / `designFamilyTwo`。

本轮新增的静态文件：

```
backend/static/elder-v6.html   elder-v6.css   elder-v6-a.js   elder-v6-b.js
backend/static/family-v6.html  family-v6.css  family-v6-a.js  family-v6-b.js
```

`*-a.js` / `*-b.js` 是交付包自带的 `script-01/02.js` 改名而来，**`fetch × 0` 的纯 UI 壳**
（吉祥物拖拽、动效），只负责纯视觉行为，不碰后端。

## v6核心代码

- `backend/youhuo/v6_models.py`：交互档案、认知计划、信任卡、安全预演、语义框架、用户实验和竞赛证据契约；
- `backend/youhuo/v6_services.py`：认知负荷治理、玻璃盒卡片、安全预演、受约束语义网关、实验汇总；
- `backend/youhuo/v6_store.py`：交互档案与知情同意实验持久化；
- `backend/youhuo/v6_api.py`：11类v6 API（含任务级玻璃盒与离线语音）；
- `backend/youhuo/semantic_router.py`：模型建议路由，确定性分类为下限；
- `backend/youhuo/care_voice.py`：语音可达层，把用药、健康、日程、亲友和适老档案接回主链，只读优先；
- `backend/youhuo/companion.py`：无忧伴主题连续性，只保存标签与轮次、不保存老人原话；
- `backend/youhuo/teach_back.py`：中文口语金额解析与权威值比对；
- `backend/youhuo/tts.py`：可选离线神经语音，缺失时自动回退浏览器语音；
- `backend/static/speech.js`：朗读文本规范化、择优选音与分句停顿；
- `backend/static/{tokens,base,components,pages}.css`：双色身份光效设计系统，拆成四层，**加载顺序即层叠顺序**（响应式覆写全在 pages 里，媒体查询不增加特异性，排在被覆写的组件之前会静默失效）；
- `backend/static/common.js`：全站唯一的身份与请求层——演示登录、401 重放、令牌缓存、结构化结果渲染、五态判定词表。此前这些在五个页面里各有一份且已经分叉；
- `backend/static/glassbox.js`：玻璃盒信任卡渲染，从 `elder.js` 抽出；
- `backend/static/icons/tabs.svg`：底部标签栏五个图标的 symbol sprite，五个页面共用一份；
- `backend/static/judge.html/js`：五步评委导览；
- `backend/static/elder.js`：老人端接入v6档案、交互计划、玻璃盒与明语记录日志。**`/elder` 与 `/elder2` 共用这一份**；
- `backend/static/family.js`：待办日历、任务进度明语化与脱敏陪伴周报，以及**家人端审批闭环**（`POST /v2/family/approve`）。`/family` 与 `/family2` 共用；
- `backend/static/care.js`：照护中心七个分区。此前**零个写操作**，本轮接上三处真写——记一次已吃 / 没吃（`POST /api/v1/medications/{id}/taken|skipped`）、记一笔身体数据（`POST /api/v1/health/events`，`value` 保持字符串因为血压是「128/82」）、添一位亲友（`POST /v4/contacts`，家人添的记成「等他确认」）。`/family2` 把它和 `family.js` 装进同一个文档，所以首屏是 11 个端点；
- `backend/static/landing.js`：首页身份记忆 + **可取消的 4 秒接管**（`#landingResume` 一句话 + 倒数 + 「现在就进」/「留在这一页」两个按钮）。上一版是无声的 `location.replace`，四个设计入口一眼都看不到；
- `backend/static/{elder-v6,family-v6}.{html,css}` 与 `*-a/b.js`：两套**设计二**。

## 可信底座与产品功能

- `v5_*`：语音共识、目的绑定策略、Saga、离线冲突、破窗、证明与隐私；
- `engine.py`：优活/无忧伴、任务锁、情绪暂停和恢复、暂存话题续聊、照护提问路由；
- `security.py`：紧急/诈骗/注入判定，跌倒按子句区分"正在发生"与"回忆或担心"；
- `trust.py`：自主权、家庭共识、审批快照和完成核验；
- `tool_registry.py`：Schema-first工具与dry-run；
- `document_guard.py`：不可信OCR/VLM防火墙；
- `memory_vault.py`：同意优先记忆；
- `v4_*`：循环事务、健康、用药、位置、跨设备和报告。

## 鸿蒙与小艺

- `harmonyos/.../pages/Index.ets`：四标签宿主。`main_pages.json` 只登记它一个路由页面，其余页面都是被它引入并渲染的 `@Component`；全工程已不再使用废弃的 `router`；
- `harmonyos/.../FinalistWalkthroughPage.ets`：v6决赛导览，现为「可信」标签页的第三节（此前登记在册但无人引用，真机上到不了）；
- **尚未接入的官方能力不再用桩代码表示。** 早前的五个 `*Adapter.ets` 已删除：共 119 行、零 `@kit.` 引用、无人 import，其中 `CoreSpeechAdapter` 永远回调空候选数组，与真正在用的 `SpeechInput.ets` 结论相反。Account Kit、Push Kit、Location Kit、Map Kit 目前均未接入，写在 `harmonyos/README.md` 的待办里；
- `harmonyos/.../services/AudioCapture.ets`：16kHz/单声道/16bit PCM 采集，参数逐个对过 SDK 声明；
- `harmonyos/.../services/SpeechInput.ets`：端侧语音识别接入；全工程唯一引用 Core Speech Kit 的文件（该 kit 不在公开 SDK 中，无法离线核实，已单独隔离）；
- `xiaoyi/plugin_openapi_v6.generated.json`：由当前FastAPI生成，99个路径；
- `xiaoyi/workflows/youhuo_workflow.json`：平台中立v6工作流蓝图；
- `xiaoyi/skills/*/SKILL.md`：13个可组合Skill；
- `xiaoyi/a2a/agent_card.json`：Agent能力声明；
- `mcp/tool_manifest.json`：高风险通用工具保持禁用。

## `/api/v1` 门面层：本轮加了九个端点，**其中一个都还没有前端入口**

`/api/v1` 不是新的一套业务，是给老人端那一屏用的**翻译层**——把 v2–v7 的能力包装成
「一屏要什么就给什么」的形状。本轮从 37 个操作涨到 **50 个**（`v2`–`v7` 仍是 102 个）：

```
GET  /api/v1/privacy/data              隐私导出。纯读，一条审计都不写（P0 契约）
POST /api/v1/privacy/erase/preview     两步删除第一步：算「类别 + 当时条数」的 semantic_hash
POST /api/v1/privacy/erase             第二步：重新数一遍再比。裸 POST 400、令牌过期 409、删空 409
GET  /api/v1/emotions/review?days=     情绪回顾
GET  /api/v1/daily-report?day=         生活日报
GET  /api/v1/memories                  记住了什么 + 等我点头的（分两段）
POST /api/v1/memories/{id}/approve     同意记
POST /api/v1/memories/{id}/decline     不让记
POST /api/v1/memories/{id}/forget      撤回一条已生效的
```

两步删除保证的**不是**防伪造（只有本人进得来），而是「确认的对象和你看到的那一份
是同一份」——回执写「删掉 7 条」实际删了 9 条，两边都不报错，那才是要防的。

契约在 `backend/youhuo/app_schemas.py`；测试在
`backend/tests/test_app_{privacy,emotions,daily_report,memories}.py`。

> ⚠ **这九个端点目前没有任何页面在调。** `backend/static/**` 全量扫过，一处调用都没有。
> 后端与测试是完整的，缺的是前端入口——见 `KNOWN_ISSUES.md` P1-E。

## 评测和验证

- `backend/tests/`：96 个测试文件、约 2100 项自动化测试；
- `backend/tests/test_{elder,family}_design2.py`、`test_landing_design_entries.py`：
  两套设计二与首页四入口的**静态契约**闸门。`test_elder_design2.py` 从 `elder.js`
  自己推出必需的 41 个 id 与运行时类名，**不手抄清单**。
  它们守的是「装进去了、接得上」，**不是**「在浏览器里跑得动、看得见、够得着」；
- `evaluation/elderbench_v5.jsonl`：300条v5专项评测；
- `evaluation/voicebench_youhuo_v6.jsonl`：800条合成ASR候选评测；
- `run_mass_audit_v6.py`：500,000项v6确定性断言；
- `run_mass_audit_v5.py`：1,000,000项可信内核回归断言；
- `run_chaos_v5.py`：400个Saga成功/失败补偿场景；
- `run_load_v6.py`：5,000请求、100并发真实Uvicorn回环负载；
- `run_http_smoke_v6.py`：v6真实HTTP闭环；
- `check_browser_js.py`：按真实加载方式（script/module）**解析**前端脚本。只解析、不执行——它对运行时错误是盲的，必须与下一条配对使用；
- `check_page_runtime.py`：七个页面在真实浏览器里加载（手机视口 390×844），再把每一页上每个可见可用的按钮**逐个按过**（当前 99 个），断言无未捕获异常、无 `console.error`、无同源 4xx/5xx、无原生对话框。加这一条的直接原因是 `care.js` / `trust.js` 曾在第一条语句就抛 `ReferenceError`，两页所有按钮全是死的，而只解析的检查一直是绿的。同一次运行还量三件事：Voice Orb 十一态在关掉动效后两两可辨、评委页七拍演得完且正文全中文、多标签页冷启动只开通一个家庭；
- `check_speech_text.mjs`：34项朗读文本规范化断言；
- `check_contrast.py`：7个页面×明暗两模式（14 个组合）的 WCAG AA、**非文字（图标）对比度 1.4.11** 与触控尺寸审计；
- `check_arkts.py`：鸿蒙端十一类静态检查。`@kit.*` 符号归属按公开 OpenHarmony SDK 的 1159 个符号逐个核对；另含**页面可达性**（任何 `.ets` 不得既未登记为路由页面、又不被任何文件引入）、登记页面必须有 `@Entry`、禁用已废弃的 `router`；
- `shoot_pages.py`：九种视口（含折叠屏内外屏、平板、桌面）× 七个页面 × 明暗两模式 = 126 组，每组两张（首屏 + 全页）共 252 个文件，落盘后逐个核对存在且非空；
- `verify_features_v6.py` / `run_feature_audit.py`：130项逐功能端到端验收与 OpenAPI 覆盖率强制校验；
- `check_artifacts_v6.py`：文件、OpenAPI、Skill、HarmonyOS、报告与敏感产物检查（全树扫描运行库、审计密钥与模型文件，并列出具体路径）。另含**重型报告新鲜度**：上面四项重型验证的结论以 JSON 留存供引用，每份都盖着它验证过的那棵 `backend/youhuo` 的指纹（`youhuo/provenance.py`），检查器重算比对——对不上就判过期。加这一条是因为曾有两天，`mass_audit_v5_1000000.json` 是 08-08 的而 `v5_services.py` 08-10 才改过，`verify_all` 照样报"全部通过"；
- `verify_all.*`：确定性日常回归；
- `verify_heavy.*`：百万回归、故障和网络重验证。

## 比赛材料

- `competition_materials/01_一句话创意描述.md`
- `competition_materials/02_设计稿与交互流程说明.md`
- `competition_materials/03_800字作品介绍.md`
- `competition_materials/04_技术方案摘要.md`
- `competition_materials/05_原创性与合规说明.md`
- `competition_materials/06_V6核心创新与技术摘要.md`

## 完整性

- `MANIFEST.sha256`：包内文件散列；
- 压缩包外提供 `.zip.sha256`；
- 发布包不包含运行数据库、生成审计密钥、`.env`、虚拟环境或缓存目录。

## 发布统计

2026-08-19 实测（起真服务敲 `/openapi.json`，跑全量 pytest）：

- FastAPI OpenAPI：**145 个路径 / 153 个操作**
  （`/api/v1` 46 路径 / 50 操作；`v2`–`v7` 102 操作：14 / 9 / 39 / 21 / 15 / 4；`/health` 1）；
- 页面路由：**10 条，逐条 200**；
- 小艺插件契约 `xiaoyi/plugin_openapi_v6.generated.json`：**99 个路径**
  （**刻意不含 `/api/v1`**，和上面那个 145 不矛盾，别互相改）；
- 小艺Skill：13个；
- 自动化测试：**7 failed, 2095 passed**——4 条是重型报告指纹过期
  （重跑 `verify_heavy` 即消），3 条是并行改动的中间态，四十分钟后重跑已绿；
- 控件清单：**376 个控件**，其中 9 个 `apis` 非空。

更早一轮 `verify_all` 的输出（08-15 / 08-16，**不是这一轮跑的**）：
逐功能验收 130 项；页面运行时闸门 7 个页面 / 99 个控件 / Voice Orb 11 态 / 评委页 7 拍；
对比度与触控 14 个页面×模式组合；全尺寸截图 252 个文件；核心 Python 语句覆盖率 91%。

**那一批闸门的页面清单是原来那七页，`/elder2` 与 `/family2` 不在里面**
（见 `KNOWN_ISSUES.md` P1-C）。`MANIFEST.sha256` 由
`backend/scripts/make_release.py` 在打包时按 `git ls-files` 重算。

推送前必跑 `backend/scripts/scan_secrets.py`，**红着不许提交**
（远端是公开仓库，而且发生过审计密钥被推上去的事故）。
