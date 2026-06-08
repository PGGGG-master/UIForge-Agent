# 使用项目 .venv（Python 3.10）调用 uiforge.py
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string[]]$Args
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "uiforge.py"

if (-not (Test-Path $Python)) {
    Write-Error "未找到 .venv。请先运行: .\scripts\setup-python.ps1"
    exit 1
}

& $Python $Script @Args
