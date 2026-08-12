
# 迁移矩阵的变异证明

对照 `MUTATION_PROOF_FOCUS.md` 的做法：逐个变异体写明，带具体数字。
既有记录只有 `POLISHING_STATE.md` 一格「✅ 四路全红」，**没有变异体清单**——
一句没有清单的「全红」和没有变异测试是一回事。

---

## 先说旧闸门的盲区（这是本轮要补的那一格）

`test_no_control_was_silently_deleted.py:197-199`：

```python
now = {id for page in app_pages for id in _ids(page)}   # ← 四页的并集
missing = before - now - known - RESTRUCTURED
```

`now` 是**并集**，所以一个控件只要还在四个 app 页面中的**任意一页**，
`missing` 就不含它。判据是「存在」，不是「在哪」。

后果：**app → app 的搬迁 100% 隐形。** 而产品架构重构的搬迁绝大多数走这一路
（`/care` 的内容进 Family shell、`/family` 的趋势进 Care、`/trust` 变成事务详情）。
旧闸门是为**一个方向**建的：手机框内 → 框外 `/stage`（`MATRIX` 那 23 行全是这个方向）。

配套的三个洞：

| 洞 | 位置 | 后果 |
|---|---|---|
| 事实源只覆盖 41 / 145 个控件 | `08_click_map.md` 手写，抽取器只认反引号 `` `#id` `` | 104 个控件从未进过事实源 |
| 单向读取 | 只有 `:177` 读它，没有「代码里的控件必须在文档里」的反向断言 | 删控件 + 删文档行 = 全绿 |
| 缺文件时 `pytest.skip` | `:179` | 事实源消失 = 静默通过 |
| `RESTRUCTURED` 8 个手写豁免 | `:204-209` | 加一个名字就能让任何删除合法化 |

---

## 变异 ①：`/care` → `/family`（旧闸门的盲区）

**变异**：把 `/care` 上一个真实控件（`data-section=today` 那一族里的一个）
的位置改成 `family.html` 的 `today` 格。

**旧判据的反应**：

```
union_before == union_after   →  True
key in union_after            →  True
→  missing 为空  →  绿
```

**新判据的反应**：

```
before_location = ("care.html",   "today")
after_location  = ("family.html", "today")
→  不相等  →  红
```

测试 `test_the_gate_catches_an_app_to_app_move_that_the_old_one_missed`
**两个方向都断言**：它先确认旧判据在这次搬迁上确实保持绿（否则说明我对旧判据的理解
错了，那时该去核对而不是改测试），再确认新判据红。只断言后者的话，这条变异
证明不了「这是旧闸门的盲区」这句话。

---

## 变异 ②：清单过期（读一份产物 ≠ 看到当前事实）

**变异**：改 HTML 但不重新生成 `11_control_inventory.json`。

**反应**：`build_control_inventory.py --diff` 退出 1，并逐条列出
「代码里新增 / 代码里消失 / 键集合相同但属性变了」三类差异。
`test_the_inventory_is_freshly_generated` 把这个退出码变成断言。

这和重型报告的源码指纹是同一个形状——那次的教训写在
`test_release_hygiene.py:70-78`：「一条记录，而不是当前的事实」。

---

## 变异 ③：控件失去稳定身份

**变异**：把某个控件的 `id` / `data-*` 摘掉。

**反应**：`test_every_control_has_a_stable_identity` 红，并点名
「哪一页、什么标签、什么文字」。

这一条守的是本轮的一个实测发现：**145 个控件里只有 57 个带 `id`**。
按 id 追踪意味着另外 88 个搬走或消失都不会有任何东西发现。所以身份放宽到一组
**稳定属性**（`id` / `data-section` / `data-text` / `data-run` / `data-jump` /
`data-sheet-*` / `name` / `href`，以及从最近一个有身份的祖先借——评委页七拍那 7 个
「看这一拍的证据」文字完全相同，靠 `data-beat=03/summary` 才分得开）。

刻意**不**用的三种：`class`（改名就断）、位置（重构必然变）、可见文字
（后面还有一整轮文案要改）。

覆盖率：57 → **145 / 145**。

---

## 变异 ④：身份重复（两个控件被当成一个）

**变异**：让两个控件在同一页里共用一个身份。

**反应**：`test_identity_is_unique_within_a_page` 红。

这一条抓到了 **21 个真实的现存问题**：`#stageRoles` / `#stageLines` / `#stageSizes`
里各五个兄弟按钮全靠祖先借身份（它们自己没有任何标识）、`/family` 有两个
`href=/trust`（正文行内链接 + 卡片链接）、`/care` 有两个 `href=/`（页头返回 +
底部导航首页）。

它们现在靠序号（`#2` `#3`）区分，是权宜。重构时补上 `data-*` 钩子，
`build_control_inventory.py` 的「靠序号才区分得开」那份名单会自己变空。

---

## 变异 ⑤：Consumer 侧长出第三个 App Shell

**变异**：给某个消费者控件标一个 `elder` / `family` / `entry` 之外的 shell。

**反应**：`test_the_consumer_surface_has_exactly_two_app_shells` 红。

这一条守的是本轮的核心约束。它同时防住一种更隐蔽的退化：
把所有页面都归进 `consumer` 会让「三个表面都非空」那条断言照样绿，而三表面架构
其实已经塌成一个——所以 `test_surface_registry.py::test_the_three_surfaces_are_all_populated`
从另一侧钉住。

---

## 覆盖率对照

| | 旧闸门 | 新闸门 |
|---|---|---|
| 事实源 | `08_click_map.md`（手写，41 / 145） | `11_control_inventory.json`（从代码生成，145 / 145） |
| 缺事实源时 | `pytest.skip` | **assert 失败** |
| 事实源过期 | 无检测 | `--diff` + 一条断言 |
| 追踪键 | `id`（57 个控件有） | 稳定属性 + 祖先借用（145 个控件有） |
| 位置粒度 | 文件 | **(文件, panel)** |
| 判据 | 存在（并集） | **相等** |
| app → app 搬迁 | **失明** | 红 |
| 反向断言 | 无 | 代码 → 清单必须一致 |

**还没做的**：矩阵目前对**运行时才存在**的控件仍然失明。实测运行时按到 119 个，
而静态可按的只有 109 个——差的 10 个是 JS `createElement('button')` 建出来的
（提醒的「我知道了 / 已完成」、任务卡的「同意 / 拒绝」）。静态扫描永远看不见它们。
另有 `/family` −1：一个静态控件运行时够不到。这两笔账要在 B–H 里由
`check_page_runtime.py` 的 `REQUIRED_PRESSES` 逐个点名补上。
