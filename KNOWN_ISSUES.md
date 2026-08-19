# 已知问题

任务书要求「不许撒谎说绝对没有 Bug」。这份文件是那句要求的对面：**已经知道、但没有修的**
东西，逐条写清楚是什么、为什么没修、以及它在什么情况下会咬人。

分级：

- **P0** 演示当场会坏，或者会让老人做错事。**当前为 0。**
- **P1** 有真实用户或评委能撞到的功能缺失。**当前为 6 条。**
- **P2** 体验或工程上的欠账，不影响正确性。
- **未验证** 我没有条件测的东西。它不是「通过」，是「不知道」。

最后更新：2026-08-19（并行九路那一批落地之后，逐条重新核实过）。

---

## 当前红灯：全量 pytest 有 4 条稳定的红

不藏，而且要连测量条件一起说：**写这份文件时有五个 agent 正在并行改代码**，
所以「全量测试数」是一个会动的数。下面两次运行都是实测的。

一次全量（2026-08-19，约 5 分 36 秒）：

```
cd backend && ..\.venv\Scripts\python.exe -m pytest -q -p no:randomly
7 failed, 2095 passed in 335.77s
```

约四十分钟后，只重跑那 7 条所在的文件：

```
tests/test_theme_color_matches_the_canvas.py  tests/test_elder_design2.py
tests/test_family_design2.py                  tests/test_release_hygiene.py
tests/test_control_inventory_is_the_fact_source.py
tests/test_landing_design_entries.py          tests/test_surface_registry.py
4 failed, 245 passed in 33.85s
```

**7 条里有 3 条自己消失了**，因为改它们的那个 agent 在这两次运行之间把工作做完了：

| 那 3 条 | 当时红在哪 | 现在 |
|---|---|---|
| `test_elder_design2.py::test_typing_reaches_the_backend_and_every_hit_area_is_big_enough` | `/elder2`「我的」两个分段按钮命中区 37×48，下限 48 | 绿 |
| `test_theme_color_matches_the_canvas.py::test_theme_color_is_the_canvas_colour[elder-v6.html]` | 只有一条不带媒体查询的 `theme-color: #eee8dd` | 绿（`elder-v6.html` 改成**刻意不引 manifest**，于是不再算「可安装页面」） |
| `test_theme_color_matches_the_canvas.py::test_every_installable_page_declares_both_schemes` | 同上 | 绿 |

**这一条本身值得记住**：并行期间的一次全量快照，分不出「真缺陷」和「别人正改到一半」。
读到这里请自己重跑一次，不要引用上面那个 7。

### 红 1–4：四份重型报告是用另一版源码跑出来的

```
test_release_hygiene.py::test_heavy_reports_were_produced_by_the_current_source
  [mass_audit_v5_1000000] [chaos_v5_400] [load_v6_5000] [http_smoke_v6]
```

四份报告都盖着 `72848d13075d…`，而当前 `backend/youhuo` 的指纹是 `d81114f09d0b…`
（两次运行相隔四十分钟，两个值都没变——所以这一条不是别的 agent 造成的抖动）。
`backend/youhuo/` 在这一轮被改过（`api.py` 加了 `/elder2` `/family2` 两条路由、
`app_api.py` 加了九个 `/api/v1` 端点、`app_schemas.py` 加了对应契约、
`surfaces.py` 登记了两条设计二），而那四份报告是 **2026-08-18 23:25–23:27** 落盘的。

**这不是缺陷，是这道闸门在正确工作**——它防的正是「读一份报告等于跑过一次验证」。

**修法**：重跑 `verify_heavy`（约四分钟）。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify_heavy.ps1
```

**注意**：跑之前先确认没有别的 agent 正在改 `backend/youhuo/`——它跑完就盖当时的指纹，
中途被改过就白跑。这四条是**交付前必须清掉**的，因为 `check_artifacts_v6` 会引用这
四份 JSON 的结论。

### 已经不存在的那条红：`test_the_apis_column_is_known_to_be_unimplemented`

上一版这份文件在这里记着「红 5：控件清单的 `apis` 列越过了它自己的天花板
（`assert 9 <= 8`）」。**那条测试已经没有了，这一段是错的**，留在这里只为了说明它去哪了。

它是一条**上限**断言，于是把「多接通一个控件」罚成红——它自己的报错信息都承认这一点。
现在 `test_control_inventory_is_the_fact_source.py` 里换成了三样东西：

- `_COVERAGE_FLOOR["apis"] = 8` —— **下限**，配 `test_no_inventory_column_gets_emptier`。
  为什么钉 8 而不是当前的 9：第 9 条 `stage.html:id=stageEscape` 是**假边**
  （清单给它挂了八个端点，而 `stage.js:275` 里它的全部行为是 `() => setClean(false)`，
  一个请求都不发）。钉 9 等于要求那个归属错误永远别被修好。
- `_REACHES_THE_BACKEND` —— 一张**核过的**「控件 → 端点」表，8 条，逐条参数化断言
  它**还**打得到（`test_a_control_that_reaches_the_backend_still_does`）。
  接通新控件不会红，**弄断**表里任何一条会红。
- `test_a_declared_edge_is_verifiable_in_the_source_not_only_in_the_artifact` ——
  同一件事去 JS 源码里再核一遍，不只读产物。

实测：落盘清单现在 **376 个控件、9 个 `apis` 非空**，这一组全绿。

---

## P1

### A. `/app` 是 consumer 侧的第三套 App Shell，而它和 `/elder` 服务同一批人

**在哪** `youhuo/surfaces.py` 的 `SURFACES`：`/elder`（旧老人端）与 `/app`
（山水版老人端）同时在册，`surface` 都是 `consumer`。

**什么样** `test_surface_registry` 原先钉死「consumer 只许 elder + family 两套壳」，
并把它注释成「本轮的核心约束」。方向变更之后这条不成立了，判据已改成
**白名单**（`DECLARED_CONSUMER_SHELLS`）——多一套没批准的壳仍然报红，
但 `app` 现在是被明确批准的。三个变异验过它还咬人。

**未决，需要人来定**：如果山水版是来**替换**旧老人端的，`/elder` 应该退役，
白名单回到三个；如果两套要并存，得说清楚谁在什么场合用哪一套。
**这个决定我没有替谁做**，判据里的白名单只是把现状记下来，不是批准它永远存在。

**这一轮把这件事变复杂了**：consumer 侧现在有**五套**前端——`/elder`、`/elder2`、
`/family`(+`/care`)、`/family2`、`/app`。前四套是有意的设计对照（见
`docs/33_FOUR_DESIGNS_WALKTHROUGH.md`），`/app` 不是。

### B. 入口页仍然会自己走人，只是现在给了 4 秒和一个按钮 ✅ 已改，但要在彩排里看一眼

**上一版这份文件在这里写的是「打开 `/` 会立刻 `location.replace` 弹走，四个设计入口
一眼都看不到」。那句话现在是错的**——`landing.js` 已经整个重写了。核对方式见下。

**现在是什么样**（读 `backend/static/landing.js`，实测服务端发出的 `/` 里四条链接都在）：

- 冷启动（`localStorage` 有 `youhuo_role_v1`、本标签页 `sessionStorage` 没有
  `youhuo_visited_v1`、没按过「留在这一页」、地址里没有 `?stay=1`）时，页面**先渲染出来**，
  在 `.landing-main` 顶上插一条 `#landingResume`：一句「这一页会自动为您打开 X 端。」
  \+ 逐秒倒数 + 两个按钮 `#landingGo`（现在就进）与 `#landingStay`（留在这一页）。
- `HANDOFF_MS = 4000`，而且表**从第一帧开始走**（`requestAnimationFrame`），不是从
  脚本执行开始——文件头记着五档 CPU 节流的实测数据，1/20 CPU 下按钮 2821ms 才可按，
  挂在脚本执行上会只剩 1.2 秒。
- 四个否决项各挡一路；`document.hidden` 时那一拍直接跳过；
  `keydown / wheel / touchmove / pointerdown` 任意一个都会停表。
- 走人用 `location.assign` 不是 `replace`，所以按「后退」能回到 `/`。
- 按过「留在这一页」会写 `youhuo_stay_v1`（localStorage，跨标签页），
  点身份卡时清掉——一次误按不会让人从此永远停在选择页。

**为什么它仍然留在 P1**：默认行为依然是「4 秒后自动离开首页」。评委如果在这 4 秒里
没有看向屏幕，四个设计入口这件事就还是会被错过；而这一节是这次并行设计在产品里
**唯一**的入口。这是一个产品取舍，不是缺陷——但答辩前必须有人拍板。

**现场三个办法，都不用改代码**

1. 地址写 `http://127.0.0.1:8041/?stay=1`；
2. 倒计时里按一下「留在这一页」（之后这台设备都会停）；
3. 用一个从没点过身份卡的浏览器 / 无痕窗口——那时根本不会有倒计时。

**没有验到的部分（这是它还在这份文件里的第二个理由）**
`test_landing_design_entries.py` 是静态契约闸门，实测 245 条那一批里它是绿的；
但**「4 秒够不够一个人反应」没有在真人身上试过**，倒计时那套交互也不在
`check_page_runtime.py` 的页面清单里跑（见 P1-C）。
自动化闸门天然摸不到这条路径：每轮全新 profile，`localStorage` 是空的，
`handOff` 恒为假——**它测的是不倒计时的那一支**。彩排时请用真正要用的那个浏览器
窗口走一遍。

### C. `/elder2` 与 `/family2` 不在四道浏览器闸门的页面清单里

**在哪** 四处写死的页面清单：

| 闸门 | 清单在 | 覆盖 |
|---|---|---|
| `check_page_runtime.py:54` | `PAGES = [...]` | 七页，无 `/elder2` `/family2` `/app` |
| `check_contrast.py:30` | `PAGES = [...]` | 同上 |
| `shoot_pages.py:73` | `PAGES = [...]` | 同上 |
| `test_mobile_reachability.py:36` | `PAGES = [...]` | **六页**，连 `/stage` 也没有 |

**什么样** 两套设计二**没有**经过：浏览器里的运行时加载（无未捕获异常 / 无
`console.error` / 无同源 4xx）、逐控件点击、WCAG AA 与触控尺寸审计、九视口截图，
以及——最要紧的那条——**七视口下打字入口必须在首屏内**。

最后一条对 `/elder2` 尤其重要：Web Speech 在 Firefox 上不存在、权限被拒、没有麦克风
的时候，打字是老人进入这个产品的唯一入口。`/elder` 为它专门修过三轮
（横屏 900px、竖屏 156px、`animation fill-mode` 的单位矩阵），**那三轮的收益不会
自动到 `/elder2` 上**——它是另一套版式。

**它们现在有什么** 各自一份静态契约闸门：`test_elder_design2.py`（从 `elder.js`
自己推出必需的 41 个 id 与运行时类名，不手抄清单）、`test_family_design2.py`、
`test_landing_design_entries.py`。这些守的是「装进去了、接得上」，不是「在浏览器里
跑得动、看得见、够得着」。

**这正是 `surfaces.py` 开头那段警告说的事**：七条路由的字面量散在八个文件里各写一遍，
「加一个新表面而不改这八处，多数闸门会**静默地不覆盖它**」。`/stage` 已经被漏掉过四次，
现在轮到 `/elder2` 和 `/family2`。

**为什么没修** 全是代码文件。修法是让这四处改读 `surfaces.ROUTES`，而不是各写一份。

### D. `backend/static/app/index.html` 是交接包留下的开发索引页，公开可达

**在哪** `backend/static/app/index.html`（2065 字节）。`api.py:277` 把整个
`backend/static` 挂在 `/static`，所以线上地址是 `/static/app/index.html`，
**不需要任何登录**。

**什么样** 标题是「优活老人端前端参考包」，左栏是一份开发者目录：
十个页面的 iframe 预览、「美术元素 QC 图谱」，以及一条
`<a href="docs/CLAUDE_HANDOFF.md">Claude 交接说明</a>`。

**为什么要处理** 远端 `github.com/zch6a/YouHuo_Agent_Competition_Kit_v6_20260723`
是**公开仓库**，而这台部署也是公开演示。一个评委顺着 `/static/app/` 点进去，看到的是
我们自己的交接文档，不是产品。

**去留未定，需要人来定**：删掉、改成 404、还是留着当开发工具但挪出 `static/`。
**这个决定我没有替谁做。**（`ONBOARDING.md` 从 08-17 起就记着「推送前处理」，
到 08-19 仍然在。）

**核对过**：`GET /static/app/index.html` → **200，2065 字节**，标题
「优活老人端前端参考包」，正文里确实有 `CLAUDE_HANDOFF.md` 这个链接。

### E. 九个 `/api/v1` 端点没有任何页面在调

**在哪** `backend/youhuo/app_api.py`。这九个端点都真的注册了、都在 `/openapi.json` 里
（实测 145 个路径 / 153 个操作，逐条 200），**但整个 `backend/static/` 里一处调用都没有**。

| 端点 | 这一轮加的 | 底层 |
|---|---|---|
| `GET  /api/v1/privacy/data` | ✔ 隐私导出（**纯读，一条审计都不写**，P0 契约） | `/v5/privacy/export` |
| `POST /api/v1/privacy/erase/preview` | ✔ 两步删除第一步 | `/v5/privacy/erase` |
| `POST /api/v1/privacy/erase` | ✔ 两步删除第二步（要带预览发的令牌） | 同上 |
| `GET  /api/v1/emotions/review?days=` | ✔ 情绪回顾 | `/v4/emotions/*` |
| `GET  /api/v1/daily-report?day=` | ✔ 生活日报 | `/v7/daily-report`＋`/v7/baseline` |
| `GET  /api/v1/memories` | 上一轮 | `memory_vault` |
| `POST /api/v1/memories/{id}/approve` | 上一轮 | 同上 |
| `POST /api/v1/memories/{id}/decline` | 上一轮 | 同上 |
| `POST /api/v1/memories/{id}/forget` | 上一轮 | 同上 |

**怎么核的**（这一条一定要按接口核，不能按页面核）：把 `backend/static/**` 下所有
`.js` 与 `.html` 逐行扫 `privacy/data|privacy/erase|emotions/review|/daily-report|/memories`，
命中 5 处，**全部不是这九个**：`family.js:74/94` 是注释、`family.js:592` 与
`care.js:360` 打的是家人侧的 `/v7/daily-report/{elder_id}`、`proof-demos.js` 打的是
`/v3/memories/*`（演示台）。三套 consumer 前端各查一遍：`elder.js` 的 11 条调用路径里
没有 `/api/v1`；山水版 `/app` 那 35 处 `YouhuoAPI.*` 里也没有。

**为什么要单独列**：这个项目已经因为「后端有、前端没画」栽过两次
（同意记忆停在 `proposed`、用药计划），两次都是**两边界面都正常、不报任何错**。
一个只有端点没有入口的能力，在演示里等于不存在——而 OpenAPI 里它看起来是有的。

**注意别把它读成「后端没做」**：`test_app_privacy.py` / `test_app_emotions.py` /
`test_app_daily_report.py` 共 49 条新测试、27 个变异全部咬住，后端这一侧是完整的。
缺的只是前端入口。

**为什么没修** 是代码。这一轮我只拥有文档，而且前端正有五个 agent 在改。

### F. `/family2` 不是一个可安装的页面，也不注册 service worker

**在哪** `backend/static/family-v6.html`。

**逐页数过**（`register-sw` / `rel="manifest"` / `theme-color` / `.needs-server` 四项）：

```
                register-sw  manifest  theme-color  needs-server
care.html            1          ✔          2            2
elder.html           1          ✔          2            2
elder-v6.html        1          ✘(注释说刻意不引)  1      2
family.html          1          ✔          2            2
index.html           1          ✔          2            2
judge.html           1          ✔          2            2
trust.html           1          ✔          2            2
stage.html           0          ✘          0            2   ← 刻意的，文件里写了理由
family-v6.html       0          ✘          0            0   ← 四项全空
```

**后果有三个，一个比一个不明显**

1. **装不到主屏。** 没有 manifest，`/family2` 只能当普通网页开；而
   `README` 讲的「可以直接装到主屏、与 App 无异」对这一页不成立。
2. **首次访问 `/family2` 不会安装 service worker。** `sw.js` 的外壳清单里确实有
   `family-v6.*`（这一轮加进去的，VERSION 已到 `youhuo-shell-v16`），但那要**先有人
   注册过 worker**。评委如果第一个打开的就是 `/family2`，离线外壳一份都没缓存。
3. **双击文件得到一张裸 HTML。** 它的样式表写成绝对路径 `/static/family-v6.css`，
   `file://` 下 404，而它没有那两句 `.needs-server` 兜底提示（这就是下面 P2 `-1.5` 条）。

**闸门为什么没抓到**：`test_theme_color_matches_the_canvas.py` 的
`INSTALLABLE` 是**按「这一页引没引 manifest」算出来的**，不是手写名单——
这个设计本身是对的（`stage.html` 因此被正确地排除在外），但它的副作用是
**一个页面只要不引 manifest 就整批绕开这条闸门**。`/family2` 现在就在这个缝里：
它不是「测了没过」，是「没被测」。

**为什么没修** 是代码，而且「设计二要不要做成可安装的 PWA」是个产品决定，不是笔误。

---

## P2

### -2. 两套设计二只有浅色一种模式

**在哪** `backend/static/elder-v6.css`、`backend/static/family-v6.css`。

**什么样** 两份里 `prefers-color-scheme` 各出现 **0 次**，也都没有声明 `color-scheme`。
它们是**单一样式表**的页面，不加载 `tokens.css`——而深色模式整套令牌就在那里
（`tokens.css` 里 `prefers-color-scheme` 出现 4 次）。

设计一的两套（`/elder`、`/family`+`/care`）加载全局四层，深色模式是有的。

**什么时候会咬人** 评委的手机是深色模式，点进 `/elder2` 或 `/family2`，看到浅色界面。
**这和山水版 `/app` 是同一个形状的欠账**（见下面第 0 条），只是这两页是这一轮新加的。

**没量过的部分**：`/app` 那两页做过逐像素比对确认「是彻底的单模式，不是一半适配」，
两套设计二**没有做过同样的比对**，也不在 `check_contrast.py` 的清单里（见 P1-C）。
所以这里只能说「样式表里没有深色规则」，不能说「深色下不会出现米色卡片里嵌系统深色
输入框」那种坏法——那需要实测。

### -1.5 `family-v6.html` 没有「这个页面要用服务器打开」的兜底

**在哪** `backend/static/family-v6.html`。

**什么样** 逐页数过 `.needs-server`：

```
care.html 2   elder.html 2   elder-v6.html 2   family.html 2
index.html 2  judge.html 2   stage.html 2     trust.html 2
family-v6.html   0
```

这一页的样式表是 `/static/family-v6.css`（绝对路径），`file://` 下 404，
于是评委解开交付包**双击这个文件**得到的是一张裸 HTML。
`test_file_protocol_fallback.py` 的 `PAGES` 写死为原来那七页（实测：`elder2`
`family2` `app` 一个都不在），所以它既没抓到这一条，也没覆盖 `elder-v6.html`
（那一页恰好有，是写它的人自己加的）。

**这一条是 P1-F 的一部分**：`family-v6.html` 缺的不只是 `.needs-server`，
`register-sw` / `rel="manifest"` / `theme-color` 也都是 0。四项一起看才看得出
它是整批漏掉，不是漏了一句提示。

### -1. 那 87 张美术素材里，有十来张烤着界面文字的残留

**在哪** `backend/static/app/art/png/`。

**什么样** 把 87 张拼成一张联络表看了一眼就看出来了——不是搜出来的，是**看**出来的：

| 素材 | 里面画着 | 用在 |
|---|---|---|
| `cert_gold_seal.png` | 绿徽章 +「**交易成功**」+ 对勾 | certificate、family-approve |
| `scene_tree_left.png` | 「请」 | voice-listening |
| `scene_pavilion_right.png` | 「听」 | voice-listening |
| `bill_scene_right.png` | 「息」 | bill-detail |
| `success_scene_right.png` | 「已」 | payment-success |
| `cert_scene_left/right`、`confirm_gold_cloud`、`confirm_scene_right`、`bill_safe_mountain_r` | 零星字块 | 各页 |

看起来是从**带界面文字的稿子上裁下来的**，文字用的是和 App 同一款黑体，不是书法。

**其中只有一张是断言，已经修了。** `cert_gold_seal` 上那句「交易成功」原先无条件铺在
凭证页和**家人确认页**上——后者正是家人还在决定同不同意的那一屏。一笔没批准的钱，
旁边一张图说它成功了。这和本项目的 P0 是同一件事，只是这次断言画在图里：
代码里的状态文案早就对了（会显示「等家人确认」），而**所有现有判据都只查文字**，
所以全绿。

改法是让它跟着状态走（默认 `hidden`，只在 `completed` 时露面），不是改图：
绿徽章在 y147–181 而金环跨 y56–209，裁不掉、抠掉会在环上留洞。
`test_art_does_not_claim_success.py` 钉住了这一条。

**其余的没修**：它们出现在山水背景里，是观感问题不是断言。修它们要重做素材，
而这一批素材过了它自己那套 QC（`data/art_asset_manifest.json` + `ART_QC_REPORT.md`）
——**那套 QC 没有检查这个**。

### 0. 山水版老人端只有浅色一种模式

**在哪** `/app` 那十七个页面（`backend/static/app/assets/css/app.css`）。

**什么样** `app.css` 里 `prefers-color-scheme` **出现 0 次**，十七个页面也都没声明
`color-scheme`。旧前端的 `tokens.css` / `components.css` 是有深色模式的，这一套没有。

**量过之后的结论：它不是「一半适配」，是彻底的单模式。** 用 CDP 把
`prefers-color-scheme` 切到 dark 重截，和浅色逐像素比对：
`settings.html` 与 `medication.html` **不同像素数都是 0**。
表单控件也验过——两页的 `<input>` 底色与字色都是显式写死的，
深浅两种模式下都是 15.45:1，不会出现「米色卡片里嵌一个系统深色输入框」那种情况
（那正是没声明 `color-scheme` 时最常见的坏法，这里没有发生）。

**为什么不修** 一整套深色令牌是一轮独立的工作，而当前这套的浅色是自洽的、
对比度是达标的。**但要说清楚：深色模式手机上打开它，看到的就是浅色界面。**

### 1. 手机横屏下对话区只有两行

**在哪** `/elder`，视口高 ≤ 540px 且宽 ≥ 640px（844×390、667×375 这类横过来的手机）。

**什么样** 麦克风移到左侧固定栏、右栏走普通块流之后，对话区拿到 16dvh，在 390px 高的
屏上是 62px——大约两行字。完整上文要滚。

**为什么不修** 逐层量过：390px 里家具本身要 670px（main 内边距 51 + app-bar 71 +
stage 内边距 44 + 角色头 61 + 今天那一行 63 + 对话 80 + 麦克风 157 + 输入区 143）。
这个视口装不下，把每一件都再缩一档也装不下。现在的取舍是「两个控件都在屏上、对话区
让步」，理由是输入行是语音失败时唯一的退路，而对话可以滚。

**什么时候会咬人** 老人横着拿手机、想回看 agent 三轮之前说过的话。

**闸门** `test_the_typing_route_is_in_the_first_screen_on_every_viewport` 钉住输入行
必须在首屏；对话区高度没有下限断言。**这条闸门不覆盖 `/elder2`**，见 P1-C。

### 2. 评委页演第二遍时，第 5、6 拍读的是上一次的记录

**在哪** `/judge`，同一个浏览器里第二次按「从头演一遍」。

**什么样** 这个月的水费已经交过，后端回 `duplicate_blocked`。第 1 拍如实说
「已经交过了，没有为了演示再扣一次」，第 5、6 拍改从审计链里读上一次的记录，并且在
正文里写明「这是上一次的」。

**为什么不修** 这不是缺陷，是「同一笔账不会扣两次」这条规则在起作用。真要让它每次都
能重演，得加一个「重置演示数据」的后端接口——为了演示效果去动业务状态机，方向是反的。

**什么时候会咬人** 答辩现场连按两次，第 5、6 拍的措辞会变。演示脚本里注明按一次。

### 3. `care.js` 的六张卡仍然各自请求

`/care` 首屏并发六个请求。合并成一个批量接口是后端改动，收益是几十毫秒，不值得在
这个阶段动接口契约。

`/family2` 把 `care.js` 和 `family.js` 装进同一个文档，于是首屏是 **11 个**端点。
这是四屏合一的直接代价，不是缺陷——但它是这个版式在性能上要付的账。

### 4. `/care`「记一次已吃」的**成功**路径没有在界面上验到

**在哪** `/care` 用药分区。

**什么样** 三个写操作是驱动验过的，但「记一次已吃」当时撞的是种子数据里今天 08:00
那一格**已经记过**，后端如实回 409「今天降压药该吃的都记过了」，语气 `warning`。
行为和话术都对，**而 200 那条路径没有在 UI 上走过一次**。

**什么时候会咬人** 现场演这个动作，走的是从没验过的分支。
演示前先造一格未记的，或者干脆演「记一次没吃」（`skipped`，那条验过）。

### 5. `_LOCK_EXEMPT_PATHS` 漏掉四条路由

**在哪** `backend/youhuo/api.py:187`。

```
exempt   /  /elder  /family  /care  /trust  /judge  /ping
漏掉     /elder2  /family2  /app  /stage
```

**什么样** 那把 SQLite 序列化锁是全进程共享的。静态 UI 页面不碰数据库，本该豁免；
这四条没豁免，意味着有人正在跑一个慢请求时，打开这四页要排在它后面。

**影响有多大** 只是延迟，不是错误——页面照样返回 200（十条路由全部实测 200）。
但它是 `surfaces.py` 开头点名的那类漂移：同一份路由清单散在八个文件里各写一遍。

### 6. 老人端面板底部的场景水印被砍掉了，下一轮的做法已经定了但没做

贴过两处（`.elder-layout::before` 山水 + 家人屏竹屏），截图核过之后全砍：
两张都是**硬边矩形**，图片自己的边框横切过卡片，读起来像一张没加载完的坏图；
竹屏那处写在 `.elder-panel` 的 `background` 上，而 `background-image` **不吃 opacity**。

一张水印要成立得同时满足两件事：**边缘化得开**（mask 渐隐，不能是矩形）、
**强度压得住**（≤10%）。下一轮用 `mask-image: linear-gradient(...)` 从底部渐隐，
并且贴在能单独控 opacity 的伪元素上。

### 7. 拿掉 Atkinson 之后，数字的辨识度弱了

`Atkinson Hyperlegible` 只覆盖拉丁与数字，于是「11:00 复诊前准备病历」里数字和汉字
是两套字形、两个重心。拿掉它是对的（同一行两种笔画粗细比缺口零更糟），
**但代价要说清楚**：Atkinson 是为低视力设计的，`0/O`、`1/l/I`、`6/9` 区分得比系统
字体好，换回系统数字之后这一点弱了。要补回来得找一款**带汉字**的高辨识度字体。

### 8. 照护页整体重构、多用美术元素——用户提过，没做

`/care` 概览那一行的金框已经去掉（改 `:root` 上那个变量，一处生效），五行现在是
干净的卡片。**但「整体重构」和「多用美术元素」这两条没有做。**

---

## 未提交：还有一批工作在磁盘上而不在 git 里

上一版这一段说「`/elder2` 整页、它的闸门、五个新端点一次提交都没有」。**那已经不成立了**
——它们在 `a788a94`（并行九路的检查点）里全部落进了 git。核对过：`git log -1` 对
`backend/static/elder-v6.html`、`landing.js`、`index.html`、
`docs/33_FOUR_DESIGNS_WALKTHROUGH.md` 都指向 `a788a94`。

写这份文件时的 `git status --short`（2026-08-19，**五个 agent 正在并行改代码**）：

```
 M backend/static/art-cards.css
 M backend/static/elder-v6.css      elder-v6.html
 M backend/static/family-v6.css
 M backend/static/judge.html        judge.js
 M backend/static/sw.js             trust.js
 M backend/tests/test_elder_design2.py   test_family_design2.py
 M frontend_redesign/ia/11_control_inventory.{json,md}
?? backend/tests/test_trust_judge_polish.py
```

**这不是缺陷，是当时的事实**，写下来是因为「文档说有」和「git 里有」在交付时是两件事。
读到这里时先跑一次 `git status` 核对——上面这张表在写完的那一分钟就开始过期了。

**并且**：`git log` 里 `20 个提交在本地，一个都没推`（`ONBOARDING.md` 第四节）这句话
也要重新数一遍再引用。推送是对外动作，必须由人明确同意。

---

## 未验证（不是通过，是不知道）

### 9. 真机鸿蒙侧

`harmonyos/` 下的 ArkTS 工程在 DevEco 里编译过，但**没有在真机或模拟器上跑过完整
流程**。所有关于鸿蒙端的说法都限定在「代码存在且能编译」。

### 10. Safari 与 Firefox

全部浏览器闸门跑在 Chromium（headless）上。两处已知的行为差异**没有实测**：

- Safari 对 `100dvh` 和 `env(safe-area-inset-*)` 的处理与 Chromium 不同，而老人端的
  定高框架依赖这两个。
- Firefox 没有 Web Speech API。代码里有降级（提示改字、聚焦输入框），逻辑上正确，
  但没有在真 Firefox 上点过。这也是「输入行必须在首屏」那条闸门存在的理由。

### 11. 离线神经语音在竞赛机上的表现

`.onnx` 模型不进交付包（体积），所以默认走浏览器合成。神经语音那条路径在这台开发机
上验证过，在竞赛机上没有。

### 12. 真实老人用户测试

零。所有适老化判断来自设计规范、参考实现和推理，**没有一位真实老人用过这个东西**。
这是这个项目最大的未验证项，比上面所有条加起来都大。

---

## 已修但值得记住的（不要再犯）

这些不是待办，是脚印。完整版见
[`frontend_redesign/reference/ANTI_PATTERN_LIBRARY.md`](frontend_redesign/reference/ANTI_PATTERN_LIBRARY.md)。

| 症状 | 根因 | 抓到它的东西 |
|---|---|---|
| CI 从没在浏览器里加载过任何页面，却一直打印 PASS | `websocket-client` 不在 lock 文件，三个闸门走 `except ImportError: return 0` | 人工核对 CI 日志 |
| 两整页按钮全死，`node --check` 全绿 | TDZ 是合法语法，解析不等于运行 | 新加的 CDP console-error 闸门 |
| 手机上五个页面首屏以下的内容不存在 | `max-height: 100dvh; overflow: hidden` 没限定页面 | `test_mobile_reachability` 的几何探针 |
| 老人看不到自己的记录 | `#logPanel` 排在定高框架里定高子元素的后面 | 手写探针，量可见高度 |
| 把手机横过来就没有输入框 | 定高处理挂在 `max-width` 下 | 七视口可达性断言 |
| Voice Orb 十一态有三态在灰度下不可辨 | 只靠动效区分，而全局 reduce 会掐掉动效 | 联系表（人眼），闸门只保证不相同 |
| 老人端三个分区整幅贴死在屏幕两侧 | 「留白改由里面的元素自己带」这个决定只执行了三分之一 | 手写探针量**字形**位置（量盒子看不出来） |
| 首页看起来没问题，所以一直没人发现上一条 | 截图只截默认那一屏；横向溢出检查也不响——贴边不是溢出 | 逐个分区切过去再量 |
| 全 App 有 12px / 14px 两种字号，而字阶里只有 13 和 15 | 写死的 px 绕开令牌层 | 手写探针列出每一处 <15px 的字 |
| 家人端「同步到他的手机」点下去什么都不发生 | 两个字段带 `required` 而表单没 `novalidate`，浏览器在 submit 之前就拦下，JS 里的中文提示从来没机会跑 | 驱动测试量 `body.innerText.length` |
| 「今天不用您操心」永远显示，而它是产品的核心主张 | 演示数据里从来没有过一件需要家属点头的事 | 驱动测试数 `needYou` |
| 老人端「家人」屏和照护页「安全」屏同时是空的 | `contact_profiles_v4` 从来没被种过（种的是另一张表 `safety_contacts_v4`） | 两屏一起看，不是一屏一屏看 |
| 服务端 500 在界面上和「真的没数据」长得一模一样 | `api(...).catch(() => [])` 把错误吞成空数组 | 判据落在接口上，不落在屏幕上 |
| 设计二四屏里有两屏是死的，而版式看起来完全正常 | `family.js` 和 `care.js` 顶层同名 `const api`，`SyntaxError` 让整个文件不执行 | 数首屏发出的后端请求个数（6 → 11） |
| 抽屉卡在屏幕中间，调平移百分比调不好 | 百分比按元素自己的高度算，藏不藏得住取决于锚点到视口底边的距离，两个数没有关系 | 改用 `visibility: hidden`；而**验证只能靠截图**——它不改变盒子几何，探针量不出来 |
| 横屏打字入口在首屏外 900px，`position: fixed` 反而更差 | `animation-fill-mode: both` 保留的是插值结果**单位矩阵**，不是 `none`，照样给 fixed 后代创建包含块 | 取每一层的 `offsetTop` 和 `offsetParent`，不要数兄弟高度 |
| 一条闸门把「多接通一个控件」罚成红 | 它写的是**上限**（`len(with_api) <= 8`），方向反了：接通更多变红、弄断反而变绿 | 换成下限 + 具名边表；它自己的报错信息早就写着该怎么改 |
| 并行期间一次全量 pytest 的 7 条红，四十分钟后只剩 4 条 | 另外 3 条是别的 agent 改到一半的中间态 | 只重跑那几个文件；一次快照分不出「真缺陷」和「正在改」 |
| 一个页面不引 manifest，就整批绕开了 theme-color 那条闸门 | `INSTALLABLE` 按「引没引 manifest」算——设计是对的，副作用是缺席即豁免 | 逐页把四项（sw / manifest / theme-color / needs-server）并排数一遍 |

---

## 这份文件自己的边界

它列的是**我知道**的问题。没有列出的东西分两类：不存在的，和我没发现的。这两类在
这份文件里长得一模一样。
