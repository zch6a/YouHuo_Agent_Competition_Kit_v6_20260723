/**
 * 可信 Agent 实验室 —— 「可信」标签页的第二节。
 *
 * 原先是 @Entry 独立页面，但全工程没有任何一处 push 到它。改成可嵌入组件，由
 * TrustTab 的分段切换承载。
 */

import { ApiClient } from '../services/ApiClient';
import { Dim } from '../theme/Theme';

@Component
export struct AgentTrustLabPage {
  @State result: string = '点击下方按钮验证可信 Agent 能力。';
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
    Column({ space: Dim.SPACE_4 }) {
      Text('演示语音共识、目的绑定、可恢复任务和能力边界。高风险动作不会因模型一句话被放行。')
        .fontSize(Dim.TEXT_BODY)
        .lineHeight(30)
        .fontColor($r('app.color.ink_2'))

      Row({ space: Dim.SPACE_3 }) {
        Button('测试语音冲突')
          .constraintSize({ minHeight: Dim.TOUCH_MIN })
          .enabled(!this.busy)
          .onClick(() => this.testVoiceConsensus())
        Button('查看能力真值')
          .constraintSize({ minHeight: Dim.TOUCH_MIN })
          .enabled(!this.busy)
          .onClick(() => this.loadTruth())
      }.width('100%')

      Scroll() {
        Text(this.result)
          .fontSize(Dim.TEXT_BODY)
          .lineHeight(32)
          .padding(Dim.SPACE_4)
          .width('100%')
          .fontColor($r('app.color.ink'))
          .backgroundColor($r('app.color.surface'))
          .borderRadius(Dim.RADIUS_LG)
      }.layoutWeight(1).width('100%')

      Text('说明：当前 ArkTS 工程是接入壳；需在 DevEco Studio 对齐 API 26、签名并真机验证。')
        .fontSize(Dim.TEXT_SM)
        .fontColor($r('app.color.ink_3'))
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .height('100%')
  }
}
