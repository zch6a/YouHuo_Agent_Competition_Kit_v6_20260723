import { Haptics } from '../services/Haptics';
import { Dim, Motion } from '../theme/Theme';

/**
 * 麦克风按钮。
 *
 * 原来的原生端没有这个控件——整页只有一个 TextInput。一个语音助手把主控件做成
 * 输入框，等于要求一位可能不会拼音、看不清小键盘的老人先学会打字，才能用上"说
 * 一句话就办事"的产品。这个按钮是整个老人端的主控件，因此它是页面上最大的东西。
 *
 * 三件事是刻意的：
 *
 * 1. **不做"按住说话"。** 长按需要持续用力，帕金森、关节炎和握力下降都会让手在
 *    中途松开，而松开就等于话说到一半被切断。这里是点一下开始、再点一下结束，
 *    两个动作都不需要维持。
 * 2. **按下的反馈是缩小而不是放大。** 放大会让按钮边缘从手指底下涨出去，看起来
 *    像没按中；缩小是"我收到了"。
 * 3. **状态有三条通道**：颜色、图标、以及按钮下方那行字。只靠颜色的状态，对色觉
 *    障碍者和在阳光下看屏幕的人来说就是没有状态。
 */
@Component
export struct MicButton {
  /** 是否正在听。由父组件持有，因为发送流程也要读它。 */
  @Prop listening: boolean;
  /** 处理中时禁用，避免连点发出两次请求。 */
  @Prop busy: boolean;
  /**
   * 当前角色配色（办事=蓝，陪伴=橙）。
   * 类型是 Resource 而不是 ResourceColor：后者是联合类型，`@Prop` 对联合类型做
   * 深拷贝时的行为在严格模式下不稳定，而这里传进来的永远是 `$r()`。
   */
  @Prop accent: Resource;

  onToggle: () => void = () => {};

  @State private pressed: boolean = false;

  build() {
    Column({ space: Dim.SPACE_3 }) {
      Stack() {
        // 正在听时的外圈。不是装饰：它让"我在录音"在余光里也看得见。
        if (this.listening) {
          Circle()
            .width(148)
            .height(148)
            .fill(this.accent)
            .opacity(0.16)
        }

        Button() {
          SymbolGlyph($r('sys.symbol.mic_fill'))
            .fontSize(46)
            .fontColor([$r('app.color.ink_invert')])
        }
        .type(ButtonType.Circle)
        .width(116)
        .height(116)
        .backgroundColor(this.accent)
        .enabled(!this.busy)
        // 按下缩到 92%，用过阻尼弹簧回位——不过冲，所以按钮不会从手指底下弹开。
        .scale({ x: this.pressed ? 0.92 : 1.0, y: this.pressed ? 0.92 : 1.0 })
        .animation({ duration: Motion.FAST, curve: Motion.SPRING_PRESS })
        // 无障碍名随状态变化，读屏软件才能报出"正在听"而不是永远的"麦克风"。
        .accessibilityText(this.listening ? '正在听，点一下结束说话' : '点一下开始说话')
        .accessibilityLevel('yes')
        .onTouch((event: TouchEvent) => {
          if (event.type === TouchType.Down) {
            this.pressed = true;
          } else if (event.type === TouchType.Up || event.type === TouchType.Cancel) {
            this.pressed = false;
          }
        })
        .onClick(() => {
          Haptics.tap();
          this.onToggle();
        })
      }
      .width(148)
      .height(148)

      // 第三条通道：把状态直接写出来。
      Text(this.busy ? '正在为您办…' : (this.listening ? '我在听，说完再点一下' : '按一下，然后慢慢说'))
        .fontSize(Dim.TEXT_BODY)
        .fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.ink_2'))
    }
    .width('100%')
  }
}
