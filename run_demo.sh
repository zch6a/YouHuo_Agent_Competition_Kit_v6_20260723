#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/backend"
mkdir -p data

# 铺一段合成的作息历史，好让个性化基线立刻有东西可看。默认关闭是对的（它写
# activity_events_v4，一张运营表，无交互预警取其中的 MAX(occurred_at)），但"演示"
# 正是该打开它的场合——关着的时候照护页五段全是「已记录 0 天」，而那五段讲的正是
# 这个项目的核心创新。详见 run_demo.ps1 里那段更长的说明。
export YOUHUO_SEED_BASELINE=true

# 有项目自己的虚拟环境就用它：裸 `python` 在装了 conda 的机器上解析到那个解释器，
# 而依赖装在 .venv 里，于是双击脚本得到 ModuleNotFoundError。没有 .venv 时行为不变。
PY="./.venv/bin/python"
[ -x "$PY" ] || PY="./.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="python"

# 端口和页面上印的那一句必须一致（每一页的 .needs-server 里写着 8041）。
# 原先这里是 8000：照着屏幕上的指示做的人得到一个连接被拒。
echo "优活演示：http://127.0.0.1:8041/"
"$PY" -m uvicorn youhuo.api:app --host 127.0.0.1 --port 8041 --app-dir backend
