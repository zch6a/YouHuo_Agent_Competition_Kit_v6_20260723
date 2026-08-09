import { speechRecognizer } from '@kit.CoreSpeechKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { common } from '@kit.AbilityKit';
import { AudioCapture } from './AudioCapture';

/**
 * 端侧语音识别：把麦克风采集到的 PCM 喂给 Core Speech Kit，回吐文字。
 *
 * ⚠️ **可核实性说明。** 这个文件是全工程唯一 import `@kit.CoreSpeechKit` 的地方。
 * 本机装的是公开的 OpenHarmony SDK，它有 47 个 kit，**不含 Core Speech Kit**——
 * 那是 HarmonyOS 闭源部分。所以 `speechRecognizer` 的符号名和调用形态无法在这台机器
 * 上核对，`check_arkts.py` 也把这个 kit 放进了"已知无法核实"的清单里，而不是假装
 * 检查过。
 *
 * 与之相对，**难的那一半是核实过的**：16kHz/单声道/16bit 的 PCM 采集走
 * `@kit.AudioKit`，那个 kit 在 SDK 里，`createAudioCapturer`、`SAMPLE_RATE_16000`、
 * `CHANNEL_1`、`SAMPLE_FORMAT_S16LE`、`SOURCE_TYPE_VOICE_RECOGNITION`、
 * `on('readData')` 全部逐个对过声明文件。识别端接错了会报错；采集端接错了只会安静地
 * 返回空结果，而后者才是真正难查的那一类。
 *
 * 降级是明确的：拿不到权限、起不了引擎、或者根本没有这个 kit，`start()` 返回 false，
 * 界面回到打字输入并**说明原因**。绝不让一位老人对着一个不会听的麦克风说完一整段话。
 */

export interface SpeechCallbacks {
  /** 识别中的临时结果，用于实时回显——老人看得见字在出来，才知道系统在听。 */
  onPartial: (text: string) => void;
  /** 最终结果。 */
  onFinal: (text: string) => void;
  /** 失败。`reason` 是可以直接念给老人听的一句话。 */
  onError: (reason: string) => void;
}

export class SpeechInput {
  private engine: speechRecognizer.SpeechRecognitionEngine | null = null;
  private capture: AudioCapture = new AudioCapture();
  private sessionId: string = '';
  private running: boolean = false;
  /**
   * `running` 只在 `start()` 的**最后一行**置位，而入口守卫读的是它。两次重叠调用
   * （权限弹窗期间的双击、或 `onFinal → send()` 之后再点一次）会双双越过守卫、
   * 双双走到 `createEngine`，第二次的赋值把第一个引擎变成孤儿——既不 finish 也不
   * shutdown。这个号从入口就领，与 AudioCapture 同一套做法。
   */
  private generation: number = 0;

  isRunning(): boolean {
    return this.running;
  }

  /**
   * 开始听。返回 false 表示这条路走不通，调用方应当立刻退回打字输入。
   *
   * 顺序是刻意的：先要权限，再起引擎，最后才开麦克风。反过来会出现"已经在录音了
   * 才发现没有权限"，那一小段录音既没用也不该存在。
   */
  async start(context: common.UIAbilityContext, callbacks: SpeechCallbacks): Promise<boolean> {
    if (this.running || this.engine !== null) {
      return true;
    }
    const mine = ++this.generation;

    if (!await AudioCapture.ensurePermission(context)) {
      // 系统在用户拒绝一次后不再弹窗，所以这里不重试，直接说明。
      callbacks.onError('还没有麦克风权限，您可以先打字，或者在设置里打开麦克风。');
      return false;
    }

    try {
      this.engine = await speechRecognizer.createEngine({
        language: 'zh-CN',
        online: 0,          // 0 = 端侧。陪伴与办事内容不出设备。
      });
    } catch (err) {
      const error = err as BusinessError;
      console.error(`SpeechInput: 引擎创建失败 ${error.code} ${error.message}`);
      callbacks.onError('这台设备暂时不能听写，您可以先打字。');
      return false;
    }
    if (mine !== this.generation) {
      // 建引擎期间有人要求停止：立刻还回去，不要留一个没人管的引擎。
      await this.stop();
      return false;
    }

    this.sessionId = `asr_${Date.now()}`;
    this.engine.setListener({
      onStart: (_sessionId: string, _eventMessage: string) => {},
      onEvent: (_sessionId: string, _eventCode: number, _eventMessage: string) => {},
      onResult: (_sessionId: string, result: speechRecognizer.SpeechRecognitionResult) => {
        if (result.isFinal) {
          callbacks.onFinal(result.result);
        } else {
          callbacks.onPartial(result.result);
        }
      },
      // 这两个回调可能在 `start()` 还没跑完时就触发。`stop()` 会把号作废，
      // 下面两个检查点会让 `start()` 自行收尾——否则会出现"麦克风开着、引擎已死、
      // writeAudio 永远静默无效"的状态，而 isRunning() 还报 true。
      // 加 catch：浮空的 Promise 拒绝会被吞掉。
      onComplete: (_sessionId: string, _eventMessage: string) => {
        this.stop().catch(() => {});
      },
      onError: (_sessionId: string, errorCode: number, errorMessage: string) => {
        console.error(`SpeechInput: 识别错误 ${errorCode} ${errorMessage}`);
        callbacks.onError('刚才没听清，您再说一遍好吗？');
        this.stop().catch(() => {});
      },
    });

    try {
      this.engine.startListening({
        sessionId: this.sessionId,
        audioInfo: {
          audioType: 'pcm',
          sampleRate: 16000,
          soundChannel: 1,
          sampleBit: 16,
        },
      });
    } catch (err) {
      const error = err as BusinessError;
      console.error(`SpeechInput: startListening 失败 ${error.code}`);
      callbacks.onError('语音功能没能启动，您可以先打字。');
      await this.stop();
      return false;
    }

    const started = await this.capture.start((chunk: ArrayBuffer) => {
      // 把每一帧原样转给识别引擎。不缓冲、不重采样——采集端已经按引擎要求的格式
      // 配好了，在这里再动一次只会引入新的出错方式。
      try {
        this.engine?.writeAudio(this.sessionId, new Uint8Array(chunk));
      } catch (err) {
        console.error('SpeechInput: writeAudio 失败');
      }
    });
    if (!started) {
      callbacks.onError('打不开麦克风，您可以先打字。');
      await this.stop();
      return false;
    }
    if (mine !== this.generation) {
      await this.stop();
      return false;
    }

    this.running = true;
    return true;
  }

  /** 停止。可重复调用，也可以在从未 start 过时调用。 */
  async stop(): Promise<void> {
    // 先作废号码：进行中的 start() 会在下一个检查点自行收尾。
    this.generation++;
    this.running = false;
    await this.capture.stop();
    const engine = this.engine;
    this.engine = null;
    if (engine === null) {
      return;
    }
    try {
      engine.finish(this.sessionId);
    } catch (err) {
      // 没在识别时 finish 会抛，这不是错误。
    }
    try {
      engine.shutdown();
    } catch (err) {
      const error = err as BusinessError;
      console.error(`SpeechInput: shutdown 失败 ${error.code}`);
    }
  }
}
