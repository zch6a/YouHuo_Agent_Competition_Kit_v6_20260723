# 老人端设计二（v6.0）接线施工图

设计二要和设计一**并行存在**：两条路由、两套版式、**同一份 `elder.js`**。

不给它单写一份接线，理由是这个项目已经因为「两套实现各自往返都绿、
跨子系统才红」栽过（见 `project_youhuo_two_sources_of_truth`）。
一份逻辑、两张皮，是唯一不会分叉的做法。

来源：`youhuo_elder_frontend_v6.0_complete.zip` → `modular/`
（`index.html` 11 KB + `css/style-01.css` + `js/script-01.js`、`script-02.js`）。
包里那个 10.3 MB 的 `source-reference` 是我们自己 2026-08-18 打的包，没有新美术。

---

## 一、契约现状

`elder.js` 需要 **41 个 id**。设计二已有 18 个，**缺 23 个**：

```
已有  agentTitle roleOpening todayLine nextItem nextTime nextTitle nextWhere
      nextOpen mic micHint typeInstead reminders focusLayer focusBack
      focusMic chat text send
```

`data-panel` / `data-section` 都是 `home / kin / log / me`，和设计一一致，
`common.js` 的 `initSections` 可以直接用，**不用改**。

---

## 二、缺的 23 个，分两类

### A. 必须是**真实容器**（11 个）

JS 会往里写内容、读值、切显隐。补成空壳的后果不是「少一个功能」，
而是**内容写进去了但看不见**——这是这个项目最典型的失败形态。

| id | JS 用途 | 设计二的落点 |
|---|---|---|
| `relianceHost` | 容器 | **`#focusLayer` 内，`#chat` 之后**。玻璃盒确认卡写在这里；放错位置＝系统在等老人确认一笔付款而屏幕上什么都没有（`elder.js:608` 有整段注释记着这个真实缺陷） |
| `status` | 写文本 + 显隐 | `#focusLayer` 内，`#chat` 之前 |
| `activityLog` | 容器 + 写文本 | **`log` 面板的 `.organic-flow`** — 直接给它加 id，它本来就装 `.record-bubble` |
| `kinList` | 容器 | **`kin` 面板的 `.family-tree`** — 直接加 id，它本来就装 `.family-person` |
| `taskDetailBody` | 容器 + 写文本 | 需要新建详情层（设计二没有） |
| `fontScale` | 读值 + 监听 | ⚠ 设计二「我的」用的是 `.segmented` 按钮组，**不是 `<select>`**。`elder.js` 读 `.value`——见下面第四节 |
| `speechRate` | 读值 + 监听 | 同上 |
| `modeName` | 写文本 | `#roleHeader` 内一个 span |
| `semanticPill` | 写文本 | `#focusLayer` 内 |
| `voicePill` | 写文本 | `#focusLayer` 内 |
| `logEntryLabel` | 写文本 | `home` 面板的记录入口按钮里 |

### B. 只挂监听或切类名（12 个）

设计二可以用**自己的控件**，只要 id 对上。

```
companionEntry  companionEntryLabel  detailBackdrop  kinContact
logEntry        modeBadge            repeatLast      saveProfile
stepBack        taskDetail           taskDetailClose taskSpace
```

对应设计二已有的控件：
- `kinContact` → `kin` 面板的 `.contact-primary`
- `logEntry` / `logEntryLabel` → `home` 面板需要新增一个记录入口
- `saveProfile` → `me` 面板需要一个保存按钮
- `taskDetail` / `taskDetailBody` / `taskDetailClose` / `detailBackdrop` → 一整个详情层
- `taskSpace` / `relianceHost` → Focus Mode 内

---

## 三、上线要动的五处

```
1. static/elder-v6.html      ← modular/index.html 改名
                                （原名 index.html 会覆盖首页）
   static/elder-v6.css       ← css/style-01.css
   static/elder-v6.js        ← script-01/02 合并；先确认它和 elder.js 不打架
2. 补上面 23 个 id
3. api.py                    加路由 /elder2
4. sw.js                     外壳清单 +3 条，VERSION v13 → v14
5. 首页                      加入口，评委能切换两版
```

`elder-v6.html` 里要引的是**仓库的** `elder.js` / `common.js` / `identity.js`，
不是包自带的 `script-*.js`——后者 `fetch×0`，一个后端调用都没有，是纯 UI 壳。
包自带的脚本只在它负责纯视觉行为（吉祥物拖拽、动效）时保留。

---

## 四、唯一一处真正的结构冲突

**「我的」那两项设置。** 设计一是 `<select>`，`elder.js` 读 `.value`；
设计二是 `.segmented` 按钮组（三个按钮，`.active` 标当前项）。

两条路：

- **改设计二的 HTML**：把按钮组换成 `<select>`。最省事，但丢掉设计二的观感。
- **让 `elder.js` 同时认两种**：读值时先看 `.value`，没有就找
  `.segmented .active` 的 `data-value`。改一处，两套皮都能用。

**推荐第二条**——它保住了「一份逻辑两张皮」这个前提。
第一条等于让逻辑绑死一种控件形态，下一套设计再来还得改一次。

---

## 五、验收判据（不许只看渲染）

装完必须驱动，不能只截图：

1. 四个面板逐个打开，每个都有真数据（对照设计一同一面板的字数）
2. `#typeInstead` → 输入一句 → **有写请求发出**（设计一验过：
   `POST /v2/chat` + `POST /v6/interaction/plan`）
3. 「我的」改语速 → `PUT /v6/profiles/{id}` 发出，刷新后仍是新值
4. 七个视口下 `#typeInstead` 都在首屏内（`test_mobile_reachability`）
5. 底栏滚动前后不动（判据要**滚到底再量**——只量 scrollTop=0 会漏）
6. 全量 pytest

第 2 条尤其不能省：设计一装完时，界面全对而打字**零请求**，
是驱动才发现的。
