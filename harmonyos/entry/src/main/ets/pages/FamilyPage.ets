/**
 * 家属协同台 —— 「家人」标签页的内容。
 *
 * 这个页面一直是完整实现（真实 ApiClient、批准/拒绝接力），但此前全工程没有任何
 * 一处 import 或跳转到它：标签页挂的是 PlaceholderScreen，两行占位文字。评委点开
 * 第二个标签看到的就是那两行。现在由 Index 直接嵌进 TabContent。
 *
 * 因此它不再是 @Entry，也不再有「返回」按钮——标签页之间没有返回这回事。
 */

import { TaskRecord } from '../model/Models';
import { ApiClient } from '../services/ApiClient';
import { Dim } from '../theme/Theme';

@Component
export struct FamilyPage {
  @State tasks: Array<TaskRecord> = [];
  @State statusText: string = '正在读取待办…';

  aboutToAppear(): void {
    this.refresh();
  }

  private async refresh(): Promise<void> {
    try {
      this.tasks = await ApiClient.listTasks();
      this.statusText = `已加载 ${this.tasks.length} 项任务`;
    } catch (_) {
      this.statusText = '无法连接后端';
    }
  }

  private async approve(taskId: string, approvalDigest: string, value: boolean): Promise<void> {
    const result = await ApiClient.approve(taskId, approvalDigest, value);
    this.statusText = result.message;
    await this.refresh();
  }

  build() {
    Column({ space: Dim.SPACE_4 }) {
      Row() {
        Text('家属协同台')
          .fontSize(Dim.TEXT_TITLE)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.ink'))
        Blank()
        Button('刷新')
          .constraintSize({ minHeight: Dim.TOUCH_MIN })
          .onClick(() => this.refresh())
      }.width('100%')

      Text(this.statusText)
        .fontSize(Dim.TEXT_BODY)
        .fontColor($r('app.color.ink_2'))

      List({ space: Dim.SPACE_3 }) {
        ForEach(this.tasks, (task: TaskRecord) => {
          ListItem() {
            Column({ space: Dim.SPACE_2 }) {
              Text(task.summary)
                .fontSize(Dim.TEXT_CHAT)
                .fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.ink'))
              Text(`状态：${task.status}  风险：${task.risk_level}`)
                .fontSize(Dim.TEXT_BODY)
                .fontColor($r('app.color.ink_2'))
              if (task.status === 'awaiting_family_approval') {
                Row({ space: Dim.SPACE_3 }) {
                  Button('确认并接力')
                    .constraintSize({ minHeight: Dim.TOUCH_MIN })
                    .onClick(() => this.approve(task.id, task.approval_digest ?? '', true))
                  Button('拒绝')
                    .constraintSize({ minHeight: Dim.TOUCH_MIN })
                    .backgroundColor($r('app.color.danger'))
                    .onClick(() => this.approve(task.id, task.approval_digest ?? '', false))
                }
              }
            }
            .alignItems(HorizontalAlign.Start)
            .padding(Dim.SPACE_4)
            .width('100%')
            .backgroundColor($r('app.color.surface'))
            .borderRadius(Dim.RADIUS_LG)
          }
        })
      }.layoutWeight(1).width('100%')
    }
    .alignItems(HorizontalAlign.Start)
    .padding(Dim.SPACE_5)
    .width('100%')
    .height('100%')
    .backgroundColor($r('app.color.bg'))
  }
}
