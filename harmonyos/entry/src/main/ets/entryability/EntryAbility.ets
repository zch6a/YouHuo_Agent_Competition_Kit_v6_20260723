import { AbilityConstant, UIAbility, Want, common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { ApiClient } from '../services/ApiClient';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(0x0000, 'YouHuo', 'EntryAbility onCreate');
    // 交出 Context，这台设备的演示家庭才能存进 preferences 跨冷启动复用。
    // 不 await：首帧不该等一次磁盘读；ApiClient 内部会把首个请求排在它后面。
    ApiClient.init(this.context as common.UIAbilityContext).catch(() => {
      hilog.warn(0x0000, 'YouHuo', '身份持久化不可用，本次启动使用临时沙箱');
    });
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        hilog.error(0x0000, 'YouHuo', `Failed to load content: ${JSON.stringify(err)}`);
      }
    });
  }
}
