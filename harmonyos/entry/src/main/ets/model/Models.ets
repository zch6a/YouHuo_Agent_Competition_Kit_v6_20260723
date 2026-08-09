/**
 * 一台设备自己的演示家庭。
 *
 * `POST /v2/auth/visitor` 每次调用会新播一户人家并直接返回两个令牌。这在公网演示
 * 里是必需的：固定用 `elder-demo` 登录意味着所有评委的手机落在同一户，彼此看得见
 * 对方的待办、也能改掉对方的数据。家庭隔离在服务端按 family_id 强制执行，所以
 * 只要每台设备拿到自己的 family_id，沙箱就是真的。
 */
export interface VisitorIdentity {
  elder_id: string;
  daughter_id: string;
  son_id: string;
  family_id: string;
  elder_token: string;
  family_token: string;
}

export interface DemoLoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
}

export interface ChatResponse {
  code: string;
  message: string;
  mode: string;
  task_id?: string;
  task_status?: string;
  risk_level?: number;
  approval_digest?: string;
  ui?: Record<string, Object>;
  data?: Record<string, Object>;
}

export interface TaskRecord {
  id: string;
  elder_id: string;
  task_type: string;
  status: string;
  risk_level: number;
  summary: string;
  approval_digest?: string;
  details?: Record<string, Object>;
  result?: Record<string, Object>;
  created_at: string;
  updated_at: string;
}
