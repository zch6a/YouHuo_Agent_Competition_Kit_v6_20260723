import { Dim } from '../theme/Theme';

/**
 * 一条对话气泡。
 *
 * `@Reusable` 让列表滚动时复用已有节点而不是重建。这里值得标注的是 `aboutToReuse`
 * 必须把**每一个**参数都重新赋值：漏掉一个，复用到的那个节点就会留着上一条消息的
 * 值——在对话界面里，这表现为一条老人说的话突然显示成助手的回复。
 */
@Reusable
@Component
export struct ChatBubble {
  @State text: string = '';
  @State isUser: boolean = false;

  aboutToReuse(params: Record<string, ESObject>): void {
    this.text = params.text as string;
    this.isUser = params.isUser as boolean;
  }

  build() {
    Row() {
      Text(this.text)
        .fontSize(Dim.TEXT_CHAT)
        .lineHeight(Dim.CHAT_LINE_HEIGHT)
        .fontColor($r('app.color.ink'))
        .padding(Dim.SPACE_4)
        .backgroundColor(this.isUser ? $r('app.color.youhuo_tint') : $r('app.color.surface_2'))
        .borderRadius(Dim.RADIUS_LG)
        // 气泡不铺满整行：读一行 390px 宽的中文，眼睛回到行首会找不到位置。
        .constraintSize({ maxWidth: '82%' })
        .textAlign(TextAlign.Start)
    }
    .width('100%')
    .justifyContent(this.isUser ? FlexAlign.End : FlexAlign.Start)
    .padding({ left: Dim.SPACE_4, right: Dim.SPACE_4, top: Dim.SPACE_1, bottom: Dim.SPACE_1 })
  }
}
