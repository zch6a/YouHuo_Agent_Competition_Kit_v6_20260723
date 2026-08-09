/**
 * 优活 v6 决赛导览 —— 「可信」标签页的第三节。
 *
 * 原先是 @Entry 独立页面，全工程无人 push。改成可嵌入组件：这一页是给评委看的，
 * 而评委能看到的前提是它在标签栏里够得着。
 */

import { ApiClient } from '../services/ApiClient';
import { Dim } from '../theme/Theme';

@Component
export struct FinalistWalkthroughPage {
  @State result: string = '依次点击四个步骤，展示优活 v6 的三项核心创新与竞赛证据。';
  @State busy: boolean = false;

  private async runSemantic(): Promise<void> {
    this.busy = true;
    try {
      const value = await ApiClient.semanticParse('提醒我下周去人民医院复诊');
      this.result = `识别意图：${String(value['intent'])}\n模型是否直接执行：否\n说明：明确"提醒"优先于医学名词，语义输出只作为受约束结构。`;
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
      this.result = `安全决策：${String(authorization['decision'])}\n剥离字段：${String(authorization['stripped_fields'])}\n说明：可信账单与 OCR 金额冲突时，系统要求重新核验，不会静默选值。`;
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
    Column({ space: Dim.SPACE_4 }) {
      Text('聚焦三项创新：认知负荷治理、玻璃盒信任校准、可信/不可信数据冲突防火墙。')
        .fontSize(Dim.TEXT_BODY)
        .lineHeight(30)
        .fontColor($r('app.color.ink_2'))

      Flex({ wrap: FlexWrap.Wrap }) {
        Button('1 语义路由').margin(Dim.SPACE_1)
          .constraintSize({ minHeight: Dim.TOUCH_MIN })
          .enabled(!this.busy).onClick(() => this.runSemantic())
        Button('2 适老交互').margin(Dim.SPACE_1)
          .constraintSize({ minHeight: Dim.TOUCH_MIN })
          .enabled(!this.busy).onClick(() => this.runCognitive())
        Button('3 安全预演').margin(Dim.SPACE_1)
          .constraintSize({ minHeight: Dim.TOUCH_MIN })
          .enabled(!this.busy).onClick(() => this.runPreview())
        Button('4 竞赛证据').margin(Dim.SPACE_1)
          .constraintSize({ minHeight: Dim.TOUCH_MIN })
          .enabled(!this.busy).onClick(() => this.runEvidence())
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

      Text('此页是 ArkTS 接入原型；当前环境未完成 DevEco Studio 编译、签名或 API 26 真机验证。')
        .fontSize(Dim.TEXT_SM)
        .fontColor($r('app.color.ink_3'))
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .height('100%')
  }
}
