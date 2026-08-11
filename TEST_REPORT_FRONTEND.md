# 前端测试报告

每一行都可以重跑。命令在下面，重跑不需要读这份报告。

最后更新：2026-08-11。

---

## 一、当前数字

```
pytest backend/tests                984 passed, 1 skipped
check_browser_js.py                 14 个 JS 文件（按真实加载方式：3 module / 11 script）
speech_text                         34 项朗读文本断言
check_page_runtime.py               7 页 · 99 控件 · Voice Orb 11 态 · 评委页 7 拍全中文
check_contrast.py                   14 个页面×模式组合
shoot_pages.py                      126 组 × 2 = 252 个文件，无横向溢出
```

跑法：

```bash
.venv/Scripts/python -m pytest -q backend/tests
.venv/Scripts/python backend/scripts/check_browser_js.py
.venv/Scripts/python backend/scripts/check_page_runtime.py
.venv/Scripts/python backend/scripts/check_contrast.py
```

整链：`./verify_all.ps1` → `./verify_heavy.ps1`。

---

## 二、这一轮（R19–R22）新增的闸门

每一条都**先红后绿**：写完之后把它要防的那个缺陷放回去，确认它变红，再复原。
一个只绿过、没红过的检查还不是检查。

| 闸门 | 它守什么 | 变异 |
|---|---|---|
| `check_voice_orb_states` | 关掉动效后 Voice Orb 十一态两两可辨 | 4 红 |
| `test_voice_orb_states.py`（7 条） | 状态声明 / 样式 / 可达性 / 标签四者对齐 | 8 红 |
| `test_the_typing_route_is_in_the_first_screen_on_every_viewport` | 七个视口下输入框整个在首屏且点得到 | 5 红 |
| `test_trust_receipt.py`（6 条） | 凭证真办、按任务筛链、失败不谎报、正文无枚举名 | 5 红 |
| `check_judge_story` | 七拍演得完，且 Product 层全中文 | 4 红 |

**变异测试自己也会说谎，两种方式：**

- 一次变异脚本里混进了一行 JS 注释（`//`）导致 SyntaxError，四个变异**全部**报红
  ——那是四次假红。
- 两次"绿"其实是我**没造出缺陷**：属性重排和类名词序调换是等价改写；`success` 在
  `activityFor()` 的两张映射表里各出现一次，只改一处根本没让它不可达。

还有第三种：锚点带 `\n` 在 CRLF 文件上匹配不到任何东西，而"锚点 0 次"和"断言没守住"
在结果里长得完全不一样。变异器现在先归一化换行。

---

## 三、这一轮实测出来的缺陷

按"是量出来的还是看出来的"分开。

### 3.1 量出来的

| # | 页面 | 实测 |
|---|---|---|
| 1 | `/elder` | 1024×768 输入行在首屏外 156px；1280×800 差 138px；**844×390（手机横屏）差 522px，麦克风也在外面** |
| 2 | `/elder` | 「我的记录」面板高 252px，只有 70px 在屏内，其余被 `overflow: hidden` 裁掉**且滚不到** |
| 3 | `/elder` | 320×568 下记录面板的标题被 sticky 抓手压住（`scrollIntoView` 把目标顶到滚动容器顶边） |
| 4 | 全站 | `prefers-reduced-motion` 下 Voice Orb 的 listening / speaking / clarifying 三态塌回别的态 |
| 5 | `/elder` | `const mic` 声明在 700 行之后而 `setActivity()` 要用它——TDZ，会把整页打哑 |
| 6 | `/judge` | 七拍 Product 层漏出三个英文枚举和一个四位小数 |
| 7 | 工具 | `shoot_pages` 汇总行报 108 而磁盘上 216 个文件 |
| 8 | 1280×800 | `.rail` 输给 `.rail.sheet`（一个类 vs 两个类），侧栏不滚而是把 main 顶大，567px 用手滚不到 |

### 3.2 看出来的（闸门全绿，人眼否掉）

Voice Orb 第一版通过了指纹闸门，然后被灰度联系表否掉：

- `processing` / `executing` / `clarifying` 三个虚线环肉眼几乎一样
- `pressed` 和 `clarifying` 的环 `inset: 22px` 正好被 orb 挡住（dial 200、orb 156，
  边界就在 22）——指纹不同，但它是**隐形的**
- `success` 弱得像什么都没发生；`speaking` 的光晕在浅色背景上基本消失

**结论写进闸门自己的注释里了**：那条闸门量的是下界。它能保证"没有两态是同一张图"，
保证不了"看得出来是两回事"。视觉的东西必须看。

---

## 四、我自己在这一轮里犯的错

写在这里，因为它们决定了这份报告该被信到什么程度。

| 错 | 后果 |
|---|---|
| 探针先调了 `scrollIntoView` 再量可见性 | 脚本能滚 `overflow: hidden` 的容器，手指不能——量的是另一个问题的答案 |
| 截图用 `getBoundingClientRect`（视口坐标）当 `captureBeyondViewport` 的 clip（文档坐标） | 我盯着一张页头的截图，以为在看凭证 |
| `position: sticky` 静静地什么都没发生 | 祖先的 `overflow: hidden` 让它成了滚动容器，而那个容器从不滚动 |
| `grid-row: 1 / -1` 退化成"跨一行" | `-1` 指显式网格的最后一条线，而我只声明了列 |
| 三条我自己写的新断言是错的 | 文档长度下限 400（实际最小 299）、"mcp 必须在 optional-dependencies"（mcp 根本不是 Python 依赖）、把「不可信」当成禁用词（它是这个代码库里的分类名） |
| 一条断言在我自己的注释上假红 | 它没有先剥注释，而那段注释里恰好同时有 `overflow: hidden` 和 `max-height` |

---

## 五、什么**没有**被测

- **Safari / Firefox**：一次都没跑过。`100dvh`、`env(safe-area-inset-*)`、
  Web Speech 缺失这三件事在这两个引擎上是不同的。
- **真机鸿蒙**：ArkTS 工程编译过，没在真机或模拟器上跑过完整流程。
- **读屏软件**：语义、`aria-live`、标签都按规范写了，NVDA / VoiceOver 没实测。
- **200% 缩放**、**Windows 强制颜色模式**。
- **真实老人用户**：零。

详见 [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md)。

---

## 六、一句话

这套闸门能证明的是：**七个页面在 Chromium 上加载干净、99 个控件按下去都有反应、
颜色和触控尺寸达标、十一个语音状态在关掉动效后仍然两两可辨、评委页七拍能演完且
说的是中文。**

它证明不了好看，也证明不了一位老人用得下去。前者你看截图自己判断，后者需要真实用户。
