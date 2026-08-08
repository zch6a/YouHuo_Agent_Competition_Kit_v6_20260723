import { router } from '@kit.ArkUI';
import { TaskRecord } from '../model/Models';
import { ApiClient } from '../services/ApiClient';

@Entry
@Component
struct FamilyPage {
  @State tasks: Array<TaskRecord> = [];
  @State statusText: string = '';

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
    Column({ space: 16 }) {
      Row() {
        Button('返回').onClick(() => router.back())
        Text('子女协同中心').fontSize(30).fontWeight(FontWeight.Bold).margin({ left: 16 })
        Blank()
        Button('刷新').onClick(() => this.refresh())
      }.width('100%')

      Text(this.statusText).fontSize(18)

      List({ space: 12 }) {
        ForEach(this.tasks, (task: TaskRecord) => {
          ListItem() {
            Column({ space: 8 }) {
              Text(task.summary).fontSize(22).fontWeight(FontWeight.Bold)
              Text(`状态：${task.status}  风险：${task.risk_level}`).fontSize(17)
              if (task.status === 'awaiting_family_approval') {
                Row({ space: 10 }) {
                  Button('确认并接力').onClick(() => this.approve(task.id, task.approval_digest ?? '', true))
                  Button('拒绝').backgroundColor('#B3261E').onClick(() => this.approve(task.id, task.approval_digest ?? '', false))
                }
              }
            }
            .padding(16)
            .width('100%')
            .backgroundColor('#FFFFFF')
            .borderRadius(16)
          }
        })
      }.layoutWeight(1).width('100%')
    }
    .padding(20)
    .width('100%')
    .height('100%')
    .backgroundColor('#F5F7FB')
  }
}
