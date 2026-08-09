import { audio } from '@kit.AudioKit';
// `PermissionRequestResult` 是**顶层导出**（@ohos.abilityAccessCtrl.d.ts:710），
// 不是 abilityAccessCtrl 命名空间的成员——命名空间在 :688 就闭合了。所以只能具名
// 导入，写成 `abilityAccessCtrl.PermissionRequestResult` 编译不过。
import {
  abilityAccessCtrl, bundleManager, common, Permissions, PermissionRequestResult,
} from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';

/**
 * 麦克风采集：16kHz / 单声道 / 16bit 小端 PCM。
 *
 * 这些参数不是随便选的，是 Core Speech Kit 端侧识别唯一接受的格式。采集这一步做错，
 * 识别端只会返回空结果，而且不会告诉你为什么——所以这里把格式写死，而不是交给调用方。
 *
 * 几处刻意的选择：
 *
 * * **`SOURCE_TYPE_VOICE_RECOGNITION` 而不是 `SOURCE_TYPE_MIC`。** 前者会启用为语音
 *   识别调校过的回声消除和降噪；后者是原始采集。对着电视说话的独居老人，这个差别
 *   就是能不能识别出来的差别。
 * * **`on('readData')` 回调式，不轮询。** 音频线程把缓冲区推给我们，漏一帧就是丢一个
 *   字；主动轮询在 UI 卡顿时必然丢帧。
 * * **`stop()` 一定要能重复调用。** 老人会连点、会在识别中途按返回、会锁屏。任何一条
 *   路径上没释放采集器，下一次录音就会直接失败，而且失败得毫无线索。
 *
 * 权限：`ohos.permission.MICROPHONE` 是 user_grant，必须运行时申请，而且
 * `module.json5` 里要写 reason 和 usedScene。
 */

export type PcmListener = (chunk: ArrayBuffer) => void;

const MIC_PERMISSION: Permissions = 'ohos.permission.MICROPHONE';


export class AudioCapture {
  private capturer: audio.AudioCapturer | null = null;
  private listener: PcmListener | null = null;
  /**
   * 每次 `start()` 领一个号，`stop()` 把号作废。
   *
   * 只有一个 `starting` 布尔量是不够的：它能挡住重入的 `start()`，却挡不住
   * `stop()` 在 `start()` 的两个 await 之间进来。那时 `this.capturer` 还是 null，
   * `stop()` 直接返回，随后 `start()` 把麦克风打开——**在停止请求之后**。
   * 这正是老人在权限弹窗上按返回时走的路径。
   */
  private generation: number = 0;

  /** 是否正在采集。UI 用它决定按钮状态，不要自己另存一份。 */
  isCapturing(): boolean {
    return this.capturer !== null;
  }

  /**
   * 申请麦克风权限。
   *
   * 返回 false 时**不要**反复弹窗：系统在用户拒绝一次后不再展示，连续调用只会得到
   * 一串静默失败，而老人会以为是自己按错了。这时应当在界面上给出文字说明。
   */
  static async ensurePermission(context: common.UIAbilityContext): Promise<boolean> {
    const manager = abilityAccessCtrl.createAtManager();
    try {
      const info = await bundleManager.getBundleInfoForSelf(
        bundleManager.BundleFlag.GET_BUNDLE_INFO_WITH_APPLICATION
      );
      const granted = manager.checkAccessTokenSync(info.appInfo.accessTokenId, MIC_PERMISSION);
      if (granted === abilityAccessCtrl.GrantStatus.PERMISSION_GRANTED) {
        return true;
      }
      // 两参重载唯一解析到 Promise 版本，不需要断言。`PermissionRequestResult`
      // 是从 `@ohos.abilityAccessCtrl.d.ts` 顶层导出的（此前这里注释说它没导出，
      // 那句话是错的，已按 SDK 声明核实）。authResults[0] === 0 表示已授权。
      const result: PermissionRequestResult =
        await manager.requestPermissionsFromUser(context, [MIC_PERMISSION]);
      return result.authResults.length > 0 && result.authResults[0] === 0;
    } catch (err) {
      const error = err as BusinessError;
      console.error(`AudioCapture: 权限检查失败 ${error.code} ${error.message}`);
      return false;
    }
  }

  /**
   * 开始采集。每读到一段 PCM 就回调一次。
   *
   * 重复调用是安全的（已在采集就直接返回 true），因为老人连点是常态而不是异常。
   */
  async start(listener: PcmListener): Promise<boolean> {
    if (this.capturer !== null) {
      return true;
    }
    const mine = ++this.generation;
    this.listener = listener;
    try {
      const options: audio.AudioCapturerOptions = {
        streamInfo: {
          samplingRate: audio.AudioSamplingRate.SAMPLE_RATE_16000,
          channels: audio.AudioChannel.CHANNEL_1,
          sampleFormat: audio.AudioSampleFormat.SAMPLE_FORMAT_S16LE,
          encodingType: audio.AudioEncodingType.ENCODING_TYPE_RAW,
        },
        capturerInfo: {
          source: audio.SourceType.SOURCE_TYPE_VOICE_RECOGNITION,
          capturerFlags: 0,
        },
      };
      const capturer = await audio.createAudioCapturer(options);
      // **立刻**登记，不要等 start() 成功。
      //
      // 原来是在 `await capturer.start()` 之后才赋值，于是 start() 一抛错，这个
      // 持有原生音频流的采集器就永远留在那里——`stop()` 只看 this.capturer，
      // 看到 null 直接返回，局部变量在 catch 里甚至不在作用域内。
      // 而 start() 失败是常态不是意外：音频焦点被抢、别的应用在用麦克风、来电。
      // 每失败一次泄漏一个，直到 createAudioCapturer 本身开始失败。
      this.capturer = capturer;
      if (mine !== this.generation) {
        await this.stop();
        return false;
      }
      capturer.on('readData', (buffer: ArrayBuffer) => {
        // 用局部引用而不是 this.listener：stop() 可能在两帧之间把它置空。
        const sink = this.listener;
        if (sink) {
          sink(buffer);
        }
      });
      await capturer.start();
      if (mine !== this.generation) {
        // 启动期间有人要求停止：立刻还回去，而不是把麦克风留着。
        await this.stop();
        return false;
      }
      return true;
    } catch (err) {
      const error = err as BusinessError;
      console.error(`AudioCapture: 启动失败 ${error.code} ${error.message}`);
      // 半开状态比不开更糟：下一次 start 会以为还在录。
      await this.stop();
      return false;
    }
  }

  /**
   * 停止并释放。
   *
   * 可以重复调用，也可以在从未 start 过时调用——老人会连点、会中途返回、会锁屏，
   * 每一条路径都会走到这里。任何一条路径上没释放，下一次录音就会失败得毫无线索。
   */
  async stop(): Promise<void> {
    // 先作废号码：进行中的 start() 会在下一个检查点看到号变了，自行释放。
    this.generation++;
    const capturer = this.capturer;
    this.capturer = null;
    this.listener = null;
    if (capturer === null) {
      return;
    }
    try {
      capturer.off('readData');
    } catch (err) {
      // 没注册过就取消注册会抛，这不是错误。
    }
    try {
      await capturer.stop();
    } catch (err) {
      const error = err as BusinessError;
      console.info(`AudioCapture: stop 失败（继续释放）${error.code}`);
    }
    try {
      await capturer.release();
    } catch (err) {
      const error = err as BusinessError;
      console.error(`AudioCapture: release 失败 ${error.code} ${error.message}`);
    }
  }
}
