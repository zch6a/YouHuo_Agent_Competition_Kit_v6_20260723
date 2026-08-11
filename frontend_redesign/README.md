# frontend_redesign/

这一轮前端重构留下的文档。**每一份都标了它的内容是量出来的还是判断出来的**，
因为把两者混在一起会让判断借到测量的可信度。

```
reference/          研究与规则
  PRODUCT_REFERENCE_AUDIT.md      看了哪些仓库、抽出什么原则、一行代码都没拿
  INTERACTION_PATTERN_LIBRARY.md  从六个仓库源码里逐行量出来的交互数字（带文件行号）
  MOBILE_PATTERN_LIBRARY.md       同上，移动端部分
  VISUAL_PATTERN_LIBRARY.md       这个项目实际采用的视觉规则和每一条的理由
  ANTI_PATTERN_LIBRARY.md         不该怎么做，每条带一个已经发生过的后果

architecture/       现状
  01_current_architecture.md      七页 / 四层 CSS / 十四个 JS，以及不迁技术栈的四条理由
  02_dom_contracts.md             每个 id/class、谁读它、断了会怎样、哪条闸门守着
  03_api_contracts.md             前端调什么、指望回什么、回不来时屏幕上会怎样
  04_state_and_data_flow.md       状态住在四个地方，权威只有后端

ia/
  07_information_architecture.md  七个页面、三种读者，一页只服务一种

accessibility/
  ACCESSIBILITY_AUDIT.md          测出来的 / 判断出来的，分开写

browser-qa/
  BROWSER_QA.md                   每一项跑在什么上，以及这些检查自己出过的错

visual-audit/
  VISUAL_SCORECARD.md             逐页五个测试 + 我的分数（是判断，不是测量）
```

配套的两份在仓库根：

- [`../TEST_REPORT_FRONTEND.md`](../TEST_REPORT_FRONTEND.md) —— 当前数字、这一轮新增
  闸门的变异结果、量出来和看出来的缺陷、我自己犯的错
- [`../KNOWN_ISSUES.md`](../KNOWN_ISSUES.md) —— 已知但没修的东西

截图由 `backend/scripts/shoot_pages.py` 生成（126 组 / 252 个文件），不进仓库。

---

## 三条贯穿全部文档的判断

**一，仪器测的必须是你关心的那件事。** 这个项目在闸门上花的时间比在特性上多，
而闸门自己出过的错比特性还多——CI 曾经从没在浏览器里加载过任何页面却一直打印 PASS，
`node --check` 曾经给两整页死掉的按钮开绿灯。

**二，闸门是下界，不是通过。** Voice Orb 十一态通过了指纹闸门，然后被灰度联系表
否掉三态。可测的部分有数字，"好看"没有仪器。

**三，不许假装。** 办不成就说办不成（事务凭证的失败分支）、重复缴费就说重复缴费
（评委页第 1 拍）、没测过就写"未验证"而不是"通过"（`KNOWN_ISSUES` 第 5–8 条）、
分数不到 94 就写不到 94（`VISUAL_SCORECARD`）。
