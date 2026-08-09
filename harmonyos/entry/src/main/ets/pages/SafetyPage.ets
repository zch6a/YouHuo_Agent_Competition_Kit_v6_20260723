/**
 * 居家与出行安全 —— 「照护」标签页里的一个子视图。
 *
 * 返回由宿主（CareHubPage）提供：这里已经不是一个独立的路由页面，自己带一个
 * `router.back()` 会在标签页内部造出一个不存在的返回栈。
 */

import { ApiClient } from '../services/ApiClient';
import { Dim } from '../theme/Theme';

@Component
export struct SafetyPage {
  @State statusText: string = '位置仅在老人授权后上传；围栏边界精度不足时不自动报警。';

  private async testLocation(outside: boolean): Promise<void> {
    try {
      await ApiClient.configureSafetyPolicy();
      const result = await ApiClient.sendLocation(
        outside ? 39.95 : 39.9042, outside ? 116.45 : 116.3974, 20);
      this.statusText = JSON.stringify(result, null, 2);
    } catch (error) {
      this.statusText = `执行失败：${String(error)}`;
    }
  }

  build() {
    Column({ space: Dim.SPACE_4 }) {
      Text('居家与出行安全')
        .fontSize(Dim.TEXT_CHAT)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink'))
      Text('正式版应接入 Location Kit、Map Kit、Navi Kit 和 Push Kit；本页只验证后端适配与安全策略。')
        .fontSize(Dim.TEXT_BODY)
        .lineHeight(28)
        .fontColor($r('app.color.ink_2'))
      Row({ space: Dim.SPACE_3 }) {
        Button('测试范围内')
          .constraintSize({ minHeight: Dim.TOUCH_MIN })
          .onClick(() => this.testLocation(false))
        Button('测试超出范围')
          .constraintSize({ minHeight: Dim.TOUCH_MIN })
          .onClick(() => this.testLocation(true))
      }
      Scroll() {
        Text(this.statusText)
          .fontSize(Dim.TEXT_SM)
          .fontColor($r('app.color.ink_2'))
          .width('100%')
      }
      .layoutWeight(1)
      .padding(Dim.SPACE_4)
      .backgroundColor($r('app.color.surface_2'))
      .borderRadius(Dim.RADIUS_LG)
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .layoutWeight(1)
  }
}
