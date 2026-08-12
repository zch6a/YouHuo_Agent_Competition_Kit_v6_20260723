/**
 * 设计令牌：尺寸、排版与动效。
 *
 * 颜色不在这里——颜色走 `$r('app.color.*')`，因为只有资源系统能在 `resources/dark/`
 * 里自动换一套值。写死在 ArkTS 常量里的颜色是不会跟着系统深色模式走的。
 *
 * 这些数值和 Web 端 `backend/static/tokens.css` 的令牌一一对应，两端刻意保持同一套
 * 比例。理由不是整齐，而是这个产品的老人端和家属端会被同一个人在同一天里分别用到
 * 手机浏览器和原生 App 上；两边的按钮不一样大、动效不一样快，用起来就是两个产品。
 * （上一版这里写的是 `backend/static/style.css`——那个文件不存在，令牌四层拆开之后
 * 权威来源是 `tokens.css`。一条指向空处的引用会让下一个人以为自己对齐过了。）
 *
 * --- 配色：本轮跟 Web 端一起转暖（设计稿第 42 节 Warm Ivory） ------------------
 *
 * 值在 `resources/base|dark/element/color.json` 里，JSON 不能写注释，所以理由记在
 * 这里。画布从冷白 `#F4F6FB`（蓝味）改成暖中性白 `#F7F6F3`，卡片面与描边一起微调；
 * 深色那一族从蓝味深灰改成暖近黑。中性面必须**一起**动：一块蓝味的深灰在纯黑旁边
 * 看不出来，在暖近黑旁边就是一道冷暖接缝，那比两边都冷更难看。
 *
 * 三个令牌**刻意**不跟 Web 端的值：`ok` / `warn` / `danger`。
 * Web 端那三个是"记号"档——它一处都没有直接当文字用，全是
 * `color-mix(… 72%, var(--ink))` 或者边框/底色，另有 `--ok-bg` 一族配套。
 * 而鸿蒙端 `TrustCenterPage` 把 `warn` 直接当 15vp 文字用在白卡片上。把 Web 的
 * `--warn: #B8710A` 搬过来，那一行就从 5.16:1 掉到 3.89:1，低于 AA 的 4.5。
 * 这和 `tokens.css` 里 `--youhuo-blue-deep` / `--youhuo-blue-ink` 分家是同一件事：
 * 一个语义色需要"填充档"和"墨水档"两个值，鸿蒙端只有一个名字，那这个名字必须是
 * 墨水档。同名不等于同值——只有当用途也相同时，同步才是对齐。
 *
 * `--youhuo-blue-shade`（Web 端用来替掉紫色的渐变暗端）没有搬过来：
 * 全工程零个渐变（已 grep 核实），搬过来就是一个没有消费者的令牌，而这个工程刚因为
 * 五个空壳 Adapter 和三个死 Tab 付过代价。紫色本来也从未出现在鸿蒙端。
 */

export class Dim {
  // 8pt 栅格。
  static readonly SPACE_1: number = 4;
  static readonly SPACE_2: number = 8;
  static readonly SPACE_3: number = 12;
  static readonly SPACE_4: number = 16;
  static readonly SPACE_5: number = 20;
  static readonly SPACE_6: number = 24;
  static readonly SPACE_8: number = 32;

  // 圆角。和 Web 端一同从 12/16/22/28 收紧过：28 的卡片读起来像消费级玩具，
  // 而且紧挨着正文时曲线会明显吃掉内容的角。
  static readonly RADIUS_SM: number = 10;
  static readonly RADIUS_MD: number = 14;
  static readonly RADIUS_LG: number = 18;
  static readonly RADIUS_XL: number = 20;

  /**
   * 触控下限。API 26 起系统表单控件从 28vp 提到 32vp，但那是**系统控件**的下限，
   * 不是这个受众的合理值。这里取 48：WCAG 2.2 的目标尺寸下限，也是老人手指在
   * 晃动的公交车上还能稳定命中的尺寸。所有可点区域都不得小于它。
   */
  static readonly TOUCH_MIN: number = 48;

  /**
   * 关键操作那一档（设计稿第 43 节，对应 Web 端 `--tap-key: 56px`）。
   *
   * 本轮之前鸿蒙端只有一档：所有可点区域一律 `TOUCH_MIN`。一档的问题不是"不够大"，
   * 是**没有层级**——一屏上每个东西都同样大的时候，手指不知道该先去哪。
   *
   * 为什么是"点名"而不是"全部按钮 56"：把所有东西放大等于取消层级。Web 端点名了
   * 打字入口、发送、下一件的「查看」和可信页唯一的出口；鸿蒙端对应的是打字入口、
   * 发送、以及照护中心子视图唯一的出口「返回」。麦克风本身 116vp，远大于 56，
   * 不需要这条。
   */
  static readonly TOUCH_KEY: number = 56;

  /** 底部标签栏高度，与"给栏让出的留白"共用同一个常量。 */
  static readonly TABBAR_H: number = 56;

  // 字号。老人端正文比常规 App 大一档，且不参与"紧凑"处理。
  static readonly TEXT_SM: number = 15;
  static readonly TEXT_BODY: number = 18;
  static readonly TEXT_CHAT: number = 21;
  static readonly TEXT_TITLE: number = 26;
  static readonly TEXT_HERO: number = 34;

  /** 对话气泡行高。中文在 1.6 倍行距下才不会挤成一团。 */
  static readonly CHAT_LINE_HEIGHT: number = 34;
}

export class Motion {
  static readonly FAST: number = 120;
  static readonly BASE: number = 200;
  static readonly SHEET: number = 250;

  /**
   * 过阻尼弹簧，不过冲。
   *
   * `springMotion(response, dampingFraction)`，dampingFraction ≥ 1 就不会回弹。
   * 这个取值是抄来的而不是调出来的：`gorhom/react-native-bottom-sheet` 用
   * ζ≈4.6 的过阻尼弹簧并显式 `overshootClamping: true`，`motion-primitives` 用
   * `bounce: 0`。回弹对前庭敏感的人读起来是"不稳"，而会过冲的控件就是会从手指
   * 底下跑掉的控件——对一位 78 岁的用户，这不是观感问题，是能不能按中的问题。
   */
  static readonly SPRING_SETTLE: string = 'springMotion(0.25, 1.1)';

  /** 按下时的即时反馈，比 settle 更快也更硬。 */
  static readonly SPRING_PRESS: string = 'springMotion(0.15, 1.0)';
}
