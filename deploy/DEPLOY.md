# 让别人能用网址访问（免费，不用 Docker）

结果：任何人打开你的网址就能直接用，**不需要注册、不需要登录**，每个浏览器自动
分到一份独立的演示数据。

## 先说结论：用 Render

| 方案 | 能不能用 | 说明 |
|---|---|---|
| **Render**（推荐） | ✅ 免费 | 直接跑 Python，固定网址，不要信用卡 |
| Hugging Face Spaces | ❌ | 2026-08 起 Docker/Gradio Space 要订阅 PRO；只有静态网页免费，跑不了后端 |
| 自己的云服务器 | ✅ 要花钱 | 学生机约 ¥10/月，答辩当天最稳，见文末 |

仓库里已经放好 `render.yaml`，你不用改任何代码。

## 步骤（大约 10 分钟）

### 1. 注册
打开 <https://render.com> → **Get Started** → 选 **GitHub** 登录（用你已有的 GitHub 账号，
它会顺便拿到仓库权限，省一步）。

### 2. 新建服务
1. 点右上 **New +** → **Blueprint**；
2. 选中仓库 `YouHuo_Agent_Competition_Kit_v6_20260723`；
3. Render 会自动读到 `render.yaml`，显示要创建一个叫 `youhuo` 的 Web Service；
4. 点 **Apply** / **Create**。

如果 Blueprint 那步找不到仓库，就改用 **New +** → **Web Service** 手动填：

| 字段 | 填什么 |
|---|---|
| Repository | 你的 GitHub 仓库 |
| Language / Runtime | `Python 3` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python -m uvicorn youhuo.api:app --host 0.0.0.0 --port $PORT --app-dir backend` |
| Instance Type | **Free** |
| Health Check Path | `/health` |

环境变量加两条：`YOUHUO_DEMO_MODE=true`、`YOUHUO_DB_PATH=/tmp/youhuo.db`。

### 3. 等它构建
首次约 3–5 分钟。日志里出现 `Application startup complete` 就成了。
网址长这样：`https://youhuo-xxxx.onrender.com`

### 4. 验证

| 打开 | 应该看到 |
|---|---|
| `https://你的网址/health` | `{"status":"ok", ... "demo_mode":true}` |
| `https://你的网址/elder` | 直接进老人端，**没有登录框** |
| 换个无痕窗口再打开 | 待办是空的 → 说明两个访客的数据是分开的 |

## 要知道的限制

- **免费实例会休眠**：约 15 分钟没人访问就睡，下次打开要等 ~50 秒唤醒。
  **答辩前先自己打开一次预热。**
- **数据会清空**：重启后 SQLite 归零。对演示是好事（永远是干净状态），
  但不要指望它保存东西。
- **不要输入真实个人信息**：这是公开演示站，页面上的健康、用药、位置都是演示数据。

## 答辩当天想更稳：自己的服务器

阿里云/腾讯云学生机约 ¥10/月，不休眠、国内访问快。装好 Docker 后：

```bash
docker compose up -d
```

`docker-compose.yml` 已经可用。注意：中国大陆服务器用域名对外提供网页服务需要
ICP 备案，用 `IP:8000` 直接访问则不需要。
