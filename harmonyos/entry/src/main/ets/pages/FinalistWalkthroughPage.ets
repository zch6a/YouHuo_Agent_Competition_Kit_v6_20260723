import { router } from '@kit.ArkUI';
import { ApiClient } from '../services/ApiClient';

@Entry
@Component
struct FinalistWalkthroughPage {
  @State result: string = '依次点击四个步骤，展示优活 v6 的三项核心创新与竞赛证据。';
  @State busy: boolean = false;

  private async runSemantic(): Promise<void> {
    this.busy = true;
    try {
      const value = await ApiClient.semanticParse('提醒我下周去人民医院复诊');
      this.result = `识别意图：${String(value['intent'])}\n模型是否直接执行：否\n说明：明确“提醒”优先于医学名词，语义输出只作为受约束结构。`;
    } catch (_) { this.result = '连接失败，请检查后端地址。'; } finally { this.busy = false; }
  }

  private async runCognitive(): Promise<void> {
    this.busy = true;
    try {
      const value = await ApiClient.interactionPlan('请确认本月水费126.50元，之后请家人完成支付。', 4);
      const options = value['visible_options'] as Array<string>;
      this.result = `交互模式：${String(value['mode'])}\n本轮选项数：${options.length}\n需要复述确认：${String(value['require_teach_back'])}\n播报：${String(value['speak_text'])}`;
    } catch (_) { this.result = '连接失败，请检查后端地址。'; } finally { this.busy = false; }
  }

  private async runPreview(): Promise<void> {
    this.busy = true;
    try {
      const value = await ApiClient.safePreviewConflict();
      const authorization = value['authorization'] as Record<string, Object>;
      this.result = `安全决策：${String(authorization['decision'])}\n剥离字段：${String(authorization['stripped_fields'])}\n说明：可信账单与OCR金额冲突时，系统要求重新核验，不会静默选值。`;
    } catch (_) { this.result = '连接失败，请检查后端地址。'; } finally { this.busy = false; }
  }

  private async runEvidence(): Promise<void> {
    this.busy = true;
    try {
      const value = await ApiClient.competitionEvidence();
      const stories = value['top_three_story'] as Array<string>;
      this.result = `三项主叙事：\n1. ${stories[0]}\n2. ${stories[1]}\n3. ${stories[2]}\n\n注意：真机、真实用户与正式平台证据仍须线下补齐。`;
    } catch (_) { this.result = '连接失败，请检查后端地址。'; } finally { this.busy = false; }
  }

  build() {
    Column({ space: 16 }) {
      Row() {
        Button('返回').onClick(() => router.back())
        Text('优活 v6 决赛导览').fontSize(30).fontWeight(FontWeight.Bold).margin({ left: 16 })
      }.width('100%')

      Text('聚焦三项创新：认知负荷治理、玻璃盒信任校准、可信/不可信数据冲突防火墙。')
        .fontSize(20).lineHeight(31)

      Flex({ wrap: FlexWrap.Wrap }) {
        Button('1 语义路由').margin(5).enabled(!this.busy).onClick(() => this.runSemantic())
        Button('2 适老交互').margin(5).enabled(!this.busy).onClick(() => this.runCognitive())
        Button('3 安全预演').margin(5).enabled(!this.busy).onClick(() => this.runPreview())
        Button('4 竞赛证据').margin(5).enabled(!this.busy).onClick(() => this.runEvidence())
      }.width('100%')

      Scroll() {
        Text(this.result)
          .fontSize(20).lineHeight(32).padding(18).width('100%')
          .backgroundColor('#FFFFFF').borderRadius(16)
      }.layoutWeight(1).width('100%')

      Text('此页是ArkTS接入原型；当前环境未完成DevEco Studio编译、签名或API 26真机验证。')
        .fontSize(16).fontColor('#555555')
    }.padding(20).width('100%').height('100%').backgroundColor('#F4F8FF')
  }
}
