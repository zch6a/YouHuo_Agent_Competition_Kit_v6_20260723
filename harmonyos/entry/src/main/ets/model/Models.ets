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
