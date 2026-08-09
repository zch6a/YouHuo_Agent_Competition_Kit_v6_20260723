import { window } from '@kit.ArkUI';
import { ApiClient } from '../services/ApiClient';
import { ChatResponse } from '../model/Models';
import { MessageItem, MessageSource } from '../model/MessageSource';
import { ChatBubble } from '../components/ChatBubble';
import { MicButton } from '../components/MicButton';
import { Dim, Motion } from '../theme/Theme';

/**
 * 老人端会话屏。
 *
 * 这一页替换掉的旧版本是一个能跑通的骨架：五个导航按钮挤在标题行里（390px 宽的
 * 屏幕上根本排不下）、用已废弃的 `router`、颜色全是写死的十六进制、消息用 ForEach
 * 整表重建，而且——对一个语音产品来说最要命的——**没有麦克风**，主控件是一个
 * 输入框。
 *
 * 结构上和 Web 端老人端保持一致：会话占满一屏，输入区吸底，其余功能不在这一屏里
 * 争位置。理由和 Web 端相同——滚下去看回答时，语音产品的主操作就离开了屏幕。
 */

const MODE_COMPANION: string = 'companion';

@Entry
@Component
struct Index {
  @State mode: string = 'youhuo';
  @State sessionId: string = '';
  @State inputText: string = '';
  @State busy: boolean = false;
  @State listening: boolean = false;
  @State tabIndex: number = 0;
  /** 底部安全区高度（vp）。手势条会盖住发送按钮，必须实测而不是猜一个常数。 */
  @State bottomInset: number = 0;

  private messages: MessageSource = new MessageSource();
  private scroller: Scroller = new Scroller();

  aboutToAppear(): void {
    this.measureBottomInset();
    this.messages.append('agent', '您好，我是优活。您可以直接说"帮我挂号""查一下水费"，我一次只问一件事。');
    ApiClient.createSession()
      .then((id: string) => {
        this.sessionId = id;
      })
      .catch(() => {
        this.messages.append('agent', '暂时连不上服务。您仍然可以先说话，网络恢复后我会再试一次。');
        this.scrollToLatest();
      });
  }

  /**
   * 实测底部避让高度，而不是写一个常数。
   *
   * 手势条的高度在直板机、折叠屏展开态和平板上都不一样，机型之间也不统一。猜一个
   * 34 在一半设备上要么压着发送按钮，要么在它下面留一条空白。`avoidAreaChange`
   * 一并订阅：折叠屏展开、分屏、旋转都会改变这个值。
   */
  private measureBottomInset(): void {
    const ctx = this.getUIContext().getHostContext();
    if (!ctx) {
      return;
    }
    window.getLastWindow(ctx).then((win: window.Window) => {
      const apply = (area: window.AvoidArea): void => {
        this.bottomInset = this.getUIContext().px2vp(area.bottomRect.height);
      };
      apply(win.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM));
      win.on('avoidAreaChange', (data: window.AvoidAreaOptions) => {
        if (data.type === window.AvoidAreaType.TYPE_SYSTEM) {
          apply(data.area);
        }
      });
    }).catch(() => {
      // 拿不到窗口就保持 0：宁可少让一点位，也不要凭空加一段谁都解释不了的留白。
    });
  }

  /** 当前角色的强调色。走资源而不是常量，深色模式才会自动换一套。 */
  private accent(): Resource {
    return this.mode === MODE_COMPANION ? $r('app.color.wuyou_orange_deep') : $r('app.color.youhuo_blue_deep');
  }

  private scrollToLatest(): void {
    // 动画滚动而不是瞬移：瞬移会让人不确定刚才是新增了内容还是整页跳了。
    this.getUIContext()?.animateTo({ duration: Motion.BASE, curve: Curve.EaseOut }, () => {
      this.scroller.scrollEdge(Edge.Bottom);
    });
  }

  private async send(text?: string): Promise<void> {
    const value = (text ?? this.inputText).trim();
    if (!value || this.busy) {
      return;
    }
    this.messages.append('user', value);
    this.inputText = '';
    this.listening = false;
    this.busy = true;
    this.scrollToLatest();

    // 占位气泡：等待期间屏幕上必须有东西在动，否则老人会以为没按中而再按一次。
    this.messages.append('agent', '正在为您办…');
    this.scrollToLatest();

    try {
      if (!this.sessionId) {
        this.sessionId = await ApiClient.createSession();
      }
      const response: ChatResponse = await ApiClient.chat(this.sessionId, value);
      this.mode = response.mode;
      // 就地改写占位，而不是删一条再加一条——后者会让列表在半秒内跳两次。
      this.messages.replaceLast(response.message);
    } catch (err) {
      this.messages.replaceLast('网络暂时不可用，我没有替您操作任何事情。稍后再说一次就行。');
    } finally {
      this.busy = false;
      this.scrollToLatest();
    }
  }

  /**
   * 语音输入开关。
   *
   * 端侧 ASR 走 Core Speech Kit，需要 PCM/16kHz/单声道/16bit 的音频流；接麦克风
   * 采集是独立的一步，尚未接入。这里**不假装**已经能听：切到 listening 只是把
   * 输入焦点和提示语交给语音路径，真正的识别结果目前仍由输入框提供。
   * 宁可让按钮少做一件事，也不能让一位老人对着一个不会听的麦克风说完一整段话。
   */
  private toggleListening(): void {
    if (this.busy) {
      return;
    }
    this.listening = !this.listening;
  }

  @Builder
  private ConversationScreen() {
    Column() {
      // ---- 顶栏：角色徽标 ----
      Row({ space: Dim.SPACE_2 }) {
        Circle().width(10).height(10).fill(this.accent())
        Text(this.mode === MODE_COMPANION ? '无忧伴 · 陪伴模式' : '优活 · 办事模式')
          .fontSize(Dim.TEXT_BODY)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.accent())
        Blank()
      }
      .width('100%')
      .padding({ left: Dim.SPACE_4, right: Dim.SPACE_4, top: Dim.SPACE_3, bottom: Dim.SPACE_3 })

      // ---- 会话区：唯一可滚动的区域 ----
      List({ space: Dim.SPACE_2, scroller: this.scroller }) {
        LazyForEach(this.messages, (item: MessageItem) => {
          ListItem() {
            ChatBubble({ text: item.text, isUser: item.role === 'user' })
          }
        }, (item: MessageItem) => item.id)
      }
      .layoutWeight(1)
      .width('100%')
      .scrollBar(BarState.Off)
      .cachedCount(3)
      // 顶部插入历史时不让可视内容跳动。
      .maintainVisibleContentPosition(true)

      // ---- 麦克风：屏幕上最大的东西 ----
      MicButton({
        listening: this.listening,
        busy: this.busy,
        accent: this.accent(),
        onToggle: () => this.toggleListening()
      })
        .margin({ top: Dim.SPACE_3, bottom: Dim.SPACE_3 })

      // ---- 输入区：吸底，且始终在安全区之上 ----
      Row({ space: Dim.SPACE_2 }) {
        TextInput({ placeholder: '也可以打字', text: $$this.inputText })
          .fontSize(Dim.TEXT_BODY)
          .height(Dim.TOUCH_MIN)
          .layoutWeight(1)
          .borderRadius(Dim.RADIUS_MD)
          .backgroundColor($r('app.color.surface'))
          .onSubmit(() => this.send())

        Button(this.busy ? '稍等' : '发送')
          .fontSize(Dim.TEXT_BODY)
          .fontWeight(FontWeight.Bold)
          .height(Dim.TOUCH_MIN)
          .constraintSize({ minWidth: 84 })
          .borderRadius(Dim.RADIUS_MD)
          .backgroundColor(this.accent())
          .enabled(!this.busy)
          .onClick(() => this.send())
      }
      .width('100%')
      .padding({
        left: Dim.SPACE_4,
        right: Dim.SPACE_4,
        top: Dim.SPACE_2,
        // 安全区加在这里而不是整页 padding 上：整页加会把定高的会话区顶出屏幕。
        bottom: this.bottomInset + Dim.SPACE_3
      })
    }
    .width('100%')
    .height('100%')
    .backgroundColor($r('app.color.bg'))
  }

  build() {
    // 底部标签栏 —— 和 Web 端同一套信息架构。老人端会话屏是 0 号页，其余是家属和
    // 评委用的。会话屏自己不放标签栏之外的入口，理由见文件头。
    Tabs({ barPosition: BarPosition.End, index: this.tabIndex }) {
      TabContent() {
        this.ConversationScreen()
      }.tabBar(this.TabItem(0, '对话', $r('sys.symbol.mic')))

      TabContent() {
        FamilyTab()
      }.tabBar(this.TabItem(1, '家人', $r('sys.symbol.person')))

      TabContent() {
        CareTab()
      }.tabBar(this.TabItem(2, '照护', $r('sys.symbol.bell')))

      TabContent() {
        TrustTab()
      }.tabBar(this.TabItem(3, '可信', $r('sys.symbol.checkmark')))
    }
    .barHeight(Dim.TABBAR_H + this.bottomInset)
    .scrollable(false)   // 误触横滑不该换页：这个受众滑动时手抖得比想象中多
    .onChange((index: number) => {
      this.tabIndex = index;
    })
    .width('100%')
    .height('100%')
    .backgroundColor($r('app.color.bg'))
    // 铺到屏幕物理边缘，安全区由各屏自己在内部让位。
    .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.BOTTOM])
  }

  // `symbol` 必须是 Resource 而不是字符串：`$r()` 只接受字面量，
  // `$r(\`sys.symbol.${name}\`)` 在 ArkTS 严格模式下是编译错误而不是运行时才发现。
  @Builder
  private TabItem(index: number, label: string, symbol: Resource) {
    Column({ space: 3 }) {
      SymbolGlyph(symbol)
        .fontSize(24)
        .fontColor([this.tabIndex === index ? this.accent() : $r('app.color.ink_3')])
      Text(label)
        .fontSize(13)
        .fontWeight(this.tabIndex === index ? FontWeight.Bold : FontWeight.Medium)
        .fontColor(this.tabIndex === index ? this.accent() : $r('app.color.ink_3'))
    }
    .justifyContent(FlexAlign.Center)
    .width('100%')
    .height(Dim.TABBAR_H)
  }
}

/** 占位分区，保持标签栏四格结构完整；各自的实现在同目录的对应页面里。 */
@Component
struct FamilyTab {
  build() {
    PlaceholderScreen({ title: '家属协同台', hint: '创建待办、查看进度、在支付与身份环节接力确认。' })
  }
}

@Component
struct CareTab {
  build() {
    PlaceholderScreen({ title: '全景照护中心', hint: '循环事务、健康档案、用药安全与位置围栏。' })
  }
}

@Component
struct TrustTab {
  build() {
    PlaceholderScreen({ title: '可信智能体实验室', hint: '语音共识、目的绑定、可恢复 Saga 与完成证明。' })
  }
}

@Component
struct PlaceholderScreen {
  @Prop title: string;
  @Prop hint: string;

  build() {
    Column({ space: Dim.SPACE_3 }) {
      Text(this.title)
        .fontSize(Dim.TEXT_TITLE)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink'))
      Text(this.hint)
        .fontSize(Dim.TEXT_BODY)
        .lineHeight(30)
        .fontColor($r('app.color.ink_2'))
        .textAlign(TextAlign.Center)
    }
    .width('100%')
    .height('100%')
    .padding(Dim.SPACE_6)
    .justifyContent(FlexAlign.Center)
    .backgroundColor($r('app.color.bg'))
  }
}
