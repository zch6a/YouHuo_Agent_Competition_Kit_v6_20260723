import { router } from '@kit.ArkUI';
import { ApiClient } from '../services/ApiClient';

@Component
export struct HealthArchivePage {
  @State reportText: string = '健康时间线采用最小必要共享；医学报告只做术语整理，不做诊断。';

  build() {
    Column({ space: 16 }) {
      Row() {
        Text('健康档案').fontSize(30).fontWeight(FontWeight.Bold)
        Blank()
        Button('返回').onClick(() => router.back())
      }.width('100%')
      Text('体检、就医、用药与复查提醒可形成统一时间线，并提供FHIR风格导出适配层。').fontSize(19)
      Button('演示报告归档').onClick(async () => {
        const result = await ApiClient.analyzeMedicalReport('体检日期2026年7月20日，空腹血糖6.2 mmol/L，建议2026年8月20日复查。');
        this.reportText = JSON.stringify(result, null, 2);
      })
      Scroll() { Text(this.reportText).fontSize(16).width('100%') }
        .layoutWeight(1).padding(16).backgroundColor('#F5F7FB').borderRadius(16)
    }.padding(20).width('100%').height('100%')
  }
}
