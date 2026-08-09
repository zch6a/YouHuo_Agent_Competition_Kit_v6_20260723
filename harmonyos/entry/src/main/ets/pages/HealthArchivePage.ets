/**
 * 健康档案 —— 「照护」标签页里的一个子视图。
 *
 * 返回由宿主（CareHubPage）提供，理由同 SafetyPage。
 */

import { ApiClient } from '../services/ApiClient';
import { Dim } from '../theme/Theme';

@Component
export struct HealthArchivePage {
  @State reportText: string = '健康时间线采用最小必要共享；医学报告只做术语整理，不做诊断。';

  private async archive(): Promise<void> {
    try {
      const result = await ApiClient.analyzeMedicalReport(
        '体检日期2026年7月20日，空腹血糖6.2 mmol/L，建议2026年8月20日复查。');
      this.reportText = JSON.stringify(result, null, 2);
    } catch (error) {
      this.reportText = `执行失败：${String(error)}`;
    }
  }

  build() {
    Column({ space: Dim.SPACE_4 }) {
      Text('健康档案')
        .fontSize(Dim.TEXT_CHAT)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink'))
      Text('体检、就医、用药与复查提醒可形成统一时间线，并提供 FHIR 风格导出适配层。')
        .fontSize(Dim.TEXT_BODY)
        .lineHeight(28)
        .fontColor($r('app.color.ink_2'))
      Button('演示报告归档')
        .constraintSize({ minHeight: Dim.TOUCH_MIN })
        .onClick(() => this.archive())
      Scroll() {
        Text(this.reportText)
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
