# 前端终极精修日志

每一条：**依据（Skill / 规则）· before → after · 浏览器证据 · 测试 · 变异结果**。
没有浏览器证据的不写进这张表；只有"看起来更好"的不算证据。

当前状态：`pytest 1217 passed` · 五道浏览器闸门 exit 0 · `verify_heavy` ALL STAGES PASSED。

---

## 一、这一轮真正学到的一件事

**读到的那个值，不一定是决定结果的那个值。**

同一个错误在这一轮出现了 **五次**，每次换一层皮，每次都让某个闸门"为了错误的理由绿"：

| # | 读的是 | 决定结果的是 | 后果 |
|---|---|---|---|
| 1 | 宿主 `<svg>` 的计算 `fill`（CSS 初始值 = 黑） | `<symbol>` 自己的 `fill="none" stroke="currentColor"` | 对比度审计报了一条不存在的失败 |
| 2 | CSS 里 `.tab.is-current svg { stroke-width: 2.3 }` 这条声明存在 | `<symbol>` 自己的 `stroke-width="1.8"` | 「当前 Tab 图标变粗」这条无障碍通道**从来没画出来过**，而守它的测试一直绿 |
| 3 | `--numeric-plain: "zero" 0` 这条声明存在 | 这一版 Atkinson 的斜杠是字形轮廓，不是可替换字形 | 两段注释描述了一个不存在的效果，斜杠零今天仍在屏幕上 |
| 4 | 子元素自己的 `display: inline` | 祖先 `nav` 的 `display: none` | Lane B 差点报出一条不存在的 P1（0×0 链接仍在焦点序） |
| 5 | 无指针悬停时的 `data-activity` 形态 | `:hover` (0,3,0) 压过 `[data-activity]` (0,2,1) | speaking 与 idle 像素相同，而闸门量的是用户永远看不到的那一版 |

**我自己也栽了两次**：把 `.tab-icon` 的修复先后写进 `@media (min-width: 761px)` 和
`@media (max-width: 760px)`——两次都只覆盖一半视口，而第一次恰好覆盖了审计所在的那一半，
所以它绿了。最后写了一个数括号判作用域的小工具，不再靠缩进看。

第三次是在**验证**上：我用 `Input.dispatchMouseEvent` 造 `:hover` 然后报「修好了 ✓」，
而同一张表里 idle 悬停时 `transform: none`——`.mic-big:hover` 明写 `scale(1.04)`，
说明 hover 根本没造出来。实测：`dispatchMouseEvent` 让 **8 个祖先**进了 `:hover`，
唯独没有 `#mic`。**造不出被测状态时，读到的"一致"不是通过，是没测。**

---

## 二、修复清单

### P0（三条，本轮早些时候）

| ID | 现象 | before → after | 证据 |
|---|---|---|---|
| A-01 | 语音说完话屏幕不动——她在等确认 126.50 元的付款，屏上写「今天没有要办的事」 | `setFocus(true)` 提到 `send()` 咽喉处 | page_runtime 绿 |
| A-02 | 「用打字说」点下去命中「已完成」 | `.mic-stage { min-height: min-content }` + 首页可滚 | **建两条真提醒后做命中测试**，三个探针全命中自己（769 vs 745 不重叠） |
| A-03 | 宽屏三个分区没有入口，含「我的」——语速与字号两个无障碍控件所在页 | `.tabbar:not(.elder-tabs)` | 实测 800×1200 / 1360×900 命中 0 个 → 全部可达 |

A-03 的根因和 Phase 0 踩的是同一个：前面那块专门写的 `.elder-tabs` 修复（注释标题
「宽屏上它不能消失。」）与后面的 `.tabbar` 特异性同为 (0,0,1,0)，后者赢——**那次修复一直是死的**。

### P1

| ID | 依据 | before → after | 浏览器证据 | 变异 |
|---|---|---|---|---|
| **MO-04** | Emil · 状态必须可见 | `body[data-activity="speaking"] .mic-big` → 加 `:not(:disabled)`，(0,2,1) → (0,3,1) | 强制 `:hover` 下：speaking 保住 12px 光晕、pressed 渲染 `0.94`（原先都被 hover 的 `1.04` 压掉） | ✅ 摘掉 `:not(:disabled)` → 闸门点名「idle 与 pressed」「idle 与 speaking」，**且只在悬停那一遍** |
| **A-02(P4)** | Impeccable · 非颜色通道冗余 | sprite 删掉 5 处 `stroke-width="1.8"`，线宽交给 CSS；规则从两个媒体查询里提到全局 | 真实页面光栅化：当前 Tab 墨量 **手机 +18.6% / 宽屏 +31.6%**（改前 0%） | ✅ 测试判据改成「CSS 有加粗规则 **且** sprite 不许钉死线宽」 |
| **MO-03/10** | Emil · UI 动效 < 300ms | `.mic-dial` 的 `border-color` 与 `.role-halo` 的 `opacity`：`--mode-fade`(1000ms) → `--dur-base`(200ms) | 实测 processing 下四条 `border-*-color` 过渡 dur=1000 → 弧要一秒才成形，而 `ring-spin` 从第 0ms 就转 | — |
| **B-02/03** | Web Vitals | `#receipt` / `#dailyReport` 加实测下界的 `min-height` | `/trust` CLS **0.2068 → 0.0187**；`/family` **0.1300 → 0.0505** | ✅ 撤掉预留 → 0.3807 / 0.1665，红 |
| **A-04** | 可达性 | `rec.onerror` 里补 `setFocus(true)` | `#status` 在 `.elder-focus` 内，而 `pages.css:304` 是 `display:none`——六句话一个字都到不了屏幕 | — |

### P2 / P3（择要）

| 内容 | before → after | 证据 |
|---|---|---|
| 老人端「我的」页的工程词 | 「语音：离线本地合成」「语义层：离线确定性」→「说话不出这台手机」「不上网也听得懂」 | HTML 占位符本来就是产品话，是 JS 盖掉的 |
| `common.js` 抛的错 | `演示登录失败：${role}` → `${ROLE_WORD[role]}没能登录` | 整句经 `addBubble` 念给老人：「系统暂时不可用：演示登录失败：elder」 |
| `/trust` 凭证行 | `任务类型 缴费 · 风险级 4 · 意图来源 语义匹配` → `缴费 · 高风险 · 照他说的意思` | 「风险级 4」是裸数字，而 `/family` 早把 1–4 翻成了词——同一件事两页两个名字 |
| 引号系统 | 前端 `「」`47:8、后端反过来 39:0 → 全部 `「」`（13 文件 106 字符） | 她的气泡由前端渲染、优活的回话由后端返回，**同一个聊天窗口里两套引号** |
| `theme-color` | `#f4f6fb`/`#0b1020`（换暖色**之前**的冷蓝）→ `#f7f6f3`/`#0f0e0c` | 色偏 R−B：冷蓝 −7/−21，暖色 +4/+3，**冷暖是反的** |
| 日报结论句 | `。），` 三标点连排、一句两个冒号 | 直接调 `_headline` 复现 |
| `pressed` 提示 | 「松开手，我就开始听」→「按到了，我这就开始听」 | 设置 `pressed` 的只有 `click` 处理器一处，触发时手**已经松开了** |
| `.sheet-handle` | 44px（iOS 下限）→ `var(--tap)` 48 | 抽屉唯一的关闭控件 |
| `.seg` / `.elder-tabs .tab` | 48 → `--tap-key` 56；`.segmented` gap 4 → 8 + `flex-wrap` | 同产品的真 Tab 是 56/57，两套高度 |
| `will-change` ×2 | 都挪到"真的要动"的那一刻 | 两处都是**永久**提合成层；`.role-halo` 那两个还是 `position:fixed; inset:0` 的全视口层 |

---

## 三、新增闸门（每一道都先红后绿 + 变异自证）

| 闸门 | 抓什么 | 变异结果 |
|---|---|---|
| `check_focus_geometry.py` | Focus Mode 几何，5 视口 × 3 Case = 15 组 | ✅ 三路全红 |
| `check_layout_stability.py` | 载入期 CLS > 0.1，7 路由 × 2 视口 | ✅ 撤预留 → 0.3807 / 0.1665 |
| `test_theme_color_matches_the_canvas.py` | 状态栏配色与 `--bg` 令牌脱钩 | ✅ 先红 6 页 × 2 档 |
| `test_report_punctuation.py` | 日报连排标点 / 一句两冒号 / 数字贴汉字 | ✅ 内含"把真的显示过的两句拼回去" |
| `check_voice_orb_states`（扩维） | 十一态在**指针停在麦克风上**时是否仍两两可辨 | ✅ 摘掉 `:not(:disabled)` → 点名两对，且只在悬停那一遍 |
| `test_app_surface_speaks_no_engineering.py`（补洞） | 脚本清单改从 HTML 推；禁用词补一批 | ✅ 三路全红，含「同一句话搬进共享文件」 |
| `write_shot_manifest.py` | 截图批次盖前端指纹，防止对着旧图下结论 | — |

**两道闸门此前不在验证栈里**（`check_focus_geometry`、`check_layout_stability`）——
只在我手敲的时候跑过。谁跑一遍 `verify_all` 看到「ALL STAGES PASSED」，都不会知道
这两件事根本没被检查。现已接进 `.ps1` 与 `.sh`，BOM 与行尾各自保持。

---

## 四、被拒绝的建议（记录理由，免得下次重来）

| 建议 | 裁决 |
|---|---|
| 删 `.notice` 的 4px 警示左边（Impeccable 判 side-tab） | **Not Applicable。** 它不是卡片是 alert；左侧警示条是几十年的既有约定；而且它是**第二条非颜色通道**——删掉会**降低**无障碍水平 |
| 删 `.receipt-offchain` 的 3px 左边 | **FalsePositive。** 中性暖灰 + 右侧圆角 + 浅底 = 引文块。检测器自己的描述写的是"thick **colored** border" |
| 宽屏 0×0 的 Tab 仍在焦点序（Lane B P3） | **FalsePositive。** nav 是 `display:none`、`checkVisibility()` false、40 次 Tab 键 0 次落入。探针读的是**子元素自己**的 `display: inline` |
| `/stage` 17 个 40px 控件 | **Not Applicable。** platform 面、鼠标场景，且注释写明是有意压低的 |
| 把 `--ease-out` 换成 skill 给的 `.23,1,.32,1` | **拒绝。** 两条曲线几乎重合，而现有那条有完整来源论证——换了只是把有论证的换成没论证的 |
| `idle` orb 一直呼吸/发光（计划书硬要求） | **规范已满足。** `getAnimations()` 在 idle 下返回 `[]`（全局取，含伪元素） |

---

## 五、明确没做的（不是通过，是没测）

- **Phase 4 的测量那一半**：Lane B 撞会话额度上限中止。缺 reduced-motion 逐条动画时长实测、
  十一态逐态截图像素差、动效可打断性实测。
- **`setStatus` 还有 5 处写进不可见元素**：这是结构问题（这一页只有一个状态通道，
  而它归 Focus Mode 管），不是五个 bug。A-04 只修了错误路径那一半。
- **13 条推到 Phase 5**：数字字体、`.panel` 三重层级、深色 surface 阶梯反向、
  Tab 图标语义撞车、描边 6 个值、全屏光晕 ≥761px、触屏按压反馈、
  `ring-breathe` / `orb-halo` 是否该删。共同理由：**必须连对照图一起看，不能只跑闸门。**
- **鸿蒙端未编译验证**：这台机器没有 DevEco Studio 与目标 SDK。这是验证边界，不是待修项。

全部条目在 `frontend_redesign/final-polish/KNOWN_ISSUES.md`。

**不宣称绝对零 Bug。** 本文件声明的是：在当前代码、1217 条测试、五道真实浏览器闸门、
上述变异测试与人工审计的范围内，没有已知 P0/P1。
