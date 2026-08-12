$ErrorActionPreference = "Stop"

# `$PSScriptRoot`，不是 `Split-Path $MyInvocation.MyCommand.Path`。
#
# 后者在 `powershell -File .\run_demo.ps1` 下是**空的**——而那正是资源管理器里
# 右键「使用 PowerShell 运行」走的调用方式，也就是一个人真的会用的那条路。
# `$Root` 为空之后第 4 行的 `Join-Path $Root "backend"` 直接抛异常，脚本在设
# PYTHONPATH 之前就死了。这个脚本一直是这样，而没有任何测试跑过它：所有闸门都
# 自己起服务器、自己选端口，从来不读这个文件。
$Root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root "backend"
if (-not (Test-Path "data")) { New-Item -ItemType Directory -Path "data" | Out-Null }

# 铺一段合成的作息历史，好让个性化基线立刻有东西可看。
#
# 这一行原先不在这里。后果不是"少了点锦上添花"：默认关闭时照护页的五段全部读到
# "已记录 0 天 · 还不能说这是他的常态"，而那五段讲的正是这个项目的核心创新——
# 系统先学这位老人**自己**的生活规律再判断今天。任何人跑这个脚本看到的都是
# "它什么都不知道"。
#
# 而每一道闸门（check_page_runtime、run_feature_audit）和线上部署（render.yaml）
# 都自己把它打开了。也就是说所有仪器看的都是有数据的版本，只有**人**看的这一条路
# 是空的。
#
# 为什么它默认关闭仍然是对的：它写 `activity_events_v4`——一张运营表，无交互预警
# 取其中的 MAX(occurred_at)。默认打开会让合成回填悄悄改掉真实功能的输入。所以它
# 是显式开关，而"演示"正是该打开它的场合。
$env:YOUHUO_SEED_BASELINE = "true"

# 有项目自己的虚拟环境就用它。
#
# 裸 `python` 在装了 Anaconda / Miniconda 的机器上解析到那个解释器，而依赖装在
# 项目的 .venv 里——双击这个脚本得到的是 `ModuleNotFoundError: No module named
# 'uvicorn'`。这台比赛用的笔记本就是这样。
# 没有 .venv 时行为不变（照 README 先装依赖，再用 PATH 上的 python）。
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

# 端口必须和页面上印的那一句对得上。
#
# 每一页在没有服务器时会露出一段话：「运行 run_demo.ps1，然后访问
# http://127.0.0.1:8041/」。这个脚本原先开的是 8000——照着屏幕上的指示做的人得到
# 一个连接被拒。唯一一条给人看的路径，指向一个没人在听的端口。
# `test_deployment.py::test_the_demo_runner_opens_the_port_the_pages_advertise` 钉住这件事。
Write-Host "优活演示：http://127.0.0.1:8041/" -ForegroundColor Green
& $Py -m uvicorn youhuo.api:app --host 127.0.0.1 --port 8041 --app-dir backend
