# 参考产品研究：真实 App 是怎么组织出来的

四个开源产品，围绕**一个问题**读：把优活从「七个网页」变成「一个真正 App + 一个产品
演示舞台 + 一个专业审计平台」，这些成熟项目里哪些结构值得吸收。

不是四份仓库报告。是四份证据，指向同一组结论。

---

## 零、先量规模，再决定投多少精力

匿名 GitHub API 取的事实（2026-08-12）：

| 仓库 | star | 体积 | 最后 push | 判读 |
|---|---|---|---|---|
| Medito `meditohq/medito-app` | 1297 | 178 MB | 2026-08-06 | 真实上架 iOS/Android，持续开发。**权重最高** |
| MedCore `Globussoft-Technologies/medcore` | 2 | 33 MB | 2026-08-10 | 1267 个 PR、有 e2e 与 lighthouse 配置 |
| Folk Care `neighborhood-lab/folk-care` | 13 | 52 MB | 2025-12-29 | api/packages/e2e/infra/k8s 齐全，AGPL-3.0 |
| MediMate `Arvindiyer/medimate` | **0** | 2.8 MB | 2026-03-15 | 创建于 03-14。**一天完成的黑客松投稿** |

MediMate 的最后一条提交信息是 `second iteration and final submission verion`（原文
拼错），零 star、零 fork、零测试、`.DS_Store` 进了仓库。它有**一个**非常好的结构想法，
其余不构成参考。按这个权重分配精力，不平均用力。

**运行到了哪一步（重要，决定下面哪些结论有多硬）**

装了 Flutter 3.44.9 stable 到 D 盘（1814 MB，官方清单的 sha256 逐字符校验过）。
然后：

| 目标 | 结果 |
|---|---|
| Medito 主 App → **web** | **不可能**。`lib/` 里 `dart:io` / `Platform.is*` 有 **128 处、跨 41 个文件**，web 上没有 `dart:io`，编译期就死。给它打补丁等于改 41 个文件，那就不是在观察这个 App 了 |
| Medito 主 App → **Windows 桌面** | **两道墙，过了第一道**。① `Building with plugins requires symlink support` —— 用户开了开发者模式之后解决。② 原生编译跑了 523 秒，倒在**一个插件**上：`flutter_local_notifications_windows\src\plugin.cpp(5,10): error C1083: 无法打开包括文件 "atlbase.h"`。ATL 是 Visual Studio 的可选组件，本机 `MSVC 14.44.35207` 有 `include`、没有 `atlmfc`，而 `vs_installer.exe modify` 要管理员权限 |
| Medito 的 **widgetbook**（自带组件画廊） | **跑起来了**。`flutter build web --release` 成功，72.1 MB 产物，`20 Components · 31 Use-cases` |
| Medito 主 App → **Windows 桌面**（第二轮） | **跑起来了**。用户装上 ATL 组件之后，原生编译 416.5 秒通过，`medito.exe` 3.4 MB，mock 模式启动正常 |

所以下面的结论分三类，我逐条标了：

**已被实际运行验证（5 条）**

| 结论 | 验证方式 |
|---|---|
| `IndexedStack` 切 tab 保留滚动位置与已渲染内容 | 滚动→切走→切回，逐像素比对，差异只落在网络封面图那 270px |
| 只有选中项显示文字（`onlyShowSelected`） | 截图：Home 有紫色文字，书本与齿轮只有图标 |
| 分区之间发丝线、分区内条目用卡片 | 截图：快捷方式 / Featured / 引言三段之间是线，Featured 内两张是卡片 |
| 详情页的返回在**底部**操作栏，不在左上角 | Pack 详情页截图：底部 ← 分享 置顶 收藏 |
| `MeditoAppBarSmall` 的 `hasBackButton` 是死参数 | widgetbook 里拨动旋钮，app bar 那一条逐字节不变 |

**仍然只是源码结论（2 条，标注保持）**

- 加载超过 3 秒淡入「去已下载内容」的逃生出口
- 七种错误分型各自给出不同动作

这两条**在 mock 模式下无法验证**：`MockHttpApiService` 返回的是罐装响应，
既不会超时也不会失败，所以那两条代码路径根本不会被走到。要验证得改掉 mock
实现，那就不是在观察这个 App 了。

**其余为源码与其自带注释的阅读结论。**

顺带记两个自己的绊脚石，都不是 Medito 的问题：pigeon 26.3.2 不再从输出路径
推导包名（仓库的 `pigeon_conf.dart` 是给旧版写的），命令行补 `--package_name`
即可；以及我写的 `.ps1` 忘了加 UTF-8 BOM，PowerShell 5.1 按 CP936 读、中文尾字节
吞掉一个大括号，报出来的是**19 行之后**的 `Missing closing '}'`。

---

## 一、为什么优活不像一个 App —— 机械原因，不是视觉原因

### Medito 的答案：它根本没有「页面跳转」

`lib/routes/routes.dart` 不是路由表。它是一个函数：

```dart
Future<void> handleNavigation(String? type, List<String?> ids, BuildContext context, …)
```

整个 App 只有一个全局 `navigatorKey`（`routes.dart:31`），所有详情页都是
`Navigator.push(MaterialPageRoute(...))` 压到**同一个栈**上（`:117-121`）。
导航目标是**数据**——后端返回 `{type: "pack", ids: [...]}`，这个函数决定推哪个屏。

而四个主 tab 的实现是 `bottom_navigation_bar_view.dart:149`：

```dart
body: IndexedStack(index: _currentPageIndex, children: _pages)
```

`IndexedStack` 让四个 tab 页**同时活着**，切 tab 只是换显示哪一个。配合
`:193-196` 的「只在第一次进 explore 时加载数据」和 `HomeView` 的
`wantKeepAlive => true`（`home_view.dart:226`），效果是**加载一次、永久保留**：
滚动位置、已展开的分区、已取到的数据，切走再切回都还在。

**这才是「为什么每个页面不像一组独立网站」的机械答案。** 不是配色统一，不是
圆角一致——是那个 App 实例从头到尾没有被销毁过。

#### 这一条**跑起来实测过了**（结论成立）

把 Medito 编成 Windows 桌面（mock 模式）跑起来，做了一次决定性实验：

```
① 在首页往下滚 6 格 → 截图
② 点底部导航的 Explore（书本）→ 截图（确认真的切过去了）
③ 点回 Home → 截图
```

然后拿 ① 和 ③ 做**逐像素比对**（430×920，单通道阈值 12）：

```
差异像素 27332 / 395600  (6.909%)
显著不同的行区间：只有 1 段
  y 393–662   高 270px   峰值 112/430 像素不同
```

**y 393–662 恰好是 Featured 那两张封面图的位置**——它们是走网络的
（`picsum.photos`），两次截图落在不同的解码/淡入帧上。

而其余部分**逐像素相同**：顶部说明条的文字、快捷方式那一行、
「Featured」标题、下方的引言、底部导航。

**这一点是决定性的**：如果滚动偏移变了哪怕 1 像素，上下那些文字行就会一起不同。
它们没有。所以切走再切回，回到的是**完全同一个位置**，
包括滚动偏移和已经渲染好的内容。

（顺带确证了 mock 模式真的在跑：首页第一张卡片写着
「Welcome to Medito mock mode! You are running with sample data.」，
往下滚能看到 mock 数据里的 `Daily Calm` / `Sleep` / `New: Mindful Morning` /
`Sleep Stories` 和那句 Thich Nhat Hanh 的引言。）

### 优活的对照事实

七个 URL 是七个 HTML 文档。每一次 `/family` → `/care` 是一次**完整的文档加载**：
JS 上下文重建、四层 CSS 重新解析、滚动位置归零、`initSections` 重跑、
底部导航从零重绘。

`09_consumer_app_architecture.md:130-148` 的 Shell Contract 让三个文档**长得一样**。
它对上面六件事**一件都没有解决**。两个页面可以像素级相同，而用户仍然知道自己
刚刚「跳了一下」——因为白闪、因为回到列表顶部、因为刚展开的那一栏又收起来了。

### 这条改动现有方案

`09_consumer_app_architecture.md:84-98` 定的 Family 四项是 今天 / 待办 / 照护 / 我的，
而 Phase D 的计划是「`/care` 保持独立文档，换上 Family Shell」。合起来意味着：

```
今天  → family.html 内切面板    瞬时
待办  → family.html 内切面板    瞬时
照护  → /care 文档加载          白闪、状态丢失
我的  → family.html 内切面板    瞬时
```

**四个入口里三个行为一致、第四个不一致。** Medito 的 `IndexedStack` 四个目的地
完全同构，而这种四分之一的差异，用户感觉得到——他会认为「照护」是另一个地方，
正是我们要消除的感觉。

三条路：

| | 做法 | 代价 |
|---|---|---|
| A | 四项全部跨文档（拆成四个文档） | 一致了，但每次点击都加载，且 `family.html` 要拆 |
| B | 四项全部文档内（合成一个文档） | `10_surface_boundaries.md:70-78` 已论证否决：`initSections` 是平坦命名空间，`family.html` 与 `care.html` **都有** `data-panel="today"`，合进一个 DOM 会同时显示两个面板且**不报错** |
| C | 保持混合，但把跨文档那一次**做成察觉不到** | 需要三件事都成立，可测 |

**取 C**，因为 A 破坏单一内容源、B 已被证据否决。C 的三个条件：

1. **首屏就带正确的激活态。** 底部导航的当前项必须由服务端渲染进 HTML，
   不能靠 JS 加载后补 class——否则每次跳转都会闪一下错误的激活项。
2. **状态跨文档恢复。** 这一条**直接照抄 Medito**：
   `bottom_navigation_bar_view.dart:39-41` 把上次的 tab 存进 SharedPreferences
   并在启动时恢复。优活对应的是 `sessionStorage` 存「当前模块 + 滚动位置」，
   `pagehide` 写、首屏读。
3. **壳从 Service Worker 缓存直出**，不等网络。`sw.js` 的 SHELL 已经有这个能力。

这三条都是可量的，应当各配一道闸门。**这是 Phase C/D 的新增前置条件。**

---

## 二、Medito 的其他可吸收模式

### ① 三态是页面顶部一次穷尽的分支 —— ADOPT

`home_view.dart:99`：

```dart
return home.when(
  loading: () => const _HomeLoadingView(),
  error:   (err, stack) => MeditoErrorWidget(…),
  data:    (HomeModel homeData) => Scaffold(…),
);
```

**解决的问题**：空态/加载/错误散在页面各处的 `if` 里，一定会漏。这里三态是一次
穷尽的分支，类型系统不允许少写一个。

优活现在没有这个结构。`renderTaskSpace` 的 `viewKindOf` 已经是这个形状
（认不出回 `null`，由调用处退回），把它推广到每个数据区块即可——纯 JS 也能做到：
一个 `renderState(host, {loading, error, empty, data})` 的调用约定，加一道闸门
断言每个 `fetch` 落点都走它。

### ② 加载态有时间维度，会降级成一个提议 —— ADOPT

`home_view.dart:229-232` 的注释写明了设计意图：

> If loading drags on (offline or a bad connection can hold this spinner for up to
> the 30s request timeout), a subtle "Go to Downloads" escape hatch fades in so
> downloaded sessions stay reachable. A normal load resolves before the button
> ever appears.

实现是 `:246-248`：3 秒后 `setState` 显示按钮，`AnimatedOpacity` 500ms 淡入。

**解决的问题**：转圈本身不携带信息，转到第 20 秒时用户只能杀掉 App。这个设计
让「慢」变成「这里还有一条路」。

优活对应：老人端语音识别失败、`/care` 数据取不到时，**3 秒后**露出「您也可以打字
告诉我」或「先看看昨天的记录」。注意优活的打字入口是常驻的（那是语音失败唯一的
退路），所以这一条更适用于 `/care` `/family` 的数据区块。

### ③ 错误是分型的，且每型给出不同的动作 —— ADOPT

`medito_error_widget.dart:36-51` 七种错误各有自己的文案：
`NetworkConnectionError / TimeoutError / UnauthorizedError / NotFoundError /
ServerError / UnknownError / RefreshTokenError`。

而且动作按型分叉（`:133`）：认证类给「重试 + 重新登录」，其余给
「重试 + 去已下载内容」。**错误页不是死路，它把你送到 App 里仍然能用的那部分。**

`:26` `:74-78` 的 `isScaffold` 开关让同一个组件既能整屏、又能内嵌在已有页面里——
一个区块失败不掀掉整个壳。

优活现在是一条通用兜底文案。至少要分出：**没有网 / 超时 / 这条记录不存在 /
服务器出错**四型，每型配一个仍然可走的动作。对老人端尤其重要：她看不懂「加载失败」，
但看得懂「家里网不通，我先用之前记下的说给您听」。

### ④ 首页的分区顺序是数据，用户可以自己排 —— ADAPT

`home_view.dart:111` 读 `homeWidgetOrderProvider`，`:148-188` 按这个顺序渲染
五种分区（shortcuts / carousel / quote / products / upNext），
配 `customise_home_layout_screen.dart` 让用户重排自己的首页。

**解决的问题**：不同用户在首页要看的东西不一样，硬编码顺序只能取平均值。

优活 **ADAPT 一半**：把 Elder 首页的分区（生活状态 / 下一件 / Orb / 今天）
做成有序数据是对的——它让「Orb 不等于整个 App」这条从一句话变成一个结构。
但**不给老人端做重排界面**：让 75 岁用户拖拽调整自己的首页是伪需求，
而 Family 端替她调、或按数据状态自动调，才是这个模式在优活的正确落点。

### ⑤ 卡片的判据 —— ADOPT

同一个 App 里两种做法并存，对比给出了规则：

- **首页**用 0.5px 发丝分隔线，**不用卡片**（`home_view.dart:140-147`，
  `Divider(height:1, thickness:0.5, indent:16, color: brandPurple @ alpha 0.2)`）
- **设置页用卡片**，`_buildSectionCard` + `_buildSectionTitle`
  （`settings_screen.dart:343` `:358`），分区是 Account / 定制 /
  Support & Community / Help & Legal

**规则**：卡片用来把**同类、可枚举、互为对等**的项归组；分隔线用来分开**性质不同**
的区块。首页那五个分区彼此不是对等项（一句引言和一个继续播放的入口不是同类），
所以不该各自装进一个盒子。

优活现在的 `.panel` 三层叠加（记在暂停清单里）正是反例：性质不同的区块被装进
一样的盒子，于是靠嵌套阴影区分层级。这一条给了「哪些该拆掉盒子」的判据。

**跑起来之后，这条规则被完整确证，而且比读源码更细。** 实测两屏：

首页（滚动到 Featured 那一段）：

```
…说明条…
──────────────  发丝线
[?] Daily Calm   [?] Sleep          ← 快捷方式，无外层盒子
──────────────  发丝线
Featured                            ← 标题，页面背景上的纯文字
 ┌────────┐ ┌────────┐
 │ 封面图  │ │ 封面图  │             ← 分区**内部**的条目是卡片
 │New: M… │ │Sleep … │
 └────────┘ └────────┘
──────────────  发丝线
《The present moment is filled…》     ← 斜体衬线引言
```

设置页（滚动到 Customisation 那一段）：

```
 ┌──────────────────────────────┐
 │ ✈  Join our Telegram …     › │   ← 一张卡片装同类对等项
 │ ──────────────────────────   │   ← 卡片**内部**：缩进发丝线，与文字对齐
 │ ☎  Follow us on WhatsApp   › │
 └──────────────────────────────┘
 Customisation                       ← 分区标题在卡片**外面**，纯文字
 ┌──────────────────────────────┐
 │ ✦  Theme                     │   ← 控件需要空间的行**自己占一张卡片**
 │  [Dark] [Light] [System]     │
 └──────────────────────────────┘
 ┌──────────────────────────────┐
 │ ▣  App Icon                  │
 │  [Classic] [Dark] [Gold…]    │   ← 横向可滚的真实预览
 └──────────────────────────────┘
```

**完整的判据（五条，都有实测支撑）：**

1. **分区标题**是页面背景上的纯文字，在卡片之外——不要把标题也塞进盒子
2. **一张卡片**装**同类、对等、可枚举**的行（Telegram + WhatsApp）
3. **控件需要空间的行自己占一张卡片**（三选一、预览条）——它不再是"一行"
4. **卡片内部**用**缩进**发丝线分隔（与文字对齐，不与图标对齐，不通栏）
5. **分区之间**（首页那种异质内容流）用发丝线，**不套盒子**

外加一条独立的：**选中态是「边框 + 颜色 + 文字」三者同时给**
（Theme 的 Dark 项：紫色边框 + 紫色文字 + 图标），**从不只靠颜色**。
这一条和 MedCore 第 ⑦ 条独立得出同一个结论，两个成熟项目都这么做。

### ⑥ 头部滚走，不钉住 —— ADAPT

`home_view.dart:121-126`：`SliverAppBar(floating: false, pinned: false, elevation: 0,
toolbarHeight: 56)`，内容是 `HeaderWidget(greeting, onStatsButtonTap)`——
一句问候加一个动作，不是标题栏。

优活的 Elder 首页已经删掉了应用栏，方向一致。但**Orb 与打字入口必须钉底**
（已确认的决定），所以优活是「头部滚走 + 底部钉住」的组合，与 Medito 的
「头部滚走 + 底部导航钉住」同构。ADAPT 成立。

### ⑦ 返回键 —— **REJECT**（这一条**跑起来验证过**）

`medito_app_bar_small.dart` 声明了 `hasBackButton = true`、`hasCloseButton`、
`closePressed` 三个参数，而 build 方法里是 `leading: null,
automaticallyImplyLeading: false`（`:31-32`）——**三个参数全是死的，这个头部
根本不渲染返回按钮**。详情页完全依赖 Android 手势返回 / iOS 边缘滑动。

**而且比「参数是死的」更进一层：它的设计系统画廊把这个死参数展示成一个开关。**

`widgetbook/lib/use_cases/medito_app_bar_small.dart:11-18`：

```dart
hasBackButton:  context.knobs.boolean(label: 'Back button',  initialValue: true),
hasCloseButton: context.knobs.boolean(label: 'Close button', initialValue: false),
```

把 widgetbook 构建成 web 跑起来，走 CDP 截图（`?path=` 无效，
这个版本的深链是 `#/?path=widgets/headers/meditoappbarsmall/default`）：

1. `Back button` 开关**开着**，中间渲染出来的 app bar 只有一个居中的
   「Meditations」，**左侧本该有返回箭头的位置是空的**
2. 变异：用 CDP 可信事件把那个开关拨到**关**。整屏截图变了
   （73 KB → 74 KB，sha 不同）说明开关确实动了；而只裁 app bar 那一条
   （x=258 起、764×60）两次**逐字节相同**——sha `7cb5834e09548b1a`、
   都是 2266 字节
3. 检查过裁的那一条不是空白：里面是深色底加居中粗体的「Meditations」，
   所以「逐字节相同」测的是对的东西

**结论：`hasBackButton` 两个方向都不影响渲染，它是画廊里的一个装饰。**
一个团队维护的组件画廊，对外提供了一个什么都不做的开关——
这比藏在实现里的死参数更容易误导人，因为画廊正是别人用来学「这个组件能干什么」
的地方。优活如果做组件画廊，**每个旋钮都要有一条变异断言证明它真的接着东西**。

**优活不能照抄，因为优活是 PWA。**
`manifest.webmanifest:10-11` 是 `"display": "standalone"` /
`display_override: ["standalone","minimal-ui"]`。独立模式下没有浏览器返回键，
而 **iOS 的独立 PWA 也没有边缘返回手势**——照抄的结果是用户进了详情页出不来。

推论（比「加个返回键」更精确）：

- `/elder` 是 `start_url`，**根页面不该有返回**——之前删掉那个应用栏是对的
- 优活新增的每一个**详情面**（事务详情、Care Detail、Trust Receipt）
  **必须自带返回或关闭**，且必须能用键盘到达
- 这条要进闸门：`display: standalone` + 存在详情面 ⇒ 详情面必有出口

### ⑦-b 把 31 个 story 逐个渲染之后额外看到的（同样是**实测**）

从生成的 `main.directories.g.dart` 解析出全部 31 个 use case 的权威深链
（不手写 slug，怕猜错），挑 14 个对优活最相关的逐个截图，只裁中间画布。
14 张的 sha 各不相同——**每个 story 都真的切过去了**，没有把「四张一样的图」
当成「四个组件都看过了」。

#### 1. 设计系统内部就不一致：大号 app bar **有**返回箭头

`widgets/headers/meditoappbarlarge/with-cover-image` 渲染出来，
**左上角有一个清晰的返回箭头**。而上面第 ⑦ 条已经证明
`MeditoAppBarSmall` 一个都没有、且它的旋钮是装饰。

所以问题不是「Medito 不放返回键」，而是——

> **同一套设计系统里，一个头部给了出口、另一个静默地省掉了，
> 而省掉的那个恰好是在画廊里被宣传成可配置的那个。**

这比原来的结论更能说明问题：出口这件事**没有一条规则守着**，
它取决于你用了哪个 header。优活的对应动作因此不是「加个返回键」，
而是**一条闸门**：任何详情面必有可键盘到达的出口，与它用了哪个抬头无关。

顺带同一张图给了卡片问题一个数据点：详情页里那串内容（Item 1…Item 13）
是**裸行**——没有卡片，也没有分隔线，只靠间距和左对齐。

#### 2. 设置行 = 标题 + **一行说明它的后果** —— ADOPT

`views/home/widgets/bottom_sheet/rowitemwidget/with-switch` 渲染出来是：

```
Do Not Disturb          ← 粗体标题
Silence all alerts      ← 小一号、暗一档的说明
                    [开关]
────────────────────    ← 发丝线，左端与文字对齐，不通栏
```

**解决的问题**：一个开关的后果不是自明的。「Do Not Disturb」是名字，
「Silence all alerts」才是它会做什么。

优活「我的」里的语速、字号、隐私三个控件正是这种情况——
「语速」是名字，「优活说话会慢一些」才是后果。老人端尤其需要这一行。

还有一个细节值得抄：**分隔线是缩进的**，左端与文字对齐而不是通栏。
通栏的线把列表「切开」，缩进的线让它读起来是「分组」。

#### 3. 图标命名：**每个概念一个名字，没有一个字形兼两职** —— ADOPT

`widgets/meditoicon/all-icons` 那一屏列了 **55 个图标**，逐个带名字。

先说清一件事：**这些图标在我的构建里一个都没渲染出来**，全是空白方块。
不要把这当成 Medito 的视觉。原因查到了，见下面「它的画廊渲染不出自己的图标」。

**但名字是可读的，而名字才是这一条的内容。** 命名方案有两个特征：

1. **每个概念一个名字。** `heart` `health` `home` `privacy` `profile` `settings`
   `bell` `calendar` `document` `graphUp` `medal` `shield` `search` `shop`
   `road` `sleep` `sun` `moon` `snow` `fire` `star` `timer` `pin` `play`
   `pause` `check` `alert` `help` `login` `logout` `xmark` …
   **没有一个字形兼两职。**
2. **变体是显式配对的**：`book`/`bookSolid`、`checkCircle`/`checkCircleSolid`、
   `compactDisc`/`compactDiscSolid`、`medal`/`medalOutline`、`pin`/`pinSolid`、
   `play`/`playSolid`、`star`/`starSolid`、`timer`/`timerOutline`，
   以及四个 `download*`。填充与描边是**同一概念的两个状态**，不是两个图标。

对优活是直接的对照：优活现有缺陷是**同一个心形在 `/elder` 是「记录」、
在 `/care` 是「照护」**（记在暂停清单里）。按这个方案，那是两个概念，
必须两个名字、两个字形；而「当前 tab」与「非当前 tab」才是同一概念的两个状态，
用 filled/outline 配对表示——优活现在靠 `stroke-width` 1.8 → 2.3 表示，
方向一致但表达力更弱。

还有一条便宜的：**它有一个叫「All icons」的 story，把整套图标枚举成一屏可看的页面。**
优活有 `icons/tabs.svg` 这个 sprite，但没有任何地方能一眼看完全集——
而「同一个心形被用了两次」这种错误，正是只有把全集摆在一起才看得见。

#### 3-b 它的画廊渲染不出自己的图标（**这是它的缺陷，已验证**）

抓控制台与网络：**60 个 404、118 个未捕获异常**，请求长这样——

```
http://127.0.0.1:8055/assets/assets/images/arrow-left.svg   404
                             ^^^^^^^^^^^^^^ assets 重复了一层
```

文件实际在 `assets/images/arrow-left.svg`。根因在
`lib/widgets/medito_icon.dart:27-28`：

```dart
return SvgPicture.asset(
  assetName,          // ← 没有 package: 参数
```

裸路径 `assets/images/...` 只在 `medito` **本身是根应用**时解析得对。
而它自己的 widgetbook 是把 `medito` 当**路径依赖**消费的，
这时资源在 `packages/medito/...` 下，正确写法是
`SvgPicture.asset(assetName, package: 'medito')`。

**所以这个设计系统的画廊，渲染不出这个设计系统最基础的那个元素。**
而且它就这样躺在仓库里（`widgetbook/` 自带 `web/` 目录，说明有人跑过它）——
没被发现的原因大概是：**一个白方块看起来像「也许图标就长这样」**，
而 118 个异常在控制台里，没人看控制台。

这一条对优活的意义不在图标，在于它是**「一个通过的闸门只是下界」的又一个实例**：
画廊能打开、能切 story、能改旋钮，看起来完全正常，
而它最主要的职责——展示图标——是坏的。优活如果做画廊，
第一条断言应该是「每个 story 渲染后 console 没有 error」，
这正是优活已经给七个页面建过的那道闸门。

#### 4. 加载骨架和真实列表**同形** —— ADOPT

`widgets/shimmers/widgets/boxshimmerwidget/list-skeleton` 是
**四个圆角条**，行数、高度、圆角、间距都与它替代的真实列表一致，
渐变扫过表示加载中。内容到达时**没有任何跳动**。

优活现在的做法是给容器硬留高度（`#receipt { min-height: 640px }`、
`#dailyReport { min-height: 260px }`）。方向对，但骨架更好，因为它多说了一句话：
**来的是四行，不是一整块**。这一条落到艺术指导阶段。

（第 5 节说过它的加载语汇是分裂的：有 5 个 shimmer 组件，
而最重要的首页用的是一个 `CircularProgressIndicator`。
所以这条是「学它做对的那一半」。）

### ⑧ 系统色由壳统一声明 —— ADOPT

`bottom_navigation_bar_view.dart:74-83` 的 `AnnotatedRegion<SystemUiOverlayStyle>`
把状态栏、系统导航栏的颜色设成 `theme.scaffoldBackgroundColor`，
**在壳这一层设一次**。

优活对应的是 `theme-color`。之前那道断言「每个 HTML 都要声明 theme-color」
过界了（`stage.html` 故意没有 manifest/SW），已收窄到 `rel="manifest"` 的页面。
方向是对的：**壳拥有系统色，不是每页各自声明**。

### ⑨ 只有选中项显示文字 —— **REJECT**

`:95` `labelBehavior: NavigationDestinationLabelBehavior.onlyShowSelected`。
对冥想 App 的年轻用户成立，对优活的老人端是明确否决：图标语义本来就靠不住
（优活自己就有「同一个心形在 `/elder` 是记录、在 `/care` 是照护」这个缺陷），
再把文字藏起来等于要求她靠猜。四项文字全程可见。

### 它最核心的结构行为，一个测试都没有

想过用「跑它自带的测试」代替观察。量了一遍：`test/` 下有 **43 个测试文件**，
而我要验证的那几条行为的命中数是——

| 关键词 | 在测试里出现 |
|---|---|
| `IndexedStack` | **0** |
| `BottomNavigation` | **0** |
| `MeditoErrorWidget` | **0** |
| `lastMainTabIndex`（切走再回来恢复上次的 tab） | **0** |
| `NetworkConnectionError` | 3 |

**这个 App 最重要的三件事——切 tab 保留状态、底部导航、错误组件——完全没有
测试覆盖。** 43 个测试覆盖的是 auth、stats、analytics、audio completion 这些
后台逻辑。

对优活的意义有两层：

1. 「跑测试代替看画面」这条路在这里走不通，所以第一节那条 `IndexedStack`
   的结论**仍然只是源码结论**，标注保持。
2. 更重要的是它印证了优活正在做的事：一个 1297 star、真实上架的 App，
   它的**导航壳与状态保持没有任何断言守着**。优活给 tab↔panel 配对、
   底部导航项数、Shell Contract 建闸门，不是过度工程——
   这恰好是成熟项目里空着的那一块。

### Medito 自身的毛病（不要照搬）

- **`_pageIndexForDestination = [0, 1, 3]`**（`:28`）：`_pages` 有四个页面，
  导航栏只有三个入口，索引 2 的 `JourneyView` 活在 `IndexedStack` 里但**没有 tab
  能到达**。`:172` 的 `tabTargets` 也同样跳过 2。像是灰度中的功能，也像是漏的。
- **首页用转圈，其他页用骨架屏**：仓库里有 5 个 shimmer 组件
  （`widgets/shimmers/`），而最重要的首页 `_HomeLoadingView:256` 是一个
  `CircularProgressIndicator`。自己的加载语汇分裂。
- **两个 0 行的空文件被提交**：`views/home/widgets/bottom_sheet/debug/debug_bottom_sheet_widget.dart`
  和 `views/home/widgets/stats/stats_widget.dart`。
- **`meditation_calendar_widget.dart` 1094 行**、`sign_up_log_in_screen.dart` 677 行、
  `products_widget.dart` 625 行——God component 不少。
- 错误页里 `ColorConstants.ebony` / `.black` 硬编码（`:18` `:75`），
  绕过了主题；而这是一个有明暗主题和多种 App 图标的 App。
- `NotFoundError` 也会显示「去已下载内容」——「这条记录不存在」和「你可以听
  已下载的」没有关系。分型做对了，动作映射没做完。

---

## 三、MediMate：Voice 怎么放进一个正常 App

这个仓库**只有一个**值得学的东西，但它很关键。

### Voice 是动作，不是目的地 —— ADOPT

`mobile/App.tsx:152-185`：

```tsx
<Tab.Screen name="Voice" component={EmptyScreen} options={{
  tabBarButton: () => (<TouchableOpacity onPress={openVoice}> … </TouchableOpacity>),
}} />
```

配 `:24-25` 的注释：`// Placeholder — Voice tab never renders a screen`。

**Voice 占了底部导航中间那一格，但它没有屏幕。** 它的 `tabBarButton` 被换成一个
按钮，按下去 `openVoice()` 打开 `<VoiceModal>`——而那个 modal 挂在
`NavigationContainer` **外面**（`:199-203`），浮在整个 App 之上。关掉之后你还在原地。

**它坐在拇指预期的位置，但按下去不导航。**

### Chat 是另一个独立的 tab —— 这条回答了你的问题

`:187` `<Tab.Screen name="Chat" component={ChatScreen} />`。这个 App 结构上区分：

- **Voice**：随处可召唤、用完归位的**能力**
- **Chat**：一个你**可以**去、但不是你**待着**的地方

代码规模也说同一件事：**ChatScreen 是整个 App 最小的屏，120 行**；
TimelineScreen 268 行、ProfileScreen 338 行、HomeScreen 180 行。
一个自称 voice-first 的健康助手里，聊天界面是最不发达的那一块。

**对优活的结论：是的，聊天应该退后，任务状态应该成为主界面。**
`task-space.js` 的方向正确。而且这条给了它一个更强的说法——

Task Space 现在是 `body[data-focus]` 一个态。按 MediMate 的结构，正确的模型是：

```
Voice Orb   = 动作（不是目的地，不占 tab）
Task Space  = 语音之后 App 的状态（不是聊天记录的替代品，是这件事本身）
聊天记录     = 一个可以去看的地方（记录 tab 下的一条入口），不是主画面
```

优活的 Orb 已经不在 tab 里（它在首页内容流中），这比 MediMate 更对——
MediMate 占了一个导航格却不给屏幕，无障碍树里留下一个可聚焦但什么都不渲染的 tab。

### 语音能到达导航栏里没有的地方 —— ADOPT

`:190-195`：`Nutrition` 是一个 `tabBarButton: () => null`、宽度 0 的隐藏目的地，
注释写着 `navigable via voice, hidden from tab bar`。

**解决的问题**：底部导航最多四五项，而语音的表达空间没有上限。语音因此可以
**扩展可达面**，而不是只做导航栏的快捷方式。

优活对应：老人说「上个月的水费交了没」应当能直接落到那笔事务的详情，
即使「事务详情」不是四个 tab 中的任何一个。这也给 `.log-item` 缺少
task_id 入口那件事补了一条动机——**语音要能指向它，它就必须可寻址**。

### MediMate 必须拒绝的几条

- **`:178` 中间那个语音按钮的图标是 emoji**：`<Text style={styles.voiceIcon}>🎤</Text>`。
  四个 tab 图标都是规规矩矩的 SVG（`:29-63`，`strokeWidth={1.8}`），
  然后全 App 最重要的那个控件用了 🎤 字符。优活「不许 emoji 当图标」这条硬约束
  防的就是这个。**REJECT**
- **`:172-177` 青→靛的渐变圆 + `shadowOpacity: 0.45, shadowRadius: 16` 的彩色投影**：
  正是优活艺术指导明确排除的「AI 渐变球」。**REJECT**
- **`:112-116` `:233` tab 文字 `fontSize: 9.5`**：9.5px。这个 App 自称有
  caregiver awareness。**REJECT**
- **`:123-124` 安全区靠硬编码平台常量**（`Platform.OS === 'ios' ? 80 : 56`，
  `paddingBottom: 22`）而不是 `useSafeAreaInsets()`。优活用
  `env(safe-area-inset-bottom)` 是对的，别退回去。
- **能力层是空的**：README 把 Voice 讲成能力层，而 `VoiceContext.ts` **只有 2 行**，
  `VoiceFAB.tsx` **497 行**——比任何一个屏都大。声明的抽象和实际的耦合相反。
  优活的 `task-space.js` 是纯函数、可在无浏览器无会话无数据库时调用，
  这一点比它强，别向它靠。
- 零测试。`:68` 用 `useState(isLoggedIn())` 同步读登录态，`storage.ts` 18 行。

---

## 四、Folk Care：产品角色怎么拆

问题：**为什么它不会让 Family、Caregiver、Professional 全挤在同一套页面里？**

答案不是一个机制，是**四层叠起来的四个机制**，而只有上面两层跟路由有关。

> 抽验过：`CarePlanProgressReport` 确实在
> `verticals/family-engagement/src/types/family-engagement.ts:372`，
> 三个叙事字段在 `:392-394`、`preparedByName`/`publishedAt` 在 `:397-399`、
> `isInternal`（注释「Internal staff note not visible to family」）在 `:311`。
> 引用可信。

### ① 角色是一个集合，一张优先级表把集合塌缩成一个落点 —— ADAPT

`packages/core/src/types/base.ts:80` 是权威的 12 角色联合类型
（`SUPER_ADMIN … AUDITOR, READ_ONLY`），而 `UserContext.roles` 是 `string[]`——
**一个人同时持有多个角色**。于是 `packages/web/src/core/utils/role-routing.ts:11`
给每个角色一个 home，`getDashboardRoute()` 按一个显式的 `rolePriority` 数组走，
`'FAMILY'` **排在第一个**，注释写着 `// Family portal is highest priority`。

**解决的问题**：一个既是协调员又是家属的人，必须有确定的落点。
而它选择让**消费者身份优先于员工身份**。

优活 ADAPT：一个老人 + 一个家属不需要 12 角色枚举，但「有一个函数独占入口分发」
这件事值一个十行的 vanilla JS 模块。留优先级的思路，丢掉角色矩阵。

### ② 消费者是被**赶出**员工树的，不是在员工树里条件渲染 —— ADOPT

`packages/web/src/App.tsx:118`：

```tsx
user?.roles.includes('FAMILY') || user?.roles.includes('CLIENT')
  ? <Navigate to="/family-portal" replace />
  : <AppShell><DashboardSelector/></AppShell>
```

而且**两个方向都有闸**：`ProtectedRoute` 拦权限，`FamilyProtectedRoute` 把员工
踢出家属门户（`ProtectedRoute.tsx:98`）。

结构上家属侧是一个**嵌套布局路由**：`App.tsx:622-639` 把 `FamilyPortalLayout`
挂一次作为父级，8 个子路由（`activity` `messages` `notifications` `schedule`
`care-plan` `health-updates` `settings` + index）通过 `<Outlet/>` 渲染进去。

**这正是优活要的 Family-App-shell-with-modules 模型**：
`/family` `/care` `/trust` 是子级，壳是父级。

### ③ 导航的**宽度**编码角色，任务的**深度**放在栈里 —— ADOPT

三套导航都是声明式数据数组，不是 markup：

| 面 | 导航项数 | 出处 |
|---|---|---|
| Professional | **14** 项（Dashboard … Compliance, Admin），每项带可选 `permission` 串 | `Sidebar.tsx:36-114`，`:122` 过滤 |
| Family | **1** 项（Dashboard）+ 页脚钉住的 Settings/Logout | `FamilyPortalLayout.tsx:18-20` |
| 现场护理员 | **4** 个底部 tab（Visits/Schedule/History/Profile） | `packages/mobile/src/navigation/RootNavigator.tsx:107-136` |

关键在第三行：那 ~10 个任务屏（`Check In` `Clock In` `Tasks` `Take Photo`
`Client Signature` `Visit Notes` `Check Out`）是压在 tab **之上的栈**里，
**没有一个被加进导航**。EVV 那条线性流程跑起来时，四个 tab 一动不动。

**规则：导航宽度是角色的函数；任务深度永远不进导航。**

这条直接印证优活 `/elder` 的四 tab，并且给出 Family 侧的答案：
**也该是四个稳定的 tab，详情从上面压过去**——而不是把详情做成第五项。

### ④ 照护计划**不是同一份数据的两个视图** —— ADOPT，这是最可迁移的一条

| | 专业侧 | 家属侧 |
|---|---|---|
| 实体 | `care_plans` 表 | `CarePlanProgressReport`（**另一个实体**） |
| 出处 | `packages/core/migrations/20251030214716_care_plans_tables.ts` | `verticals/family-engagement/src/types/family-engagement.ts:372` |
| 字段 | `plan_number` `physician_id` `supervisor_id` `authorization_number` `compliance_status` `version` + 软删除 | `reportPeriodStart/End` `reportType`（WEEKLY/MONTHLY/QUARTERLY/AD_HOC）`goalsAchieved` `goalsAtRisk` |
| 性质 | 运营与法律记录 | **三个叙事字段**：`overallSummary` `concernsNoted` `recommendationsForFamily`（`:392-394`） |
| 署名 | — | `preparedBy` `preparedByName` `publishedAt`（`:397-399`） |

**解决的问题**：家属不该读一份运营记录然后自己推断含义。
**由专业方撰写并发布一份解释，署名、注明日期。**

我一开始按计划书把这条写成「优活的 `/care` 正是被否决的那种做法——把原始指标
渲染得薄一点」。**读 `care.js` 之后这句话是错的**，记在这里免得再传下去。

`care.js:80` 读 `/v7/daily-report/{elderId}`，已经渲染：结论句在最前
（`report.overall` + `report.headline`，判定色**由后端给不由前端猜**）、
三个分项各带判定词且**药丸只留给偏离项**、办事进度四个计数、
`需要您做的：`（`report.suggested_for_family`，空列表时说「今天不用您操心。」）、
以及一个 Folk Care **没有**的东西——**「这份日报不包含什么」**（`report.privacy_note`）。

对着 `CarePlanProgressReport` 逐字段比，真正缺的只有两项：
**`preparedByName` 署名**与**`publishedAt` 生成时刻**
（`report.day` 是哪一天，不是什么时候算出来的）；
第三项 `concernsNoted` 是「部分有」——偏离散在三个分项里，没有汇总成一条。

署名者不是护士而是 Agent，那就署 Agent 与生成时间——它和 DemoClock 是一套东西：
**结论必须能追到它是什么时候、由谁下的**。字段对照表和 Phase D 的三件真实工作
写在 `09_consumer_app_architecture.md` 的 Care 一节。

### ⑤ 可见性是记录上的一个字段，不是一条路由 —— ADAPT（大幅削减）

`visibleToFamily`（`:347`）、`publishedAt`（`:348`）、
`isInternal`（`:311`，注释「Internal staff note not visible to family」）
都长在记录上，`messages` 是员工和家属**共用一张表**。
另有 `PortalAccessLevel` 五档拨盘（`VIEW_BASIC`→`FULL_ACCESS`），DB 层约束。

优活 ADAPT 成**一个布尔**：家属能看到的记录带「已发布」。
**REJECT 五档拨盘和 `familyMemberIds[]`**——只有一个家属时这两个都没有意义。

### ⑥ 审计与活动是**两个模型**，从来不是一个视图加过滤器 —— ADOPT

| | 取证 | 叙事 |
|---|---|---|
| 类型 | `AuditEvent`（`packages/core/src/audit/audit-service.ts:9`） | `ActivityFeedItem`（`:230`） |
| 字段 | `eventId` `timestamp` `userId` `organizationId` `eventType` `resource` `resourceId` `action` `result: SUCCESS\|FAILURE` `metadata` `ipAddress` `userAgent` | `activityType`（11 值，如 `GOAL_ACHIEVED` `INCIDENT_REPORTED`）`title` `description` `summary` `relatedEntityType/Id` `performedByName` `occurredAt` `iconType` `viewedByFamily` |
| 谁能看 | 只有 `audits:view` / `AUDITOR → /quality-assurance`。**家属门户下没有任何审计路由** | 按接收人物化，自带显示提示 |

**同一个事件写两条记录，词汇完全不同。不要建一个再过滤。**

**优活现在做的正是被避开的那件事**，已核实：

- `trust.js:223-224` 取 `/v2/audit?limit=200`，然后在浏览器里
  `.filter(e => e.entity_id === taskId)`——消费者凭证是**把取证审计日志
  拉到前端过滤出来的**。
- 后果不止于词汇：那个 200 条的窗口会让**较早的事务链被截断**，凭证静默丢事件。
- 而且 `trust.js:187-188` 硬过滤 `task_type === 'bill_payment'`，
  挂号和用药永远出不了凭证。

结论：`/judge` = `AuditEvent` 形状（取证），`/trust` = `ActivityFeedItem` 形状
（叙事）。后端应当在**产生事件时**同时写出「给人看的那一条」，
而不是让前端从审计链里现推。这也让 `/trust` 不再需要 `/v2/audit`。

### ⑦ 现场/离线是**另一个应用** —— REJECT

`packages/mobile` 是独立的 React Native 应用，自带导航器、离线数据库、
`OfflineIndicator`、`ConflictResolutionModal`。不是响应式变体。
优活没有现场工作者，也没有构建步骤。

### 优活三个面各属于什么层级

- **Family + Care → 同一个 Family App 壳的两个模块。** Folk Care 的证据是明确的：
  `schedule` `care-plan` `health-updates` `messages` 是**同一个布局的兄弟子级**，
  定义一次，写成数据数组。**`/care` 不是 `/family` 的对等页，它是里面的一个 tab。**
- **Trust → Family App 里的叶子/详情面**，不是对等 tab。它是一个已发布、有署名、
  有版本的产物，你从一条活动项**点进去**才到它。
- **`/judge` 与 `/stage` → 完全另一个面。** Folk Care 把审计锁在角色后面，
  且从不在消费者门户里渲染它。这印证优活三表面的目标。

**「Family 与 Care 作为两个对等页、各带不同的底部导航」站得住吗？站不住。**
Folk Care 从不为同一个人发两套消费者壳。

而且优活 `/family` 顶部那个多余的 `.segmented` 和 Folk Care 犯的是**同一个错**：
它的家属侧边栏退化成 1 项，于是真正的导航搬进了 dashboard 上的 4 个
`QuickLinkCard`（`FamilyDashboard.tsx:108-134`），凭空长出**隐藏的第二层导航**。

落地做法（同时满足严格 CSP 和无构建步骤）：
**导航定义一次，写成一个 JS 数组，由一个共享函数渲染进三个静态文档。**
数组住在 `.js` 文件里，没有内联脚本。——这正好是第一节 C.1 那个条件的实现路径。

### Folk Care 自己的毛病（九条，几条是很好的反面教材）

1. **前端的权限判断不会展开通配符。** `permissions.ts:17` 是
   `user.permissions.includes(permission)`——字面比较。而
   `getPermissionsForRoles()`（`permission-service.ts:240`）把原始串**不展开**
   地放进令牌，`SUPER_ADMIN` 是 `['*:*']`（`:37`）。于是 SUPER_ADMIN
   **每一个前端 `can()` 都判否**：侧边栏塌成只剩 Dashboard，`/clients` 把他重定向走。
   服务端的 `hasPermission()`（`:179-207`）**会**展开通配符——
   **同一条规则两个互相背离的实现。**
2. **五个侧边栏权限串没有任何角色授予**：`audits:view` `care_plans:read`
   `care_plans:create` `evv:read` `incidents:read`。注意下划线 vs 服务里带连字符的
   `care-plans:*`。`/quality-assurance` 要 `audits:view`，
   所以除超管以外**没人到得了 QA**。
3. **`<AppShell>` 在 `App.tsx` 里手写重复 50 次**，而家属门户用的是正确的
   `Outlet` 布局路由。**新写的那一面反而是建得更好的那一面。**
4. **`FamilyPortalLayout` 为 8 个子路由声明了 1 个导航项。**
   `/family-portal/activity` 和 `/notifications` 从任何地方都到不了——
   `NotificationBell.tsx:17` 链到后者，而那个组件从没被挂载过。
5. **家属侧的照护计划整个是编的。** `CarePlanPage.tsx:24-121` 硬编码四个目标、
   叙事文本、三人护理团队（假邮箱假电话），标着 `// Mock care plan report data`。
   **模式是对的，实现是个门面。**
6. **发布闸门建了索引但没接线。** `family_visit_summaries.visible_to_family`
   有偏索引，却没有任何读取路径查这张表；
   `family-engagement-service.ts:637-765` 返回硬编码对象。
7. **死的安全代码**：`shouldRedirect()`（`role-routing.ts:71`）与
   `filterByScope()`（`permission-service.ts:258`）只被它们自己的测试引用。
   租户隔离被设计成**取数之后在内存里过滤**，然后从未被调用——
   **一个有测试、却什么都没保护的 API。**
8. **可见性写死在 SQL 里而不是参数化**：`getMessagesInThread`（`:574`）
   永远追加 `is_internal = false`，员工无法通过这个共用方法读内部备注，
   于是被迫再写一条员工专用路径。
9. **两份互相背离的角色清单**：core 的 12 角色联合类型 vs
   `ROLE_DASHBOARDS`（`role-routing.ts:11`）的 17 个键，多出 `ADMIN` `NURSE`
   `CLINICAL` `NURSE_RN` `NURSE_LPN`。`UserContext.roles` 被声明成 `string[]`，
   注释是「Accepting string[] instead of Role[] for flexibility」——
   **枚举恰好在最需要它的那个边界上被丢掉了。**

第 1、7 条对优活尤其有用，它们是本项目两条既有教训的外部实例：
「同一条规则两个实现」= 闸门与检测器不是同一套信号；
「有测试却什么都没保护」= 只通过过的检查还不算检查。

---

## 五、MedCore：专业平台怎么高级（以及哪里不高级）

先说结论：**MedCore 的专业面不是靠信息架构组织的，是靠角色组织的**，
而消费者/专业的界线画在**行范围和导航范围上，从来不在字段上**。
它真正让人觉得像产品的地方只有三处（工作台、主体抬头、双表面拆分），
**不包括它的 dashboard**——那是常规 SaaS，有些地方比常规还差。

### ① 依赖图就是设计文档 —— ADOPT（最强的一条）

抽验过，实测：

| App | `@medcore/db` | `@medcore/shared` |
|---|---|---|
| `apps/api` | 有 | 有 |
| `apps/web`（员工 + 患者网页） | **无** | 有 |
| `apps/mobile`（患者 RN/Expo） | **无** | **无** |

`apps/mobile` 的 28 个依赖里 `@medcore/*` **零命中**。而且是刻意的，
`apps/mobile/app/ai/triage.tsx:26` 写着 "The mobile workspace intentionally does
NOT depend on `@medcore/shared`"，然后手抄了一份常量清单，注明后端的 Zod schema
才是可接受编码的唯一事实源。

**消费者 App 除了 HTTP 契约什么都不共享。**

**解决的问题**：消费者面一旦和专业面共用一套组件库，它就会不可避免地朝专业面的
样子漂移。只共享线上契约，让「分开」成为默认，而不是需要靠纪律维持的事。

优活 ADOPT：`/trust` 与 `/judge` 现在已经只共享 FastAPI 的 JSON 层，
把这一条**写成规则**——它们可以共用 `tokens.css`（颜色、间距的原语），
但**不许共用 `components.css` 里卡片、表格、徽章的类**。

**而它自己破了这条规则，这是最有用的部分。**
`apps/web/src/app/patient/_components/PatientLayoutShell.tsx:87-97` 给除了
`/patient`、`/patient/login`、`/patient/register` 之外的**每一条患者路由**
套上了 `<DashboardLayout>`。于是患者看到的是**员工的侧边栏**，按
`navByRole.PATIENT`（`dashboard/layout.tsx:365-385`）过滤成 11 项，
**其中 5 项指回 `/dashboard/*`**。

这正是优活必须避开的失效模式，而 MedCore 是它**会因为疏忽而发生**的活证据。

反过来，它**守住**的那一层是 PWA：`patient/manifest.ts` 是**自己的** manifest
（`start_url: /patient`、`scope: /patient`、主题色 `#0f172a` 对根的 `#2563eb`），
`public/sw.js:4` 给 SW 划了 scope，注释写着它「不拦截员工 dashboard 的请求」。
优活只有一个 manifest（`start_url: /elder`），而 `/judge` 属于另一个表面——
**这一条要检查：Service Worker 不该把专业面的请求也管起来。**

### ② 专业侧边栏 —— **REJECT**

`dashboard/layout.tsx:160` 的 `navByRole` 是**每个角色一个平数组，完全没有分组**。
项数：ADMIN **85**、DOCTOR 35、RECEPTION 34、NURSE 24、PHARMACIST 15、
PATIENT 11、LAB_TECH 10。结构里**没有** `group` / `section` 这样的键。
`:229-238` 那一段 ADMIN 的相邻项是：
`Reports, Scheduled Reports, Analytics, Notifications, Audit Log, Feedback,
Complaints, Chat, Visitors, Leads`——相邻纯属偶然。过滤按角色、功能开关、
计费套餐（`:1170`），**不按任务**。

85 项无分组的侧边栏正是优活想避免的东西。**不要抄。**
唯一可捡的是 `SUPER_ADMIN_ONLY_ROUTES`（`:1157`），见第 ⑤ 条。

### ③ 表格契约好，采用率是灾难 —— ADAPT，并记住它的教训

`apps/web/src/components/DataTable.tsx:21-56` 定义了一份相当好的专业表格契约：
每列 `sortable` / `filterable` / `hideMobile`、`bulkActions`、`defaultSort`、
`pageSize`、CSV 导出、加载骨架、空态，以及关键的
`urlState?: boolean`——注释「Persist sort/filter state in URL query」。

**URL 里带住排序与筛选状态，是让一个专业视图变得「可引用」的东西。**
（专业面的人要把一个视图发给同事看，这一条决定他能不能。）

**警告在采用率**：只有 **5** 个 dashboard 页面用它，
另外 **86** 个手写 `<table>`——**审计页就是那 86 个里的一个**。
`apps/web/src/components/` 里也**没有**共享的徽章组件，
**25 个** dashboard 页面各自定义了本地的 `statusColors` 映射表。

**半采用的抽象比没有抽象更贵。** 优活的 `/judge` 六个页签必须共用
**同一个**表格样式和**同一个**徽章样式，定义在 `components.css` 里一次。

### ④ 主体抬头 + 三栏工作台 —— ADOPT 两个

**主体抬头**（`dashboard/patients/[id]/page.tsx:702-738`）：
`data-testid="patient-detail-header"`，里面依次是头像、`<h1>` 姓名、
病历号做成 `font-mono` 药丸、然后风险徽章。

**身份、标识符、风险在同一行；等宽字体只留给机器标识符。**
页签在这个抬头**下面**（定义在 `:617`，渲染在 `:1155-1159`）。

还有一个便宜又有效的东西，`:381-391`：**跟着来路变的返回链接**，
由 `?from=` 驱动，给出「返回队列」/「返回住院」/「返回预约」/「返回患者列表」。
**它让详情页感觉是嵌在一条工作流里，而不是浮在空中。**

这一条和第一节 Medito 那个「PWA 必须自带返回」正好合上：
优活的详情面不但要**有**返回，返回的**目标和文案**应当跟着来路变。

**三栏工作台**（`dashboard/consult/[appointmentId]/page.tsx:6-18`，
文件顶部注释直接写明）：

```
左栏  患者卡：姓名、年龄、性别、电话、过敏、在用药、最近体征
中栏  SOAP 页签：Subjective / Objective / Assessment / Plan
右栏  ConsultRightRail：常用处方模板 + 最近三次就诊
```

右栏**不是更多数据**。`components/ConsultRightRail.tsx:15-18`：
「Every favourite is click-to-paste: diagnoses paste into the SOAP
Subjective.chiefComplaint」。

**决策上下文的定义是「你能拿来用的先前证据」，不是「旁边的统计数字」。**

这是整个仓库里最接近优活 `Timeline / Evidence Viewer / Decision Context`
的东西，它印证了那个计划。而它给第三栏的教训是：
里面必须是审阅者**能用**的东西（跳到源记录、复制那个 ID、打开上一版），
不是第二份数字。

### ⑤ 第一屏应该是一笔事务，不是 dashboard —— 三层证据

- KPI 磁贴在整个 MedCore 里只出现在**两个**地方：`dashboard/observability`
  和 `dashboard/admin-console`，**都是管理面**。
  `observability/page.tsx:11-12`：「Tiles up top show platform totals;
  below is a sortable per-tenant table」。
- `/dashboard` 根页面在测试里**不断言任何 KPI**。
  `e2e/quick-actions.spec.ts:22-26` 只断言动作磁贴；
  `e2e/cross-tenant-isolation.spec.ts:68` 只断言渲染出了一个 `<h1>`
  （注释「Sanity: the dashboard DID render」）。**根页面是壳，不是内容。**
- 真正的工作从**工作清单**打开，不是从指标。
  `e2e/workstation.spec.ts:139-165` 钉住五个面板标题，包括
  `Medications Due in Next 30 Minutes`、`My Assigned Patients`、
  `ER Cases Awaiting Triage`。
- 系统健康是**按角色挡住的，不是一等内容**：`dashboard/layout.tsx:1157`
  把 `/dashboard/observability` 放进 `SUPER_ADMIN_ONLY_ROUTES`，
  让租户管理员「never see the nav entry」。

**但这里要 ADAPT 而不是照抄**：MedCore 从工作清单打开，是因为员工带着会话上下文
来的。而 `/judge` 的访客是**冷启动**的——所以正确做法是
**打开时就已经选中了一笔事务**，让 Timeline 那一栏充当工作清单。

> 注：计划书说要「把 KPI 行挪到 System 页」。实测 `1217` / `KPI` /
> `PWA Ready` / `Runtime Healthy` 在整个 `backend/static` 里**零命中**——
> 那一行早就整个移除了，没有东西要搬。但原则仍然成立，而且优活已经符合。

### ⑥ 审计：显示层 ADAPT，完整性模型 **REJECT**（优活比它强）

记录形状（`packages/db/prisma/schema.prisma:2619-2645`）：
`id, userId, action, entity, entityId, details Json?, ipAddress, createdAt, tenantId`。
只有一条写入路径（`apps/api/src/middleware/audit.ts:60`），没有任何更新路径。

显示（`dashboard/audit/page.tsx:473-481`）七列：
`Timestamp, User, Action, Entity, Entity ID, Tenant, IP Address`。
筛选（`:342-460`）：起止日期、实体类型、动作、用户、「IP 包含」，
外加对 entity/action/details 的全文搜索。有 Load More、CSV 导出，
以及一条**留存横幅**（`:320`）写明留存天数、总条数、最早一条的时间。

**留存横幅值得抄**：它在任何人开口之前就回答了「这份记录是完整的吗」。

**最值得偷的一个细节**（`:510-530`）：Entity ID 那一格主行显示服务端解析出来的
**人类可读标签**，UUID 作为 `text-[10px]` 等宽小字放在下面；
引用的记录已被删除时，退回裸 UUID。
**人读的在主位，机器读的在次位，两个都在。**

**三条它做得不好、优活要超过它的：**

1. **没有完整性链。** schema 和 service 里没有任何 `prevHash` / `signature` /
   checksum。「append-only」只是一个约定。
2. **它真的会删。** `apps/api/src/services/audit-archival.ts:10` 管这张表叫
   append-only，然后 `:168` 在 gzip 到 `backups/audit-archive-*.jsonl.gz`
   之后跑 `prisma.auditLog.deleteMany`，默认留存 365 天。
   **可验证性取决于磁盘上的一个文件。**
3. **`details` 从来没被渲染。** 它在 `audit/page.tsx:33` 声明了，
   服务端能搜它，**而 JSX 里没有它**。于是这份审计日志只说明
   **有什么东西变了、是谁改的，从不说变成了什么。**

**优活在第 1、2 条上已经比它强**——优活有哈希链和 `verify_audit_chain`，
审计事件不删。这一点在 `/judge` 上应当被明确说出来，
因为那是一个真实的商业 HMS 都没做到的事。

第 3 条是**优活最高价值的空缺**：把「改动前 / 改动后」的载荷放进
Evidence Viewer 那一栏。优活的 `details` 里有东西（复述原话、金额、机构回执），
现在没有一个地方把它们并排摆出来。

### ⑦ 状态永远是颜色**加**文字 —— ADOPT

`dashboard/admin-console/page.tsx:851-861` 把绿/红的类和渲染出来的 `{status}`
字符串配在一起；`status/page.tsx:44-58` 返回 `{label: "Operational", cls, Icon}`
——标签、颜色、图标一起给。而且**测试刻意钉住文字**：
`e2e/antenatal.spec.ts:85` 说明它锚在「the unique label copy … rather than
colour」，`e2e/pharmacy-inventory.spec.ts:171` 钉住文字
「so a colour-swap regression surfaces here」。全仓库没有只靠颜色的状态。

**但它的无障碍闸门是「棘轮到现状」而不是「棘轮到标准」**：
`e2e/a11y.spec.ts:82-100` 给 `color-contrast` 留了 **36** 个允许失败的额度
（admin-console 是 80），而 `:116-119` **整页跳过** `/dashboard/admin-console`。

这是优活「一个通过的闸门只是下界」那条教训的外部实例。优活的对比度闸门
是 12/12 零容差，这一点也比它强，别退。

### ⑧ 页签 —— ADAPT，并补上它漏掉的东西

`patients/[id]/page.tsx:1155-1159` 用的是普通 `<button>` 加 `border-b-2
border-primary`，**没有 `role="tab"`，没有 `aria-selected`**。
而 `e2e/doctor-chart-review.spec.ts:106` **记录**了这件事却没有修它：
「the tabs render as `<button>` elements, not `<a>`/role=tab」。

优活 ADOPT 它的**位置**（在主体抬头下面），并补上它漏掉的 ARIA tablist ——
这是免费的差异化。

### ⑨ `/trust` 对 `/judge`：MedCore 自己的先例

`/status`（公开）和 `/dashboard/observability`（操作者）**读同一张
维护窗口表**，而呈现完全分叉：

| | `/status`（公开） | `/observability`（操作者） |
|---|---|---|
| 鉴权 | 无 | 仅超管 |
| 外壳 | 「No dashboard chrome」（`status/page.tsx:16`） | 完整外壳 |
| 内容 | 一个全局药丸 + 组件名 + 可选响应时间 | 汇总磁贴、按租户表格、`p95DurationMs`、慢端点排行 |
| 行数 | 244 | 792 |

**留在手机上的**：一个带文字标签的结论、一小串用人话说的组件名、
人类可读的时间、接下来会怎样、一个刷新的入口。

还有一个更精确的先例：患者账单页**自己重算**一个 `OVERDUE` 徽章
（`patient/bills/page.tsx:133-146`），而不是把员工那边的原始
`daysOverdue` 整数显示出来（`dashboard/billing/page.tsx:776-783`）。
**消费者面显示的是结论，不是让人自己算的中间量。**

**只应存在于 `/judge` 的**：等宽的实体 ID、IP 地址、操作者身份与邮箱、
分组件延迟、`details` 的前后载荷、留存与覆盖统计、CSV 导出、
按操作者/日期/全文筛选、跨记录跳转。

**一条必须说清的警告**：MedCore **没有**字段剥离层。
`apps/api/src/routes/billing.ts:711-733` 按 `role === "PATIENT"` 只收窄**行**，
而 `include` 对两类读者**逐字节相同**。字段的分叉完全活在前端。

对优活来说这是可接受的（同一个后端、两套模板），
**但不许把它描述成一个安全边界，因为它不是。**
优活 `10_surface_boundaries.md` 现在的写法没有这个错误，保持。

### ⑩ 其他两条

- **可捡的便宜东西**：URL 别名桩。`dashboard/blood-bank/page.tsx` 和
  `operating-theatres/page.tsx` 是 `router.replace` 重定向到正规路由，
  注释说是为了让书签和拼写变体「still wrap the page (no flash 404)」。
  优活如果给 `/judge` 改名，这是那条路。
- **Ctrl+K 命令面板**（`dashboard/_components/search-palette.tsx`）搜的是
  **记录**（患者、预约、发票、住院），**不是导航目标**——所以它其实救不了那个
  85 项无分组的侧边栏。但对优活正好：**做成一个事务 ID 跳转框**，
  那正是 `/judge` 需要的「一笔事务」入口。

### MedCore 自己的毛病

- **`patients/[id]/page.tsx` 有 6536 行**，9 个页签挤在一个客户端组件里，
  主体抬头挂着 7 个以上的内联动作按钮，**没有溢出菜单**。
  优活六个页签的 `/judge` 必须让每个页签的取数和渲染各自成模块。
- **`docs/` 有 30 多个文件，没有一个是关于 UI / 信息架构的**，
  `CLAUDE.md` 只讲后端安全。**这就是平导航、25 份重复状态映射、
  DataTable 只到 5/86 的根因**——没有人写下过这个产品的界面该长什么样。

  这一条反过来说明优活 `frontend_redesign/ia/` 这一叠文档是有价值的，
  不是文书工作。

---

## 六、量优活自己：两条计划书前提已经过期

读参考项目的过程中顺手量了优活的真实状态，撞出两条**计划书写错了**的前提。
先修正它们，否则后面的 Phase F/G 是照着不存在的问题在做。

> 仪器局限先说明：下面的「可见文本」提取器只解析 HTML 文本节点，
> **不跑 CSS**。所以 `.needs-server` 那段被 `base.css` 的
> `.needs-server{display:none}` 藏起来的提示也被它收进去了——那不是用户
> 真看到的第一句。除此之外的统计不受影响。

### ① 「去掉评委/Judge/比赛术语」是改 6 个字符串，不是重写

按用户真正看得到的字量（走真实服务器 8041，去 script/style/注释）：

| 路由 | 可见字符 | 比赛词汇 | 工程词汇 |
|---|---|---|---|
| `/` | 186 | — | — |
| `/elder` | 569 | — | — |
| `/family` | 420 | — | — |
| `/care` | 383 | — | — |
| `/trust` | 490 | — | — |
| `/stage` | 2685 | 评委×2 答辩×2 | — |
| `/judge` | 1695 | 评委×1 评分×1 | API×1 |

**五个消费者面比赛词汇和工程词汇都是零命中**——现有那道
`test_app_surface_speaks_no_engineering.py` 是有效的，不是自我安慰。

全产品可见的比赛词汇合计 **6 处**。源码里 `judge.html` 有 249 行命中 `judge`，
但那些是类名（`judge-body` `judge-shell`）、id（`judgeStatus` `judgePhone`）
和注释；`judge.js` 里 7 处全部在注释里。**唯一可见的那句**是
`judge.html:54` 的「正在建立评委演示环境……」。

缺的不是工作量，是**闸门**：现有闸门管「消费者面不许有工程词」，
没有任何闸门管「任何产品面不许有比赛词」。这才是要补的东西。

### ② `/judge` 的首屏**已经**是一笔事务，KPI 行不存在

计划书写「它的第一屏是 KPI 行（99 APIs / 1217 Tests / PWA Ready /
Runtime Healthy）」。在 `judge.html` 里搜 `1217` / `KPI` / `PWA Ready` /
`Runtime Healthy`：**零命中**。第 220 行的注释说明评分权重条早就挪走了。

`/judge` 现在的首屏是：一句标题「一位老人交一次水费，中间发生了七件事」，
接着七拍，每拍带「看这一拍的证据」和「单独跑这一拍」，右边一台跑 `/elder`
的真手机。**这已经是「围绕一笔事务」的形状了。**

### ③ 但 `/stage` 与 `/judge` 的内容和它们的角色是**反的**

我先假设这两页已经重复了（都是七拍加一台手机）。**量下来假设是错的**——
它们不重复，而是**互换了**：

| | `data-beat` 拍数 | id 数 | 可见文本块 | 标题里是什么 | 实际是什么 |
|---|---|---|---|---|---|
| `/stage` | **0** | 69 | 145 | 看哪一端 · 演示台词 · 视口 · 舞台 · 场景注入 · 他自己的常态与今天 · 循环事务与月报 · 用药与库存安全 | **一个导演控制台** |
| `/judge` | **7**（01–07） | 22 | 71 | 她开口 · 听不清就不猜 · 一次只问一件事 · 账单图片说 9999.99 优活不听它的 · 她得把金额念一遍 · 第二个人点头 · 办好了而且说得清为什么 | **一段有引导的叙事** |

重合度：可见文本相似度 **9.1%**，同名 id **0 个**，逐字相同的文本块 9 个——
其中 8 个是共用的 `.needs-server` 提示样板，加一句「老人端 · 390 × 844」
和一个「可信中心」。所以确实不是两份拷贝。

**问题在于名字和内容对不上：**

- 那段七拍叙事（`/judge` 上）是**给观众看的故事**，它属于 Presentation。
  写得也好——每拍都是一句人话的主张加一条真实证据链接。
- 那 69 个 id 的控制台（`/stage` 上）是**给操作者用的**，
  它属于计划书里说的 Director Controls。

Phase F/G 因此不是「把 `/stage` 分成两层、把 `/judge` 改成工作台」，而是：

```
七拍叙事      /judge  →  /stage 的 Presentation View        （搬，不删）
导演控制台     /stage  →  /stage 的 Director Controls（默认收起）
事务工作台     新建     →  /judge                          （Timeline / Evidence / Decision Context）
```

这个方向同时满足「不得 Silent Delete」：七拍不是被删掉，是搬到它该在的表面；
`/stage` 那些控件不是消失，是收进一个不起眼的入口。

`/judge` 上「这一页自己的边界」那一节是个好东西——一个专业面自己声明
它不负责什么。搬迁时保留。

---

## 六点五、副产品：我自己建的那道矩阵闸门有一半是惰性的

为了给 Phase F/G 出一份精确的搬迁工作单，我从生成的清单里取真实的控件键，
顺手量了各列的填充率。结果是这一轮最重要的发现之一，而且它是关于**闸门自己**的。

| 列 | 已填 | 填充率 |
|---|---|---|
| `key` `source_file` `surface` `shell` `module` `visibility` | 145 | 100% |
| `handler_file` `handler` | 117 | 81% |
| `interaction_type` | 102 | **70%** |
| `panel` | **55** | **38%** |
| `apis` | **5** | **3%** |

**问题在 `panel` 那一行。** A2 这一轮矩阵的升级点是
「dst 从**文件**升级到 `(文件, panel)` 二元组，判据从**存在**升级到**相等**」——
而 90 个控件的 `panel` 是空字符串。对这 62% 来说，判据在拿
`(file, "")` 和 `(file, "")` 比，**panel 那一半恒真**。

清单报告「145 个控件、145 个可追踪、0 个无标识」。**那句话是真的，
但它只对身份成立。可追踪 ≠ 位置可比较。**
这和这个项目反复踩的是同一个坑：读到的那个值不一定是决定结果的那个值。

`apis` 只填了 5 个，其中 3 个还是同一个 `/v2/family/reminders`。
而计划书里矩阵的形状是
`现有控件 → handler → API → 新 Surface → 新位置`——**中间那一环现在是空的**。
`/judge` 上七拍每一拍的可见文案都点名了一个端点（`/v2/chat` `/v2/tasks`
`/v5/voice/resolve` `/v6/interaction/plan`），而那 27 个控件的 `apis` 全是空数组。
所以矩阵**追踪不了「控件背后的 API 有没有跟着搬」**。

`visibility` 的六个文档取值里 `contextual` **从未被使用**（0 个）。

### 已补的三道断言（`test_control_inventory_is_the_fact_source.py`）

1. `test_no_inventory_column_gets_emptier` —— 十一列各自的填充数作为下界，
   只许涨。空列是**静默**失效：矩阵照着空值断言「相等」然后全绿，
   正是它替换掉的那份手写点击地图的毛病（缺文件就 `pytest.skip`）。
2. `test_the_apis_column_is_known_to_be_unimplemented` —— 不要求它变好，
   要求这件事不被忘记；填到 8 个以上就会红，逼人把它改成正向断言。
3. `test_a_declared_move_must_be_detectable_by_the_criterion` ——
   B–H 每加一行 MIGRATIONS 先过这一关：同文件、两侧 panel 均为空的声明
   直接拒绝，因为那种搬迁这个判据测不出来。

变异证明（七条，全部按预期）：清空 `panel` → 红；`handler` 只掉 3 个 → 红；
声明一次同文件双空 panel 的搬迁 → 红；声明一次真正跨文件的搬迁 → 放行，
而「落在声明位置上」那条立刻红并指出实际位置（`id=playStory` 声明搬到
`('stage.html','demo')`，实际在 `('judge.html','')`）。

### 这份工作单本身

搬迁的规模量出来了：

| 文件 | 控件数 | 其中 |
|---|---|---|
| `stage.html` | 57 | 无 panel **24**（导演控制台本体）· `demo` 14 · `proof` 16 · `engineering` 3 |
| `judge.html` | 27 | **21 个是七拍**：`data-jump=01..07` · `data-beat=01..07/summary` · `data-run=runOpen/runVoice/runLoad/runPreview/runTeachBack/runRelay/runCard`；其余 6 个是 `id=playStory` `id=demoBoard` 和四条导航 |

**`/judge` 的 27 个控件里 21 个（78%）属于要搬去 `/stage` 的七拍。**
所以 Phase G 不是「改造 `/judge`」，是**新建**——搬走之后它只剩 6 个控件。
这一点计划书没有说清，现在有数了。

另外 `judge.html` 全部 27 个控件的 `panel` 都是空的，
所以按上面第 3 条断言，七拍那次搬迁**必须**在两侧标上 `data-panel`
（源侧标 `data-panel="story"` 之类），否则矩阵测不出它。

---

## 七、跨仓库组合出来的三个表面

不是「一个仓库对应一个页面」。真正有用的结论是四份证据交叉出来的：

```
Elder App Shell
├── Medito   一个从不被销毁的 App 实例（IndexedStack）
├── Medito   穷尽三态 + 加载降级成提议 + 错误分型带出路
├── MediMate Voice 是动作不是目的地；Chat 是可去之处不是所在之处
└── 否决      Medito 的「详情页不放返回」（PWA standalone 没有系统返回）

Family / Care
├── Folk Care 一个壳挂多个模块（FamilyPortalLayout + Outlet）
├── Folk Care 导航宽度编码角色，任务深度进栈不进导航
├── Folk Care 家属侧读的是**另一个实体**：署名、注明日期的解释
├── Medito    首页分区是有序数据；卡片只给同类对等项
└── 否决       五档可见性拨盘、租户/角色矩阵、离线现场应用

Professional Audit
├── MedCore   主体抬头（身份+标识符+风险一行）+ 三栏工作台
├── MedCore   决策上下文 = 能拿来用的先前证据，不是旁边的数字
├── MedCore   留存横幅、人读标签在主位 / UUID 在次位
├── MedCore   系统健康按角色挡住，不进第一屏
├── Folk Care 取证与叙事是两个模型，不是一个视图加过滤器
└── 否决       85 项无分组侧边栏、半采用的表格抽象、留额度的无障碍闸门
```

**优活已经比参考项目强的三处**（要在 `/judge` 上说出来）：
审计有哈希链且不删（MedCore 有 `deleteMany` 且无 `prevHash`）；
对比度闸门零容差（MedCore 留 36–80 个额度）；
`task-space.js` 是可在无浏览器无数据库时调用的纯函数
（MediMate 的「能力层」只有 2 行而实现 497 行）。

---

## 八、这一轮已经确定要改的方案条目

| # | 改什么 | 依据 | 落到哪 |
|---|---|---|---|
| 1 | Family 四个入口的**行为一致性**成为 Phase C/D 前置条件，三条可测判据 | Medito `IndexedStack` vs 优活七文档 | `09` 新增一节 |
| 2 | 导航定义**一次**，写成 JS 数组，由共享函数渲染进三个文档 | Folk Care `FamilyPortalLayout.tsx:18-20` + 它 1 项管 8 路由的反面 | `09` |
| 3 | 每个数据区块走**穷尽三态**的统一渲染约定 | `home_view.dart:99` | `09` + 新闸门 |
| 4 | 加载超过 3 秒**降级成一个提议** | `home_view.dart:229-248` | `09` |
| 5 | 错误**至少分四型**，每型给不同的可走动作 | `medito_error_widget.dart:36-51` `:133` | `09` + 新闸门 |
| 6 | **详情面必有出口**（闸门守，**与用了哪个抬头无关**），且返回目标跟着来路变 | 实测 `MeditoAppBarLarge` 有箭头、`Small` 没有且旋钮是装饰 + `manifest.webmanifest:10` + MedCore `patients/[id]:381-391` | `09` + 新闸门 |
| 6b | 设置行 = **标题 + 一行说明它的后果**；分隔线**缩进**与文字对齐，不通栏 | 实测 `rowitemwidget/with-switch`：「Do Not Disturb」/「Silence all alerts」 | `09`「我的」一节 |
| 6c | 加载骨架与真实列表**同形**（行数/高度/圆角/间距一致），取代硬留高度 | 实测 `boxshimmerwidget/list-skeleton` 四个同形圆角条 | 艺术指导阶段 |
| 6d | 组件画廊的**每个旋钮都要有一条变异断言**证明它真的接着东西 | 实测 `hasBackButton` 旋钮拨动后 app bar 逐字节不变 | 若做画廊 |
| 7 | 卡片判据：同类对等项用卡片，性质不同用分隔线 | `home_view.dart:140` vs `settings_screen.dart:343` | 艺术指导阶段 |
| 8 | 聊天从主画面降为「记录」下的一个入口 | MediMate `ChatScreen` 120 行是最小屏 | `09` Task Space 一节 |
| 9 | 语音必须能到达 tab 之外的地址 ⇒ 事务详情必须可寻址 | MediMate `App.tsx:190-195` | 迁移矩阵 |
| 10 | `/care` 改成**有日期、有署名**的解释，含「需要注意什么」「你可以做什么」两个显式字段 | Folk Care `family-engagement.ts:372` `:392-394` `:397-399` | `09` Care 一节 |
| 11 | `/trust` **不再从 `/v2/audit` 现推**；后端在产生事件时同时写「给人看的那一条」 | Folk Care `AuditEvent` vs `ActivityFeedItem` + 实测 `trust.js:223-224` | `10` + Phase E |
| 12 | `/judge` 新建三栏工作台，**打开即选中一笔事务**；七拍搬去 `/stage` | MedCore `consult/[appointmentId]:6-18` + 实测两页角色互换 | `10` + Phase F/G |
| 13 | `/judge` 的 Evidence Viewer 必须摆出 `details` 的**前后载荷** | MedCore 三条审计缺陷的第 3 条 | Phase G |
| 14 | 补一道闸门：**任何产品面不许出现比赛词汇**（现有闸门只管工程词） | 实测全产品可见比赛词 6 处，无闸门 | 新闸门 |
| 15 | `/trust` 与 `/judge` 只许共用 `tokens.css`，**不许共用** `components.css` 的卡片/表格/徽章类 | MedCore 依赖图 + 它自己破规则让患者看到员工侧边栏 | `10` |
| 16 | 检查 Service Worker 的 scope 不把专业面的请求也管起来 | MedCore `public/sw.js:4` 是它守住的那一层 | Phase G |
| 17 | `/judge` 页签补 `role="tab"` / `aria-selected`；表格与徽章各**一套**样式 | MedCore `patients/[id]:1155-1159` + DataTable 5/86 | Phase G |
| 18 | `/judge` 加一个**事务 ID 跳转框**作为冷启动入口 | MedCore `search-palette.tsx` 搜记录而非导航 | Phase G |
