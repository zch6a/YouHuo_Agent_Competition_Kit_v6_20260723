# 后端融合说明

默认 `assets/js/config.js` 使用 Mock。联调时改成：

```js
window.YOUHUO_CONFIG = {
  mode: "rest",
  apiBase: "https://your-domain.example/api/v1",
  timeoutMs: 8000
};
```

## DOM 数据绑定
`profile.name`, `profile.days`, `profile.weather`, `bill.amount`, `bill.company`, `bill.accountTail`, `bill.month`, `bill.paidAt`

## 核心 API
- `GET /profile`
- `GET /bills/water/current`
- `POST /voice/sessions`
- `POST /payments/prepare`
- `POST /payments/:id/teach-back`
- `POST /payments/:id/execute`
- `GET /records?type=...`
- `GET /payments/:id/certificate`
- `POST /emergency/call`

业务数据全部 DOM 化；山水、竹林、亭台、祥云、鹤、水花、发光球等作为独立 art/scene 资产。
