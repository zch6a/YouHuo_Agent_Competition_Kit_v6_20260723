// 接真后端。`/api/v1` 是 `backend/youhuo/app_api.py` 那一层门面，
// 它把这套前端写死的路径翻译到真实业务（复述核验、任务状态机、审计链）。
// 想回到假数据看纯视觉，把 mode 改回 "mock" 即可。
window.YOUHUO_CONFIG={mode:"rest",apiBase:"/api/v1",timeoutMs:8000};
