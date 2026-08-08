export interface AgentProgressState {
  taskId: string
  stage: string
  spokenSummary: string
  canPause: boolean
  canCancel: boolean
  needsHuman: boolean
}

/**
 * Maps YouHuo durable tasks to the HarmonyOS device A2A companion UI.
 * The actual AgentExtensionAbility and protocol calls must be generated from
 * the official API 26 template in DevEco Studio and verified on device.
 */
export class AgentCompanionAdapter {
  toStatusCapsule(state: AgentProgressState): Record<string, string | boolean> {
    return {
      title: state.stage,
      summary: state.spokenSummary,
      canPause: state.canPause,
      canCancel: state.canCancel,
      needsHuman: state.needsHuman
    }
  }
}
