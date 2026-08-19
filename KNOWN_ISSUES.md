# 已知问题

任务书要求「不许撒谎说绝对没有 Bug」。这份文件是那句要求的对面：**已经知道、但没有修的**
东西，逐条写清楚是什么、为什么没修、以及它在什么情况下会咬人。

分级：

- **P0** 演示当场会坏，或者会让老人做错事。**当前为 0。**
- **P1** 有真实用户或评委能撞到的功能缺失。**当前为 4 条。**
- **P2** 体验或工程上的欠账，不影响正确性。
- **未验证** 我没有条件测的东西。它不是「通过」，是「不知道」。

最后更新：2026-08-19（两套设计二 `/elder2` `/family2` 并行上线之后）。

---

## 当前红灯：全量 pytest 有 5 条红

不藏。2026-08-19 02:00 的一次全量：

```
cd backend && ..\.venv\Scripts\python.exe -m pytest -q -p no:randomly
5 failed, 2053 passed in 387.75s
```

### 红 1–4：四份重型报告是用另一版源码跑出来的

```
test_release_hygiene.py::test_heavy_reports_were_produced_by_the_current_source
  [mass_audit_v5_1000000] [chaos_v5_400] [load_v6_5000] [http_smoke_v6]
```

四份报告都盖着 `72848d13…`，而当前 `backend/youhuo` 的指纹是 `d81114f0…`。
`backend/youhuo/` 在这一轮被改过（`api.py` 加了 `/elder2` 路由、`app_api.py` 加了
五个 `/api/v1` 端点、`app_schemas.py` 加了对应契约、`surfaces.py` 登记了 `/elder2`），
而重型验证是 08-18 23:27 跑的。

**这不是缺陷，是这道闸门在正确工作**——它防的正是「读一份报告等于跑过一次验证」。

**修法**：重跑 `verify_heavy`（约四分钟）。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify_heavy.ps1
```

**注意**：跑之前先确认没有别的 agent 正在改 `backend/youhuo/`——它跑完就盖当时的指纹，
中途被改过就白跑。

### 红 5：控件清单的 `apis` 列越过了它自己的天花板

```
test_control_inventory_is_the_fact_source.py::test_the_apis_column_is_known_to_be_unimplemented
AssertionError: `apis` 列已经填到 9 个了——好事。assert 9 <= 8
```

这是一条**棘轮断言**：它写死了「`apis` 只填到 5/145，等于没实现」这个事实，并要求
这件事不被忘记。断言本身带着修法（「把这条测试改成正向断言，并把 `_COVERAGE_FLOOR['apis']`
抬上去」）。

**触发它的是这一轮的改动，而且是往好里改的那个方向。** 逐条比过：
`HEAD` 那版清单 339 个控件、`apis` 填了 **8** 个（正好卡在天花板上）；
当前工作树 376 个控件、填了 **9** 个，多出来的是 `family-v6.html` 里第二个
`#reminderTitle`（`/v2/family/reminders`）。

**为什么这里没修**：`test_control_inventory_is_the_fact_source.py` 是代码文件，
这一轮我只拥有文档。它归改 `family-v6.html` 的那个 agent，或者归下一个人。

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

### B. 入口页会跳过自己：冷启动跳转让评委看不到四个设计入口

**在哪** `backend/static/landing.js:40`。

**什么样** 判据是「`localStorage` 里有 `youhuo_role_v1`（此前点过身份卡）
**并且** 这个标签页的 `sessionStorage` 里没有 `youhuo_visited_v1`（本标签页还没打开过
任何内页）」。两条同时成立时：

```js
location.replace(DESTINATION[remembered]);   // '/elder' 或 '/family'
```

于是打开 `/` 会**立刻**弹走，`.yh-designs` 那一节（四个设计入口）一眼都看不到。

**这一段逻辑本身是对的**，而且是上一轮修好的：它防的是「从站内点回首页被一路弹回去」，
第一版用 `document.referrer` 判冷启动，被 `Referrer-Policy: no-referrer` 弄成恒真。
问题是**前提变了**：这一页多了一节只有停在首页才看得见的内容，而它是这次并行设计
在产品里唯一的入口。

**为什么没修** 这是代码文件，这一轮我只拥有文档；另有 agent 在改前端。
真要修，方向是「有设计入口这一节时不自动跳转」或者「跳转前给一个可取消的提示」，
**不是**把身份记忆整个拿掉——那会把上一轮修好的问题带回来。

**现场绕过（两个都不用改代码）**

1. 地址写 `http://127.0.0.1:8041/?stay=1`；`landing.js:32` 的 `params.has('stay')`
   会跳过这次跳转。
2. 或者用一个从没点过身份卡的浏览器 / 无痕窗口。

**什么时候会咬人** 彩排时点过一次身份卡，答辩当天用同一个浏览器新开标签页打开首页。
**自动化闸门天然看不到这一条**：每轮全新 profile，`localStorage` 是空的。

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
`test_file_protocol_fallback.py` 的 `PAGES` 写死为原来那七页，
所以它既没抓到这一条，也没覆盖 `elder-v6.html`（那一页恰好有，是写它的人自己加的）。

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

## 未提交：这一轮有一批工作在磁盘上而不在 git 里

2026-08-19 02:00 的 `git status`：

```
 M backend/static/family-v6-a.js  family-v6-b.js  family-v6.css  family-v6.html
 M backend/static/index.html  landing.css  sw.js
 M backend/youhuo/api.py  app_api.py  app_schemas.py  surfaces.py
 M frontend_redesign/ia/11_control_inventory.{json,md}
?? backend/static/elder-v6.{html,css}  elder-v6-a.js  elder-v6-b.js
?? backend/tests/test_elder_design2.py  test_family_design2.py
?? backend/tests/test_landing_design_entries.py
?? backend/tests/test_app_daily_report.py  test_app_emotions.py  test_app_privacy.py
```

也就是说：**`/elder2` 整页、它的闸门、以及五个新的 `/api/v1` 端点
（`privacy/data`、`privacy/erase/preview`、`privacy/erase`、`emotions/review`、
`daily-report`）目前一次提交都没有。** 写这份文件时另有 agent 正在改这些文件。

**这不是缺陷，是当时的事实**，写下来是因为「文档说有」和「git 里有」在交付时是两件事。
读到这里时先跑一次 `git status` 核对。

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

---

## 这份文件自己的边界

它列的是**我知道**的问题。没有列出的东西分两类：不存在的，和我没发现的。这两类在
这份文件里长得一模一样。
