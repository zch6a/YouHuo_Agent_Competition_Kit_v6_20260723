import { http } from '@kit.NetworkKit';
import { ChatResponse, DemoLoginResponse, TaskRecord } from '../model/Models';

// Replace with the HTTPS address reachable by the test device. Do not commit a production token.
const BASE_URL: string = 'http://192.168.1.100:8000';

export class ApiClient {
  private static elderToken: string = '';
  private static familyToken: string = '';

  private static async demoLogin(actorId: string): Promise<string> {
    const result = await ApiClient.rawPost('/v2/auth/demo', { actor_id: actorId }, '');
    return (result as DemoLoginResponse).access_token;
  }

  private static async ensureElderToken(): Promise<string> {
    if (!ApiClient.elderToken) ApiClient.elderToken = await ApiClient.demoLogin('elder-demo');
    return ApiClient.elderToken;
  }

  private static async ensureFamilyToken(): Promise<string> {
    if (!ApiClient.familyToken) ApiClient.familyToken = await ApiClient.demoLogin('daughter-demo');
    return ApiClient.familyToken;
  }

  static async createSession(): Promise<string> {
    const token = await ApiClient.ensureElderToken();
    const result = await ApiClient.rawPost('/v2/sessions', {}, token);
    return String(result['session_id']);
  }

  static async chat(sessionId: string, text: string): Promise<ChatResponse> {
    const token = await ApiClient.ensureElderToken();
    const result = await ApiClient.rawPost('/v2/chat', {
      session_id: sessionId,
      text: text,
      request_id: `${Date.now()}-${Math.random()}`
    }, token);
    return result as ChatResponse;
  }

  static async listTools(): Promise<Array<Object>> {
    const token = await ApiClient.ensureElderToken();
    const result = await ApiClient.get('/v3/tools', token);
    return result as Array<Object>;
  }

  static async listTasks(): Promise<Array<TaskRecord>> {
    const token = await ApiClient.ensureFamilyToken();
    const result = await ApiClient.get('/v2/tasks?limit=100', token);
    return result as Array<TaskRecord>;
  }


  static async analyzeEmotion(text: string): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    return await ApiClient.rawPost('/v4/emotions/analyze', {
      elder_id: 'elder-demo', text: text, source: 'harmonyos', store_event: true
    }, token);
  }

  static async analyzeMedicalReport(text: string): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    return await ApiClient.rawPost('/v4/medical-reports/analyze', {
      elder_id: 'elder-demo', kind: 'checkup_report', text: text,
      source_name: 'HarmonyOS拍照OCR', create_followup_reminder: true
    }, token);
  }

  static async checkMedicationInteraction(names: Array<string>): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    return await ApiClient.rawPost('/v4/medications/interactions/check', { medication_names: names }, token);
  }

  static async monthlyReport(): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureFamilyToken();
    return await ApiClient.rawPost('/v4/reports/monthly', {
      elder_id: 'elder-demo', year: 2026, month: 7
    }, token);
  }

  static async listCapabilities(): Promise<Array<Record<string, Object>>> {
    const token = await ApiClient.ensureElderToken();
    const result = await ApiClient.get('/v4/capabilities', token);
    return result as Array<Record<string, Object>>;
  }

  static async resolveVoice(candidates: Array<Record<string, Object>>, sideEffectPossible: boolean): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    return await ApiClient.rawPost('/v5/voice/resolve', {
      elder_id: 'elder-demo', candidates: candidates, side_effect_possible: sideEffectPossible
    }, token);
  }

  static async capabilityTruth(): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    const result = await ApiClient.get('/v5/capability-truth', token);
    return result as Record<string, Object>;
  }

  static async semanticParse(text: string): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    return await ApiClient.rawPost('/v6/semantic/parse', {
      elder_id: 'elder-demo', text: text, permit_remote_model: false
    }, token);
  }

  static async interactionPlan(message: string, riskLevel: number): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    return await ApiClient.rawPost('/v6/interaction/plan', {
      elder_id: 'elder-demo', message: message,
      options: ['确认', '取消', '再听一遍', '问家人'],
      risk_level: riskLevel, asr_confidence: 0.76,
      recent_retries: 1, reversible: riskLevel < 4
    }, token);
  }

  static async safePreviewConflict(): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    return await ApiClient.rawPost('/v6/actions/preview', {
      elder_id: 'elder-demo', goal: '帮我交本月水费', action: 'create_payment_request',
      arguments: { bill_id: 'b1', amount_cents: 6840, elder_id: 'elder-demo' },
      facts: [
        { name: 'bill_id', value: 'b1', origin: 'trusted_tool', purpose: 'bill_payment', trusted_for_control: true },
        { name: 'amount_cents', value: 6840, origin: 'trusted_tool', purpose: 'bill_payment', trusted_for_control: true },
        { name: 'amount_cents', value: 999999, origin: 'untrusted_document', purpose: 'bill_payment', trusted_for_control: false },
        { name: 'elder_id', value: 'elder-demo', origin: 'system', sensitivity: 3, purpose: 'bill_payment', trusted_for_control: true }
      ],
      ambiguity: 0.0, user_confirmed: true, family_approvals: 1, reversible: true, emergency: false
    }, token);
  }

  static async competitionEvidence(): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureFamilyToken();
    return await ApiClient.get('/v6/competition/evidence', token) as Record<string, Object>;
  }

  static async configureSafetyPolicy(): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureFamilyToken();
    return await ApiClient.rawPut('/v4/safety/policy', {
      elder_id: 'elder-demo', inactivity_minutes: 720, home_lat: 39.9042, home_lon: 116.3974,
      geofence_radius_m: 1000, notify_community: true
    }, token);
  }

  static async sendLocation(latitude: number, longitude: number, accuracy: number): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    return await ApiClient.rawPost('/v4/location/ping', {
      elder_id: 'elder-demo', latitude: latitude, longitude: longitude, accuracy_m: accuracy,
      occurred_at: new Date().toISOString(), source: 'harmonyos_location_adapter'
    }, token);
  }

  static async approve(taskId: string, approvalDigest: string, approve: boolean): Promise<ChatResponse> {
    const token = await ApiClient.ensureFamilyToken();
    const result = await ApiClient.rawPost('/v2/family/approve', {
      task_id: taskId,
      approve: approve,
      approval_digest: approvalDigest,
      reason: approve ? '家属已在端侧核对任务摘要' : '家属拒绝',
      request_id: `${Date.now()}-${Math.random()}`
    }, token);
    return result as ChatResponse;
  }

  private static async get(path: string, token: string): Promise<Object> {
    const request = http.createHttp();
    try {
      const response = await request.request(`${BASE_URL}${path}`, {
        method: http.RequestMethod.GET,
        header: { 'Authorization': `Bearer ${token}` },
        connectTimeout: 10000,
        readTimeout: 10000
      });
      if (response.responseCode < 200 || response.responseCode >= 300) throw new Error(String(response.result));
      return JSON.parse(String(response.result)) as Object;
    } finally {
      request.destroy();
    }
  }

  private static async rawPut(path: string, body: Record<string, Object>, token: string): Promise<Record<string, Object>> {
    const request = http.createHttp();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    try {
      const response = await request.request(`${BASE_URL}${path}`, {
        method: http.RequestMethod.PUT,
        header: headers,
        extraData: JSON.stringify(body),
        connectTimeout: 10000,
        readTimeout: 20000
      });
      if (response.responseCode < 200 || response.responseCode >= 300) throw new Error(String(response.result));
      return JSON.parse(String(response.result)) as Record<string, Object>;
    } finally {
      request.destroy();
    }
  }

  private static async rawPost(path: string, body: Record<string, Object>, token: string): Promise<Record<string, Object>> {
    const request = http.createHttp();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    try {
      const response = await request.request(`${BASE_URL}${path}`, {
        method: http.RequestMethod.POST,
        header: headers,
        extraData: JSON.stringify(body),
        connectTimeout: 10000,
        readTimeout: 20000
      });
      if (response.responseCode < 200 || response.responseCode >= 300) throw new Error(String(response.result));
      return JSON.parse(String(response.result)) as Record<string, Object>;
    } finally {
      request.destroy();
    }
  }
}
