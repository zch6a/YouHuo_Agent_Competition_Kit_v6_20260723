import { vibrator } from '@kit.SensorServiceKit';
import { BusinessError } from '@kit.BasicServicesKit';

/**
 * 触感反馈。
 *
 * ⚠️ 这个文件存在的理由是**隔离一个我没能离线核实的 import**。
 *
 * 这台开发机上没有装 HarmonyOS SDK，所以 `vibrator` 属于 `@kit.SensorServiceKit`
 * 还是 `@kit.BasicServicesKit`，我无法用编译器确认——两者在不同资料里都出现过。
 * 错的 import 是编译错误而不是运行时错误，try/catch 兜不住。
 *
 * 所以全工程只有这一行 import 碰它。在 DevEco Studio 里首次编译时如果报
 * "Cannot find name 'vibrator'"，只需把上面第一行换成：
 *
 *     import { vibrator } from '@kit.BasicServicesKit';
 *
 * 其余代码一行都不用动。把它写在这里，而不是让调用方各自 import，是为了让这个
 * 待核实项只有一个位置、并且写着为什么。
 *
 * `module.json5` 需要 `ohos.permission.VIBRATE`（system_grant，无需运行时申请）。
 */
export class Haptics {
  /**
   * 轻触。失败一律静默：不是所有设备都有马达，而没有震动完全不影响按钮可用；
   * 为此弹一个错误提示，才是真的把一个不存在的问题变成故障。
   */
  static tap(): void {
    try {
      vibrator.startVibration(
        { type: 'preset', effectId: 'haptic.clock.timer', count: 1 },
        { usage: 'touch' },
        (error: BusinessError) => {
          if (error) {
            console.info(`Haptics: 设备无震动能力，忽略 (${error.code})`);
          }
        }
      );
    } catch (err) {
      console.info('Haptics: 震动调用失败，忽略');
    }
  }
}
