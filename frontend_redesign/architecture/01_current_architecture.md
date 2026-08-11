# 前端架构现状

## 一句话

七个页面、四层 CSS、十四个 JS 文件，**没有构建步骤**：浏览器请求什么，磁盘上就是
什么。这不是"还没来得及上工程化"，是一条有理由的约束——见文末。

---

## 1. 页面

| 路由 | 文件 | 给谁看 | 视口假设 |
|---|---|---|---|
| `/` | `index.html` + `landing.js` | 第一次打开的人 | 手机优先 |
| `/elder` | `elder.html` + `elder.js` | 老人本人 | **只有手机**（定高框架） |
| `/family` | `family.html` + `family.js` | 子女 | 手机 / 桌面 |
| `/care` | `care.html` + `care.js` | 子女 / 照护者 | 手机 / 桌面 |
| `/trust` | `trust.html` + `trust.js` | 评委 / 审计 | 手机 / 桌面 |
| `/judge` | `judge.html` + `judge.js` | 评委 | 手机 / 桌面 |
| `/stage` | `stage.html` + `stage.js` | 答辩现场 | **只有桌面** |

`/stage` 是唯一一个不注册 service worker 的页面：它是展示环境，一个会缓存自己的舞台
在反复改版时只会给出昨天的样子。

`/elder` 和 `/stage` 是这套里两个"单一视口"的页面，理由相反：老人端定高是为了让输入
行永远在屏幕上；舞台只在桌面出现是因为它的全部内容就是一台手机。

---

## 2. CSS 的四层

```
tokens.css      →  base.css  →  components.css  →  pages.css
（只有变量）      （元素默认）    （可复用组件）      （页面 + 全部响应式覆盖）
```

**加载顺序就是层叠顺序**，这是这套架构唯一的规则。四层里没有任何一层用
`!important` 去赢过前一层（唯一的例外是 `prefers-reduced-motion` 那一块，它必须赢过
一切）。

`pages.css` 的响应式覆盖**集中在文件最末尾**，并且那里写着理由：媒体查询不增加特异
性，一条 `@media (max-width: 760px) { .elder-layout { … } }` 写在 `.elder-layout` 声明
之前会被后者全胜。这个文件里曾经有五条声明因此**永远不可达**，有人写下它们、以为在
调小屏尺寸，实际一次都没有应用过。

### 层与层之间的边界

- `tokens.css` 是**唯一**允许出现颜色字面量与间距字面量的地方。
- `components.css` 里的类名必须带上它所属的那一块（`.demo-stage` 而不是 `.stage`）
  ——四层是全站共享的，通用名词必然撞车。
- `pages.css` 不定义新组件，只定位与覆盖。

三条标尺由 `test_design_rulers.py` 守着：间距落在 4px 网格上、13/15px 字号走令牌、
阴影颜色不写死。三条都只查后三层，`tokens.css` 是定义层，本身就该出现字面量。

---

## 3. JS

十四个文件，两种加载方式：

| 模块（`type="module"`） | 脚本（普通 `<script>`） |
|---|---|
| `elder.js`、`speech.js`、`glassbox.js` | 其余十一个 |

`check_browser_js.py` 按**真实的加载方式**逐个做语法检查——用 script 的规则去检查一个
module 会漏掉 `import`，反过来会漏掉顶层 `this`。

### 共享层

`common.js` 是 `api()` / `login()` / `resolveIdentity()` 的唯一实现。此前这三个函数
在五个页面里各有一份分叉的副本，改一处 API 契约要改五个地方，而漏掉的那个会在演示
当天才被发现。

`identity.js` 负责访客身份：公网部署时每个浏览器拿到自己的隔离演示家庭。它用
**Web Locks** (`navigator.locks.request('youhuo-visitor-provision')`) 做跨标签页互斥
——同时打开三个标签页，只开通一个家庭。

`speech.js` 是朗读层：分句、把日期与金额转成口语（"六十八块四"而不是 "68.40"），
优先走离线神经语音、失败逐句回落到浏览器合成。34 项朗读文本断言守着它。

---

## 4. 严格 CSP 与它的代价

```
default-src 'self'; script-src 'self'; frame-src 'self';
connect-src 'self'; object-src 'none'; base-uri 'self';
frame-ancestors 'self'; form-action 'self'
```

- **无内联脚本**——所以没有 `onclick=`，全部 `addEventListener`。
- **无内联样式表**——`<style>` 会被静默拦掉。要在运行时注入样式只能用
  constructable stylesheet（`new CSSStyleSheet()` + `adoptedStyleSheets`），CSSOM 不受
  style-src 管辖。`check_page_runtime.py` 的 Voice Orb 检查就是这么做的。
- **无 CDN、无网络字体**——字体走系统栈。
- **`docs_url=None`**——Swagger UI 在这套 CSP 下是一张保证白屏的页面，留着它只会让人
  以为接口文档坏了。

`frame-ancestors` 从 `'none'` 放到 `'self'`（配套 `X-Frame-Options: SAMEORIGIN`）是
**唯一一处真的放宽**，为了让 `/stage` 把真实 App 装进同源 iframe。保住的安全属性是
"第三方站点不能把我们的页面套进它的框里"——点击劫持的实际威胁面。
`test_security_headers_are_set` 钉住它的值必须**恰好**是 `'self'`。

---

## 5. Service Worker

`sw.js` 走 stale-while-revalidate 缓存外壳，API 请求整体绕开：

```js
/^\/(v\d+|health|ping|docs|redoc|openapi)(\/|$|\.)/
```

`v\d+` 而不是逐个列 `v2|v3|v4`——此前 `/v7/*` 不在名单里，于是走了陈旧缓存，新加的
接口在装过一次的浏览器上返回上一版的数据。

**外壳清单必须跟着页面走。** 加一个页面而忘了加进外壳，它离线时是一张 404。

---

## 6. 不迁移技术栈的理由

这不是"暂时先这样"。

1. **这是一个要在答辩现场断网演示的东西。** 没有构建步骤意味着交付包解开就能跑，
   不需要 node、不需要 npm install、不需要一次成功的构建。
2. **改一行 CSS 的成本是 0 秒。** 这一轮前端重构里量了几百次布局，每次量都要改一点
   再量一次；有构建步骤时这个循环是分钟级，没有时是秒级。
3. **CSP 能收到这么紧，正是因为没有打包器。** 大多数打包器默认注入内联 runtime。
4. **总量撑得住。** 十四个 JS 文件、四个 CSS 文件，最大的 `elder.js` 也在一千行量级。
   这个规模下模块系统带来的收益小于它带来的构建复杂度。

代价也要说清楚：没有类型检查、没有 tree shaking、没有热更新、依赖顺序靠人维护。
第三条已经在 `elder.js` 上咬过一次——`const mic` 声明在七百行之后，而
`setActivity()` 要用它，暂时性死区会把整页打哑。

---

## 7. 闸门链

```
verify_all.ps1
 ├─ pytest backend/tests                    单元 + 契约 + 静态断言
 ├─ check_browser_js.py                     14 个 JS 按真实加载方式做语法检查
 ├─ check_page_runtime.py                   真浏览器：7 页 / 84 控件 / Voice Orb 11 态
 ├─ check_contrast.py                       14 个页面×模式组合
 └─ …
verify_heavy.ps1                            重型报告，盖当前源码指纹
make_release.py                             只打 git 跟踪的文件
```

`check_page_runtime.py` 是这条链里唯一**真的在浏览器里加载页面**的一环。它曾经因为
`websocket-client` 不在 lock 文件里而整体退化成 `return 0`，验证链照样打印 PASS。
现在缺依赖是硬失败。
