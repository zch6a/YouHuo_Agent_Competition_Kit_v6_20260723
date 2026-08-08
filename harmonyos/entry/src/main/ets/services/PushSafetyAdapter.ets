export type PushUrgency = 'digest' | 'normal' | 'urgent' | 'sos'

export interface FamilyPushMessage {
  eventId: string
  elderId: string
  urgency: PushUrgency
  title: string
  privacySafeSummary: string
  expiresAt?: number
}

/** Server-side Push Kit calls must use service-account credentials.
 * The app only registers its push token and receives privacy-minimized data.
 */
export class PushSafetyAdapter {
  registerToken(token: string): void {
    if (!token || token.length < 16) {
      throw new Error('invalid push token')
    }
  }

  validateIncoming(message: FamilyPushMessage): boolean {
    return message.eventId.length > 0 && message.elderId.length > 0 && message.privacySafeSummary.length <= 240
  }
}
