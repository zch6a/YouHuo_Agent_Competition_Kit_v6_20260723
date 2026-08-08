import { router } from '@kit.ArkUI';
import { ApiClient } from '../services/ApiClient';

@Entry
@Component
struct AgentTrustLabPage {
  @State result: string = '点击下方按钮验证 可信 Agent 能力。';
  @State busy: boolean = false;

  private async testVoiceConsensus(): Promise<void> {
    this.busy = true;
    try {
      const value = await ApiClient.resolveVoice([
        { text: '确认办理缴费', confidence: 0.91, engine: 'harmony-asr' },
        { text: '取消不要缴费', confidence: 0.90, engine: 'backup-asr' }
      ], true);
      this.result = `结果：${String(value['status'])}\n意图：${String(value['semantic_intent'])}\n系统没有猜测，而是要求澄清。`;
    } catch (_) {
      this.result = '无法连接后端，请检查 BASE_URL。';
    } finally {
      this.busy = false;
    }
  }

  private async loadTruth(): Promise<void> {
    this.busy = true;
    try {
      const value = await ApiClient.capabilityTruth();
      const items = value['implemented_and_tested'] as Array<string>;
      this.result = items.map((item: string, index: number) => `${index + 1}. ${item}`).join('\n');
    } catch (_) {
      this.result = '能力真值表读取失败。';
    } finally {
      this.busy = false;
    }
  }

  build() {
    Column({ space: 18 }) {
      Row() {
        Button('返回').onClick(() => router.back())
        Text('可信 Agent 实验室').fontSize(30).fontWeight(FontWeight.Bold).margin({ left: 16 })
      }.width('100%')

      Text('演示语音共识、目的绑定、可恢复任务和能力边界。高风险动作不会因模型一句话被放行。')
        .fontSize(20).lineHeight(31)

      Row({ space: 12 }) {
        Button('测试语音冲突').enabled(!this.busy).onClick(() => this.testVoiceConsensus())
        Button('查看能力真值').enabled(!this.busy).onClick(() => this.loadTruth())
      }.width('100%')

      Scroll() {
        Text(this.result)
          .fontSize(20)
          .lineHeight(32)
          .padding(18)
          .width('100%')
          .backgroundColor('#FFFFFF')
          .borderRadius(16)
      }.layoutWeight(1).width('100%')

      Text('说明：当前 ArkTS 工程是接入壳；需在 DevEco Studio 对齐 API 26、签名并真机验证。')
        .fontSize(16).fontColor('#555555')
    }
    .padding(20).width('100%').height('100%').backgroundColor('#F3F7FF')
  }
}
