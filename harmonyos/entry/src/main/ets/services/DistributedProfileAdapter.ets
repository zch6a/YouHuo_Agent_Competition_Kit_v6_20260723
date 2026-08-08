export interface ProfilePatch {
  elderId: string
  baseVersion: number
  operationId: string
  fields: Record<string, string | number | boolean>
}

/**
 * Adapter boundary for ArkData same-app cross-device synchronization.
 * High-sensitivity conflicts must be sent to the backend v5 conflict resolver;
 * they must never use last-write-wins silently.
 */
export class DistributedProfileAdapter {
  canAutoMerge(fieldName: string): boolean {
    const highRisk: string[] = ['payment', 'identity', 'health', 'location', 'medication']
    return !highRisk.some((prefix: string) => fieldName.toLowerCase().includes(prefix))
  }

  validatePatch(patch: ProfilePatch): boolean {
    return patch.baseVersion >= 0 && patch.operationId.length > 0 && Object.keys(patch.fields).length > 0
  }
}
