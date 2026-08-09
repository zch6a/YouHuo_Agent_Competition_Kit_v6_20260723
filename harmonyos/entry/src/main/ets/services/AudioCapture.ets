import { audio } from '@kit.AudioKit';
import { abilityAccessCtrl, bundleManager, common, Permissions } from '@kit.AbilityKit';
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

/**
 * `requestPermissionsFromUser` 有回调和 Promise 两个重载，类型检查偶尔会把它们交成
 * `void & Promise<…>`，于是 `.authResults` "不存在"。而 `PermissionRequestResult`
 * 本身并没有从 `@ohos.abilityAccessCtrl.d.ts` 导出（已核对 SDK 声明文件）。
 * 所以在本地声明需要的那一部分并显式断言——这是官方文档记录的写法。
 */
interface PermResult {
  authResults: number[];
}

export class AudioCapture {
  private capturer: audio.AudioCapturer | null = null;
  private listener: PcmListener | null = null;
  private starting: boolean = false;

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
      const result = await (
        manager.requestPermissionsFromUser(context, [MIC_PERMISSION]) as Promise<PermResult>
      );
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
    if (this.capturer !== null || this.starting) {
      return true;
    }
    this.starting = true;
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
      capturer.on('readData', (buffer: ArrayBuffer) => {
        // 用局部引用而不是 this.listener：stop() 可能在两帧之间把它置空。
        const sink = this.listener;
        if (sink) {
          sink(buffer);
        }
      });
      await capturer.start();
      this.capturer = capturer;
      return true;
    } catch (err) {
      const error = err as BusinessError;
      console.error(`AudioCapture: 启动失败 ${error.code} ${error.message}`);
      // 半开状态比不开更糟：下一次 start 会以为还在录。
      await this.stop();
      return false;
    } finally {
      this.starting = false;
    }
  }

  /**
   * 停止并释放。
   *
   * 可以重复调用，也可以在从未 start 过时调用——老人会连点、会中途返回、会锁屏，
   * 每一条路径都会走到这里。任何一条路径上没释放，下一次录音就会失败得毫无线索。
   */
  async stop(): Promise<void> {
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
