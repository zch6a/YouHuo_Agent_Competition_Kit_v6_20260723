# 优活 Agent v6.0 交付索引

## 首先查看

| 文件 | 内容 |
|---|---|
| `README.md` | 运行、功能、验证结果与能力边界 |
| `reports/TEST_REPORT.md` | 最终测试证据和准确解释 |
| `docs/28_V6_CHAMPIONSHIP_PLAN.md` | 决赛主线、三项创新与线下Go/No-Go门槛 |
| `docs/29_V6_RESEARCH_GROUNDING.md` | 官方赛事、鸿蒙、老年交互与Agent工程依据 |
| `docs/30_V6_USER_STUDY_PROTOCOL.md` | 待执行的知情同意老人—家属实验 |
| `docs/31_V6_DEMO_SCRIPT.md` | 五分钟决赛演示脚本 |
| `docs/32_V6_JUDGE_QA.md` | 评委高频问题与边界回答 |

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
- `backend/static/elder.js`：老人端接入v6档案、交互计划、玻璃盒与明语记录日志；
- `backend/static/family.js`：待办日历、任务进度明语化与脱敏陪伴周报。

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

## 评测和验证

- `backend/tests/`：939项自动化测试；
- `evaluation/elderbench_v5.jsonl`：300条v5专项评测；
- `evaluation/voicebench_youhuo_v6.jsonl`：800条合成ASR候选评测；
- `run_mass_audit_v6.py`：500,000项v6确定性断言；
- `run_mass_audit_v5.py`：1,000,000项可信内核回归断言；
- `run_chaos_v5.py`：400个Saga成功/失败补偿场景；
- `run_load_v6.py`：5,000请求、100并发真实Uvicorn回环负载；
- `run_http_smoke_v6.py`：v6真实HTTP闭环；
- `check_browser_js.py`：按真实加载方式（script/module）**解析**前端脚本。只解析、不执行——它对运行时错误是盲的，必须与下一条配对使用；
- `check_page_runtime.py`：六个页面在真实浏览器里加载，再把每一页上每个可见可用的按钮**逐个按过**（当前 41 个），断言无未捕获异常、无 `console.error`、无同源 4xx/5xx、无原生对话框。加这一条的直接原因是 `care.js` / `trust.js` 曾在第一条语句就抛 `ReferenceError`，两页所有按钮全是死的，而只解析的检查一直是绿的；
- `check_speech_text.mjs`：29项朗读文本规范化断言；
- `check_contrast.py`：6个页面×明暗两模式的 WCAG AA、**非文字（图标）对比度 1.4.11** 与触控尺寸审计；
- `check_arkts.py`：鸿蒙端十一类静态检查。`@kit.*` 符号归属按公开 OpenHarmony SDK 的 1159 个符号逐个核对；另含**页面可达性**（任何 `.ets` 不得既未登记为路由页面、又不被任何文件引入）、登记页面必须有 `@Entry`、禁用已废弃的 `router`；
- `shoot_pages.py`：七种视口（含折叠屏内外屏、平板）× 明暗两模式的真机尺寸截图；
- `verify_features_v6.py` / `run_feature_audit.py`：130项逐功能端到端验收与 OpenAPI 覆盖率强制校验；
- `check_artifacts_v6.py`：文件、OpenAPI、Skill、HarmonyOS、报告与敏感产物检查（全树扫描运行库、审计密钥与模型文件，并列出具体路径）；
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

- FastAPI OpenAPI路径：99个；OpenAPI 操作覆盖：103/103；
- 小艺Skill：13个；
- 自动化测试：939项；逐功能验收：130项；
- 页面运行时闸门：6个页面、41个控件逐个按过；
- 核心Python语句覆盖率：91%。

以上全部是 `verify_all` 单次运行的实测输出，不是估计值。`MANIFEST.sha256` 由
`backend/scripts/make_release.py` 在打包时按 `git ls-files` 重算。
