# 四套设计怎么对比看（答辩现场用）

同一套业务逻辑现在挂着**四张皮**。这份文件回答三件事：它们分别在哪、差在哪、
以及站在评委面前该拿哪一套讲哪一件事。

最后更新：2026-08-19（第二轮核实：十条路由 + 新增静态资源逐条真实请求过，
入口页四个 id 在服务端发出的 HTML 里核过，方法记在最后一节）。

> **写这份文件时有五个 agent 正在并行改前端**，`elder-v6.{html,css}`、
> `family-v6.css`、`art-cards.css`、`judge.*`、`trust.js`、`sw.js` 都在工作树里带着改动。
> 路由、共用逻辑、面板集这些结构性的事实是稳的；**具体的像素、命中区、配色请以
> 当时的截图为准**，不要引用这份文件里的数字去做验收。

---

## 一、四条路由

| 路由 | 是谁的界面 | 一句话 |
|---|---|---|
| `/elder` | 老人端设计一 | 现在这一版。大字、大按钮，麦克风是屏幕上最大的控件 |
| `/elder2` | 老人端设计二 | 另一套版式与美术：内联水墨山峦、纸张质感、底部一条 `dock` |
| `/family` + `/care` | 家人端设计一 | 今天 / 待办 / 我的三屏，**照护单独一页** |
| `/family2` | 家人端设计二 | 今天 / 待办 / 照护 / 我的**四屏合在一个文档里** |

入口页 `/` 上有这四条链接，`id` 分别是 `designElderOne` / `designElderTwo` /
`designFamilyOne` / `designFamilyTwo`，排在两张身份卡**之后**——那一节是次要层级，
入口页的主问题仍然是「今天您是谁」。

还有第五套 consumer 前端：`/app`（山水版老人端，`backend/static/app/` 下十七个页面）。
**它不在这次的四套对比里**，它是另一条线，去留未定，见 `KNOWN_ISSUES.md` 的 P1-A。

---

## 二、两套设计共用同一份业务逻辑

这是这次并行设计最要紧的一条，也是现场最值得讲的一条。

| 页面 | 版式与美术 | 业务逻辑（**共用**） |
|---|---|---|
| `elder.html` | `tokens` + `base` + `components` + `pages` + `art-cards` + `elder-family-v3`，六层 | `elder.js` |
| `elder-v6.html` | `elder-v6.css`，单一样式表 | `elder.js` |
| `family.html` | 五层，视觉层是 `art-cards-family.css` | `family.js` |
| `care.html` | 同上 | `care.js` |
| `family-v6.html` | `family-v6.css`，单一样式表 | `family.js` + `care.js`，两份同时加载 |

**不给设计二单写一份接线**，理由不是省事，是这个项目为此栽过：字号语速和 SOS
各有两套实现，**两边各自往返都绿，跨子系统才红**。一份逻辑、两张皮，是唯一不会
分叉的做法。

包自带的 `script-01/02.js` 是 `fetch × 0` 的纯 UI 壳（吉祥物拖拽、动效），
落到仓库里改名成 `elder-v6-a/b.js` 与 `family-v6-a/b.js`，**只负责纯视觉行为**。

设计二为此付的代价写在页面自己的注释里，值得当作一个工程细节讲：`family-v6.html`
两份逻辑同时在全局作用域会撞车（`Identifier 'api' has already been declared`，
整个文件不执行、四屏里两屏是死的），改成 `type="module"` 之后各有顶层作用域；
`elder-v6.html`「我的」那两项设置是 `.segmented` 按钮组而 `elder.js` 读
`select.value`，解法是**按钮组仍然是屏幕上的控件，旁边挂一个 `hidden` 的
`<select>` 当值的载体**，两边双向同步——逻辑一个字不用改。

---

## 三、差在哪

### 老人端

| | `/elder` 设计一 | `/elder2` 设计二 |
|---|---|---|
| 面板 | `home` / `log` / `kin` / `me`，四个 | **完全相同的四个** |
| 底部导航 | `nav.tabbar.elder-tabs`，body 带 `data-nav="tabbar"` | `nav.dock.elder-tabs`，`.seg` 按钮，**不声明 tabbar** |
| 样式层数 | 6 个样式表，全站共用前四层 | 1 个样式表，页面自带全部 |
| 美术 | 交付包位图 + 卡内景 + 角标意象 | 内联 SVG 水墨山峦、底部草丛，全部矢量 |
| 字号设置 | `<select>` | `.segmented` 三按钮 + 隐藏 `<select>` 镜像 |
| 深色模式 | 有（`tokens.css`） | **没有**，只有浅色 |
| 回首页 | 「我的」里的「换一个人用」 | 「我的」里的 `#leaveApp` |

`data-nav="tabbar"` 那个属性**是一个承诺**：它在告诉全局样式「这一页有底部标签栏，
可以放心藏起返回链接」。设计二的导航是它自己的 `.seg` 按钮、没有 `class="tabbar"`，
兑现不了这个承诺，所以只保留 `data-surface="consumer"`。这条在 `/family2` 上被闸门
当场抓到过。

### 家人端

| | `/family` + `/care` 设计一 | `/family2` 设计二 |
|---|---|---|
| 文档数 | **两个**：`family.html` 三屏 + `care.html` 七分区 | **一个**：四屏都在里面 |
| 面板 | `today` / `todo` / `mine`；照护在另一页 | `today` / `todo` / `care` / `mine` |
| 「照护」怎么去 | 底部标签栏跨文档跳 `/care` | 页内 `.seg` 切换，**不重载** |
| 照护内部 | 页面自己的七个分区 | 面板里再嵌一条 `nav.care-seg`，同样七个分区 |
| 返回首页 | 「我的」里的「换一个人用」 | 顶部一条 `.back-link` |

**这个差异是有意的，它正是要比较的东西**：把照护拆出去，家人端主页就只剩「今天要
我做什么」；合进来，一个文档装得下全部，但首屏要发的请求从 6 个涨到 11 个。

---

## 四、现场怎么走

### 起服务

```powershell
.\run_demo.ps1
```

```bash
./run_demo.sh
```

**端口是 8041，不是 8000。** 每一页在没有服务器时会露出的那句提示里印的就是 8041，
`test_deployment.py::test_the_demo_runner_opens_the_port_the_pages_advertise` 钉住这件事。

四个入口：

- <http://127.0.0.1:8041/elder>
- <http://127.0.0.1:8041/elder2>
- <http://127.0.0.1:8041/family>
- <http://127.0.0.1:8041/family2>

### 一条现场必须先知道的：入口页会在 4 秒后自己走人

入口页**记住上次选过的身份**（`localStorage` 的 `youhuo_role_v1`）。冷启动时——
也就是「这个标签页还没打开过任何内页」——它不会立刻弹走，但会**倒数 4 秒然后自动
打开**上次那一端。

> 这一段在 08-19 之前是 `location.replace`，打开 `/` 在第一帧之前就没了，四个设计入口
> 一眼都看不到。`landing.js` 已经整个重写：现在页面**先渲染**，在正文顶上插一条
> `#landingResume`，里面是一句话 + 逐秒倒数 + 两个按钮
> （`#landingGo` 现在就进 / `#landingStay` 留在这一页）。表从**第一帧**开始走
> （`requestAnimationFrame`），不是从脚本执行开始；页面在后台时不走表；
> 按键、滚轮、触摸、指针按下任意一个都会停表；走人用 `location.assign`，
> 所以按「后退」能回到 `/`。

**默认行为仍然是「4 秒后离开首页」**，所以现场三个办法任选一个：

1. 地址直接写 `http://127.0.0.1:8041/?stay=1`，`stay` 参数会跳过这次接管；
2. 倒计时里按一下「留在这一页」——它写 `youhuo_stay_v1`，**这台设备以后都会停**
   （点身份卡时会清掉，所以不怕误按）；
3. 或者用一个从没点过身份卡的浏览器 / 无痕窗口——那时压根不会有倒计时。

彩排时**先用真正要用的那个浏览器窗口走一遍**。这条路径只在「点过身份卡的浏览器
+ 新标签页」这个组合下出现，用别的窗口试是试不出来的；**自动化闸门也摸不到它**
（每轮全新 profile，`localStorage` 是空的，倒计时那一支恒不触发）。
详见 `KNOWN_ISSUES.md` 的 P1-B。

### 建议顺序

1. `/` （`?stay=1`）—— 先给出「四套设计」这件事本身
2. `/family` 今天 —— 讲**审批闭环**（见下节），这是产品核心主张唯一能在屏幕上看见的地方
3. `/family2` —— 同一件事、另一张皮，顺手证明「一份逻辑两张皮」
4. `/elder` —— 讲适老化：麦克风、打字退路、玻璃盒确认卡
5. `/elder2` —— 讲美术与版式，不要在这里演关键流程（原因见第六节）

---

## 五、每套适合讲什么

**`/family` 家人端设计一 —— 讲「重要的事两边都同意才办」。**
这次之前，演示数据里**从来没有过一件需要家属点头的事**，唯一那笔缴费一入库就是
completed，「今天」面板永远显示「今天不用您操心」。现在种子里有一件停在
`awaiting_family_approval` 的任务：点之前 `needYou=1`、有「核对后确认接力」和
「拒绝」两个按钮，点下去发 `POST /v2/family/approve`，任务从 `awaiting_family_approval`
转 `completed`，`needYou` 回到 0。**这是这个产品的核心主张第一次真的在屏幕上跑通。**

顺便可以讲防篡改：批准请求带着审批摘要，后端拿它和现算的
`SafetyPolicy.approval_digest(task)` 比对，对不上就 403 拒绝执行。种子第一版伪造了
一个签名，就是被这条挡下来的——**那不是缺陷，是控制在正确工作**。

**`/care` 照护中心 —— 讲「不只是看，还能记」。**
这一页此前七个分区、**零个写操作**，而空态文案还在承诺界面上根本没有的能力。
现在有三处真的写：记一次已吃 / 没吃（两个都要有，少了 `skipped`，漏服在数据里
永远看不见）、记一笔身体数据（`value` 保持字符串，血压是「128/82」不是一个数）、
添一位亲友（家人添的记成「等他确认」，要本人点头才生效）。

**`/family2` 家人端设计二 —— 讲版式取舍，以及「一份逻辑两张皮」。**
首屏 11 个后端端点、四个面板全是真数据（today 555 字 / todo 339 / care 216 /
mine 451）。

**`/elder` 老人端设计一 —— 讲适老化与安全兜底。**
麦克风是最大的控件；打字入口在**七个视口下都必须在首屏内**（Web Speech 在 Firefox
上不存在、权限被拒、没有麦克风时，它是老人进入这个产品的唯一入口）；「家人」屏现在
有真的亲友档案（儿子 `*******9002` / 女儿 `*******8001`），此前那张
`contact_profiles_v4` **一行都没有被种过**，所以老人端「家人」屏和照护页「安全」屏
是同时空着的。

**`/elder2` 老人端设计二 —— 讲美术。**
内联 SVG 的水墨层、章节标题下的渐变分隔栏、卡片右上角的意象角标（今天＝亭、
家人＝莲、记录＝鹤、我的＝金莲）。角标放右上不放右下是量出来的：右下会压住卡片里的
主数值，家人端上量过 123×102 的卡上重叠近一半。

---

## 六、不要在这四套上讲的东西

- **不要在 `/elder2` 上演关键流程。** 它是这次最新、也最少被闸门覆盖的一页：
  `check_page_runtime.py`、`check_contrast.py`、`shoot_pages.py`、
  `test_mobile_reachability.py` 四个页面清单**全部写死为原来那七页**，
  `/elder2` 和 `/family2` 一条都不在里面。它们通过的是各自那份静态契约闸门
  （`test_elder_design2.py` / `test_family_design2.py`），不是浏览器里的运行时检查。
- **不要说「四套设计功能完全一样」之后又只在其中一套上演某个功能。** 入口页上那句
  「两套设计的功能完全一样，不同的只是版式和美术」是对逻辑层说的（同一份 JS），
  两套设计二的**运行时覆盖**并不相同。
- **不要在深色模式下演设计二。** `elder-v6.css` 与 `family-v6.css` 里
  `prefers-color-scheme` 出现 **0 次**，也没有声明 `color-scheme`；
  评委的手机如果是深色模式，看到的就是浅色界面。
- **不要连按两次 `/judge` 的「从头演一遍」**（第 5、6 拍会改读上一次的记录，
  见 `KNOWN_ISSUES.md` P2-2）。
- **不要在这四套上演隐私导出、两步删除、情绪回顾、生活日报、同意记忆的批准与撤回。**
  这九个 `/api/v1` 端点都真的在（`/openapi.json` 里有，逐条实测 200），
  **但没有任何页面在调它们**——`backend/static/**` 全量扫过，一处调用都没有。
  它们能在 `/openapi.json` 或 `curl` 上讲，不能在这四套界面上点。
  见 `KNOWN_ISSUES.md` P1-E。
  （「同意记忆」这四个端点尤其要当心：产品的招牌功能，端点齐了、后端测试齐了，
  但老人端**仍然没有入口**。别顺口说成「老人可以在这里点头」。）
- **不要把 `/family2` 装到主屏、也不要拿它演离线。** 它不引 `manifest`、
  不注册 service worker、没有 `theme-color`（四项全空，见 `KNOWN_ISSUES.md` P1-F）。
  要演 PWA 就用 `/family` 或 `/elder`。

---

## 七、怎么核对这份文件

这里每一条路由、每一个文件名都是核对过的，不是抄来的。

### 起一个真服务再敲，不要只用 TestClient

```powershell
$env:YOUHUO_DEMO_STATE="attention"
.\.venv\Scripts\python.exe -m uvicorn youhuo.api:app --host 127.0.0.1 --port 8057 --app-dir backend
```

**这台机器上 `HTTP_PROXY=127.0.0.1:7897`，而 `urllib` 不认 `NO_PROXY`**——
探针不显式绕过的话会卡在代理上，然后你以为是服务没起来：

```python
import urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for path in ("/", "/elder", "/elder2", "/family", "/family2",
             "/care", "/trust", "/app", "/stage", "/judge"):
    print(path, opener.open("http://127.0.0.1:8057" + path, timeout=20).status)
```

**挑端口时先确认它是空的。** 写这份文件时 8047 上已经有别人的服务在跑，
uvicorn 报 `[Errno 10048]` 绑不上，而探针照样收到 200——**它敲的是别人的服务**。
`Get-NetTCPConnection -State Listen` 先看一眼。

### 2026-08-19 的实测结果

`/` `/elder` `/elder2` `/family` `/family2` `/care` `/trust` `/app` `/stage` `/judge`
**十条全部 200**；`/health` `/ping` 200；
`/static/{elder-v6,family-v6}.{css}`、`/static/{elder-v6,family-v6}-{a,b}.js`、
`/static/landing.js`、`/static/app/index.html` 全部 200。

服务端发出的 `/` 里，`designElderOne` / `designElderTwo` / `designFamilyOne` /
`designFamilyTwo` 四个 id 与 `.yh-designs` 那一节都在。
`/elder2` 的 HTML 里有 `elder-v6.css` 和 `elder.js`；
`/family2` 的 HTML 里有 `family-v6.css` 和 `family.js`——**共用逻辑这件事在服务端
发出的字节里就能核**，不用开浏览器。

`/openapi.json`：**145 个路径、153 个操作**，其中 `/api/v1` 46 个路径 / 50 个操作，
`v2`–`v7` 102 个操作（14 / 9 / 39 / 21 / 15 / 4），`/health` 1 个。
（`xiaoyi/plugin_openapi_v6.generated.json` 仍是 **99 个路径**——那份**刻意不含
`/api/v1`**，是给小艺平台的插件契约。两个数不是矛盾，别互相改。）

路由的唯一事实源是 `backend/youhuo/surfaces.py` 的 `SURFACES`，
`test_surface_registry` 拿它和应用真正服务的路由逐条对——**新加一页只改那一处**。
但要记住 `surfaces.py` 开头那段警告：路由字面量还散在**八个文件**里，
其中四份浏览器闸门的页面清单**仍然写死为原来那七页**（实测 `elder2` / `family2`
一个都不在，见第六节和 `KNOWN_ISSUES.md` P1-C）。
