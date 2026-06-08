# UIForge-Agent: Python 3.10 虚拟环境（首次或重装依赖时运行）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 py 启动器。请先安装 Python 3.10，例如："
    Write-Host "  winget install Python.Python.3.10 --accept-package-agreements --accept-source-agreements"
    exit 1
}

$py310 = & py -3.10 -c "import sys; print(sys.executable)" 2>$null
if (-not $py310) {
    Write-Host "未检测到 Python 3.10。请安装后重试。"
    exit 1
}

Write-Host "使用: $py310"
& py -3.10 -m venv "$Root\.venv"
& "$Root\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$Root\.venv\Scripts\python.exe" -m pip install -r "$Root\requirements.txt"

if (-not (Test-Path "$Root\.env")) {
    Copy-Item "$Root\.env.example" "$Root\.env"
    Write-Host "已创建 .env，请编辑 DEEPSEEK_API_KEY"
}

Write-Host "完成。运行示例："
Write-Host "  cd D:\wt"
Write-Host "  & `"$Root\.venv\Scripts\python.exe`" `"$Root\uiforge.py`" --task design --input `"$Root\examples\user_list_page.md`""
