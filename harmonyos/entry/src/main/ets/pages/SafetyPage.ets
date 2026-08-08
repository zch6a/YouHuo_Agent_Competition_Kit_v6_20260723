import { router } from '@kit.ArkUI';
import { ApiClient } from '../services/ApiClient';

@Component
export struct SafetyPage {
  @State statusText: string = '位置仅在老人授权后上传；围栏边界精度不足时不自动报警。';

  private async testLocation(outside: boolean): Promise<void> {
    await ApiClient.configureSafetyPolicy();
    const result = await ApiClient.sendLocation(outside ? 39.95 : 39.9042, outside ? 116.45 : 116.3974, 20);
    this.statusText = JSON.stringify(result, null, 2);
  }

  build() {
    Column({ space: 16 }) {
      Row() {
        Text('居家与出行安全').fontSize(30).fontWeight(FontWeight.Bold)
        Blank()
        Button('返回').onClick(() => router.back())
      }.width('100%')
      Text('正式版应接入Location Kit、Map Kit、Navi Kit和Push Kit；本页只验证后端适配与安全策略。').fontSize(18)
      Row({ space: 12 }) {
        Button('测试范围内').onClick(() => this.testLocation(false))
        Button('测试超出范围').onClick(() => this.testLocation(true))
      }
      Scroll() { Text(this.statusText).fontSize(16).width('100%') }
        .layoutWeight(1).padding(16).backgroundColor('#F5F7FB').borderRadius(16)
    }.padding(20).width('100%').height('100%')
  }
}
