import { vibrator } from '@kit.SensorServiceKit';
import { BusinessError } from '@kit.BasicServicesKit';

/**
 * 触感反馈。
 *
 * `vibrator` 属于 `@kit.SensorServiceKit`——这一点已经用 SDK 自己的 kit 配置核实过
 * （`ets-loader/kit_configs/@kit.SensorServiceKit.json` 里有 `vibrator` 符号，
 * 指向 `@ohos.vibrator.d.ts`），不再是猜测。`check_arkts.py` 现在会对每一个
 * `@kit.*` import 做同样的核对，写错 kit 会直接失败而不是等到编译。
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
