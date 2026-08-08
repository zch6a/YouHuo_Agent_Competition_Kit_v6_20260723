/**
 * v6 Core Speech integration boundary.
 *
 * This file intentionally contains no fake SDK calls. Replace the callback
 * body with the HarmonyOS Core Speech Kit API available in the team's actual
 * DevEco Studio/API 26 environment, then validate permissions and lifecycle.
 */
export interface SpeechCandidate {
  text: string
  confidence: number
  engine: string
  language: string
}

export interface SpeechTurn {
  candidates: SpeechCandidate[]
  startedAt: number
  endedAt: number
}

export class CoreSpeechAdapter {
  private listening: boolean = false

  isListening(): boolean {
    return this.listening
  }

  async startNBestRecognition(onFinal: (turn: SpeechTurn) => void): Promise<void> {
    if (this.listening) {
      throw new Error('speech recognition is already active')
    }
    this.listening = true
    // Official Core Speech Kit integration point. Never synthesize a fake
    // recognition result in production builds.
    onFinal({ candidates: [], startedAt: Date.now(), endedAt: Date.now() })
    this.listening = false
  }

  stop(): void {
    this.listening = false
  }
}
