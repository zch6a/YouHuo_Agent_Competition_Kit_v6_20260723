import { router } from '@kit.ArkUI';
import { ApiClient } from '../services/ApiClient';

@Component
export struct CareHubPage {
  @State resultText: string = '选择一个演示模块。';
  @State busy: boolean = false;

  private async run(action: () => Promise<Object>): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try {
      const result = await action();
      this.resultText = JSON.stringify(result, null, 2);
    } catch (error) {
      this.resultText = `执行失败：${String(error)}`;
    } finally {
      this.busy = false;
    }
  }

  build() {
    Column({ space: 14 }) {
      Row() {
        Text('优活 v4 全景照护中心').fontSize(30).fontWeight(FontWeight.Bold)
        Blank()
        Button('返回').onClick(() => router.back())
      }.width('100%')

      Text('以下能力均通过后端权限、同意和安全边界控制；真机位置、相机和推送仍需对齐正式SDK。')
        .fontSize(18).lineHeight(28)

      Grid() {
        GridItem() { Button('情绪隐私信号').onClick(() => this.run(() => ApiClient.analyzeEmotion('我一个人很孤单，没人陪'))) }
        GridItem() { Button('体检报告整理').onClick(() => this.run(() => ApiClient.analyzeMedicalReport('血压138/86，发现结节，建议2026年8月20日复查'))) }
        GridItem() { Button('药品相互作用').onClick(() => this.run(() => ApiClient.checkMedicationInteraction(['华法林', '阿司匹林']))) }
        GridItem() { Button('月度事务报告').onClick(() => this.run(() => ApiClient.monthlyReport())) }
        GridItem() { Button('能力真实性清单').onClick(() => this.run(() => ApiClient.listCapabilities())) }
        GridItem() { Button('位置安全页').onClick(() => router.pushUrl({ url: 'pages/SafetyPage' })) }
        GridItem() { Button('健康档案页').onClick(() => router.pushUrl({ url: 'pages/HealthArchivePage' })) }
      }.columnsTemplate('1fr 1fr').rowsGap(12).columnsGap(12).width('100%')

      Scroll() {
        Text(this.resultText).fontSize(16).fontFamily('monospace').width('100%')
      }.layoutWeight(1).padding(14).backgroundColor('#F5F7FB').borderRadius(16)
    }.padding(20).width('100%').height('100%')
  }
}
