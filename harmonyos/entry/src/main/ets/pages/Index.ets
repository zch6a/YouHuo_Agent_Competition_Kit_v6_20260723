import { router } from '@kit.ArkUI';
import { ApiClient } from '../services/ApiClient';

interface MessageItem {
  role: string;
  text: string;
}

@Entry
@Component
struct Index {
  @State mode: string = 'youhuo';
  @State sessionId: string = '';
  @State inputText: string = '';
  @State busy: boolean = false;
  @State messages: Array<MessageItem> = [
    { role: 'agent', text: '您好，我是优活。您可以直接告诉我想办什么事情。' }
  ];

  aboutToAppear(): void {
    ApiClient.createSession().then((id: string) => this.sessionId = id).catch(() => {
      this.messages.push({ role: 'agent', text: '暂时无法连接服务，请检查局域网地址。' });
    });
  }

  private async send(text?: string): Promise<void> {
    const value = (text ?? this.inputText).trim();
    if (!value || this.busy || !this.sessionId) return;
    this.messages.push({ role: 'user', text: value });
    this.inputText = '';
    this.busy = true;
    try {
      const response = await ApiClient.chat(this.sessionId, value);
      this.mode = response.mode;
      this.messages.push({ role: 'agent', text: response.message });
      // TODO: 接入当前 HarmonyOS SDK 的官方 TTS，让提示自动播报。
    } catch (_) {
      this.messages.push({ role: 'agent', text: '网络暂时不可用，核心离线演示仍可在网页端运行。' });
    } finally {
      this.busy = false;
    }
  }

  build() {
    Column({ space: 14 }) {
      Row() {
        Text(this.mode === 'companion' ? '● 无忧伴陪伴模式' : '● 优活办事模式')
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.mode === 'companion' ? '#C65D00' : '#155ACB')
        Blank()
        Row({ space: 8 }) {
          Button('照护中心').onClick(() => router.pushUrl({ url: 'pages/CareHubPage' }))
          Button('信任中心').onClick(() => router.pushUrl({ url: 'pages/TrustCenterPage' }))
          Button('可信实验室').onClick(() => router.pushUrl({ url: 'pages/AgentTrustLabPage' }))
          Button('决赛导览').onClick(() => router.pushUrl({ url: 'pages/FinalistWalkthroughPage' }))
          Button('子女端').onClick(() => router.pushUrl({ url: 'pages/FamilyPage' }))
        }
      }.width('100%')

      Text(this.mode === 'companion' ? '无忧伴' : '优活')
        .fontSize(48)
        .fontWeight(FontWeight.Bold)

      List({ space: 10 }) {
        ForEach(this.messages, (item: MessageItem) => {
          ListItem() {
            Row() {
              Text(item.text)
                .fontSize(22)
                .lineHeight(34)
                .padding(16)
                .backgroundColor(item.role === 'user' ? '#DDEBFF' : '#F0F2F7')
                .borderRadius(18)
            }.justifyContent(item.role === 'user' ? FlexAlign.End : FlexAlign.Start).width('100%')
          }
        })
      }.layoutWeight(1).width('100%')

      Flex({ wrap: FlexWrap.Wrap }) {
        Button('演示挂号').margin(4).onClick(() => this.send('帮我挂明天下午两点第一医院骨科王医生的号'))
        Button('演示缴费').margin(4).onClick(() => this.send('帮我交水费'))
        Button('设置提醒').margin(4).onClick(() => this.send('提醒我明天上午九点复诊'))
        Button('切换角色').margin(4).onClick(() => this.send(this.mode === 'companion' ? '调用优活' : '调用无忧伴'))
      }.width('100%')

      Row({ space: 8 }) {
        TextInput({ placeholder: '请慢慢说，或输入一句话', text: this.inputText })
          .fontSize(20)
          .layoutWeight(1)
          .onChange((value: string) => this.inputText = value)
        Button(this.busy ? '处理中' : '发送')
          .enabled(!this.busy)
          .onClick(() => this.send())
      }.width('100%')

      // TODO: 使用官方语音识别能力替换 TextInput；保留大按钮作为无障碍备选。
    }
    .padding(20)
    .width('100%')
    .height('100%')
    .backgroundColor(this.mode === 'companion' ? '#FFF6EB' : '#F4F8FF')
  }
}
