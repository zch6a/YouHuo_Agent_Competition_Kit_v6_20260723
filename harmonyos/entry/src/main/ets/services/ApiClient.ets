import { http } from '@kit.NetworkKit';
import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { ChatResponse, DemoLoginResponse, TaskRecord, VisitorIdentity } from '../model/Models';

// 公网演示地址。HTTPS 而不是 HTTP：这条链路上会走审计凭据和账单摘要，明文承载
// 它们在任何一个咖啡店的 Wi-Fi 上都是可读的。之前这里写的是一个局域网 IP
// (`http://192.168.1.100:8000`)，那个地址只在某一台开发机的网段里存在——装到评委
// 的手机上就是一个永远连不上的 App。
//
// 本地联调时改成开发机的地址即可；不要提交任何生产 token。
const BASE_URL: string = 'https://youhuo.onrender.com';

const PREF_STORE: string = 'youhuo_identity';
const PREF_KEY: string = 'visitor_v1';

export class ApiClient {
  private static identity: VisitorIdentity | null = null;
  private static store: preferences.Preferences | null = null;
  private static pending: Promise<VisitorIdentity> | null = null;

  /**
   * 由 EntryAbility.onCreate 调用。给出 Context 之后，这台设备的演示家庭就能存到
   * preferences 里、跨冷启动复用；不给也能跑，只是每次启动会新播一户。
   */
  static async init(context: common.UIAbilityContext): Promise<void> {
    try {
      ApiClient.store = await preferences.getPreferences(context, PREF_STORE);
    } catch (err) {
      ApiClient.store = null;
    }
  }

  /**
   * 拿到这台设备自己的身份。
   *
   * 三层退路，从好到差：已持久化的沙箱 → 新播一户 → 回落到固定的 elder-demo。
   * 最后一层只在服务端没有 visitor 端点（旧版本、或演示模式关闭）时才会走到，
   * 行为与这个方法存在之前完全一致，而不是直接报错打不开。
   */
  private static async ensureIdentity(): Promise<VisitorIdentity> {
    if (ApiClient.identity) {
      return ApiClient.identity;
    }
    // memoise：五个并发调用不该播出五户人家。
    if (!ApiClient.pending) {
      ApiClient.pending = ApiClient.provision();
    }
    ApiClient.identity = await ApiClient.pending;
    return ApiClient.identity;
  }

  private static async provision(): Promise<VisitorIdentity> {
    const cached = await ApiClient.readCached();
    if (cached) {
      return cached;
    }
    try {
      const result = await ApiClient.rawPost('/v2/auth/visitor', {}, '');
      const fresh = result as VisitorIdentity;
      if (fresh.elder_token && fresh.family_token) {
        await ApiClient.writeCached(fresh);
        return fresh;
      }
    } catch (err) {
      // 落到下面的共享家庭。
    }
    const elderToken = await ApiClient.demoLogin('elder-demo');
    const familyToken = await ApiClient.demoLogin('daughter-demo');
    return {
      elder_id: 'elder-demo',
      daughter_id: 'daughter-demo',
      son_id: 'son-demo',
      family_id: 'family-demo',
      elder_token: elderToken,
      family_token: familyToken
    };
  }

  private static async readCached(): Promise<VisitorIdentity | null> {
    if (!ApiClient.store) {
      return null;
    }
    try {
      const raw = await ApiClient.store.get(PREF_KEY, '') as string;
      return raw ? JSON.parse(raw) as VisitorIdentity : null;
    } catch (err) {
      return null;
    }
  }

  private static async writeCached(identity: VisitorIdentity): Promise<void> {
    if (!ApiClient.store) {
      return;
    }
    try {
      await ApiClient.store.put(PREF_KEY, JSON.stringify(identity));
      await ApiClient.store.flush();
    } catch (err) {
      // 存不下就只是这次启动有效，不影响可用性。
    }
  }

  /** 丢掉本机沙箱，下次启动会拿到全新的一户。 */
  static async resetIdentity(): Promise<void> {
    ApiClient.identity = null;
    ApiClient.pending = null;
    if (ApiClient.store) {
      try {
        await ApiClient.store.delete(PREF_KEY);
        await ApiClient.store.flush();
      } catch (err) {
        // 清不掉也无所谓，内存里已经清了。
      }
    }
  }

  /** 老人本人的 id，用于所有以老人身份发起的请求。 */
  static async elderId(): Promise<string> {
    return (await ApiClient.ensureIdentity()).elder_id;
  }

  private static async demoLogin(actorId: string): Promise<string> {
    const result = await ApiClient.rawPost('/v2/auth/demo', { actor_id: actorId }, '');
    return (result as DemoLoginResponse).access_token;
  }

  private static async ensureElderToken(): Promise<string> {
    return (await ApiClient.ensureIdentity()).elder_token;
  }

  private static async ensureFamilyToken(): Promise<string> {
    return (await ApiClient.ensureIdentity()).family_token;
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
    const elderId = await ApiClient.elderId();
    return await ApiClient.rawPost('/v4/emotions/analyze', {
      elder_id: elderId, text: text, source: 'harmonyos', store_event: true
    }, token);
  }

  static async analyzeMedicalReport(text: string): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    const elderId = await ApiClient.elderId();
    return await ApiClient.rawPost('/v4/medical-reports/analyze', {
      elder_id: elderId, kind: 'checkup_report', text: text,
      source_name: 'HarmonyOS拍照OCR', create_followup_reminder: true
    }, token);
  }

  static async checkMedicationInteraction(names: Array<string>): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    return await ApiClient.rawPost('/v4/medications/interactions/check', { medication_names: names }, token);
  }

  static async monthlyReport(): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureFamilyToken();
    const elderId = await ApiClient.elderId();
    return await ApiClient.rawPost('/v4/reports/monthly', {
      elder_id: elderId, year: 2026, month: 7
    }, token);
  }

  static async listCapabilities(): Promise<Array<Record<string, Object>>> {
    const token = await ApiClient.ensureElderToken();
    const result = await ApiClient.get('/v4/capabilities', token);
    return result as Array<Record<string, Object>>;
  }

  static async resolveVoice(candidates: Array<Record<string, Object>>, sideEffectPossible: boolean): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    const elderId = await ApiClient.elderId();
    return await ApiClient.rawPost('/v5/voice/resolve', {
      elder_id: elderId, candidates: candidates, side_effect_possible: sideEffectPossible
    }, token);
  }

  static async capabilityTruth(): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    const result = await ApiClient.get('/v5/capability-truth', token);
    return result as Record<string, Object>;
  }

  static async semanticParse(text: string): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    const elderId = await ApiClient.elderId();
    return await ApiClient.rawPost('/v6/semantic/parse', {
      elder_id: elderId, text: text, permit_remote_model: false
    }, token);
  }

  static async interactionPlan(message: string, riskLevel: number): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    const elderId = await ApiClient.elderId();
    return await ApiClient.rawPost('/v6/interaction/plan', {
      elder_id: elderId, message: message,
      options: ['确认', '取消', '再听一遍', '问家人'],
      risk_level: riskLevel, asr_confidence: 0.76,
      recent_retries: 1, reversible: riskLevel < 4
    }, token);
  }

  static async safePreviewConflict(): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    const elderId = await ApiClient.elderId();
    return await ApiClient.rawPost('/v6/actions/preview', {
      elder_id: elderId, goal: '帮我交本月水费', action: 'create_payment_request',
      arguments: { bill_id: 'b1', amount_cents: 6840, elder_id: elderId },
      facts: [
        { name: 'bill_id', value: 'b1', origin: 'trusted_tool', purpose: 'bill_payment', trusted_for_control: true },
        { name: 'amount_cents', value: 6840, origin: 'trusted_tool', purpose: 'bill_payment', trusted_for_control: true },
        { name: 'amount_cents', value: 999999, origin: 'untrusted_document', purpose: 'bill_payment', trusted_for_control: false },
        { name: 'elder_id', value: elderId, origin: 'system', sensitivity: 3, purpose: 'bill_payment', trusted_for_control: true }
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
    const elderId = await ApiClient.elderId();
    return await ApiClient.rawPut('/v4/safety/policy', {
      elder_id: elderId, inactivity_minutes: 720, home_lat: 39.9042, home_lon: 116.3974,
      geofence_radius_m: 1000, notify_community: true
    }, token);
  }

  static async sendLocation(latitude: number, longitude: number, accuracy: number): Promise<Record<string, Object>> {
    const token = await ApiClient.ensureElderToken();
    const elderId = await ApiClient.elderId();
    return await ApiClient.rawPost('/v4/location/ping', {
      elder_id: elderId, latitude: latitude, longitude: longitude, accuracy_m: accuracy,
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
