/**
 * 全景照护中心 —— 「照护」标签页的内容。
 *
 * 这里原先用 `router.pushUrl()` 跳到 SafetyPage 和 HealthArchivePage，是全工程仅
 * 有的两处页面跳转。`router` 已废弃，而且这两个目标页在 main_pages.json 里登记了
 * 却没有 `@Entry`——真按下去是白屏。改成在本标签页内部切换子视图：两个子页本来就
 * 是 `@Component export struct`，直接嵌进来即可，不需要路由。
 */

import { ApiClient } from '../services/ApiClient';
import { Dim } from '../theme/Theme';
import { HealthArchivePage } from './HealthArchivePage';
import { SafetyPage } from './SafetyPage';

@Component
export struct CareHubPage {
  @State resultText: string = '选择一个演示模块。';
  @State busy: boolean = false;
  /** '' = 模块网格；'safety' / 'health' = 子视图。 */
  @State sub: string = '';

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

  @Builder
  private ModuleGrid() {
    Column({ space: Dim.SPACE_4 }) {
      Text('以下能力均通过后端权限、同意和安全边界控制；真机位置、相机和推送仍需对齐正式 SDK。')
        .fontSize(Dim.TEXT_BODY)
        .lineHeight(28)
        .fontColor($r('app.color.ink_2'))

      Grid() {
        GridItem() {
          Button('情绪隐私信号')
            .width('100%')
            .constraintSize({ minHeight: Dim.TOUCH_MIN })
            .enabled(!this.busy)
            .onClick(() => this.run(() => ApiClient.analyzeEmotion('我一个人很孤单，没人陪')))
        }
        GridItem() {
          Button('体检报告整理')
            .width('100%')
            .constraintSize({ minHeight: Dim.TOUCH_MIN })
            .enabled(!this.busy)
            .onClick(() => this.run(() => ApiClient.analyzeMedicalReport(
              '血压138/86，发现结节，建议2026年8月20日复查')))
        }
        GridItem() {
          Button('药品相互作用')
            .width('100%')
            .constraintSize({ minHeight: Dim.TOUCH_MIN })
            .enabled(!this.busy)
            .onClick(() => this.run(() => ApiClient.checkMedicationInteraction(['华法林', '阿司匹林'])))
        }
        GridItem() {
          Button('月度事务报告')
            .width('100%')
            .constraintSize({ minHeight: Dim.TOUCH_MIN })
            .enabled(!this.busy)
            .onClick(() => this.run(() => ApiClient.monthlyReport()))
        }
        GridItem() {
          Button('能力真实性清单')
            .width('100%')
            .constraintSize({ minHeight: Dim.TOUCH_MIN })
            .enabled(!this.busy)
            .onClick(() => this.run(() => ApiClient.listCapabilities()))
        }
        GridItem() {
          Button('居家与出行安全')
            .width('100%')
            .constraintSize({ minHeight: Dim.TOUCH_MIN })
            .onClick(() => { this.sub = 'safety'; })
        }
        GridItem() {
          Button('健康档案')
            .width('100%')
            .constraintSize({ minHeight: Dim.TOUCH_MIN })
            .onClick(() => { this.sub = 'health'; })
        }
      }
      .columnsTemplate('1fr 1fr')
      .rowsGap(Dim.SPACE_3)
      .columnsGap(Dim.SPACE_3)
      .width('100%')
      .height(220)

      Scroll() {
        Text(this.resultText)
          .fontSize(Dim.TEXT_SM)
          .fontFamily('monospace')
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

  build() {
    Column({ space: Dim.SPACE_4 }) {
      Row({ space: Dim.SPACE_3 }) {
        if (this.sub !== '') {
          Button('返回')
            .constraintSize({ minHeight: Dim.TOUCH_MIN })
            .backgroundColor($r('app.color.surface_3'))
            .fontColor($r('app.color.ink'))
            .onClick(() => { this.sub = ''; })
        }
        Text('全景照护中心')
          .fontSize(Dim.TEXT_TITLE)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink'))
      }.width('100%')

      if (this.sub === 'safety') {
        SafetyPage()
      } else if (this.sub === 'health') {
        HealthArchivePage()
      } else {
        this.ModuleGrid()
      }
    }
    .alignItems(HorizontalAlign.Start)
    .padding(Dim.SPACE_5)
    .width('100%')
    .height('100%')
    .backgroundColor($r('app.color.bg'))
  }
}
