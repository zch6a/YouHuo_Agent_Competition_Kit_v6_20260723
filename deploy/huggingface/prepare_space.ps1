# Assemble a Hugging Face Space commit without touching the GitHub working tree.
#
# A Space is its own git repo and needs a README.md carrying YAML frontmatter at
# its root. The project README is the project's, so we stage a copy: project
# files + the Space README, in a temp directory.
param(
    [Parameter(Mandatory = $true)][string]$SpaceRepo
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Stage = Join-Path ([System.IO.Path]::GetTempPath()) ("youhuo-space-" + [guid]::NewGuid().ToString("N").Substring(0, 8))

New-Item -ItemType Directory -Path $Stage | Out-Null
Write-Host "staging in $Stage"

# Only what the image needs, plus the docs a visitor might follow.
$include = @(
    "backend", "xiaoyi", "Dockerfile", ".dockerignore",
    "requirements.txt", "requirements.lock.txt", "LICENSE", "THIRD_PARTY_NOTICES.md"
)
foreach ($item in $include) {
    $source = Join-Path $Root $item
    if (-not (Test-Path $source)) { throw "missing $item" }
    Copy-Item -Recurse -Force $source (Join-Path $Stage $item)
}

# Drop test and cache noise; the Space only runs the app.
Get-ChildItem -Path $Stage -Recurse -Force -Directory |
    Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", "tests", "data") } |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue }

Copy-Item -Force (Join-Path $PSScriptRoot "README.md") (Join-Path $Stage "README.md")

Push-Location $Stage
# git writes routine notices (CRLF conversion, hints) to stderr, and Windows
# PowerShell turns any native stderr into a terminating error while
# ErrorActionPreference is Stop — which silently skipped the commit below.
# Check exit codes explicitly instead.
$ErrorActionPreference = "Continue"

# Called directly rather than through a helper: PowerShell binds a leading -A or
# -c to the *function's* parameters even with ValueFromRemainingArguments.
# Plain `git init` because --initial-branch needs git >= 2.28; the push names the
# remote branch explicitly, so the local default branch name does not matter.
# The commit message is ASCII on purpose — a BOM-less UTF-8 .ps1 is decoded as
# ANSI by Windows PowerShell 5.1, which corrupts CJK. Chinese lives in the .md.
git init 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "git init failed" }

git add -A 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "git add failed" }

git -c user.email=space@youhuo.local -c user.name=youhuo commit -m "YouHuo online demo (login-free, per-visitor sandbox)" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }

git remote add space $SpaceRepo 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "git remote add failed" }
Pop-Location

Write-Host ""
Write-Host "ready. now run:" -ForegroundColor Green
Write-Host "  cd $Stage"
Write-Host "  git push space HEAD:main --force"
Write-Host ""
Write-Host "username = your Hugging Face name; password = a Write access token."
