import { router } from '@kit.ArkUI';
import { ApiClient } from '../services/ApiClient';

interface ToolInfo {
  name: string;
  purpose: string;
  risk_level: number;
  reversible: boolean;
}

@Entry
@Component
struct TrustCenterPage {
  @State tools: Array<ToolInfo> = [];
  @State statusText: string = '正在读取可信能力边界…';

  aboutToAppear(): void {
    this.refresh();
  }

  private async refresh(): Promise<void> {
    try {
      this.tools = await ApiClient.listTools() as Array<ToolInfo>;
      this.statusText = `已加载 ${this.tools.length} 个受治理工具。写操作仍需服务端确认。`;
    } catch (_) {
      this.statusText = '无法连接后端；请检查BASE_URL和令牌。';
    }
  }

  build() {
    Column({ space: 16 }) {
      Row() {
        Button('返回').onClick(() => router.back())
        Text('优活信任中心').fontSize(30).fontWeight(FontWeight.Bold).margin({ left: 16 })
      }.width('100%')

      Text('这里展示Agent能做什么、需要谁确认，以及为什么不能静默执行高风险操作。')
        .fontSize(20).lineHeight(30)
      Text(this.statusText).fontSize(17)

      List({ space: 12 }) {
        ForEach(this.tools, (tool: ToolInfo) => {
          ListItem() {
            Column({ space: 7 }) {
              Text(tool.name).fontSize(22).fontWeight(FontWeight.Bold)
              Text(tool.purpose).fontSize(18)
              Text(`风险等级：${tool.risk_level}｜${tool.reversible ? '可撤销' : '不可保证撤销'}`).fontSize(16)
            }
            .padding(16).width('100%').backgroundColor('#FFFFFF').borderRadius(16)
          }
        })
      }.layoutWeight(1).width('100%')

      Text('长期记忆必须由老人本人批准；家属不能查看私人陪伴全文。')
        .fontSize(18).fontWeight(FontWeight.Medium)
    }
    .padding(20).width('100%').height('100%').backgroundColor('#F5F7FB')
  }
}
