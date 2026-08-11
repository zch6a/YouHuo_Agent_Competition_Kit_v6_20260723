# 浏览器 QA

**每一项都在真实浏览器里跑过。** 这句话在这个项目里不是套话——CI 曾经因为
`websocket-client` 不在 lock 文件里，三个浏览器闸门全部走 `except ImportError:
return 0`，验证链紧接着打印 `ALL V6 DETERMINISTIC VERIFICATION STAGES PASSED`。
把 `care.js` 第一行改回那个让两整页按钮全死的 TDZ 缺陷，CI 照样全绿。

现在缺依赖是**硬失败**。

最后更新：2026-08-11。

---

## 一、跑在什么上

| | |
|---|---|
| 引擎 | Chromium（`--headless=new`），本机 Chrome |
| 协议 | CDP（Chrome DevTools Protocol），无 Selenium / Playwright |
| profile | **每次运行前 `shutil.rmtree`**。这一站注册 service worker，复用 profile 会让浏览器拿上一次构建的 HTML 和 CSS——一个会给你看昨天构建的工具不是测量，是传闻 |
| 数据库 | 一次性临时库。这些检查会真的按下 SOS、限时破窗和支付授权，那些写操作不能落进仓库的 `data/youhuo.db` |

**没跑在什么上**：Safari、Firefox、真机鸿蒙。见 `KNOWN_ISSUES.md` 第 6、5 条。

---

## 二、每次跑什么

### 2.1 页面加载（7 页）

`/`、`/elder`、`/family`、`/care`、`/trust`、`/judge`、`/stage`

每页在 **390×844 手机视口**下加载（视口在 `Page.navigate` **之前**设置，媒体查询才能
从加载那一刻就生效），然后：

- 无未捕获异常
- 无 `console.error`
- 无同源 4xx / 5xx 请求
- 无横向溢出（文档宽度与每个元素的右边缘都在视口内）
- 标签栏的 sprite 图标全部解析出来（外部 sprite 解析失败时图标是空的，但布局照旧）

### 2.2 控件遍历（99 个）

**逐个按下**页面上的每一个 `<button>`。三层顺序：

1. 先按展开类（`.seg`、`<summary>`、`[data-sheet-open]`）——不先展开，抽屉里的控件
   永远按不到
2. 再按普通控件
3. 最后按关闭类（`[data-sheet-close]`）

可见性用**命中测试**判定：先滚进视野，再看中心点上最上面的元素是不是它。
`!el.offsetParent` 那种判法会把 111 个真实可见的元素判成不可见。

上限 60 次，超过就报错——两个按钮互相召唤会无限循环。

`REQUIRED_PRESSES` 钉住几个关键控件必须真的被按到（`#saveProfile`、`#repeatLast`、
`#companionEntry`、`#logEntry`、`#scheduler`、四个照护演示、四个可信演示）。
"没按到"和"按了没事"在遍历结果里长得一样，所以要点名。

### 2.3 玻璃盒

高风险任务必须带出信任卡（`relianceHost` 非空）。

### 2.4 身份自愈

服务器不认识的身份（换库、换部署）必须被自动换掉，而不是把这个浏览器永久变砖。
检查会写一个假身份进 `localStorage`，然后确认：页面不再报错、数据回来了、生活日报
打得开。

R18 还补了会话那一半：`renew()` 清身份但没清会话，`youhuo_session_v2` 还指着旧家庭，
于是"应用打得开、待办看得见、但一说话就报系统暂时不可用"。

### 2.5 多标签页身份

三个标签页同时冷启动，必须只开通**一个**家庭。用 Web Locks
（`navigator.locks.request('youhuo-visitor-provision')`）+ 锁后二次读缓存。

检查读的是每个 document 自己 `YouHuoIdentity.ready()` 的结果，**不是 localStorage**
——读存储只能证明最后写进去的是什么，证明不了三个页面各自认为自己是谁。

### 2.6 Voice Orb 十一态

模拟 `prefers-reduced-motion: reduce`，用 constructable stylesheet 停掉全部过渡与
动画（这一站的 CSP 是 `default-src 'self'`，行内 `<style>` 会被**静默**拦掉），
逐态取两道环与 orb 的计算样式指纹，两两比对。

状态名从页面自己的 `window.__voiceOrbStates` 读——脚本里另写一份，两份就会各自漂移，
而漂移之后检查照样绿。

汇总行印出量到的态数并设下限：一个"跑了但什么都没量到"的检查和没有这个检查是一回事。

### 2.7 评委页七拍

按下「从头演一遍」，等七拍走完，然后逐句检查 Product 层**不含英文**。

这条只有演过之后才测得到——那七句话是运行时从真实响应里拼出来的，静态扫源码看不见。
第一版演完之后漏出了三个英文枚举和一个四位小数。

### 2.8 对比度（14 个组合）

见 [`ACCESSIBILITY_AUDIT.md`](../accessibility/ACCESSIBILITY_AUDIT.md) 第 1.1 节。

### 2.9 首屏可达（7 个视口）

`test_the_typing_route_is_in_the_first_screen_on_every_viewport`：
390×844、320×568、768×1024、1024×768、1280×800、844×390、667×375。

### 2.10 全尺寸截图

`shoot_pages.py`：9 视口 × 7 页 × 明暗 = 126 组，每组两张（首屏 + 全页）= **252 个
文件**。落盘后逐个核对存在且非空。

首屏那张必须**先拍**：`captureBeyondViewport=True` 会把视口内部撑到内容高度且不可靠
地还原，之后再拍首屏就是一个 2288px 视口的顶部 844px，所有 `position: fixed` 的东西
都掉到裁切线以外——底部标签栏在每一张首屏图里都消失过，而它的布局一直是对的。

---

## 三、当前结果

```
pytest                984 passed, 1 skipped
check_browser_js      14 个 JS 按真实加载方式（module / script）逐个语法检查
speech_text           34 项朗读文本断言
check_page_runtime    7 页 · 99 控件 · Voice Orb 11 态 · 评委页 7 拍全中文
check_contrast        14 个页面×模式组合
shoot_pages           126 组 / 252 个文件，无横向溢出
```

---

## 四、这些检查自己出过的错

记在这里，因为下一个改闸门的人需要知道。

| 症状 | 根因 |
|---|---|
| CI 从没在浏览器里加载过页面，一直 PASS | 缺依赖被当成"跳过"，然后 `return 0` |
| 两整页按钮全死，语法检查全绿 | `node --check` 解析不执行；TDZ 是合法语法 |
| 收起分区后测得的高度"没变" | 复用 profile，service worker 给了昨天的构建 |
| 底部标签栏在每张首屏图里消失 | `captureBeyondViewport` 之后视口没还原 |
| 汇总行报 108 张而磁盘上 216 个 | 数的是组数，每组两张 |
| 四个变异全"红" | 变异脚本自己有 SyntaxError，红的是脚本不是缺陷 |
| 两个变异"绿" | 属性重排和类名词序调换是**等价改写**，我没造出缺陷 |
| 探针说面板可见 | 探针自己调了 `scrollIntoView`——脚本能滚 `overflow: hidden` 的容器，手指不能 |
