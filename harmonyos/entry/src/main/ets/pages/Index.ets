import { window } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';
import { ApiClient } from '../services/ApiClient';
import { SpeechInput } from '../services/SpeechInput';
import { ChatResponse } from '../model/Models';
import { MessageItem, MessageSource } from '../model/MessageSource';
import { ChatBubble } from '../components/ChatBubble';
import { MicButton } from '../components/MicButton';
import { Dim, Motion } from '../theme/Theme';
import { FamilyPage } from './FamilyPage';
import { CareHubPage } from './CareHubPage';
import { TrustCenterPage } from './TrustCenterPage';
import { AgentTrustLabPage } from './AgentTrustLabPage';
import { FinalistWalkthroughPage } from './FinalistWalkthroughPage';

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
  private speech: SpeechInput = new SpeechInput();
  /** 正在启动语音（权限弹窗可能停留数秒）。与 `listening` 分开，见 toggleListening。 */
  private startingVoice: boolean = false;
  /** 持有窗口引用才能反注册监听；不反注册，闭包会一直抓着这个页面。 */
  private win: window.Window | null = null;
  private insetListener: ((data: window.AvoidAreaOptions) => void) | null = null;

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
      // 存下 win 和回调本身：`off` 需要它们，而匿名回调是取消不掉的。
      this.win = win;
      this.insetListener = (data: window.AvoidAreaOptions): void => {
        if (data.type === window.AvoidAreaType.TYPE_SYSTEM) {
          apply(data.area);
        }
      };
      win.on('avoidAreaChange', this.insetListener);
    }).catch(() => {
      // 拿不到窗口就保持 0：宁可少让一点位，也不要凭空加一段谁都解释不了的留白。
    });
  }

  private stopWatchingInsets(): void {
    if (this.win !== null && this.insetListener !== null) {
      try {
        this.win.off('avoidAreaChange', this.insetListener);
      } catch (err) {
        // 没注册成功过就取消注册会抛，这不是错误。
      }
    }
    this.win = null;
    this.insetListener = null;
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
   * 语音输入开关。真的会听。
   *
   * 走 `SpeechInput`：`@kit.AudioKit` 采 16kHz/单声道/16bit PCM，喂给 Core Speech Kit
   * 端侧识别。识别中的临时结果直接回显到输入框——老人看得见字在一个一个出来，才知道
   * 系统真的在听；一个只会变色的麦克风，和一个坏掉的麦克风在体验上没有区别。
   *
   * 任何一步失败都退回打字，并**说明原因**，而不是留下一个安静地什么也不做的按钮。
   */
  private async toggleListening(): Promise<void> {
    if (this.busy) {
      return;
    }
    if (this.listening) {
      this.listening = false;
      await this.speech.stop();
      // 松手时把已经听到的内容直接发出去，不用老人再找一次发送键。
      if (this.inputText.trim()) {
        await this.send();
      }
      return;
    }

    const context = this.getUIContext().getHostContext() as common.UIAbilityContext | undefined;
    if (!context) {
      // getHostContext() 的返回类型是 `Context | undefined`。不判空的话
      // undefined 会一路传到 requestPermissionsFromUser 抛出，然后被采集层的
      // catch 吞成"还没有麦克风权限"——一句**错误**的解释。
      this.messages.append('agent', '这台设备暂时不能听写，您可以先打字。');
      this.scrollToLatest();
      return;
    }
    // `starting` 与 `listening` 分开：`listening` 是给界面看的状态，
    // 而权限弹窗会让下面这个 await 停留好几秒。原来在 await **之前**就把
    // listening 置 true，于是第二次点击看到 true、把它改回 false、await 一个还没
    // 开始的 stop()；第一次点击随后拿到权限、打开麦克风并返回成功。
    // 最终状态是**麦克风在录、按钮显示未开启、读屏念的是"点一下开始说话"**。
    // 对这个受众这是隐私缺陷，不是界面瑕疵。
    if (this.startingVoice) {
      return;
    }
    this.startingVoice = true;
    const ok = await this.speech.start(context, {
      onPartial: (text: string) => {
        this.inputText = text;
      },
      onFinal: (text: string) => {
        this.inputText = text;
        this.listening = false;
        // 识别结束不等于麦克风已关。不显式停，采集器会一直录到引擎自己
        // 触发 onComplete 为止——同样是"麦克风开着、指示灯灭着"。
        this.speech.stop().catch(() => {});
        this.send();
      },
      onError: (reason: string) => {
        this.listening = false;
        // 用对话气泡说，而不是一个 Toast：Toast 会在老人抬头看之前消失。
        this.messages.append('agent', reason);
        this.scrollToLatest();
      },
    });
    // 只有在 await 之后才把状态告诉界面——它现在反映的是真实情况。
    this.listening = ok;
    this.startingVoice = false;
  }

  /** 无论从哪条路径离开对话屏，麦克风都必须关掉。 */
  private async releaseVoice(): Promise<void> {
    this.listening = false;
    this.startingVoice = false;
    await this.speech.stop();
  }

  onPageHide(): void {
    // 按 Home 键、锁屏、被其它页面覆盖——`aboutToDisappear` 在这些情况下都不触发，
    // 只有页面被销毁时才会。少了这一句，老人按下 Home 之后麦克风还在录。
    this.releaseVoice().catch(() => {});
  }

  aboutToDisappear(): void {
    // 页面离开时一定要释放麦克风。漏掉这一句，下一次录音会失败得毫无线索。
    // 框架不会等这个 Promise，所以显式 catch，别让拒绝被静默吞掉。
    this.releaseVoice().catch(() => {});
    this.stopWatchingInsets();
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
      //
      // 打字入口和发送键走 `TOUCH_KEY`（56）而不是 `TOUCH_MIN`（48）。这两个是设计稿
      // 第 43 节点名的关键操作：麦克风之外，它们是这一屏唯一的两个出口。原先整屏
      // 一律 48，等于告诉手指"这里每个东西都一样重要"——而在一个语音产品里，
      // 打字是退路，退路必须比旁边那些次要按钮更好按中，否则语音失败时人就卡住了。
      Row({ space: Dim.SPACE_2 }) {
        TextInput({ placeholder: '也可以打字', text: $$this.inputText })
          .fontSize(Dim.TEXT_BODY)
          .height(Dim.TOUCH_KEY)
          .layoutWeight(1)
          .borderRadius(Dim.RADIUS_MD)
          .backgroundColor($r('app.color.surface'))
          .onSubmit(() => this.send())

        Button(this.busy ? '稍等' : '发送')
          .fontSize(Dim.TEXT_BODY)
          .fontWeight(FontWeight.Bold)
          .height(Dim.TOUCH_KEY)
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
        FamilyPage()
      }.tabBar(this.TabItem(1, '家人', $r('sys.symbol.person')))

      TabContent() {
        CareHubPage()
      }.tabBar(this.TabItem(2, '照护', $r('sys.symbol.bell')))

      TabContent() {
        TrustTab()
      }.tabBar(this.TabItem(3, '可信', $r('sys.symbol.checkmark')))
    }
    .barHeight(Dim.TABBAR_H + this.bottomInset)
    .scrollable(false)   // 误触横滑不该换页：这个受众滑动时手抖得比想象中多
    .onChange((index: number) => {
      this.tabIndex = index;
      // 切到家人/照护/可信时，Index 这个 struct 还活着，`aboutToDisappear`
      // 不会触发——麦克风会在一个连录音指示都没有的屏幕上继续录。
      if (index !== 0) {
        this.releaseVoice().catch(() => {});
      }
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

/**
 * 「可信」标签页：三节内容用分段切换，而不是三个够不着的路由页面。
 *
 * 这三节此前都是写好的 @Entry 页面，登记在 main_pages.json 里，却没有任何一处
 * push 到它们——`ApiClient` 21 个 public 方法里有 16 个因此在运行时永远发不出去。
 */
@Component
struct TrustTab {
  @State section: number = 0;

  // 选中态的填充用 `youhuo_blue_deep` 而不是 `youhuo_blue`。
  //
  // 这不是配色偏好，是量出来的：白字（`ink_invert`）压在品牌蓝 #4A90D9 上只有
  // 3.34:1，而这行分段标签是小字号，AA 要求 4.5。换成 #2F6FB5 是 5.17:1。
  // 全工程其它填充控件（发送键、麦克风）本来就用 `*_deep`，这一处是唯一的例外——
  // 既是对比度缺陷，也是不一致。
  //
  // 会漏这么久的原因和 tokens.css 里记的那次一样：对比度审计只盯文字颜色令牌，
  // 而这里错的是**背景**令牌，前景是对的。`youhuo_blue` 因此不再有消费者，
  // 但令牌保留——它是品牌主色，删掉会让下一个人以为这个产品没有主色。
  @Builder
  private SegmentButton(index: number, label: string) {
    Button(label)
      .layoutWeight(1)
      .constraintSize({ minHeight: Dim.TOUCH_MIN })
      .backgroundColor(this.section === index
        ? $r('app.color.youhuo_blue_deep') : $r('app.color.surface'))
      .fontColor(this.section === index
        ? $r('app.color.ink_invert') : $r('app.color.ink_2'))
      .fontWeight(this.section === index ? FontWeight.Bold : FontWeight.Medium)
      .onClick(() => { this.section = index; })
  }

  build() {
    Column({ space: Dim.SPACE_4 }) {
      Text('可信智能体实验室')
        .fontSize(Dim.TEXT_TITLE)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.ink'))

      Row({ space: Dim.SPACE_2 }) {
        this.SegmentButton(0, '工具治理')
        this.SegmentButton(1, '实验室')
        this.SegmentButton(2, '决赛导览')
      }.width('100%')

      if (this.section === 0) {
        TrustCenterPage()
      } else if (this.section === 1) {
        AgentTrustLabPage()
      } else {
        FinalistWalkthroughPage()
      }
    }
    .alignItems(HorizontalAlign.Start)
    .padding(Dim.SPACE_5)
    .width('100%')
    .height('100%')
    .backgroundColor($r('app.color.bg'))
  }
}
