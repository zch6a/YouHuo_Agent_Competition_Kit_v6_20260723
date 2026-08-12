# Impeccable 改动记录

裁决过程在 `IMPECCABLE_AUDIT.md`。这一份只记**改了什么**：before / after / 依据 / 复验。

八条里采纳四条、拒绝两条、延后两条。四条采纳的都属于修复顺序里的 **clarify** 与
**harden**，一条 bolder / colorize / delight 都没有——这是计划书第 12 章的要求，
也是这四条的共同性质：它们全是**删**，没有一条是加。

---

## 1 · `.next-item` 的 4px 强调色左边 —— 删

```diff
  .next-item {
-   border-left: 4px solid var(--role-accent);
    …
  }
```

**Skill Authority**：Impeccable · `side-tab`（"the most recognizable tell of AI-generated UIs"）
**依据**：老人端首页唯一的卡片，而这道线是**我这一轮自己加的**。这张卡已经有 28px
等宽数字的时间、22px 的标题、阴影和 1px 描边——彩色左边是在同一件事上再喊一遍。
**复验**：检测器复跑不再报它；删掉之后它仍然是首页最重的东西，因为那是**内容**给的。

## 2 · `.score-ribbon strong` 的渐变文字 —— 改实色

```diff
- background: linear-gradient(…); -webkit-background-clip: text; color: transparent;
+ color: var(--youhuo-blue-ink);
```

**Skill Authority**：Impeccable · `gradient-text`
**依据**：这一条不只是 AI 签名，**它还是一个让自己逃出无障碍安全网的处理**。
原写法把渐变裁进 36px 的分数字形里，计算 `color` 是 `transparent`，而
`check_contrast.py` 里有一行 `if (/rgba\(0, 0, 0, 0\)|transparent/.test(cs.color)) continue;`
——**整个对比度审计把这个数字跳过去了**。
**复验**：改成实色之后它重新进入审计范围，`check_contrast` 14/14 仍然全过
（也就是说它本来就够，只是从来没被查过）。

## 3 / 4 · `.stage::before`（3px）与 `.reliance-card::before`（4px）—— 删

两个伪元素顶边通长彩色横线，整条规则删掉，历史写进注释。

**Skill Authority**：Impeccable · `side-tab`
**依据**：两个互不相干的方法指向同一个元素——Impeccable 判它们属于 side-tab 一族，
而**之前那次逐像素视觉审查**独立地写过：「卡片顶边有一条通长蓝色横线……眯眼看第一眼
落在这条线上，而不是落在麦克风按钮上」。
判据不是"不好看"，是**它不携带任何信息**：不表示状态、不表示分组、不表示进度，
而它抢走了这一屏的第一落点，那个位置属于麦克风。

**一个过程记录**：我先试过保留规则、只把 `content` 置成 `none`，想留住这个伪元素的
历史。结果检测器读的是声明本身、读不出"它不渲染"，那两条就**永久**留在报告里。
一份长期挂着两条已知误报的报告，下次真出问题时没人会注意到——所以真删，历史写进注释。

---

## 装依赖：检测器第一次跑是残的

```
impeccable detect: DEGRADED - HTML parser modules unavailable
  (htmlparser2, css-select, css-tree, domutils).
  … findings are an undercount, not a clean bill of health.
```

**6 条** → 装上四个依赖（13 个包 3.6 MB）后 **8 条**。降级模式漏了 1/4。

值得记一笔：**它比很多闸门诚实**——不是安静地少测，而是先声明自己残了。
如果它只是安静地报 6 条，我会当成审计通过。

---

## 一处仪器缺陷（Lane B 发现，未修）

`detect.mjs` 把 `<link href="/static/x.css">` 解析成 `F:\static\x.css`，读失败，
裸 `catch` 吞掉 → **189,514 字节的 CSS 被静默忽略，退出码 0，没有 DEGRADED 横幅**。

后果：这个检测器**依赖层叠的那一半**（对比度、字号层级、辉光）在这个项目上
**从来没有运行过**。上面那 8 条全部来自不依赖层叠的规则。

这是第三方 skill 的代码，不在本项目仓库内。记录在此，不改它——但也**不能**把
"检测器 4 条已裁决"当成"整份 Impeccable 审计通过"。已在 `IMPECCABLE_AUDIT.md`
更正过我早先「全强度」的说法。

---

## 复跑结果

```
检测器：4 条
  [em-dash-overuse] stage.html:0   16 em-dashes → Phase 5 文案轮（判定：字符依据在中文里不成立，理由成立）
  [em-dash-overuse] judge.html:0    8 em-dashes → 同上
  [side-tab] pages.css   .receipt-offchain（中性引文块） → FalsePositive，拒绝
  [side-tab] components.css .notice（警示左边）        → Not Applicable，拒绝
```

目标状态不是 0 条，而是**没有一条未经裁决**——一份长期挂着未裁决条目的报告会训练人
忽略它。
