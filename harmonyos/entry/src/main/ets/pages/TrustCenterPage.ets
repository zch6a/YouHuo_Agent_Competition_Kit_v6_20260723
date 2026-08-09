/**
 * 工具治理清单 —— 「可信」标签页的第一节。
 *
 * 与 FamilyPage 同样的处境：实现是完整的，但此前无人引用。现在由 TrustTab 嵌入。
 */

import { ApiClient } from '../services/ApiClient';
import { Dim } from '../theme/Theme';

interface ToolInfo {
  name: string;
  purpose: string;
  risk_level: number;
  reversible: boolean;
}

@Component
export struct TrustCenterPage {
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
      this.statusText = '无法连接后端；请检查 BASE_URL 和令牌。';
    }
  }

  build() {
    Column({ space: Dim.SPACE_4 }) {
      Text('这里展示 Agent 能做什么、需要谁确认，以及为什么不能静默执行高风险操作。')
        .fontSize(Dim.TEXT_BODY)
        .lineHeight(30)
        .fontColor($r('app.color.ink_2'))
      Text(this.statusText)
        .fontSize(Dim.TEXT_SM)
        .fontColor($r('app.color.ink_3'))

      List({ space: Dim.SPACE_3 }) {
        ForEach(this.tools, (tool: ToolInfo) => {
          ListItem() {
            Column({ space: Dim.SPACE_2 }) {
              Text(tool.name)
                .fontSize(Dim.TEXT_CHAT)
                .fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.ink'))
              Text(tool.purpose)
                .fontSize(Dim.TEXT_BODY)
                .fontColor($r('app.color.ink_2'))
              Text(`风险等级：${tool.risk_level}｜${tool.reversible ? '可撤销' : '不可保证撤销'}`)
                .fontSize(Dim.TEXT_SM)
                .fontColor(tool.reversible ? $r('app.color.ink_3') : $r('app.color.warn'))
            }
            .alignItems(HorizontalAlign.Start)
            .padding(Dim.SPACE_4)
            .width('100%')
            .backgroundColor($r('app.color.surface'))
            .borderRadius(Dim.RADIUS_LG)
          }
        })
      }.layoutWeight(1).width('100%')

      Text('长期记忆必须由老人本人批准；家属不能查看私人陪伴全文。')
        .fontSize(Dim.TEXT_SM)
        .fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.ink_2'))
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .height('100%')
  }
}
