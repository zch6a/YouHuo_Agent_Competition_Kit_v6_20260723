# 部署到 Hugging Face Spaces（免费固定公网地址）

结果：任何人打开 `https://huggingface.co/spaces/<你的用户名>/youhuo` 就能直接用，
**不需要注册、不需要登录**，每个浏览器自动分到一份独立的演示家庭。

## 为什么需要你自己操作最后一步

创建账号和输入密码/令牌这类事我不能代做。下面每条命令都可以直接复制运行，
真正需要你本人的只有第 1 步（注册并创建 Space）和第 3 步（推送时输入访问令牌）。

## 1. 创建 Space

1. 注册 <https://huggingface.co/join>；
2. 打开 <https://huggingface.co/new-space>；
3. 填写：
   - **Space name**：`youhuo`
   - **License**：`mit`
   - **Select the SDK**：**Docker** → **Blank**
   - **Space hardware**：`CPU basic · free`
   - **Visibility**：`Public`
4. 创建后到 <https://huggingface.co/settings/tokens> 生成一个 **Write** 权限的
   Access Token，待第 3 步使用。

## 2. 在本地准备一份 Space 用的提交

Space 是一个独立的 git 仓库，它的根目录必须有带 YAML 头的 `README.md`。
下面的脚本把项目文件和 Space 用的 README 组装到一个临时目录，不影响你的
GitHub 仓库。

Windows PowerShell：

```powershell
.\deploy\huggingface\prepare_space.ps1 -SpaceRepo https://huggingface.co/spaces/<你的用户名>/youhuo
```

Linux/macOS：

```bash
./deploy/huggingface/prepare_space.sh https://huggingface.co/spaces/<你的用户名>/youhuo
```

脚本会打印临时目录路径，并已在其中完成 `git init` 与 `git commit`。

## 3. 推送

```bash
git push space main --force
```

提示输入用户名时填 Hugging Face 用户名，密码处**粘贴第 1 步生成的 Access Token**
（不是登录密码）。

推送后 Space 会自动构建镜像，首次约 3–5 分钟。构建日志在 Space 页面的
**Logs** 标签。出现 `Application startup complete` 即可访问。

## 4. 验证

| 检查 | 期望 |
|---|---|
| `https://<space>.hf.space/health` | `{"status":"ok", ... "demo_mode":true}` |
| `https://<space>.hf.space/elder` | 直接进入老人端，没有登录框 |
| 换一个浏览器（或无痕窗口）再开 | 待办列表是空的，说明两个访客的数据是分开的 |

## 需要知道的限制

- **数据会丢**：Spaces 的容器文件系统是临时的，重启或重新构建后 SQLite 归零。
  对演示是好事（永远是干净状态），但不要指望它保存任何东西。
- **免费实例会休眠**：48 小时无访问后进入睡眠，下次访问需要几十秒唤醒。
  答辩前先自己打开一次预热。
- **不要输入真实个人信息**：这是公开演示，页面上的健康、用药、位置都是演示数据。
- 如果需要固定不休眠、国内访问更快的地址，用阿里云/腾讯云的服务器 +
  `docker compose up -d` 更合适，`docker-compose.yml` 已经可用。
