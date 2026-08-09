/**
 * 设计令牌：尺寸、排版与动效。
 *
 * 颜色不在这里——颜色走 `$r('app.color.*')`，因为只有资源系统能在 `resources/dark/`
 * 里自动换一套值。写死在 ArkTS 常量里的颜色是不会跟着系统深色模式走的。
 *
 * 这些数值和 Web 端 `backend/static/style.css` 的令牌一一对应，两端刻意保持同一套
 * 比例。理由不是整齐，而是这个产品的老人端和家属端会被同一个人在同一天里分别用到
 * 手机浏览器和原生 App 上；两边的按钮不一样大、动效不一样快，用起来就是两个产品。
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
